import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from stt.engine import Engine
from stt.formats import format_transcript, timestamp


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.job = {"segments": [{"start": 1.25, "end": 3.5, "text": "Příliš žluťoučký kůň."}]}

    def test_czech_and_json_roundtrip(self):
        self.assertIn("žluťoučký", format_transcript(self.job, "txt"))
        self.assertEqual(json.loads(format_transcript(self.job, "json")), self.job)

    def test_subtitles_use_correct_time_separators(self):
        self.assertEqual(format_transcript(self.job, "srt"),
                         "1\n00:00:01,250 --> 00:00:03,500\nPříliš žluťoučký kůň.\n\n")
        self.assertTrue(format_transcript(self.job, "vtt").startswith("WEBVTT\n\n1\n00:00:01.250"))

    def test_rounding_carries_across_minute(self):
        self.assertEqual(timestamp(59.9999), "00:01:00,000")
        self.assertEqual(timestamp(3600.001), "01:00:00,001")

    def test_user_edits_cannot_inject_subtitle_cues(self):
        self.job["segments"][0]["text"] = "a\n\n00:00:01 --> 00:00:02\nb"
        self.assertEqual(format_transcript(self.job, "srt").count("-->"), 1)

    def test_invalid_values_rejected(self):
        for value in [float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                timestamp(value)
        with self.assertRaises(ValueError):
            format_transcript(self.job, "html")


class EngineTests(unittest.TestCase):
    def test_cpu_int8_progress_model_reuse_and_device_switch(self):
        model = Mock()
        model.transcribe.side_effect = lambda *a, **k: (
            iter([SimpleNamespace(start=0, end=2, text=" Ahoj. ")]),
            SimpleNamespace(duration=2, language='cs'),
        )
        ctor = Mock(return_value=model)
        progress = Mock()
        with patch('stt.engine.hardware', return_value={"default":"cpu", "cuda":True}), \
             patch.dict('sys.modules', {"faster_whisper": SimpleNamespace(WhisperModel=ctor)}):
            engine = Engine(Path('/tmp/models'))
            result = engine.transcribe(Path('audio.wav'), 'small', 'auto', 'cs', '', progress)
            self.assertEqual(result['segments'][0]['text'], 'Ahoj.')
            self.assertEqual(result['device'], 'cpu')
            self.assertEqual(ctor.call_args.kwargs['compute_type'], 'int8')
            self.assertTrue(model.transcribe.call_args.kwargs['vad_filter'])
            engine.transcribe(Path('audio.wav'), 'small', 'cpu', 'cs', '', progress)
            self.assertEqual(ctor.call_count, 1)
            engine.transcribe(Path('audio.wav'), 'small', 'cuda', 'cs', '', progress)
            self.assertEqual(ctor.call_args.kwargs['compute_type'], 'float16')

    def test_unavailable_gpu_has_clear_error(self):
        with patch('stt.engine.hardware', return_value={"cuda":False, "apple_silicon":False}):
            for device in ('cuda', 'mlx'):
                with self.assertRaises(RuntimeError):
                    Engine(Path('/tmp/models')).transcribe('x', 'tiny', device, 'cs', '', Mock())

    def test_mlx_mapping_and_timestamps(self):
        transcribe = Mock(return_value={"language":"cs", "segments":[{"start":0, "end":3, "text":" Test. "}]})
        with patch('stt.engine.hardware', return_value={"default":"mlx", "apple_silicon":True, "ffmpeg":True}), \
             patch.dict('sys.modules', {"mlx_whisper":SimpleNamespace(transcribe=transcribe)}):
            result = Engine(Path('/tmp/models')).transcribe('audio.wav', 'turbo', 'auto', 'cs', 'Jihlava', Mock())
        self.assertEqual(transcribe.call_args.kwargs['path_or_hf_repo'], 'mlx-community/whisper-large-v3-turbo')
        self.assertEqual(transcribe.call_args.kwargs['initial_prompt'], 'Jihlava')
        self.assertEqual(result['duration'], 3)
        self.assertEqual(result['segments'][0]['text'], 'Test.')


if __name__ == '__main__':
    unittest.main()
