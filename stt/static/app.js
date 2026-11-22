'use strict';
const $ = id => document.getElementById(id);
let current = null, dirty = false, objectUrl = null, chosenFile = null, submitting = false;
let noticeTimer, polling = false, catalog = [], hw = {}, modelFetchKey = '';
const modelLabels = {queued:'Čeká na stažení',downloading:'Stahování',ready:'Staženo',error:'Chyba stažení'};
const labels = {queued:'Ve frontě', loading:'Načítání modelu', downloading:'Příprava / stahování modelu', decoding:'Načítání audia', saving:'Ukládání přepisu', transcribing:'Přepisování', done:'Dokončeno', error:'Chyba'};
function notice(text) { $('notice').textContent = text; $('notice').hidden = false; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => $('notice').hidden = true, 6000); }
async function api(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Požadavek se nezdařil (${response.status}).`);
  }
  return response.status === 204 ? null : response.json();
}
function time(seconds) { const s = Math.floor(seconds || 0); return `${String(Math.floor(s/3600)).padStart(2,'0')}:${String(Math.floor(s%3600/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`; }
function mayLeave() { return !dirty || confirm('Máte neuložené úpravy. Opravdu je chcete zahodit?'); }
function showNew() { if (!mayLeave()) return; current = null; dirty = false; $('upload-view').hidden = false; $('result-view').hidden = true; refreshHistory().catch(e => notice(e.message)); }
$('new').onclick = $('back').onclick = showNew;
function selectFile(file) {
  chosenFile = file;
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = URL.createObjectURL(file);
  $('preview').src = objectUrl; $('preview').hidden = false;
  $('file-title').textContent = file.name;
  $('file-detail').textContent = `${(file.size / 1024 / 1024).toFixed(1)} MB · kliknutím soubor změníte`;
}
$('file').onchange = () => { if ($('file').files[0]) selectFile($('file').files[0]); };
for (const type of ['dragover','dragleave','drop']) $('drop').addEventListener(type, e => {
  e.preventDefault(); $('drop').classList.toggle('dragover', type === 'dragover');
  if (type === 'drop' && e.dataTransfer.files[0]) { selectFile(e.dataTransfer.files[0]); $('file').required = false; }
});
$('upload-form').onsubmit = async e => {
  e.preventDefault(); if (submitting) return;
  if (!chosenFile) return notice('Nejprve vyberte nahrávku.');
  submitting = true; $('submit').disabled = true; $('submit').textContent = 'Nahrávám soubor…';
  try {
    const data = new FormData($('upload-form')); data.set('file', chosenFile);
    const job = await api('/api/jobs', {method:'POST', body:data});
    await openJob(job.id);
  } catch(e) { notice(e.message); }
  finally { submitting = false; $('submit').disabled = false; $('submit').textContent = 'Přepsat nahrávku ↗'; }
};
async function refreshHistory() {
  const jobs = await api('/api/jobs'); $('count').textContent = jobs.length; $('history').replaceChildren();
  if (!jobs.length) { const p = document.createElement('p'); p.className='empty'; p.textContent='Zatím tu nejsou žádné přepisy.'; $('history').append(p); }
  for (const j of jobs) {
    const b = document.createElement('button'); b.className = current?.id === j.id ? 'active' : ''; b.textContent = j.filename; b.title = j.filename;
    const small = document.createElement('small'); small.textContent = `${labels[j.status] || j.status}${j.status === 'transcribing' ? ' '+(j.progress || 0)+' %' : ''} · ${new Date(j.created * 1000).toLocaleDateString('cs')}`; b.append(small);
    b.onclick = () => { if(mayLeave()) openJob(j.id).catch(e => notice(e.message)); }; $('history').append(b);
  }
}
async function openJob(id) {
  const job = await api(`/api/jobs/${id}`);
  current = job; dirty = false; $('upload-view').hidden = true; $('result-view').hidden = false;
  renderJob(job); await refreshHistory();
}
function updateCount() {
  const text = [...$('segments').querySelectorAll('textarea')].map(t => t.value).join(' ');
  $('word-count').textContent = `${text.trim() ? text.trim().split(/\s+/u).length : 0} slov${dirty ? ' · neuložené úpravy' : ''}`;
}
function renderJob(j) {
  $('result-title').textContent = j.filename;
  $('result-meta').textContent = `${j.model_name || j.model} · ${j.device || j.requested_device} · ${j.language || 'automatický jazyk'}${j.duration ? ' · '+time(j.duration) : ''}${j.elapsed ? ' · zpracováno za '+j.elapsed+' s' : ''}${j.status === 'done' ? ' · Dokončeno 100 %' : ''}`;
  $('processing').hidden = ['done','error'].includes(j.status);
  $('result-content').hidden = j.status !== 'done'; $('job-error').hidden = j.status !== 'error';
  if (j.status === 'error') { $('job-error').textContent = j.error; addErrorDelete(j); }
  if (!$('processing').hidden) {
    $('status-label').textContent = labels[j.status] || j.status;
    const active = ['transcribing','saving'].includes(j.status);
    $('percent').hidden = !active;
    $('progress-note').hidden = !active;
    $('percent').textContent = `${Number(j.progress || 0).toLocaleString('cs')} %`;
    if (active) {
      $('progress').value = j.progress || 0;
      $('status-detail').textContent = `${time(j.processed_seconds)} z ${time(j.duration)} audia${j.status === 'saving' ? ' · ukládám výsledek' : ''}`;
    } else {
      $('progress').removeAttribute('value');
      const messages = {queued:'Čeká na dokončení předchozích úloh.',loading:'Načítám model do paměti. Tato fáze se nezapočítává do přepisu.',decoding:'Připravuji zvukovou stopu a zjišťuji její délku.',downloading:'Kontroluji nebo stahuji model. První použití může trvat několik minut.'};
      $('status-detail').textContent = messages[j.status] || '';
      if (j.status === 'downloading' && j.download_files_total) $('status-detail').textContent += ` Hotovo ${j.download_files_done || 0} z ${j.download_files_total} souborů (nikoli bajtů).`;
    }
  }
  if (j.status === 'done') {
    $('segments').replaceChildren();
    if (!j.segments.length) { const p = document.createElement('p'); p.textContent='V nahrávce nebyla rozpoznána řeč.'; $('segments').append(p); }
    j.segments.forEach((s,i) => {
      const row = document.createElement('div'); row.className='segment';
      const clock = document.createElement('time'); clock.textContent=time(s.start);
      const input = document.createElement('textarea'); input.value=s.text; input.setAttribute('aria-label',`Text úseku ${i+1} v čase ${time(s.start)}`);
      input.oninput = () => { dirty=true; updateCount(); }; row.append(clock,input); $('segments').append(row);
    }); updateCount();
  }
}
function editedSegments() { return [...$('segments').querySelectorAll('textarea')].map((t,i) => ({...current.segments[i],text:t.value})); }
async function save() {
  if (!current || current.status !== 'done') return;
  const id=current.id, segments=editedSegments();
  await api(`/api/jobs/${id}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({segments})});
  if (current?.id === id) { current.segments=segments; dirty=false; updateCount(); }
}
$('save').onclick = async () => { try { await save(); notice('Úpravy byly uloženy.'); } catch(e) { notice(e.message); } };
$('copy').onclick = async () => { try { await navigator.clipboard.writeText(editedSegments().map(s => s.text).join('\n')); notice('Přepis zkopírován.'); } catch { notice('Kopírování není dostupné. Stáhněte přepis jako TXT.'); } };
document.querySelectorAll('[data-export]').forEach(b => b.onclick = async () => {
  try { const id=current.id; await save(); const a=document.createElement('a'); a.href=`/api/jobs/${id}/export/${b.dataset.export}`; a.download=''; a.click(); } catch(e) { notice(e.message); }
});
async function removeJob() {
  if (!current || !confirm('Smazat tento přepis z místní historie?')) return;
  try { await api(`/api/jobs/${current.id}`, {method:'DELETE'}); dirty=false; showNew(); } catch(e) { notice(e.message); }
}
$('delete').onclick=removeJob;
function addErrorDelete() { const b=document.createElement('button'); b.textContent='Smazat neúspěšný přepis'; b.onclick=removeJob; $('job-error').append(document.createElement('br'),document.createElement('br'),b); }
window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue=''; } });
async function poll() {
  if(polling) return; polling=true;
  try {
    if (current && !['done','error'].includes(current.status)) {
      const id=current.id, job=await api(`/api/jobs/${id}`);
      if (current?.id===id) { current=job; renderJob(job); }
    }
    await refreshHistory();
    await refreshModels();
  } catch(e) { notice('Spojení se serverem se nezdařilo. '+e.message); }
  finally { polling=false; setTimeout(poll,2500); }
}
function modelKind(m) {
  if(m.format !== 'builtin') return m.format;
  const d=$('device').value;
  return d === 'mlx' || (d === 'auto' && hw.apple_silicon) ? 'mlx' : 'ctranslate2';
}
function modelHint() {
  const m=catalog.find(m=>m.id === $('model').value);
  if (!m) return;
  const kind=modelKind(m), download=m.downloads[kind], ready=download?.status === 'ready';
  $('model-hint').textContent = `${kind === 'transformers' ? 'Transformers · na Macu používá MPS, na NVIDIA CUDA. ' : kind === 'mlx' ? 'MLX · Apple GPU. ' : 'CTranslate2 · CPU / NVIDIA CUDA. '}${ready ? 'Model je stažený.' : 'Model se stáhne při prvním přepisu nebo tlačítkem ve správě modelů.'}`;
}
async function refreshModels() {
  const models=await api('/api/models');
  const key=JSON.stringify([models,$('device').value]);
  if(key === modelFetchKey) return;
  modelFetchKey=key; catalog=models;
  const selected=$('model').value || 'small';
  $('model').replaceChildren(); $('model-list').replaceChildren();
  for(const m of models) {
    const kind=modelKind(m), state=m.downloads[kind];
    const option=document.createElement('option'); option.value=m.id;
    option.textContent=`${m.name}${state?.status === 'ready' ? ' · staženo' : ''}`;
    $('model').append(option);
    const row=document.createElement('div'); row.className='model-row';
    const content=document.createElement('div');
    const title=document.createElement('strong'); title.textContent=m.name;
    const repo=document.createElement('small'); repo.textContent=m.repo_id || `Základní Whisper · ${kind}`;
    const status=document.createElement('small'); status.className='model-status';
    status.textContent=state ? `${modelLabels[state.status] || state.status}${state.status === 'downloading' && state.files_total ? ' · '+state.files_done+'/'+state.files_total+' souborů' : ''}` : 'Zatím nestaženo';
    content.append(title,repo,status);
    if(state?.error) { const err=document.createElement('small'); err.className='model-download-error'; err.textContent=state.error; content.append(err); }
    const button=document.createElement('button'); button.type='button';
    button.textContent=state?.status === 'ready' ? 'Použít' : ['queued','downloading'].includes(state?.status) ? 'Stahuji…' : 'Stáhnout';
    button.disabled=['queued','downloading'].includes(state?.status);
    button.onclick=async()=> {
      if(state?.status === 'ready') { $('model').value=m.id; modelHint(); notice('Model vybrán pro nový přepis.'); return; }
      button.disabled=true;
      try { await api('/api/models/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_id:m.id,device:$('device').value})}); await refreshModels(); }
      catch(e) { notice(e.message); button.disabled=false; }
    };
    row.append(content,button); $('model-list').append(row);
  }
  if(models.some(m=>m.id === selected)) $('model').value=selected;
  modelHint();
}
$('model').onchange=modelHint;
$('device').onchange=()=>{ modelFetchKey=''; refreshModels().catch(e=>notice(e.message)); };
$('model-add-form').onsubmit=async e=> {
  e.preventDefault(); const button=e.target.querySelector('button[type=submit]'); button.disabled=true;
  try {
    const model=await api('/api/models',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({repo_id:$('model-repo').value,format:$('model-format').value,name:$('model-name').value})});
    await refreshModels(); $('model').value=model.id; modelHint(); notice('Model přidán. Nyní jej můžete stáhnout.');
  } catch(e) { notice(e.message); } finally { button.disabled=false; }
};
async function init() {
  try {
    const info=await api('/api/info'); hw=info.hardware; $('limit').textContent=info.max_upload_mb;
    $('hardware').textContent=hw.apple_silicon ? 'Apple Silicon · GPU MLX / ARM CPU' : hw.cuda ? 'NVIDIA CUDA GPU · CPU' : `CPU · ${hw.cpu}`;
    $('device').querySelector('[value=mlx]').disabled=!hw.apple_silicon;
    $('device').querySelector('[value=cuda]').disabled=!hw.cuda;
    $('device').querySelector('[value=mps]').disabled=!hw.apple_silicon;
    await refreshModels();
    await refreshHistory();
  } catch(e) { notice(e.message); }
  poll();
}
init();
