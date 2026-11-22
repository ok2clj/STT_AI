"""Local Whisper backends with progress measured from completed audio windows."""
import gc
import importlib
import platform
import sys
import time

from .models import BUILTINS as MODELS, ModelLibrary, resolve_spec

SAMPLE_RATE = 16000
CHUNK_SECONDS = 30


def hardware():
    import ctranslate2
    apple = platform.system() == 'Darwin' and platform.machine() == 'arm64'
    try:
        cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        cuda = False
    if not cuda:
        try:
            import torch
            cuda = torch.cuda.is_available()
        except ImportError:
            pass
    return {'apple_silicon': apple, 'cuda': cuda, 'cpu': platform.machine(),
            'default': 'mlx' if apple else 'cuda' if cuda else 'cpu'}


def audio_windows(audio, chunk_seconds=CHUNK_SECONDS):
    """Process every sample exactly once, including silent windows."""
    size = int(chunk_seconds * SAMPLE_RATE)
    for start in range(0, len(audio), size):
        yield start / SAMPLE_RATE, audio[start:start + size]


def offset_segments(segments, offset, duration):
    result = []
    for s in segments:
        text = s['text'].strip()
        start = min(duration, max(0, float(s['start'])))
        end = min(duration, max(start, float(s['end'])))
        if text and end > start:
            result.append({'start': offset + start, 'end': offset + end, 'text': text})
    return result


class Engine:
    def __init__(self, cache, library=None):
        self.cache, self.library = cache, library
        self.key = self.model = self.processor = None

    def _release(self):
        if self.key and self.key[0] == 'mlx':
            holder = importlib.import_module('mlx_whisper.transcribe').ModelHolder
            holder.model, holder.model_path = None, None
        self.model, self.processor, self.key = None, None, None
        gc.collect()
        torch = sys.modules.get('torch')
        if torch:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()

    def transcribe(self, path, model, device, language, prompt, progress):
        if self.library is None:
            self.library = ModelLibrary(self.cache)
        spec = resolve_spec(self.library.get(model), device, hardware())
        started = time.monotonic()
        progress(device=spec['device'], backend=spec['format'], progress=0, processed_seconds=0)
        model_path = self.library.ensure(spec, progress)
        progress(status='loading')
        infer = self._load(spec, model_path)
        progress(status='decoding')
        from faster_whisper.audio import decode_audio
        audio = decode_audio(str(path), sampling_rate=SAMPLE_RATE)
        duration = len(audio) / SAMPLE_RATE
        if not duration:
            raise ValueError('Nahrávka neobsahuje žádné audio vzorky.')
        segments, detected = [], language or None
        progress(status='transcribing', duration=duration, progress=0, processed_seconds=0)
        for offset, window in audio_windows(audio):
            raw, window_language = infer(window, detected, prompt)
            if any(s['text'].strip() for s in raw):
                detected = detected or window_language
            seconds = len(window) / SAMPLE_RATE
            segments.extend(offset_segments(raw, offset, seconds))
            processed = min(duration, offset + seconds)
            progress(progress=min(99, round(100 * processed / duration, 1)),
                     processed_seconds=processed, language=detected or '', segments=segments)
        progress(status='saving')
        return {'segments': segments, 'language': detected or '', 'duration': duration,
                'elapsed': round(time.monotonic() - started, 2), 'device': spec['device'],
                'backend': spec['format'], 'model_repo': spec['repo_id'], 'processed_seconds': duration}

    def _load(self, spec, path):
        kind, device = spec['format'], spec['device']
        key = (kind, path, device)
        if self.key != key:
            self._release()
            if kind == 'ctranslate2':
                from faster_whisper import WhisperModel
                self.model = WhisperModel(path, device=device, local_files_only=True,
                                          compute_type='float16' if device == 'cuda' else 'int8')
            elif kind == 'transformers':
                try:
                    import torch
                    from transformers import WhisperForConditionalGeneration, WhisperProcessor
                except ImportError as exc:
                    raise RuntimeError('Pro tento model nainstalujte rozšíření: uv sync --extra hf') from exc
                if device == 'mps' and not torch.backends.mps.is_available():
                    raise RuntimeError('PyTorch MPS není dostupné. Vyberte CPU nebo aktualizujte macOS/PyTorch.')
                if device == 'cuda' and not torch.cuda.is_available():
                    raise RuntimeError('PyTorch nemá CUDA. Nainstalujte CUDA verzi PyTorch nebo vyberte CPU.')
                self.processor = WhisperProcessor.from_pretrained(path, local_files_only=True)
                self.model = WhisperForConditionalGeneration.from_pretrained(
                    path, local_files_only=True, use_safetensors=True,
                    torch_dtype=torch.float32 if device == 'cpu' else torch.float16,
                    attn_implementation='eager',
                ).to(device).eval()
                self.model.generation_config.forced_decoder_ids = None
            else:
                from mlx_whisper.transcribe import ModelHolder
                import mlx.core as mx
                ModelHolder.get_model(path, mx.float16)
            self.key = key
        if kind == 'mlx':
            return self._mlx(path)
        if kind == 'transformers':
            return self._transformers(device)
        return self._ct2()

    def _ct2(self):
        def infer(audio, language, prompt):
            stream, info = self.model.transcribe(audio, language=language, initial_prompt=prompt or None,
                                                 beam_size=5, vad_filter=True, condition_on_previous_text=False)
            return ([{'start': s.start, 'end': s.end, 'text': s.text} for s in stream], info.language)
        return infer

    def _mlx(self, path):
        import mlx_whisper

        def infer(audio, language, prompt):
            result = mlx_whisper.transcribe(audio, path_or_hf_repo=path, language=language,
                                            initial_prompt=prompt or None, verbose=None,
                                            condition_on_previous_text=False)
            return result['segments'], result.get('language', language)
        return infer

    def _transformers(self, device):
        import torch

        def infer(audio, language, prompt):
            inputs = self.processor(audio, sampling_rate=SAMPLE_RATE, return_tensors='pt',
                                    return_attention_mask=True)
            features = inputs.input_features.to(device=device, dtype=self.model.dtype)
            kwargs = {'task': 'transcribe', 'return_timestamps': True, 'num_beams': 1,
                      'attention_mask': inputs.attention_mask.to(device),
                      'max_length': self.model.config.max_target_positions}
            if language:
                kwargs['language'] = language
            if prompt:
                kwargs['prompt_ids'] = self.processor.get_prompt_ids(prompt, return_tensors='pt').to(device)
            with torch.inference_mode():
                ids = self.model.generate(features, **kwargs)
            result = self.processor.tokenizer.decode(ids[0].cpu(), skip_special_tokens=True, output_offsets=True)
            segments = [{'start': s['timestamp'][0], 'end': s['timestamp'][1], 'text': s['text']}
                        for s in result.get('offsets', [])]
            if not segments and result['text'].strip():
                segments = [{'start': 0, 'end': len(audio) / SAMPLE_RATE, 'text': result['text']}]
            detected = language
            if not detected:
                lang_ids = {value: key for key, value in self.model.generation_config.lang_to_id.items()}
                detected = next((lang_ids[token].strip('<|>') for token in ids[0].tolist()
                                 if token in lang_ids), None)
            return segments, detected
        return infer
