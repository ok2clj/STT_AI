"""Real decoding regression tests: no downloaded model and no GPU are needed."""
from array import array
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import wave

import av
import numpy as np

from stt.audio import decode_audio
from stt.engine import Engine


class AudioTests(unittest.TestCase):
    def make_wav(self, root, rate=16000, channels=1, frames=1600, silence=False):
        path = Path(root) / 'nahravka.wav'
        pcm = array('h')
        for i in range(frames):
            sample = 0 if silence else round(8000 * math.sin(2 * math.pi * 440 * i / rate))
            pcm.extend([sample] * channels)
        with wave.open(str(path), 'wb') as out:
            out.setnchannels(channels)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(pcm.tobytes())
        return str(path)

    def test_real_wav_decode_without_removed_metadata_argument(self):
        with TemporaryDirectory() as root:
            path = self.make_wav(root)
            with patch('stt.audio.av.open', wraps=av.open) as opened:
                audio = decode_audio(path)
            self.assertNotIn('metadata_errors', opened.call_args.kwargs)
            self.assertEqual(audio.dtype, np.float32)
            self.assertEqual(audio.shape, (1600,))
            self.assertGreater(float(np.max(np.abs(audio))), .2)
            self.assertLessEqual(float(np.max(np.abs(audio))), 1)

    def test_stereo_resampling_retains_full_duration(self):
        with TemporaryDirectory() as root:
            audio = decode_audio(self.make_wav(root, rate=44100, channels=2, frames=4410))
        self.assertEqual(audio.ndim, 1)
        self.assertEqual(audio.dtype, np.float32)
        # The resampler's final delayed samples must be flushed.
        self.assertLessEqual(abs(len(audio) - 1600), 1)
        self.assertTrue(np.all(np.isfinite(audio)))
        self.assertGreater(float(np.max(np.abs(audio))), .1)

    def test_silence_is_preserved(self):
        with TemporaryDirectory() as root:
            audio = decode_audio(self.make_wav(root, silence=True))
        self.assertEqual(len(audio), 1600)
        self.assertTrue(np.all(audio == 0))

    def test_empty_wav_returns_empty_float32(self):
        with TemporaryDirectory() as root:
            audio = decode_audio(self.make_wav(root, frames=0))
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(len(audio), 0)

    def test_invalid_file_is_not_treated_as_successful_silence(self):
        with TemporaryDirectory() as root:
            path = Path(root) / 'corrupt.wav'
            path.write_bytes(b'not audio')
            with self.assertRaises(av.error.InvalidDataError):
                decode_audio(str(path))

    def test_engine_uses_real_decoder_before_model_inference(self):
        library = Mock()
        library.get.return_value = {'id': 'small', 'format': 'builtin'}
        library.ensure.return_value = '/local/model'
        infer = Mock(return_value=([{'start': 0, 'end': .1, 'text': 'Test.'}], 'cs'))
        engine = Engine(Path('/tmp/models'), library)
        progress = Mock()
        with TemporaryDirectory() as root, \
             patch('stt.engine.hardware', return_value={'cuda': False}), \
             patch.object(engine, '_load', return_value=infer):
            result = engine.transcribe(self.make_wav(root), 'small', 'cpu', 'cs', '', progress)
        self.assertEqual(result['duration'], .1)
        self.assertEqual(infer.call_args.args[0].dtype, np.float32)
        self.assertEqual(result['segments'][0]['text'], 'Test.')
        self.assertEqual(progress.call_args.kwargs, {'status': 'saving'})


if __name__ == '__main__':
    unittest.main()
