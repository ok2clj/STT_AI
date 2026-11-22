import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from stt.models import CZECH, ModelLibrary, normalize_repo, resolve_spec, validate_snapshot
from stt.engine import audio_windows, offset_segments


class ModelTests(unittest.TestCase):
    def test_czech_model_uses_mps_on_mac_and_cuda_elsewhere(self):
        mac=resolve_spec(CZECH,'auto',{'apple_silicon':True})
        self.assertEqual((mac['format'],mac['device']),('transformers','mps'))
        self.assertEqual(resolve_spec(CZECH,'auto',{'cuda':True})['device'],'cuda')
        self.assertEqual(resolve_spec(CZECH,'auto',{})['device'],'cpu')

    def test_format_device_mismatch_is_not_silently_substituted(self):
        for model, device in [(CZECH,'mlx'), ({'id':'a','format':'mlx'},'cpu'),
                              ({'id':'a','format':'ctranslate2'},'mps')]:
            with self.assertRaises(ValueError):
                resolve_spec(model,device,{'apple_silicon':True})

    def test_builtin_still_selects_mlx_or_ct2(self):
        builtin={'id':'small','format':'builtin'}
        self.assertEqual(resolve_spec(builtin,'auto',{'apple_silicon':True})['format'],'mlx')
        self.assertEqual(resolve_spec(builtin,'cpu',{'apple_silicon':True})['format'],'ctranslate2')

    def test_repo_validation_accepts_only_model_ids(self):
        self.assertEqual(normalize_repo('https://huggingface.co/mikr/whisper-large-v3-czech-cv13/'),CZECH['repo_id'])
        for value in ['../../etc','http://evil/a/b','author/model/tree/main','/tmp/model','a/../b','a/b?x=1']:
            with self.assertRaises(ValueError):
                normalize_repo(value)

    def test_custom_models_persist_and_deduplicate(self):
        with TemporaryDirectory() as root:
            lib=ModelLibrary(root)
            try:
                first=lib.register('author/czech','transformers','Můj model')
                self.assertEqual(first['id'],lib.register('author/czech','transformers')['id'])
                self.assertEqual(len(lib.catalog()),8)
                state=json.loads(lib.manifest.read_text())
                self.assertEqual(state['custom'][0]['repo_id'],'author/czech')
                self.assertEqual(lib.register(CZECH['repo_id'],'transformers')['id'],'czech-cv13')
                with self.assertRaises(ValueError): lib.get('unknown')
            finally: lib.close()
            restored=ModelLibrary(root)
            try: self.assertEqual(restored.get(first['id'])['name'],'Můj model')
            finally: restored.close()

    def test_restart_marks_interrupted_download_as_error(self):
        with TemporaryDirectory() as root:
            Path(root,'catalog.json').write_text(json.dumps({'custom':[],'downloads':{
                'tiny:mlx':{'status':'downloading'}}}))
            lib=ModelLibrary(root)
            try: self.assertEqual(lib.get('tiny')['downloads']['mlx']['status'],'error')
            finally: lib.close()

    def test_invalid_checkpoint_format_is_rejected(self):
        with TemporaryDirectory() as root:
            Path(root,'config.json').write_text('{"model_type":"whisper"}')
            for kind in ['transformers','mlx','ctranslate2']:
                with self.assertRaises(ValueError): validate_snapshot(root,kind)
            Path(root,'model.safetensors').write_bytes(b'dummy')
            Path(root,'preprocessor_config.json').write_text('{}')
            Path(root,'tokenizer_config.json').write_text('{}')
            validate_snapshot(root,'transformers')

    def test_download_error_persisted_and_can_retry(self):
        with TemporaryDirectory() as root:
            lib=ModelLibrary(root)
            spec=resolve_spec(CZECH,'cpu',{})
            try:
                with patch.object(lib,'_download',side_effect=RuntimeError('offline')):
                    with self.assertRaises(RuntimeError): lib.ensure(spec)
                self.assertEqual(lib.get('czech-cv13')['downloads']['transformers']['status'],'error')
                with patch.object(lib,'_download',return_value='/local/snapshot') as download:
                    self.assertEqual(lib.ensure(spec),'/local/snapshot')
                    download.assert_called_once()
            finally: lib.close()

    def test_snapshot_download_counts_files_and_records_revision(self):
        with TemporaryDirectory() as root:
            lib=ModelLibrary(root)
            snapshot=Path(root)/'snapshots'/'test-revision'
            snapshot.mkdir(parents=True)
            (snapshot/'config.json').write_text('{"n_mels":80}')
            (snapshot/'weights.npz').write_bytes(b'dummy')
            seen=[]
            def download(repo, **kw):
                self.assertNotIn('*.py',kw['allow_patterns'])
                bar=kw['tqdm_class'](total=2)
                bar.update(1); bar.update(1); bar.close()
                return str(snapshot)
            try:
                with patch.dict('sys.modules',{'huggingface_hub':SimpleNamespace(snapshot_download=download)}):
                    spec=resolve_spec({'id':'tiny','format':'builtin'},'mlx',{'apple_silicon':True})
                    lib.ensure(spec,lambda **kw: seen.append(kw))
                self.assertEqual(seen[-1]['download_files_done'],2)
                state=lib.get('tiny')['downloads']['mlx']
                self.assertEqual(state['status'],'ready')
                self.assertEqual(state['revision'],'test-revision')
                with patch.object(lib,'_download') as fn:
                    self.assertEqual(lib.ensure(spec),str(snapshot))
                    fn.assert_not_called()
            finally: lib.close()

    def test_windows_cover_all_samples_including_final_short_window(self):
        audio=list(range(67))
        windows=list(audio_windows(audio,chunk_seconds=30/16000))
        self.assertEqual([len(a) for _,a in windows],[30,30,7])
        self.assertEqual([s for _,a in windows for s in a],audio)

    def test_offsets_clamp_invalid_or_padded_timestamps(self):
        raw=[{'start':-2,'end':9,'text':' ahoj '},{'start':9,'end':10,'text':'padding'}]
        self.assertEqual(offset_segments(raw,30,5),[{'start':30,'end':35,'text':'ahoj'}])


if __name__ == '__main__': unittest.main()
