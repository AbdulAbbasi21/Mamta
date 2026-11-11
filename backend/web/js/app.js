// Mamta web app — plain JavaScript single-page app (hash routing).
// Talks to the FastAPI backend; API keys never reach the browser.
// ===================== config & API =====================
const API = location.protocol.startsWith('http') ? location.origin : 'http://localhost:8000';
let LHW_ID = 'lhw_shazia';

// ===================== login session (per browser tab/window) =====================
let SESSION = null;
try { SESSION = JSON.parse(sessionStorage.getItem('mamta_session') || 'null'); } catch { SESSION = null; }
function setSession(s) {
  SESSION = s;
  try { s ? sessionStorage.setItem('mamta_session', JSON.stringify(s)) : sessionStorage.removeItem('mamta_session'); } catch {}
  if (s && s.role === 'lhw') LHW_ID = s.id;
  if (s && s.role === 'mother') M.id = s.id;
}
function logout() { setSession(null); consentGiven = false; resetMother(); go('#home'); }
function updateHeader() {
  const b = $('#homeBtn');
  if (SESSION) { b.textContent = `⎋ Logout (${SESSION.name})`; b.onclick = logout; }
  else { b.textContent = '⌂ Home'; b.onclick = () => go('#home'); }
}
const MOTHERS = [['m_ayesha','Ayesha Bibi (day 2)'],['m_fatima','Fatima Noor (day 5)'],['m_rukhsana','Rukhsana Akhtar (day 9)'],
                 ['m_saima','Saima Parveen (day 14)'],['m_nasreen','Nasreen Kausar (day 28)'],['m_kiran','Kiran Shahzadi (day 40)']];
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function api(path, opts = {}) {
  const r = await fetch(API + path, opts);
  const t = await r.text();
  if (!r.ok) throw new Error(`Server ${r.status}: ${t.slice(0, 200)}`);
  return JSON.parse(t);
}
const postForm = (path, fields, file, fileField, filename) => {
  const fd = new FormData();
  Object.entries(fields).forEach(([k, v]) => v != null && fd.append(k, v));
  if (file) fd.append(fileField, file, filename);
  return api(path, { method: 'POST', body: fd });
};
const postJson = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

function toast(msg) { const d = document.createElement('div'); d.className = 'toast'; d.textContent = msg; document.body.appendChild(d); setTimeout(() => d.remove(), 3500); }
const aiTag = (src) => src === 'fixture' ? '<span class="ai off">✦ recorded demo response (offline)</span>'
  : src === 'offline_rules' ? '<span class="ai off">⚙ offline rule-based screening (AI busy)</span>'
  : src === 'fallback' ? '<span class="ai off">⚠ AI busy — safe fallback</span>'
  : '<span class="ai">✦ AI-generated</span>';
const disclaimer = '<div class="disc"><div class="ur">یہ صرف اسکریننگ ہے، طبی تشخیص نہیں</div>Screening result — not a medical diagnosis</div>';
const loading = (ur, en) => `<div class="loading"><div class="spinner"></div><div class="ur" style="font-size:20px">${ur}</div><div class="muted">${en}</div></div>`;

// ===================== audio: record WAV, play replies =====================
let mediaRec = null, chunks = [], micStream = null;
async function startRec() {
  micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  chunks = [];
  mediaRec = new MediaRecorder(micStream);
  mediaRec.ondataavailable = e => e.data.size && chunks.push(e.data);
  mediaRec.start();
}
function stopRec() {   // -> Promise<Blob WAV 16 kHz mono> (Gemini accepts WAV)
  return new Promise(resolve => {
    mediaRec.onstop = async () => {
      micStream.getTracks().forEach(t => t.stop());
      const blob = new Blob(chunks, { type: mediaRec.mimeType });
      try { resolve(await toWav(blob)); } catch (e) { console.warn('WAV convert failed', e); resolve(blob); }
    };
    mediaRec.stop();
  });
}
async function toWav(blob) {
  const buf = await blob.arrayBuffer();
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const decoded = await ctx.decodeAudioData(buf);
  const rate = 16000, len = Math.ceil(decoded.duration * rate);
  const off = new OfflineAudioContext(1, len, rate);
  const src = off.createBufferSource(); src.buffer = decoded; src.connect(off.destination); src.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const w = (o, s) => [...s].forEach((c, i) => out.setUint8(o + i, c.charCodeAt(0)));
  w(0, 'RIFF'); out.setUint32(4, 36 + pcm.length * 2, true); w(8, 'WAVE'); w(12, 'fmt ');
  out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
  out.setUint32(24, rate, true); out.setUint32(28, rate * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true);
  w(36, 'data'); out.setUint32(40, pcm.length * 2, true);
  pcm.forEach((v, i) => out.setInt16(44 + i * 2, Math.max(-1, Math.min(1, v)) * 0x7fff, true));
  ctx.close();
  return new Blob([out], { type: 'audio/wav' });
}
let player = null;
function speak(b64, text) {
  try {
    if (player) player.pause();
    speechSynthesis.cancel();
    if (b64) { player = new Audio(`data:${b64.startsWith('UklGR') ? 'audio/wav' : 'audio/mpeg'};base64,` + b64); player.play(); return; }
    const u = new SpeechSynthesisUtterance(text); u.lang = 'ur-PK'; u.rate = 0.9;
    const v = speechSynthesis.getVoices().find(v => v.lang.startsWith('ur')); if (v) u.voice = v;
    speechSynthesis.speak(u);
  } catch (e) { console.warn(e); }
}

// ===================== router =====================
let timers = [];
function clearTimers() { timers.forEach(clearInterval); timers = []; if (typeof fsUnsub === 'function') { fsUnsub(); fsUnsub = null; } }
function go(hash) { location.hash = hash; }
window.addEventListener('hashchange', route);
function route() {
  clearTimers(); $('#fabs').innerHTML = ''; $('#live').style.display = 'none';
  const [page, arg] = (location.hash || '#home').slice(1).split('/');
  if (SESSION) setSession(SESSION);
  updateHeader();
  // Route guards: each role only sees its own screens
  const needs = { mother: 'mother', lhw: 'lhw', scan: 'lhw', visit: 'lhw' }[page];
  if (needs && (!SESSION || SESSION.role !== needs)) return go('#login/' + needs);
  ({ home, mother, lhw, scan, visit, login }[page] || home)(arg);
}

// ===================== HOME =====================
async function home() {
  $('#title').textContent = 'Mamta  ممتا';
  $('#view').innerHTML = `
    <div class="center" style="margin:8px 0 4px"><img src="img/logo.png" alt="Mamta logo" style="width:190px;height:190px;border-radius:50%;background:#fff;box-shadow:0 6px 24px rgba(142,31,74,.18)"></div>
    <h1 class="center" style="margin:6px 0 0;color:var(--rose);font-size:40px">Mamta <span class="ur" style="font-size:38px">ممتا</span></h1>
    <p class="muted center" style="font-size:17px;margin-top:4px">Voice-first postnatal care for new mothers · <b>AI screens, the LHW decides.</b></p>
    <div class="modes">
      <div class="mode" style="background:var(--rose)" onclick="go(SESSION?.role === 'mother' ? '#mother' : '#login/mother')"><div class="icon">🎙️</div><div class="ur">ماں</div><div class="en">Mother</div></div>
      <div class="mode" style="background:#37474F" onclick="go(SESSION?.role === 'lhw' ? '#lhw' : '#login/lhw')"><div class="icon">🩺</div><div class="ur">لیڈی ہیلتھ ورکر</div><div class="en">Lady Health Worker</div></div>
    </div>
    <p class="center"><button class="btn out" onclick="resetDemo()">↻ Reset demo data</button></p>
    <p class="center muted" id="status" style="font-size:12px">Checking server…</p>`;
  const st = (t) => { const el = $('#status'); if (el) el.textContent = t; };
  try { const h = await api('/health'); st(`Server OK · db: ${h.db} · demo mode: ${h.demoMode} · model: ${h.model} · Gemini key: ${h.geminiKey ? 'yes' : 'NO'}`); }
  catch { st('Server not reachable at ' + API); }
}
// ===================== LOGIN =====================
function login(role) {
  const isM = role === 'mother';
  $('#title').textContent = isM ? 'ماں · Mother login' : 'Lady Health Worker login';
  $('#view').innerHTML = `<div class="card" style="max-width:520px;margin:30px auto;text-align:center">
    <img src="img/logo.png" alt="Mamta logo" style="width:120px;height:120px;border-radius:50%"><div style="font-size:36px;margin-top:-8px">${isM ? '🎙️' : '🩺'}</div>
    <h2 style="margin:4px 0">${isM ? '<span class="ur" style="font-size:30px">ماں</span> · Mother' : '<span class="ur" style="font-size:26px">لیڈی ہیلتھ ورکر</span><br>Lady Health Worker'}</h2>
    <label style="display:block;text-align:left;margin-top:14px"><span class="ur" style="font-size:18px">${isM ? 'اپنا موبائل نمبر لکھیں' : 'موبائل نمبر'}</span> · Mobile number
      <input id="lgPhone" class="txt" type="tel" inputmode="numeric" placeholder="03XX XXXXXXX" style="font-size:24px;text-align:center;margin-top:6px"></label>
    ${isM ? '' : `<label style="display:block;text-align:left;margin-top:12px">PIN
      <input id="lgPin" class="txt" type="password" inputmode="numeric" maxlength="6" placeholder="••••" style="font-size:24px;text-align:center;margin-top:6px"></label>`}
    <button class="btn" style="width:100%;margin-top:18px;font-size:20px;padding:16px" onclick="doLogin('${role}')">${isM ? '<span class="ur">داخل ہوں</span> · Enter' : 'Log in'}</button>
    <p id="lgErr" style="color:var(--red);font-weight:600"></p>
    <details style="text-align:left" class="muted"><summary>Demo accounts</summary>
      ${isM ? MOTHERS.map(([id, n], i) => `<button class="btn out" style="margin:4px;padding:6px 10px;font-size:13px" onclick="$('#lgPhone').value='0300000000${i + 1}'">${n} · 0300000000${i + 1}</button>`).join('')
            : `<button class="btn out" style="margin:4px;padding:6px 10px;font-size:13px" onclick="$('#lgPhone').value='03001234567';$('#lgPin').value='1234'">Shazia Bibi · 03001234567 · PIN 1234</button>`}
    </details>
    <p class="muted" style="font-size:12px">Demo login for the hackathon. Production: Firebase Authentication with phone OTP.</p></div>`;
  const enter = (e) => e.key === 'Enter' && doLogin(role);
  $('#lgPhone').onkeydown = enter; if ($('#lgPin')) $('#lgPin').onkeydown = enter;
  $('#lgPhone').focus();
}
async function doLogin(role) {
  try {
    const body = { phone: $('#lgPhone').value, ...(role === 'lhw' ? { pin: $('#lgPin').value } : {}) };
    const s = await postJson('/auth/' + role, body);
    consentGiven = false; resetMother();
    setSession(s);
    go(role === 'mother' ? '#mother' : '#lhw');
  } catch (e) {
    $('#lgErr').textContent = role === 'mother' ? 'یہ نمبر رجسٹرڈ نہیں · This number is not registered' : 'Wrong phone number or PIN';
  }
}

async function resetDemo() { try { await api('/demo/reset', { method: 'POST' }); toast('Demo data reset'); } catch (e) { toast(e.message); } }

// ===================== MOTHER =====================
let consentGiven = false;
const M = { id: 'm_fatima', history: [], phase: 'idle', last: null, pending: null };
function mother() {
  $('#title').textContent = 'ممتا · Mother check-in';
  if (!consentGiven) return showConsent();
  renderMother(); loadAppts();
  api('/mothers/' + M.id).then(m => { const el = $('#mname'); if (el) el.textContent = `${m.name} · ${m.daysPostpartum} days after delivery`; }).catch(() => {});
}
function showConsent() {
  $('#view').innerHTML = `<div class="card" style="max-width:640px;margin:30px auto">
    <h2>Consent · اجازت</h2>
    <div class="ur" style="font-size:20px">ممتا آپ سے آپ کی اور بچے کی صحت کے بارے میں چند سوال پوچھے گی۔ آپ کے جواب صرف آپ کی لیڈی ہیلتھ ورکر دیکھ سکے گی۔ آپ کی آواز محفوظ نہیں کی جاتی۔ یہ ڈاکٹر نہیں، صرف اسکریننگ ہے۔</div>
    <p class="muted">Mamta will ask a few health questions. Only your Lady Health Worker sees the answers. Your voice recording is not stored. This is screening, not a doctor.</p>
    <div style="display:flex;gap:12px;justify-content:flex-end">
      <button class="btn out" onclick="go('#home')">نہیں · No</button>
      <button class="btn" style="font-size:20px" onclick="consentGiven=true;mother()">✔ جی ہاں · I agree</button>
    </div></div>`;
}
function renderMother() {
  const r = M.last, ph = M.phase;
  let res = '';
  if (r && r.done) {
    const [icon, ur, en] = { red: ['🏥', 'فوراً ہسپتال جائیں', 'Go to hospital now'], yellow: ['🏠', 'لیڈی ہیلتھ ورکر 24 گھنٹے میں آئیں گی', 'LHW will visit within 24h'] }[r.triage] || ['💚', 'سب ٹھیک ہے', 'All looks well'];
    const unsure = r.triage === 'yellow' || (r.confidence != null && r.confidence < 0.6);
    res = `<div class="result ${esc(r.triage)}"><div class="big">${icon}</div><div class="ur title">${ur}</div><div style="font-size:18px">${en}</div>
      <div class="ur" style="font-size:18px">${esc(r.reply_ur)}</div>
      ${r.lhwNotified ? `<div style="background:rgba(255,255,255,.2);border-radius:12px;padding:8px;margin:8px 0"><div class="ur" style="font-size:20px">📞 ${esc(r.lhwName || 'لیڈی ہیلتھ ورکر')} کو اطلاع دے دی گئی ہے، وہ آپ کو فون کریں گی</div><b>Your Lady Health Worker has been alerted and will call you.</b></div>` : ''}
      ${unsure ? '<p><b>Please confirm with your LHW · اپنی ایل ایچ ڈبلیو سے تصدیق کریں</b></p>' : ''}
      <div>${aiTag(r.source)} ${r.confidence != null ? `<small>confidence ${Math.round(r.confidence * 100)}%</small>` : ''} ${r.ruleOverride ? '<small>· safety rule applied</small>' : ''}</div></div>`;
  } else if (r) {
    res = `<div class="card"><div class="ur" style="font-size:26px">${esc(r.reply_ur)}</div>${aiTag(r.source)}</div>`;
  }
  const busy = ph === 'thinking' || ph === 'transcribing';
  const p = M.pending;
  const confirmCard = ph === 'confirm' && p ? `<div class="card" style="max-width:620px;margin:0 auto;border:3px solid var(--rose);text-align:center">
      <div class="ur" style="font-size:20px;color:var(--muted)">آپ نے کہا · You said:</div>
      <div class="ur" style="font-size:30px;font-weight:700;margin:6px 0">“${esc(p.text)}”</div>
      ${p.clear === false ? '<div class="ur" style="color:#8d6e00;font-size:18px">⚠ آواز صاف نہیں تھی · The audio was not clear</div>' : ''}
      <div class="ur" style="font-size:22px">کیا یہ درست ہے؟ · Is this correct?</div>
      <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;margin-top:12px">
        <button class="btn" style="background:var(--green);font-size:22px;padding:16px 26px" onclick="confirmTranscript()">✔ <span class="ur">جی ہاں، درست ہے</span></button>
        <button class="btn" style="background:var(--red);font-size:22px;padding:16px 26px" onclick="reRecord()">🎙️ <span class="ur">نہیں، دوبارہ بولیں</span></button>
        <button class="btn out" onclick="editTranscript()">✎ Edit text</button>
      </div>
      <div style="margin-top:8px">${aiTag(p.source)} <small class="muted">speech-to-text</small></div></div>` : '';
  const chat = M.history.length ? `<div class="card" style="max-width:620px;margin:12px auto"><b>گفتگو · Conversation</b>${M.history.map(h =>
      `<div class="bubble ${h.role === 'mother' ? 'm' : 'a'} ur" style="font-size:18px;${h.role === 'mother' ? 'margin-left:40px' : 'margin-right:40px'}">${h.role === 'mother' ? '👩 آپ: ' : '🤖 ممتا: '}${esc(h.text)}</div>`).join('')}</div>` : '';
  const hint = ph === 'confirm' ? 'اوپر دیکھیں: کیا یہ آپ کی بات ہے؟' : ph === 'rec' ? 'بول رہی ہیں… ختم ہو تو دوبارہ دبائیں' : ph === 'done' ? 'نئی بات کے لیے مائیک دبائیں' : r ? 'جواب دینے کے لیے مائیک دبائیں' : 'مائیک دبا کر اپنی طبیعت بتائیں';
  $('#view').innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
      <span class="muted" id="mname"></span>

    </div>
    ${disclaimer}
    ${M.appts && M.appts.length ? `<div class="card" style="max-width:620px;margin:12px auto;background:#E8F5E9"><b>📅 <span class="ur">میری اپوائنٹمنٹس</span> · My appointments</b>${M.appts.map(a => `<div>• ${esc(a.doctorName)} — <b>${esc(a.slot)}</b> · ${esc(a.clinic)}, ${esc(a.address)} · ${a.fee ? 'Rs ' + a.fee : 'Free'}</div>`).join('')}</div>` : ''}
    ${chat}
    <div style="max-width:620px;margin:16px auto">${res}</div>
    ${confirmCard}
    ${r && r.done && (r.selfcare_ur || []).length ? `<div class="card" style="max-width:620px;margin:12px auto;background:#F1F8E9;border:2px solid var(--green)">
      <h3 style="margin-top:0">🏠 <span class="ur">گھریلو مشورے</span> · Home-care tips ${aiTag(r.source)}</h3>
      ${r.selfcare_ur.map((t, i) => `<div class="ur" style="font-size:19px">• ${esc(t)}</div>${r.selfcare_en && r.selfcare_en[i] ? `<div class="muted" style="margin:-4px 0 6px">${esc(r.selfcare_en[i])}</div>` : ''}`).join('')}
      <div style="background:#FFF8E1;border-radius:10px;padding:8px;margin-top:8px"><div class="ur" style="font-size:17px">💊 دوا لینے سے پہلے ڈاکٹر یا فارماسسٹ سے پوچھیں، کیونکہ آپ بچے کو دودھ پلا رہی ہیں۔</div>
      <b>Medicines:</b> ask a doctor or pharmacist first — some medicines are not safe while breastfeeding. You can book a check-up below.</div></div>` : ''}
    ${r && r.done && M.docs ? doctorsHtml(r) : ''}
    <div class="center" style="margin:24px 0">
      ${ph === 'transcribing' ? loading('آپ کی بات لکھی جا رہی ہے…', 'Converting your voice to text…')
        : ph === 'thinking' ? loading('ممتا سن رہی ہے…', 'Mamta is listening…')
        : ph === 'confirm' ? ''
        : `<button class="mic ${ph === 'rec' ? 'rec' : ''}" onclick="onMic()">${ph === 'rec' ? '⏹' : '🎙️'}</button>`}
      <div class="ur" style="font-size:20px">${hint}</div>
    </div>
    <div class="center" style="display:flex;gap:12px;justify-content:center">
      ${r ? '<button class="btn out" onclick="speak(M.last.audio_base64, M.last.reply_ur)">🔊 Play again</button>' : ''}
      <button class="btn out" onclick="typeAnswer()" ${busy ? 'disabled' : ''}>⌨ Type instead</button>
      ${r ? '<button class="btn out" onclick="resetMother();renderMother()">↺ Start over</button>' : ''}
    </div>
`;
}
function resetMother() { M.history = []; M.last = null; M.phase = 'idle'; M.pending = null; M.docs = null; M.booked = null; }

// ===================== nearby doctors + booking =====================
async function loadDoctors(r) {
  try { M.docs = await api(`/doctors?triage=${r.triage}&flags=${(r.flags || []).join(',')}&specialty=${r.specialty || ''}`); renderMother(); } catch {}
}
function doctorsHtml(r) {
  const d = M.docs;
  const title = r.triage === 'red' ? '🚨 <span class="ur">فوراً یہاں جائیں</span> · Go now'
    : r.triage === 'yellow' ? '🩺 <span class="ur">قریبی ڈاکٹر</span> · Recommended doctors nearby'
    : '🩺 <span class="ur">معمول کا چیک اپ</span> · Optional routine check-up';
  return `<div class="card" style="max-width:620px;margin:12px auto"><h3 style="margin-top:0">${title}</h3>
    <p class="muted" style="margin-top:-6px">For the ${d.for === 'baby' ? 'baby' : 'mother'} · sample directory for the demo</p>
    ${M.booked ? `<div class="card" style="background:#E8F5E9;border:2px solid var(--green)"><b>✔ Appointment booked</b><br>${esc(M.booked.doctorName)} · ${esc(M.booked.slot)}<br>${esc(M.booked.clinic)}, ${esc(M.booked.address)} · Fee: ${M.booked.fee ? 'Rs ' + M.booked.fee : 'Free'}<br><span class="ur">آپ کی لیڈی ہیلتھ ورکر کو بھی اطلاع ہے</span></div>` : ''}
    ${d.doctors.map(doc => `<div style="border-top:1px solid #eee;padding:10px 0">
      <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap"><b style="font-size:17px">${esc(doc.name)}</b><span class="chip" style="background:${doc.emergency ? 'var(--red)' : '#607D8B'}">${doc.distanceKm} km</span></div>
      <div>${esc(doc.specialty)} · ${esc(doc.clinic)}</div>
      <div class="muted">📍 ${esc(doc.address)}<br>🕒 ${esc(doc.timings)} · 💰 ${doc.fee ? 'Rs ' + doc.fee : 'Free'} · 📞 ${esc(doc.phone)}</div>
      <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">
        ${doc.emergency ? `<a class="btn" style="background:var(--red);text-decoration:none" href="tel:${esc(doc.phone)}">📞 Call ${esc(doc.phone)}</a>`
          : doc.slots.map(sl => `<button class="btn out" style="padding:6px 10px;font-size:14px" onclick="bookDoctor('${doc.id}','${sl}')">Book ${esc(sl)}</button>`).join('')}
      </div></div>`).join('')}</div>`;
}
async function loadAppts() { try { M.appts = await api(`/mothers/${M.id}/appointments`); renderMother(); } catch {} }
async function bookDoctor(doctorId, slot) {
  try { M.booked = await postJson('/appointments', { motherId: M.id, doctorId, slot }); loadAppts(); toast('Appointment booked · اپوائنٹمنٹ بک ہو گئی'); }
  catch (e) { toast(e.message); }
}
async function onMic() {
  if (M.phase === 'thinking' || M.phase === 'transcribing') return;
  if (M.phase === 'rec') {
    // Step 1: voice -> text. Step 2: mother confirms the text. Step 3: screening on the confirmed text.
    M.phase = 'transcribing'; renderMother();
    const wav = await stopRec();
    try {
      const firstTurn = !M.history.some(h => h.role === 'mother');
      const t = await postForm('/transcribe', { firstTurn }, wav, 'audio', 'audio.wav');
      if (!t.transcript || !t.transcript.trim()) {
        M.phase = M.last && M.last.done ? 'done' : 'idle'; renderMother();
        toast('آواز سنائی نہیں دی، دوبارہ بولیں · Could not hear you, please speak again');
        return;
      }
      M.pending = { text: t.transcript.trim(), clear: t.clear, source: t.source };
      M.phase = 'confirm'; renderMother();
    } catch (e) { M.phase = 'idle'; renderMother(); toast('Could not reach Mamta server: ' + e.message); }
    return;
  }
  if (M.phase === 'done') resetMother();
  try { await startRec(); M.phase = 'rec'; renderMother(); }
  catch (e) { toast('Microphone permission needed · مائیک کی اجازت دیں'); }
}
async function sendTurn(call, motherText) {
  M.phase = 'thinking'; renderMother();
  try {
    const r = await call();
    M.history.push({ role: 'mother', text: motherText || r.transcript_turn || '' }, { role: 'mamta', text: r.reply_ur || '' });
    M.last = r; M.phase = r.done ? 'done' : 'idle'; M.docs = null; M.booked = null; renderMother();
    if (r.done) loadDoctors(r);
    speak(r.audio_base64, r.reply_ur);
  } catch (e) { M.phase = 'idle'; renderMother(); toast('Could not reach Mamta server: ' + e.message); }
}
function confirmTranscript() {
  const text = M.pending.text; M.pending = null;
  if (M.last && M.last.done) { M.history = []; M.last = null; }
  sendTurn(() => postForm('/checkin/text', { motherId: M.id, text, history: JSON.stringify(M.history) }), text);
}
async function reRecord() {
  M.pending = null; M.phase = 'idle';
  try { await startRec(); M.phase = 'rec'; } catch { toast('Microphone permission needed · مائیک کی اجازت دیں'); }
  renderMother();
}
function editTranscript() {
  ask('Correct the text · درست کریں', '', false, (text) => { M.pending.text = text; M.pending.clear = true; renderMother(); }, M.pending.text);
}
function typeAnswer() {
  ask('Type instead (mic fallback)', 'e.g. Kal se bohat khoon aa raha hai', false, (text) => {
    if (M.phase === 'done') resetMother();
    sendTurn(() => postForm('/checkin/text', { motherId: M.id, text, history: JSON.stringify(M.history) }));
  });
}
function ask(title, placeholder, multiline, cb, initial = '') {
  const d = document.createElement('dialog');
  d.innerHTML = `<h3>${title}</h3>${multiline ? `<textarea rows="5" placeholder="${placeholder}"></textarea>` : `<input class="txt" dir="auto" placeholder="${placeholder}">`}
    <p style="text-align:right"><button class="btn out" value="cancel">Cancel</button> <button class="btn" value="ok">Send</button></p>`;
  document.body.appendChild(d); d.showModal();
  const inp = d.querySelector('input,textarea'); inp.value = initial; inp.focus();
  const done = (ok) => { const v = inp.value.trim(); d.close(); d.remove(); if (ok && v) cb(v); };
  d.querySelectorAll('button').forEach(b => b.onclick = () => done(b.value === 'ok'));
  if (!multiline) inp.onkeydown = (e) => e.key === 'Enter' && done(true);
}

// ===================== LHW DASHBOARD =====================
let lastAlertIds = '';
let fsUnsub = null;
function lhw() {
  $('#title').textContent = 'LHW dashboard';
  $('#view').innerHTML = loading('لوڈ ہو رہا ہے…', 'Loading…');
  $('#fabs').innerHTML = `<button class="btn" style="background:#37474F" onclick="go('#scan')">📷 Scan register</button>
    <button class="btn" onclick="pickVisit()">🎙️ Record visit note</button>`;
  $('#live').style.display = ''; $('#live').textContent = '● Live (auto-refresh 2s)';
  refreshLhw();
  timers.push(setInterval(refreshLhw, 2000));
  // Real-time Firestore listener (if firebase-config.js is filled in): new alert -> instant refresh
  if (window.MamtaFirebase) {
    window.MamtaFirebase.listenAlerts(LHW_ID, refreshLhw).then(unsub => {
      fsUnsub = unsub; if (unsub) $('#live').textContent = '● Live (Firestore listener)';
    });
  }
}
let lhwData = null;
async function refreshLhw() {
  try {
    const d = await api(`/lhw/${LHW_ID}/today`); lhwData = d;
    if (d.lhw) $('#title').textContent = `${d.lhw.name} · ${d.lhw.area}`;
    const ids = d.alerts.map(a => a.id).join(',');
    if (ids && ids !== lastAlertIds && d.alerts.some(a => a.level === 'red')) beep();
    lastAlertIds = ids;
    $('#view').innerHTML = `
      ${d.alerts.map(a => `<div class="banner ${a.level === 'red' ? 'red' : 'yellow'}">
        <div style="font-size:42px">${a.level === 'red' ? '⚠️' : 'ℹ️'}</div>
        <div class="t"><b>${a.level === 'red' ? 'RED ALERT' : 'YELLOW'} · ${esc(a.motherName)}</b><br>${esc((a.signs || []).join(', '))}${a.summary ? `<br><small>🤖 ${esc(a.summary)}</small>` : ''}${a.motherSaid ? `<br><span class="ur" style="font-size:16px">👩 “${esc(a.motherSaid)}”</span>` : ''}<br>
          <small>${a.level === 'red' ? 'Advised to go to hospital now · from voice check-in' : 'Visit within 24 hours'} · ${new Date(a.createdAt).toLocaleTimeString()}</small></div>
        <a class="btn" href="tel:${esc(a.motherPhone)}">📞 Call</a>
        <button class="btn out" style="background:transparent;color:#fff;border-color:#fff" onclick="ack('${a.id}')">Seen</button></div>`).join('')}
      <div style="display:flex;align-items:center;gap:12px;margin-top:10px">
        <h2 style="flex:1;margin:0">Today's visits (${d.mothers.length})</h2>
        <button class="btn out" onclick="report()">📝 Monthly report</button>
      </div>
      <p class="muted">Ranked: RED → YELLOW → overdue visits → routine. AI screens, you decide.</p>
      ${d.mothers.map(m => `<div class="mrow ${m.riskStatus === 'red' ? 'isred' : ''}">
        <div class="avatar ${esc(m.riskStatus)}">${m.daysPostpartum}</div>
        <div class="info"><span class="name">${esc(m.name)}</span> <span class="chip ${esc(m.riskStatus)}">${esc((m.riskStatus || '').toUpperCase())}</span>
          ${m.source === 'register' ? '<span class="chip" style="background:#607D8B">from register</span>' : ''}
          <div class="muted">Day ${m.daysPostpartum} after delivery · ${esc(m.reason)}</div>
          ${m.appointment ? `<div style="color:var(--green);font-size:14px">📅 Appointment: ${esc(m.appointment.doctorName)} · ${esc(m.appointment.slot)}</div>` : ''}</div>
        <button class="iconbtn" title="Record visit note" onclick="go('#visit/${m.id}')">📝</button>
        ${m.phone ? `<a class="iconbtn" style="display:flex;align-items:center;justify-content:center;text-decoration:none" title="Call" href="tel:${esc(m.phone)}">📞</a>` : ''}
      </div>`).join('')}
      <div style="height:140px"></div>`;
  } catch (e) { $('#live').textContent = '● Server not reachable'; }
}
function beep() {
  try { const c = new AudioContext(), o = c.createOscillator(), g = c.createGain(); o.frequency.value = 880; o.connect(g); g.connect(c.destination);
        g.gain.value = 0.15; o.start(); setTimeout(() => { o.stop(); c.close(); }, 400); } catch {}
}
async function ack(id) { await api(`/alerts/${id}/ack`, { method: 'POST' }); refreshLhw(); }
function pickVisit() {
  const d = document.createElement('dialog');
  d.innerHTML = `<h3>Visit note for…</h3>${(lhwData?.mothers || []).map(m => `<p><button class="btn out" style="width:100%" data-id="${m.id}">${esc(m.name)}</button></p>`).join('')}`;
  document.body.appendChild(d); d.showModal();
  d.querySelectorAll('button').forEach(b => b.onclick = () => { d.close(); d.remove(); go('#visit/' + b.dataset.id); });
  d.onclick = (e) => { if (e.target === d) { d.close(); d.remove(); } };
}
async function report() {
  const now = new Date(), month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  const d = document.createElement('dialog'); d.innerHTML = loading('رپورٹ بن رہی ہے…', 'Drafting monthly report…');
  document.body.appendChild(d); d.showModal();
  try {
    const r = await postJson('/report/monthly', { lhwId: LHW_ID, month });
    d.innerHTML = `<h3>Monthly report ${aiTag(r.source)}</h3><pre>${esc(r.markdown)}</pre><p style="text-align:right"><button class="btn">Close</button></p>`;
  } catch (e) { d.innerHTML = `<p>${esc(e.message)}</p><button class="btn">Close</button>`; }
  d.querySelector('button').onclick = () => { d.close(); d.remove(); };
}

// ===================== REGISTER SCAN =====================
const FIELDS = { motherName: 'Mother name', guardianName: 'Husband / father', houseNo: 'House no.', deliveryDate: 'Delivery date (YYYY-MM-DD)',
  deliveryPlace: 'Place (home/facility/unknown)', parity: 'Parity', babySex: 'Baby sex (M/F)', babyBirthWeightKg: 'Birth weight (kg)',
  vaccinesGiven: 'Vaccines (comma separated)', pncVisitDates: 'PNC visit dates', remarks: 'Remarks' };
const S = { rows: [], checked: new Set(), source: null, notes: '' };
function scan() {
  $('#title').textContent = 'Scan register page';
  S.rows = []; S.checked = new Set();
  $('#view').innerHTML = `<div class="card">
    <p>Photograph a page of the paper postnatal register. Mamta reads it; <b>you check and confirm</b> before anything is saved.</p>
    <label class="btn" style="display:inline-block">📷 Take photo / choose image<input id="img" type="file" accept="image/*" capture="environment" style="display:none"></label>
    <div id="preview"></div></div><div id="rows"></div>`;
  $('#img').onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    $('#preview').innerHTML = `<img src="${URL.createObjectURL(f)}" style="max-height:240px;max-width:100%;border-radius:12px;margin-top:10px">`;
    $('#rows').innerHTML = loading('ممتا رجسٹر پڑھ رہی ہے…', 'Mamta is reading the register…');
    try {
      const r = await postForm('/register/digitize', { lhwId: LHW_ID }, f, 'image', f.name || 'page.jpg');
      S.rows = r.rows; S.source = r.source; S.notes = r.page_notes || ''; renderRows();
    } catch (err) { $('#rows').innerHTML = ''; toast(err.message); }
  };
}
const show = (v) => Array.isArray(v) ? v.join(', ') : (v ?? '');
function pendingAmber() { let n = 0; S.rows.forEach((r, i) => (r.low_confidence || []).forEach(f => !S.checked.has(i + ':' + f) && n++)); return n; }
function renderRows() {
  $('#rows').innerHTML = `<div class="card"><h3>${S.rows.length} rows found ${aiTag(S.source)}</h3>
    ${S.notes ? `<p class="muted">${esc(S.notes)}</p>` : ''}
    <p style="color:#8d6e00;font-weight:600">Draft only — check the amber cells, then Confirm to save.</p>
    ${S.rows.map((r, i) => `<div class="card" style="background:#fffdfd">
      <div style="display:flex;justify-content:space-between"><b>Row ${esc(r.serial ?? i + 1)}</b><button class="iconbtn" onclick="S.rows.splice(${i},1);renderRows()">🗑</button></div>
      <div class="grid">${Object.entries(FIELDS).map(([k, label]) => {
        const amber = (r.low_confidence || []).includes(k) && !S.checked.has(i + ':' + k);
        return `<label class="field ${amber ? 'amber' : ''}">${label}<input value="${esc(show(r[k]))}" oninput="upd(${i},'${k}',this.value)">
          ${amber ? `<span class="hint">AI unsure — please check <a href="#" onclick="S.checked.add('${i}:${k}');renderRows();return false">✔ looks right</a></span>` : ''}</label>`; }).join('')}</div></div>`).join('')}
    <button id="confirmBtn" class="btn" style="width:100%;padding:16px" onclick="confirmRows()">✔ Confirm & save${pendingAmber() ? ` (${pendingAmber()} amber cells unchecked)` : ''}</button></div>`;
}
function upd(i, k, v) {
  const r = S.rows[i]; v = v.trim();
  if (k === 'parity') r[k] = parseInt(v) || null;
  else if (k === 'babyBirthWeightKg') r[k] = parseFloat(v) || null;
  else if (k === 'vaccinesGiven' || k === 'pncVisitDates') r[k] = v.split(',').map(s => s.trim()).filter(Boolean);
  else if (k === 'deliveryPlace') r[k] = ['home', 'facility'].includes(v.toLowerCase()) ? v.toLowerCase() : 'unknown';
  else if (k === 'babySex') r[k] = ['M', 'F'].includes(v.toUpperCase()) ? v.toUpperCase() : 'unknown';
  else r[k] = v || null;
  if ((r.low_confidence || []).includes(k) && !S.checked.has(i + ':' + k)) {
    S.checked.add(i + ':' + k);
    const input = document.activeElement; const lbl = input?.closest('.field'); if (lbl) { lbl.classList.remove('amber'); lbl.querySelector('.hint')?.remove(); }
    const b = $('#confirmBtn'); if (b) b.textContent = '✔ Confirm & save' + (pendingAmber() ? ` (${pendingAmber()} amber cells unchecked)` : '');
  }
}
async function confirmRows() {
  try { const r = await postJson('/register/confirm', { lhwId: LHW_ID, rows: S.rows }); toast(`Saved ${r.ids.length} mothers to your list`); go('#lhw'); }
  catch (e) { toast(e.message); }
}

// ===================== VISIT NOTE =====================
const V = { motherId: null, draft: null, risk: null, rec: false, busy: false, name: '' };
async function visit(motherId) {
  Object.assign(V, { motherId, draft: null, risk: null, rec: false, busy: false, name: '' });
  try { V.name = (await api('/mothers/' + motherId)).name; } catch {}
  renderVisit();
}
function renderVisit() {
  $('#title').textContent = 'Visit note · ' + V.name;
  const d = V.draft;
  const list = (t, xs) => `<p><b>${t}</b><br>${(xs || []).length ? xs.map(x => `<span class="chip" style="background:#eee;color:#333;margin:2px">${esc(x)}</span>`).join('') : '<span class="muted">— not mentioned</span>'}</p>`;
  $('#view').innerHTML = `<div class="center">
      <button class="mic ${V.rec ? 'rec' : ''}" style="width:140px;height:140px;font-size:60px" onclick="visitMic()" ${V.busy ? 'disabled' : ''}>${V.rec ? '⏹' : '🎙️'}</button>
      <p>${V.rec ? 'Recording… tap to finish' : 'Tap and speak your visit note (Urdu / Punjabi / English)'}</p>
      <button class="btn out" onclick="visitType()" ${V.busy ? 'disabled' : ''}>⌨ Type instead</button></div>
    ${V.busy ? loading('ممتا نوٹ لکھ رہی ہے…', 'Mamta is structuring your note…') : ''}
    ${d && !V.busy ? `<div class="card"><h3>Draft visit record ${aiTag(d.source)}</h3>
      <p>Visit type: <b>${esc(d.visitType)}</b> · Next visit: <b>${esc(d.nextVisitDate || '—')}</b></p>
      ${list('Mother findings', d.motherFindings)}${list('Baby findings', d.babyFindings)}${list('Vaccines given', d.vaccinesGiven)}${list('Counselling done', d.counsellingDone)}
      ${d.referral ? `<p style="color:var(--red);font-weight:700">REFERRAL: ${esc(d.referralReason)}</p>` : ''}
      <hr><b>Transcript</b><div class="ur" style="font-size:16px">${esc(d.transcript)}</div></div>
      <div class="card"><b>Risk status — AI suggests ${esc((d.suggestedRiskStatus || '').toUpperCase())}. You decide:</b>
        <div class="riskpick" style="margin:12px 0">${['green', 'yellow', 'red'].map(r => `<button class="${V.risk === r ? 'sel ' + r : ''}" style="border-color:var(--${r});color:var(--${r})" onclick="V.risk='${r}';renderVisit()">${r.toUpperCase()}</button>`).join('')}</div>
        <button class="btn" style="width:100%;padding:16px" onclick="confirmVisit()">✔ Confirm & save visit</button></div>` : ''}`;
}
async function visitMic() {
  if (V.rec) {
    V.rec = false; V.busy = true; renderVisit();
    const wav = await stopRec();
    return structure(() => postForm('/visit/note', { motherId: V.motherId }, wav, 'audio', 'note.wav'));
  }
  try { await startRec(); V.rec = true; renderVisit(); } catch { toast('Microphone permission needed'); }
}
function visitType() { ask('Type visit note', 'e.g. Aaj Saima se mili, khoon nahi aa raha, bacha theek doodh pee raha hai…', true, (t) => structure(() => postForm('/visit/note', { motherId: V.motherId, text: t }))); }
async function structure(call) {
  V.busy = true; renderVisit();
  try { V.draft = await call(); V.risk = V.draft.suggestedRiskStatus; } catch (e) { toast(e.message); }
  V.busy = false; renderVisit();
}
async function confirmVisit() {
  const d = V.draft, keys = ['visitType', 'motherFindings', 'babyFindings', 'vaccinesGiven', 'counsellingDone', 'referral', 'referralReason', 'nextVisitDate', 'suggestedRiskStatus', 'transcript'];
  const body = Object.fromEntries(keys.map(k => [k, d[k]]));
  Object.assign(body, { motherId: V.motherId, lhwId: LHW_ID, riskStatusConfirmed: V.risk });
  try { await postJson('/visit/confirm', body); toast('Visit saved · risk status confirmed'); go('#lhw'); } catch (e) { toast(e.message); }
}

route();
