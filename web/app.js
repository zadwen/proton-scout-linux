'use strict';
const $ = s => document.querySelector(s);
const token = location.hash.slice(1) || sessionStorage.getItem('scoutToken') || '';
sessionStorage.setItem('scoutToken', token);
history.replaceState(null, '', '/');
let system, selected, requestId = 0, searchId = 0;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date = n => n ? new Date(n * 1000).toLocaleDateString() : 'Date unknown';
async function api(path, body) {
  const result = await fetch(path, {method: body ? 'POST' : 'GET', headers: {'X-Scout-Token':token,'Content-Type':'application/json'}, ...(body ? {body:JSON.stringify(body)} : {})});
  const data = await result.json();
  if (!result.ok) throw Error(data.error || 'Request failed');
  return data;
}
function showSystem(data) {
  system = data;
  const h = data.hardware;
  const fields = [['PROCESSOR', h.cpu], ['GRAPHICS', h.gpus.join(' · ')], ['MEMORY', h.ram ? h.ram + ' GiB' : 'Unknown'], ['SYSTEM', h.os], ['SESSION / KERNEL', h.session + ' / ' + h.kernel], ['DRIVER', h.nvidia || h.drivers.join(', ') || 'Unavailable']];
  $('#hardware').innerHTML = fields.map(([k,v]) => `<div class="spec"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('');
  $('#protons').innerHTML = data.protons.length ? data.protons.map(p => `<span class="chip">${esc(p)}</span>`).join('') : 'No installed Proton tools detected';
  $('#gameCount').textContent = data.games.length + ' installed titles';
  showGames(data.games);
}
function showGames(games) {
  const box = $('#games');
  box.replaceChildren();
  if (!games.length) box.innerHTML = '<p class="muted">No titles found. Search by name or Steam app ID. For a custom library, start Scout with <code>--steam-path /path/to/SteamLibrary</code>.</p>';
  games.forEach(g => {
    const b = document.createElement('button'); b.className = 'game' + (selected?.id === g.id ? ' selected' : '');
    b.dataset.id = g.id;
    b.innerHTML = `${esc(g.name)}<small>${g.installed ? '<b>● Installed</b> · ' : ''}Steam ${esc(g.id)}</small>`;
    b.onclick = () => selectGame(g); box.append(b);
  });
}
async function selectGame(g, refresh=false) {
  selected = g;
  const id = ++requestId;
  document.querySelectorAll('.game').forEach(b => b.classList.toggle('selected', b.dataset.id === g.id));
  $('#detail').innerHTML = '<div class="card loading" role="status">Reading ProtonDB reports…<p class="muted">Checking recent PC reports and GPU matches. This may take a moment.</p></div>';
  try {
    const data = await api('/api/game?id=' + encodeURIComponent(g.id) + (refresh ? '&refresh=1' : ''));
    if (id === requestId) render(data);
  } catch(e) { if (id === requestId) $('#detail').innerHTML = `<div class="card warning">${esc(e.message)}</div>`; }
}
function render(data) {
  const a = data.analysis, s = data.summary;
  const appid = encodeURIComponent(data.id);
  const tier = s.tier || 'Unavailable';
  const stale = data.meta.some(m => m.stale);
  const fetched = data.meta.length ? Math.min(...data.meta.map(m => m.at)) : 0;
  const winner = a.ranking.find(r => r.version === a.recommendation);
  const flags = a.flags && a.flags !== '%command%' ? a.flags : '';
  $('#detail').innerHTML = `
    <div class="card"><div class="eyebrow">COMPATIBILITY BRIEF · STEAM ${esc(data.id)}</div><h2>${esc(selected.name)}</h2>
    <span class="badge">${esc(tier).toUpperCase()}</span><span class="muted">${esc(s.total ?? '—')} total ProtonDB reports · ${a.sample} PC reports analyzed</span>
    <p class="muted">Trend: ${esc(s.trendingTier || 'unknown')} · Rating confidence: ${esc(s.confidence || 'unknown')}<br>${fetched ? `Data fetched ${date(fetched)}${stale ? ' · OFFLINE / STALE CACHE' : ''}` : 'No live data timestamp'}</p>
    <div class="links"><a href="https://www.protondb.com/app/${appid}" target="_blank" rel="noreferrer">Read ProtonDB ↗</a><a href="https://store.steampowered.com/app/${appid}" target="_blank" rel="noreferrer">Steam store ↗</a><a href="https://github.com/ValveSoftware/Proton/issues?q=${encodeURIComponent('is:issue ' + data.id)}" target="_blank" rel="noreferrer">Valve issue reports ↗</a></div>
    ${data.errors.length ? `<details><summary>Data availability (${data.errors.length})</summary><p class="warning">${data.errors.map(esc).join('<br>')}</p></details>` : ''}
    <div class="buttons"><button id="refresh" class="secondary">Refresh reports</button><button id="import" class="secondary">Import report JSON</button></div></div>
    <div class="card result"><div class="eyebrow">${a.recommendation ? 'COMMUNITY-SUPPORTED CANDIDATE' : 'NO SUPPORTED WINNER'}</div>
    <div class="version">${esc(a.recommendation || 'Start with Steam’s default')}</div><span class="badge">${esc(a.confidence)}</span>
    <p>${winner ? `${winner.positive} positive / ${winner.negative} negative reports for this version; ${winner.matching} match your GPU vendor. These counts include reports up to one year old.` : esc(a.fallback)}</p>
    <p>${esc(a.explanation)}</p>
    ${system.hardware.gpus.length > 1 ? '<p class="warning">Multiple GPUs detected: vendor matching includes both. Check the report’s GPU against the GPU actually running your game.</p>' : ''}
    <h3>Launch options</h3><div class="flags">${esc(flags || 'Leave launch options empty')}</div>
    <p>${flags ? `This complete option string appears in ${a.flagReports} positive reports within 180 days, for the candidate version and a matching GPU vendor. Review the reports before testing it.` : 'No repeated, eligible launch-option string was found. An empty field is a baseline, not proof that no tweaks are needed.'}</p>
    ${flags ? '<button id="copy" class="secondary">Copy launch options</button>' : ''}
    <details><summary>Apply & test in Steam</summary><p>Game → Properties → Compatibility → choose the exact candidate if available. Launch options go in Properties → General. A reported version may need installation separately.</p><p>Test the same scene and graphics settings before and after. Compare frame time and FPS. Change one setting at a time. Remove options to undo them.</p><p>Check online modes separately: a working single-player report does not establish multiplayer or anti-cheat support.</p><p>Installed helpers: GameMode ${system.hardware.gamemode ? 'detected' : 'not detected'} · MangoHud ${system.hardware.mangohud ? 'detected' : 'not detected'}. Host detection does not verify availability inside Flatpak Steam.</p></details></div>
    ${a.ranking.length ? `<div class="card"><h3>Version comparison · last 365 days</h3><div class="tablewrap"><table><thead><tr><th>Proton</th><th>Works / fails</th><th>GPU match</th><th>Evidence score¹</th></tr></thead><tbody>${a.ranking.map(r => `<tr><td>${esc(r.version)}</td><td>${r.positive} / ${r.negative}</td><td>${r.matching}</td><td>${r.score.toFixed(2)}</td></tr>`).join('')}</tbody></table></div><p class="muted">¹ A ranking score, not a performance estimate or probability. Only this fetched sample is compared.</p></div>` : ''}
    <div class="card"><h3>What people reported</h3><p class="muted">PC reports only · newest first · GPU match means vendor, not an identical configuration. Unsupported command strings stay in notes and are never executed.</p>
    ${a.reports.length ? a.reports.slice(0,40).map(r => `<article class="report"><span class="badge">${r.success === true ? 'WORKS' : r.success === false ? 'ISSUES' : 'UNCLASSIFIED'}</span><strong>${esc(r.version || 'Version unknown')}</strong><div class="meta">${date(r.timestamp)} · ${esc(r.gpu || 'GPU unknown')}${r.match ? ' · SAME GPU VENDOR' : ''}<br>${esc(r.os)} · ${esc(r.cpu)}<br>${esc(r.driver)} · ${esc(r.kernel)}</div>${r.launchOptions ? `<p class="flags">Reported options (unverified):\n${esc(r.launchOptions)}</p>` : ''}<p>${esc(r.notes.slice(0,700) || 'No written notes.')}</p>${r.notes.length > 700 ? `<details><summary>Full report notes</summary><p>${esc(r.notes)}</p></details>` : ''}<a class="muted" href="${esc(r.source)}" target="_blank" rel="noreferrer">Source: ProtonDB game reports ↗</a></article>`).join('') : '<p class="muted">No detailed reports available. Open ProtonDB to check the latest community feedback, or import saved report JSON.</p>'}
    ${a.reports.length > 40 ? `<p class="muted">Showing 40 of ${a.reports.length} analyzed reports.</p>` : ''}</div>`;
  $('#refresh').onclick = () => selectGame(selected, true);
  $('#import').onclick = () => $('#importFile').click();
  if ($('#copy')) $('#copy').onclick = async () => {
    try { await navigator.clipboard.writeText(flags); $('#copy').textContent = 'Copied'; }
    catch { $('#copy').textContent = 'Select the option text above to copy'; }
  };
}
$('#search').onsubmit = async e => {
  e.preventDefault(); const q = $('#query').value.trim(), id = ++searchId;
  $('#status').textContent = 'Searching…';
  try { const d = await api('/api/search?q=' + encodeURIComponent(q)); if(id !== searchId) return; showGames(d.games); $('#status').textContent = d.error ? 'Online search unavailable. Installed matches are shown. ' + d.error : d.games.length + ' matches'; }
  catch(e) { if(id === searchId) $('#status').textContent = e.message; }
};
$('#installed').onclick = () => { ++searchId; $('#query').value=''; showGames(system?.games || []); $('#status').textContent=''; };
$('#rescan').onclick = async () => {
  $('#rescan').disabled = true;
  try { showSystem(await api('/api/rescan', {})); $('#status').textContent = 'Hardware and Steam library rescanned.'; }
  catch(e) { $('#status').textContent=e.message; }
  finally { $('#rescan').disabled=false; }
};
$('#importFile').onchange = async e => {
  const file = e.target.files[0], game = selected;
  if (!file || !game) return;
  try {
    if(file.size > 7_500_000) throw Error('Choose a per-game JSON file smaller than 7.5 MB.');
    const raw = JSON.parse(await file.text());
    const rows = Array.isArray(raw) ? raw : raw.reports;
    if(!Array.isArray(rows)) throw Error('Expected a JSON array or an object containing reports.');
    if (selected?.id !== game.id) return;
    const id = ++requestId;
    const result = await api('/api/import', {id:game.id, reports:rows});
    if(id === requestId) render(result);
  } catch(e) { $('#status').textContent=e.message; }
  finally { e.target.value=''; }
};
$('#quit').onclick = async () => { await api('/api/quit', {}); document.body.innerHTML='<main><h1>Scout is closed.</h1><p>You can close this tab.</p></main>'; };
api('/api/system').then(showSystem).catch(e => $('#status').textContent = e.message);
