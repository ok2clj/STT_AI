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
    def test_progress_tracks_audio_including_silence_and_offsets(self):
        library = Mock()
        library.get.return_value = {'id':'small', 'format':'builtin'}
        library.ensure.return_value = '/local/model'
        # Three windows: speech, silence, speech. Silent windows still count.
        infer = Mock(side_effect=[([{'start':1,'end':2,'text':'První.'}], 'cs'),
                                  ([], 'cs'), ([{'start':0,'end':10,'text':'Konec.'}], 'cs')])
        progress = Mock()
        with patch('stt.engine.hardware', return_value={'cuda':False}), \
             patch.dict('sys.modules', {'stt.audio': SimpleNamespace(
                 decode_audio=lambda *a, **k: [0] * (65 * 16000))}):
            engine=Engine(Path('/tmp/models'), library)
            with patch.object(engine, '_load', return_value=infer):
                result=engine.transcribe('audio.wav','small','cpu','cs','Jihlava',progress)
        values=[c.kwargs['progress'] for c in progress.call_args_list if 'progress' in c.kwargs]
        self.assertEqual(values, [0,0,46.2,92.3,99])
        self.assertEqual(result['duration'],65)
        self.assertEqual(result['segments'][-1],{'start':60,'end':65,'text':'Konec.'})
        self.assertEqual(infer.call_count,3)
        self.assertEqual(progress.call_args.kwargs, {'status':'saving'})

    def test_model_loading_uses_local_weights_and_cpu_int8(self):
        ctor=Mock()
        with patch.dict('sys.modules', {'faster_whisper':SimpleNamespace(WhisperModel=ctor)}):
            engine=Engine(Path('/tmp/models'))
            engine._load({'format':'ctranslate2','device':'cpu'},'/local/model')
            engine._load({'format':'ctranslate2','device':'cpu'},'/local/model')
        self.assertEqual(ctor.call_count,1)
        self.assertTrue(ctor.call_args.kwargs['local_files_only'])
        self.assertEqual(ctor.call_args.kwargs['compute_type'],'int8')

    def test_initial_silence_does_not_lock_wrong_language(self):
        library=Mock()
        library.get.return_value={'id':'small','format':'builtin'}
        infer=Mock(side_effect=[([], 'en'), ([{'start':0,'end':2,'text':'Ahoj'}], 'cs')])
        engine=Engine(Path('/tmp/models'),library)
        with patch('stt.engine.hardware',return_value={'cuda':False}), \
             patch.object(engine,'_load',return_value=infer), \
             patch.dict('sys.modules',{'stt.audio':SimpleNamespace(
                 decode_audio=lambda *a,**k:[0]*(31*16000))}):
            result=engine.transcribe('x','small','cpu','','',Mock())
        self.assertIsNone(infer.call_args_list[1].args[1])
        self.assertEqual(result['language'],'cs')

    def test_zero_length_audio_fails_before_percentage_division(self):
        library=Mock()
        library.get.return_value={'id':'tiny','format':'builtin'}
        engine=Engine(Path('/tmp/models'),library)
        with patch('stt.engine.hardware',return_value={'cuda':False}), \
             patch.object(engine,'_load'), \
             patch.dict('sys.modules',{'stt.audio':SimpleNamespace(decode_audio=lambda *a,**k: [])}):
            with self.assertRaisesRegex(ValueError,'vzorky'):
                engine.transcribe('x','tiny','cpu','cs','',Mock())

    def test_mlx_passes_numpy_window_and_prompt(self):
        fn=Mock(return_value={'language':'cs','segments':[{'start':0,'end':1,'text':'Test.'}]})
        with patch.dict('sys.modules',{'mlx_whisper':SimpleNamespace(transcribe=fn)}):
            engine=Engine(Path('/tmp/models'))
            result,language=engine._mlx('/local/mlx')([0,0],'cs','Jihlava')
        self.assertEqual(language,'cs')
        self.assertEqual(fn.call_args.args[0],[0,0])
        self.assertEqual(fn.call_args.kwargs['path_or_hf_repo'],'/local/mlx')
        self.assertEqual(fn.call_args.kwargs['initial_prompt'],'Jihlava')

    def test_transformers_offsets_and_language_detection(self):
        from contextlib import nullcontext
        engine=Engine(Path('/tmp/models'))
        engine.model=Mock()
        engine.model.config.max_target_positions=448
        engine.model.generation_config.lang_to_id={'<|cs|>':123}
        ids=Mock(); ids.tolist.return_value=[1,123,2]
        engine.model.generate.return_value=[ids]
        engine.processor=Mock()
        engine.processor.tokenizer.decode.return_value={
            'text':'Ahoj','offsets':[{'timestamp':(0,1.2),'text':'Ahoj'}]}
        with patch.dict('sys.modules',{'torch':SimpleNamespace(inference_mode=nullcontext)}):
            segments,language=engine._transformers('cpu')([0]*32000,None,'Jihlava')
        self.assertEqual(language,'cs')
        self.assertEqual(segments,[{'start':0,'end':1.2,'text':'Ahoj'}])
        self.assertTrue(engine.model.generate.call_args.kwargs['return_timestamps'])
        self.assertIn('prompt_ids',engine.model.generate.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
