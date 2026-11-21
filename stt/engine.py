"""Inference imports are lazy: the web UI starts without loading model weights."""
import gc
import platform
import shutil
import time

MODELS = ("tiny", "base", "small", "medium", "large-v3", "turbo")
MLX_MODELS = {
    **{name: f"mlx-community/whisper-{name}-mlx" for name in MODELS if name != "turbo"},
    "turbo": "mlx-community/whisper-large-v3-turbo",
}


def hardware():
    import ctranslate2
    apple = platform.system() == "Darwin" and platform.machine() == "arm64"
    try:
        cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        cuda = False
    return {"apple_silicon": apple, "cuda": cuda, "cpu": platform.machine(),
            "ffmpeg": bool(shutil.which("ffmpeg")), "default": "mlx" if apple else "cuda" if cuda else "cpu"}


class Engine:
    def __init__(self, cache):
        self.cache = cache
        self.key = None
        self.model = None

    def transcribe(self, path, model, device, language, prompt, progress):
        hw = hardware()
        device = hw["default"] if device == "auto" else device
        if device == "cuda" and not hw["cuda"]:
            raise RuntimeError("NVIDIA GPU není dostupná. Vyberte CPU nebo zkontrolujte ovladače CUDA.")
        if device == "mlx" and not hw["apple_silicon"]:
            raise RuntimeError("Apple MLX vyžaduje macOS a Apple Silicon.")
        started = time.monotonic()
        progress(status="loading", device=device)
        if device == "mlx":
            if not hw["ffmpeg"]:
                raise RuntimeError("Chybí FFmpeg. Na Macu spusťte: brew install ffmpeg")
            import mlx_whisper
            # MLX manages its own single-model cache. Drop the CPU/CUDA model first.
            self.model, self.key = None, None
            gc.collect()
            progress(status="transcribing")
            result = mlx_whisper.transcribe(
                str(path), path_or_hf_repo=MLX_MODELS[model], language=language or None,
                initial_prompt=prompt or None, verbose=None, condition_on_previous_text=False,
            )
            segments = [{"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()}
                        for s in result["segments"]]
            return {"segments": segments, "language": result.get("language", language),
                    "duration": max((s["end"] for s in segments), default=0),
                    "elapsed": round(time.monotonic() - started, 2), "device": device}

        from faster_whisper import WhisperModel
        key = (model, device)
        if self.key != key:
            self.model, self.key = None, None
            gc.collect()
            self.model = WhisperModel(model, device=device,
                                      compute_type="float16" if device == "cuda" else "int8",
                                      download_root=str(self.cache))
            self.key = key
        stream, info = self.model.transcribe(
            str(path), language=language or None, initial_prompt=prompt or None,
            beam_size=5, vad_filter=True, condition_on_previous_text=False,
        )
        progress(status="transcribing", duration=info.duration, language=info.language)
        segments = []
        for s in stream:
            segments.append({"start": float(s.start), "end": float(s.end), "text": s.text.strip()})
            progress(progress=min(99, round(100 * s.end / max(info.duration, 1))))
        return {"segments": segments, "language": info.language, "duration": info.duration,
                "elapsed": round(time.monotonic() - started, 2), "device": device}
