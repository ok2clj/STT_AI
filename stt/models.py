"""Persistent local model catalog; repository code is never downloaded or executed."""
import hashlib
import io
import json
import logging
from pathlib import Path
import queue
import re
import threading

BUILTINS = ('tiny', 'base', 'small', 'medium', 'large-v3', 'turbo')
MLX_MODELS = {**{n: f'mlx-community/whisper-{n}-mlx' for n in BUILTINS if n != 'turbo'},
              'turbo': 'mlx-community/whisper-large-v3-turbo'}
CT2_MODELS = {**{n: f'Systran/faster-whisper-{n}' for n in BUILTINS if n != 'turbo'},
              'turbo': 'mobiuslabsgmbh/faster-whisper-large-v3-turbo'}
CZECH = {'id': 'czech-cv13', 'name': 'Čeština · mikr Large v3 CV13', 'format': 'transformers',
         'repo_id': 'mikr/whisper-large-v3-czech-cv13', 'description': 'Český fine-tuning · váhy přibližně 3,22 GB'}
FORMATS = ('transformers', 'ctranslate2', 'mlx')
PATTERNS = {
    'transformers': ['*.json', '*.txt', '*.model', 'model*.safetensors'],
    'ctranslate2': ['config.json', 'model.bin', 'tokenizer.json', 'vocabulary.*', 'preprocessor_config.json'],
    'mlx': ['config.json', 'weights.npz', 'weights.safetensors'],
}


def normalize_repo(value):
    value = value.strip()
    prefix = 'https://huggingface.co/'
    if value.startswith(prefix):
        value = value[len(prefix):].rstrip('/')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', value):
        raise ValueError('Zadejte Hugging Face ID ve tvaru autor/model nebo odkaz na jeho hlavní stránku.')
    return value


def resolve_spec(model, device, hw):
    kind = model['format']
    if kind == 'builtin':
        kind = 'mlx' if device == 'mlx' or (device == 'auto' and hw.get('apple_silicon')) else 'ctranslate2'
        if device == 'mps':
            raise ValueError('Pro základní modely na Apple GPU zvolte MLX nebo Automaticky.')
    if device == 'auto':
        if kind == 'mlx':
            device = 'mlx'
        elif kind == 'transformers' and hw.get('apple_silicon'):
            device = 'mps'
        else:
            device = 'cuda' if hw.get('cuda') else 'cpu'
    if kind == 'mlx' and device != 'mlx':
        raise ValueError('Model MLX vyžaduje Apple GPU · MLX.')
    if kind == 'ctranslate2' and device not in ('cpu', 'cuda'):
        raise ValueError('Model CTranslate2 vyžaduje CPU nebo NVIDIA CUDA.')
    if kind == 'transformers' and device == 'mlx':
        raise ValueError('Model Transformers používá na Macu MPS. Zvolte Automaticky nebo Apple GPU · MPS.')
    if device in ('mlx', 'mps') and not hw.get('apple_silicon'):
        raise ValueError('Apple GPU vyžaduje Mac s Apple Silicon.')
    if device == 'cuda' and not hw.get('cuda'):
        raise ValueError('NVIDIA GPU není dostupná. Zkontrolujte ovladače nebo vyberte CPU.')
    repo = model.get('repo_id')
    if model['format'] == 'builtin':
        repo = (MLX_MODELS if kind == 'mlx' else CT2_MODELS)[model['id']]
    return {'format': kind, 'device': device, 'repo_id': repo,
            'key': f"{model['id']}:{kind}", 'model_id': model['id']}


def validate_snapshot(path, kind):
    path = Path(path)
    config = json.loads((path / 'config.json').read_text())
    if kind == 'transformers':
        if config.get('model_type') != 'whisper' or not list(path.glob('model*.safetensors')):
            raise ValueError('Podporován je pouze Whisper Transformers s váhami Safetensors.')
        if any(not (path / f).is_file() for f in ('preprocessor_config.json', 'tokenizer_config.json')):
            raise ValueError('Model neobsahuje kompletní Whisper processor/tokenizer.')
    elif kind == 'ctranslate2':
        if not (path / 'model.bin').is_file() or not (path / 'tokenizer.json').is_file():
            raise ValueError('Chybí model.bin nebo tokenizer.json. Vyberte konvertovaný model CTranslate2.')
    elif kind == 'mlx':
        if 'n_mels' not in config or not any((path / f).is_file() for f in
                ('weights.npz', 'weights.safetensors')):
            raise ValueError('Nejde o model MLX Whisper. Původní Transformers váhy zde nelze použít.')


class ModelLibrary:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest = self.root / 'catalog.json'
        self.lock = threading.RLock()
        self.transfer_lock = threading.Lock()
        self.state = json.loads(self.manifest.read_text()) if self.manifest.exists() else {'custom': [], 'downloads': {}}
        for item in self.state['downloads'].values():
            if item.get('status') in ('queued', 'downloading'):
                item.update(status='error', error='Stažení přerušil restart. Spusťte je znovu.')
        self._save()
        self.queue = queue.Queue(maxsize=8)
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()

    def close(self):
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass

    def _save(self):
        with self.lock:
            tmp = self.manifest.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))
            tmp.replace(self.manifest)

    def catalog(self):
        with self.lock:
            models = [{'id': n, 'name': 'Whisper ' + n, 'format': 'builtin'} for n in BUILTINS]
            models += [dict(CZECH)] + [dict(m) for m in self.state['custom']]
            for m in models:
                m['downloads'] = {k.split(':', 1)[1]: {a: b for a, b in v.items() if a != 'path'}
                                  for k, v in self.state['downloads'].items() if k.startswith(m['id'] + ':')}
            return models

    def get(self, model_id):
        for model in self.catalog():
            if model['id'] == model_id:
                return model
        raise ValueError('Model není v katalogu. Nejprve ho přidejte ve správě modelů.')

    def register(self, repo_id, kind, name=''):
        repo_id = normalize_repo(repo_id)
        if kind not in FORMATS:
            raise ValueError('Neznámý formát modelu.')
        with self.lock:
            for m in self.catalog():
                if m.get('repo_id') == repo_id and m['format'] == kind:
                    return m
            model = {'id': 'custom-' + hashlib.sha256(f'{repo_id}:{kind}'.encode()).hexdigest()[:16],
                     'name': name.strip() or repo_id, 'repo_id': repo_id, 'format': kind}
            self.state['custom'].append(model)
            self._save()
            return dict(model)

    def _update(self, key, **fields):
        with self.lock:
            self.state['downloads'].setdefault(key, {}).update(fields)
            self._save()

    def enqueue(self, spec):
        with self.lock:
            state = self.state['downloads'].get(spec['key'], {})
            if state.get('status') in ('queued', 'downloading') or self._ready(spec):
                return
            previous = dict(state)
            self._update(spec['key'], status='queued', error=None, files_done=0, files_total=0)
            try:
                self.queue.put_nowait(spec)
            except queue.Full:
                self.state['downloads'][spec['key']] = previous
                self._save()
                raise ValueError('Fronta stahování je plná. Počkejte na dokončení předchozích modelů.')

    def _ready(self, spec):
        with self.lock:
            state = self.state['downloads'].get(spec['key'], {})
            path = state.get('path')
            return path if state.get('status') == 'ready' and path and Path(path).is_dir() else None

    def ensure(self, spec, report=lambda **kw: None):
        report(status='downloading', download_files_done=0, download_files_total=0)
        with self.transfer_lock:
            path = self._ready(spec)
            if path:
                return path
            try:
                return self._download(spec, report)
            except Exception as exc:
                self._update(spec['key'], status='error', error=str(exc)[:1000])
                raise

    def _download(self, spec, report):
        from huggingface_hub import snapshot_download
        from tqdm.auto import tqdm
        library, key = self, spec['key']
        self._update(key, status='downloading', error=None, files_done=0, files_total=0)

        class FileProgress(tqdm):
            def __init__(self, *args, **kwargs):
                kwargs.update(disable=False, file=io.StringIO(), mininterval=0, miniters=1)
                super().__init__(*args, **kwargs)
                self.emit()

            def emit(self):
                done, total = int(self.n), int(self.total or 0)
                library._update(key, files_done=done, files_total=total)
                report(status='downloading', download_files_done=done, download_files_total=total)

            def update(self, n=1):
                super().update(n)
                self.emit()

        FileProgress.set_lock(threading.RLock())
        cache = str(self.root.parent / 'models') if spec['format'] == 'ctranslate2' else None
        path = snapshot_download(spec['repo_id'], cache_dir=cache,
                                 allow_patterns=PATTERNS[spec['format']], tqdm_class=FileProgress,
                                 max_workers=2)
        validate_snapshot(path, spec['format'])
        self._update(key, status='ready', path=str(path), revision=Path(path).name, error=None)
        return str(path)

    def _work(self):
        while True:
            spec = self.queue.get()
            if spec is None:
                return
            try:
                self.ensure(spec)
            except Exception:
                logging.getLogger(__name__).exception('Model download failed: %s', spec['repo_id'])
            finally:
                self.queue.task_done()
