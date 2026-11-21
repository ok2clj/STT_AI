'use strict';
const $ = id => document.getElementById(id);
let current = null, dirty = false, objectUrl = null, chosenFile = null, submitting = false;
let noticeTimer, polling = false;
const labels = {queued:'Ve frontě', loading:'Načítání modelu', transcribing:'Přepisování', done:'Dokončeno', error:'Chyba'};
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
    const small = document.createElement('small'); small.textContent = `${labels[j.status]} · ${new Date(j.created * 1000).toLocaleDateString('cs')}`; b.append(small);
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
  $('result-meta').textContent = `${j.model} · ${j.device || j.requested_device} · ${j.language || 'automatický jazyk'}${j.duration ? ' · '+time(j.duration) : ''}${j.elapsed ? ' · zpracováno za '+j.elapsed+' s' : ''}`;
  $('processing').hidden = ['done','error'].includes(j.status);
  $('result-content').hidden = j.status !== 'done'; $('job-error').hidden = j.status !== 'error';
  if (j.status === 'error') { $('job-error').textContent = j.error; addErrorDelete(j); }
  if (!$('processing').hidden) {
    $('status-label').textContent = labels[j.status];
    $('status-detail').textContent = j.status === 'queued' ? 'Čeká na dokončení předchozích úloh.' : j.status === 'loading' ? 'Při prvním použití se model stahuje. To může trvat několik minut.' : j.device === 'mlx' ? 'Apple GPU zpracovává nahrávku. První použití zahrnuje stažení modelu; průběh v procentech není dostupný.' : `Přepsáno ${j.progress || 0} % nahrávky.`;
    if (j.device === 'mlx' || j.status !== 'transcribing') $('progress').removeAttribute('value'); else $('progress').value=j.progress;
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
  } catch(e) { notice('Spojení se serverem se nezdařilo. '+e.message); }
  finally { polling=false; setTimeout(poll,2500); }
}
async function init() {
  try {
    const info=await api('/api/info'), hw=info.hardware; $('limit').textContent=info.max_upload_mb;
    $('hardware').textContent=hw.apple_silicon ? 'Apple Silicon · GPU MLX / ARM CPU' : hw.cuda ? 'NVIDIA CUDA GPU · CPU' : `CPU · ${hw.cpu}`;
    $('device').querySelector('[value=mlx]').disabled=!hw.apple_silicon;
    $('device').querySelector('[value=cuda]').disabled=!hw.cuda;
    await refreshHistory();
  } catch(e) { notice(e.message); }
  poll();
}
init();
