"""API integration tests replace inference only; no model download is needed."""
import time

from fastapi.testclient import TestClient
import pytest

import stt.app as module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'DATA', tmp_path)
    monkeypatch.setattr(module, 'hardware', lambda: {"default":"cpu", "cpu":"arm64"})

    def fake(self, path, model, device, language, prompt, progress):
        if path.read_bytes() == b'bad':
            raise ValueError('Invalid audio')
        assert path.read_bytes() == b'audio'
        progress(status='transcribing', progress=50)
        return {"segments":[{"start":0, "end":1.5, "text":"Ahoj světe."}],
                "duration":1.5, "language":"cs", "elapsed":0.1, "device":"cpu"}

    monkeypatch.setattr(module.Engine, 'transcribe', fake)
    with TestClient(module.app) as c:
        yield c


def wait_job(client, job_id):
    for _ in range(100):
        job = client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in ('done', 'error'):
            return job
        time.sleep(.02)
    pytest.fail('Worker did not finish')


def test_upload_edit_export_persist_delete(client):
    response = client.post('/api/jobs', files={'file':('hlas.m4a', b'audio')})
    assert response.status_code == 202
    job = wait_job(client, response.json()['id'])
    assert job['status'] == 'done'
    job_id = job['id']
    assert not list((module.DATA / 'uploads').iterdir())
    body = {'segments':[{'start':0, 'end':1.5, 'text':'Upravený český přepis.'}]}
    assert client.put(f'/api/jobs/{job_id}', json=body).status_code == 200
    for fmt in ('txt', 'srt', 'vtt', 'json'):
        export = client.get(f'/api/jobs/{job_id}/export/{fmt}')
        assert export.status_code == 200
        assert 'Upravený český přepis.' in export.text
    assert module.Store(module.DATA).get(job_id)['segments'] == body['segments']
    assert client.delete(f'/api/jobs/{job_id}').status_code == 204
    assert client.get(f'/api/jobs/{job_id}').status_code == 404


def test_validation_and_origin(client):
    assert client.post('/api/jobs', files={'file':('bad.exe', b'audio')}).status_code == 415
    assert client.post('/api/jobs', files={'file':('empty.wav', b'')}).status_code == 400
    assert client.post('/api/jobs', files={'file':('a.wav', b'audio')}, data={'device':'wrong'}).status_code == 422
    assert client.post('/api/jobs', headers={'Origin':'https://evil.example'},
                       files={'file':('a.wav', b'audio')}).status_code == 403
    assert client.get('/api/jobs', headers={'Host':'evil.example'}).status_code == 400


def test_failed_decode_deletes_audio(client):
    response = client.post('/api/jobs', files={'file':('broken.wav', b'bad')})
    job = wait_job(client, response.json()['id'])
    assert job['status'] == 'error'
    # Terminal status is written just before the finally block deletes the file.
    for _ in range(100):
        if not list((module.DATA / 'uploads').iterdir()):
            break
        time.sleep(.01)
    assert not list((module.DATA / 'uploads').iterdir())
    assert client.get(f"/api/jobs/{job['id']}/export/txt").status_code == 409


def test_oversize_and_invalid_timing(client, monkeypatch):
    monkeypatch.setattr(module, 'MAX_BYTES', 4)
    assert client.post('/api/jobs', files={'file':('big.wav', b'12345')}).status_code == 413
    job = {'id':'edit-test', 'status':'done', 'created':time.time(), 'segments':[]}
    module.app.state.store.put(job)
    assert client.put('/api/jobs/edit-test', json={'segments':[{'start':3, 'end':2, 'text':'x'}]}).status_code == 422
