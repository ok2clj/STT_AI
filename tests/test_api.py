"""In-process ASGI tests run the real routes, middleware, lifespan and job workers."""
from contextlib import ExitStack
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

import stt.app as module


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack()
        self.addCleanup(self.stack.close)
        root=self.stack.enter_context(TemporaryDirectory())
        self.stack.enter_context(patch.object(module,'DATA',Path(root)))
        self.stack.enter_context(patch.object(module,'hardware',return_value={
            'default':'cpu','cpu':'arm64','apple_silicon':False,'cuda':False}))
        self.pause=threading.Event()
        self.resume=threading.Event()
        self.block=False
        test=self

        def fake(engine,path,model,device,language,prompt,progress):
            if path.read_bytes() == b'bad':
                raise ValueError('Invalid audio')
            progress(status='transcribing',progress=50,duration=60,processed_seconds=30)
            if test.block:
                test.pause.set()
                if not test.resume.wait(5): raise RuntimeError('Test timed out')
            return {'segments':[{'start':0,'end':1.5,'text':'Ahoj světe.'}],
                    'duration':60,'language':'cs','elapsed':0.1,'device':'cpu'}

        self.stack.enter_context(patch.object(module.Engine,'transcribe',fake))
        self.runner=asyncio.Runner()
        self.addCleanup(self.runner.close)
        self.lifespan=module.app.router.lifespan_context(module.app)
        self.runner.run(self.lifespan.__aenter__())

    def tearDown(self):
        self.resume.set()
        module.app.state.queue.join()
        self.runner.run(self.lifespan.__aexit__(None,None,None))

    def request(self,method,path,body=None,headers=None):
        async def call():
            payload=body.encode() if isinstance(body,str) else body or b''
            values={'host':'testserver',**{k.lower():v for k,v in (headers or {}).items()}}
            values['content-length']=str(len(payload))
            scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},
                   'http_version':'1.1','method':method,'scheme':'http','path':path,
                   'raw_path':path.encode(),'query_string':b'','root_path':'',
                   'headers':[(k.encode(),v.encode()) for k,v in values.items()],
                   'server':('testserver',80),'client':('127.0.0.1',12345)}
            messages=[]
            sent=False
            async def receive():
                nonlocal sent
                if not sent:
                    sent=True
                    return {'type':'http.request','body':payload,'more_body':False}
                await asyncio.Event().wait()
            async def send(message): messages.append(message)
            await module.app(scope,receive,send)
            start=next(m for m in messages if m['type']=='http.response.start')
            content=b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body')
            return start['status'],content.decode(),{k.decode():v.decode() for k,v in start['headers']}
        return self.runner.run(call())

    def json_request(self,method,path,body=None):
        status,text,_=self.request(method,path,None if body is None else json.dumps(body),
                                   {'Content-Type':'application/json'})
        return status,json.loads(text) if text else None

    def upload(self,content=b'audio',name='hlas.m4a',fields=None,origin=None):
        boundary='STTTestBoundary'
        parts=[]
        for key,value in (fields or {}).items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"'
                      '\r\nContent-Type: audio/wav\r\n\r\n').encode()+content+b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        headers={'Content-Type':f'multipart/form-data; boundary={boundary}'}
        if origin: headers['Origin']=origin
        status,text,_=self.request('POST','/api/jobs',b''.join(parts),headers)
        return status,json.loads(text)

    def wait_job(self,job_id):
        for _ in range(200):
            _,job=self.json_request('GET',f'/api/jobs/{job_id}')
            if job['status'] in ('done','error'): return job
            time.sleep(.01)
        self.fail('Worker did not finish')

    def test_upload_edit_export_persist_delete(self):
        status,job=self.upload()
        self.assertEqual(status,202)
        job=self.wait_job(job['id'])
        self.assertEqual(job['status'],'done')
        self.assertEqual(job['progress'],100)
        self.assertFalse(list((module.DATA/'uploads').iterdir()))
        prefix='/api/jobs/'+job['id']
        body={'segments':[{'start':0,'end':1.5,'text':'Upravený český přepis.'}]}
        self.assertEqual(self.json_request('PUT',prefix,body)[0],200)
        for fmt in ('txt','srt','vtt','json'):
            status,text,_=self.request('GET',prefix+'/export/'+fmt)
            self.assertEqual(status,200)
            self.assertIn('Upravený český přepis.',text)
        self.assertEqual(module.Store(module.DATA).get(job['id'])['segments'],body['segments'])
        self.assertEqual(self.request('DELETE',prefix)[0],204)
        self.assertEqual(self.request('GET',prefix)[0],404)

    def test_progress_can_be_polled_before_completion(self):
        self.block=True
        status,job=self.upload()
        self.assertEqual(status,202)
        self.assertTrue(self.pause.wait(3))
        prefix='/api/jobs/'+job['id']
        _,running=self.json_request('GET',prefix)
        self.assertEqual(running['status'],'transcribing')
        self.assertEqual(running['progress'],50)
        self.assertEqual(running['processed_seconds'],30)
        self.assertEqual(self.request('DELETE',prefix)[0],409)
        self.assertEqual(self.request('GET',prefix+'/export/txt')[0],409)
        self.resume.set()
        self.assertEqual(self.wait_job(job['id'])['progress'],100)

    def test_validation_and_origin(self):
        self.assertEqual(self.upload(name='bad.exe')[0],415)
        self.assertEqual(self.upload(content=b'')[0],400)
        self.assertEqual(self.upload(fields={'device':'wrong'})[0],422)
        self.assertEqual(self.upload(fields={'model':'unknown'})[0],400)
        self.assertEqual(self.upload(origin='https://evil.example')[0],403)
        self.assertEqual(self.request('GET','/api/jobs',headers={'Host':'evil.example'})[0],400)

    def test_failed_decode_deletes_audio(self):
        status,job=self.upload(content=b'bad')
        self.assertEqual(status,202)
        self.assertEqual(self.wait_job(job['id'])['status'],'error')
        self.assertFalse(list((module.DATA/'uploads').iterdir()))

    def test_oversize_and_invalid_timing(self):
        with patch.object(module,'MAX_BYTES',4):
            self.assertEqual(self.upload(content=b'12345')[0],413)
        module.app.state.store.put({'id':'edit','status':'done','created':time.time(),'segments':[]})
        self.assertEqual(self.json_request('PUT','/api/jobs/edit',{
            'segments':[{'start':3,'end':2,'text':'x'}]})[0],422)

    def test_model_registration_catalog_and_download(self):
        _,catalog=self.json_request('GET','/api/models')
        self.assertIn('czech-cv13',[m['id'] for m in catalog])
        status,model=self.json_request('POST','/api/models',{
            'repo_id':'https://huggingface.co/author/czech','format':'transformers','name':'Čeština'})
        self.assertEqual(status,201)
        self.assertEqual(self.json_request('POST','/api/models',{
            'repo_id':'http://evil/x','format':'transformers'})[0],400)
        lib=module.app.state.models
        def download(spec, report):
            path=module.DATA/'snapshot'
            path.mkdir(exist_ok=True)
            lib._update(spec['key'],status='ready',path=str(path),revision='test',error=None)
            return str(path)
        with patch.object(lib,'_download',download):
            self.assertEqual(self.json_request('POST','/api/models/download',{
                'model_id':model['id'],'device':'cpu'})[0],202)
            for _ in range(200):
                state=lib.get(model['id'])['downloads'].get('transformers',{})
                if state.get('status') == 'ready': break
                time.sleep(.01)
            self.assertEqual(state['status'],'ready')
        self.assertEqual(self.json_request('POST','/api/models/download',{
            'model_id':'czech-cv13','device':'mlx'})[0],400)
        self.assertEqual(self.json_request('POST','/api/models/download',{
            'model_id':'nonexistent'})[0],400)

    def test_page_and_assets_serve_with_security_headers(self):
        for path in ('/','/static/app.js','/static/style.css'):
            status,body,headers=self.request('GET',path)
            self.assertEqual(status,200)
            self.assertTrue(body)
            self.assertIn("script-src 'self'",headers['content-security-policy'])
        _,_,headers=self.request('GET','/api/models')
        self.assertEqual(headers['cache-control'],'no-store')


if __name__ == '__main__': unittest.main()
