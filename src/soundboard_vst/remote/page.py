"""Pagina web del controllo remoto (un unico file: HTML, CSS e JavaScript)."""

PAGE_HTML = r"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#15171c">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>Soundboard VST</title>
<style>
:root{--bg:#15171c;--panel:#1e2128;--panel2:#262a33;--border:#323743;--text:#e6e8ee;--muted:#8b92a3;
--accent:#f2a93b;--accent2:#3ec7b2;--danger:#e5534b}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--text);font:15px/1.35 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);padding:10px 14px 0;border-bottom:1px solid var(--border)}
.top{display:flex;align-items:center;gap:8px}
.top h1{font-size:17px;margin:0;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chip{font-size:12px;padding:5px 10px;border-radius:99px;background:var(--panel2);border:1px solid var(--border);color:var(--muted);white-space:nowrap;max-width:46vw;overflow:hidden;text-overflow:ellipsis}
.chip.on{color:#10221f;background:var(--accent2);border-color:var(--accent2)}
button{font:inherit;color:var(--text);background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:9px 12px;cursor:pointer}
button:active{transform:scale(.97)}
button.danger{color:var(--danger)}
button.primary{background:var(--accent);color:#1b1406;border:none;font-weight:600}
nav{display:flex;gap:4px;margin-top:8px}
nav button{flex:1;background:transparent;border:none;border-bottom:2px solid transparent;border-radius:0;color:var(--muted);font-weight:600;padding:10px 4px}
nav button.sel{color:var(--text);border-bottom-color:var(--accent)}
main{padding:12px 12px calc(16px + env(safe-area-inset-bottom))}
section{display:none}section.sel{display:block}
.pages{display:flex;gap:6px;overflow-x:auto;padding-bottom:8px;scrollbar-width:none}
.pages button{white-space:nowrap;padding:6px 12px;font-size:13px;border-radius:8px;color:var(--muted)}
.pages button.sel{color:var(--text);border-color:var(--accent);background:var(--panel2)}
.grid{display:grid;gap:7px}
.pad{position:relative;aspect-ratio:1.15;border-radius:12px;background:var(--panel2);border:1px solid var(--border);
display:flex;flex-direction:column;align-items:center;justify-content:center;padding:6px;overflow:hidden;
font-weight:600;font-size:13px;text-align:center;user-select:none;background-size:cover;background-position:center}
.pad .em{font-size:clamp(20px,7vw,30px);line-height:1.15}
.pad .lb{max-width:100%;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.pad.img .lb{position:absolute;left:0;right:0;bottom:0;padding:16px 6px 6px;background:linear-gradient(transparent,rgba(0,0,0,.8));color:#fff}
.pad.empty{background:transparent;border-style:dashed;opacity:.35}
.pad.playing{outline:3px solid #fff;outline-offset:-3px;filter:brightness(1.25)}
.pad.missing{opacity:.5;text-decoration:line-through}
.pad .n{position:absolute;left:7px;top:5px;font-size:10px;opacity:.6;font-weight:500}
.card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:14px;margin-bottom:12px}
.np-title{font-size:19px;font-weight:700;margin:0 0 2px}
.muted{color:var(--muted);font-size:13px}
#addmsg{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;word-break:break-word}
.row{display:flex;align-items:center;gap:8px}
.transport{display:flex;justify-content:center;gap:10px;margin-top:10px}
.transport button{font-size:22px;width:58px;height:50px;padding:0}
.transport button.big{width:72px;font-size:26px}
input[type=range]{width:100%;accent-color:var(--accent2);height:28px}
input[type=text]{flex:1;font:inherit;color:var(--text);background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:10px}
.time{font:12px ui-monospace,Consolas,monospace;color:var(--muted);min-width:44px;text-align:center}
.queue{list-style:none;margin:0;padding:0}
.queue li{padding:10px 8px;border-bottom:1px solid var(--panel2);display:flex;gap:8px;cursor:pointer}
.queue li.cur{color:var(--accent);font-weight:700}
.queue li span:first-of-type{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.queue .qi{width:18px;flex:0 0 18px;display:flex;align-items:center}
.transport button{display:flex;align-items:center;justify-content:center}
.pad .prog{position:absolute;left:0;bottom:0;height:4px;width:0;background:currentColor;opacity:.85;display:none}
.pad .vu{position:absolute;right:4px;top:8px;bottom:10px;width:4px;border-radius:2px;background:rgba(255,255,255,.12);display:none;overflow:hidden}
.pad .vu i{position:absolute;left:0;right:0;bottom:0;height:0;background:linear-gradient(to top,var(--accent2) 0%,#e3c84b 75%,var(--danger) 100%);background-size:100% var(--vuh,100px);background-position:bottom}
.pad.playing .prog,.pad.active .vu{display:block}
/* Mixer: stesse colonne del programma */
.mixer{display:flex;gap:8px;overflow-x:auto;padding-bottom:6px;scroll-snap-type:x proximity}
.mstrip{flex:0 0 156px;scroll-snap-align:start;background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:10px;display:flex;flex-direction:column;gap:6px}
.mtitle{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sect{color:var(--muted);font-size:11px;font-weight:600;letter-spacing:.04em}
.ins{list-style:none;margin:0;padding:0;background:var(--bg);border:1px solid var(--border);border-radius:6px;min-height:86px;max-height:150px;overflow-y:auto}
.ins li{display:flex;align-items:center;gap:6px;padding:6px;border-bottom:1px solid var(--panel2);font-size:13px;cursor:pointer}
.ins li.sel{background:var(--panel2)}
.ins li span{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ins li.off span{color:var(--muted);text-decoration:line-through}
.ins li.err span{color:var(--danger)}
.ins input{margin:0;accent-color:var(--accent2);width:16px;height:16px}
.itools{display:flex;gap:4px}
.itools button{flex:1;padding:4px 0;font-size:13px;border-radius:6px}
.hear label,.tobot{display:flex;align-items:center;gap:6px;font-size:13px;padding:2px 0}
.tobot input{accent-color:var(--accent2);width:16px;height:16px;margin:0}
select.inp{width:100%;font:inherit;font-size:12px;color:var(--text);background:var(--panel2);border:1px solid var(--border);border-radius:6px;padding:6px}
.hear input{accent-color:var(--accent2);width:16px;height:16px;margin:0}
.fm{display:flex;justify-content:center;align-items:flex-end;gap:12px;padding:6px 0;flex:1}
.fader{position:relative;width:26px;height:230px;touch-action:none;cursor:ns-resize}
.fader .track{position:absolute;left:10px;width:6px;top:0;bottom:0;background:var(--bg);border-radius:3px}
.fader .fill{position:absolute;left:10px;width:6px;bottom:0;background:var(--accent2);border-radius:3px}
.fader .thumb{position:absolute;left:0;width:26px;height:16px;margin-bottom:-8px;background:#e6e8ee;border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,.5)}
canvas.vu{width:48px;height:230px}
.mstrip .db{text-align:center;font:12px ui-monospace,Consolas,monospace;color:var(--muted)}
.mstrip button.mute{padding:6px 0;font-weight:700;font-size:13px}
.mstrip button.mute.on{background:var(--danger);color:#fff;border:none}
.mstrip .btns{display:flex;gap:6px}.mstrip .btns button{flex:1}
.mstrip button.solo{padding:6px 0;font-weight:700;font-size:13px}
.mstrip button.solo.on{background:#e8d44d;color:#15171c;border:none}
.pan{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--muted)}
.pan input{flex:1;min-width:0;accent-color:var(--accent2)}
.pan .pv{font:11px ui-monospace,Consolas,monospace;min-width:34px;text-align:right}
/* Pannello dal basso (aggiungi inserto, parametri) */
.sheet{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;z-index:20;align-items:flex-end;justify-content:center}
.sheet.open{display:flex}
.sheet .box{background:var(--panel);border:1px solid var(--border);border-radius:14px 14px 0 0;width:min(560px,100%);max-height:82vh;overflow-y:auto;padding:14px 14px calc(14px + env(safe-area-inset-bottom))}
.sheet h3{margin:0 0 10px;font-size:16px;display:flex;align-items:center;gap:8px}
.sheet h3 span{flex:1}
.sheet .opt{display:block;width:100%;text-align:left;margin-bottom:6px}
.prm{padding:6px 0;border-bottom:1px solid var(--panel2)}
.prm .row span:first-child{flex:1;font-size:13px}
.prm .val{font:12px ui-monospace,Consolas,monospace;color:var(--muted);min-width:70px;text-align:right}
.offline{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:var(--danger);color:#fff;padding:8px 14px;border-radius:99px;font-size:13px;display:none;z-index:9}
.botbtns{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.botbtns button{flex:1}
</style>
</head>
<body>
<header>
  <div class="top">
    <h1>🎛️ Soundboard</h1>
    <span id="botchip" class="chip">🤖 —</span>
    <button class="danger" id="stopall" title="Ferma tutti i suoni">■</button>
  </div>
  <nav>
    <button data-tab="pads" class="sel">Pad</button>
    <button data-tab="player">Player</button>
    <button data-tab="mixer">Mixer</button>
  </nav>
</header>
<main>
  <section id="pads" class="sel">
    <div class="pages" id="pages"></div>
    <div class="grid" id="grid"></div>
    <div class="row" style="margin-top:10px">
      <input type="text" id="saytext" placeholder="💬 Scrivi una frase da far dire…" maxlength="300" enterkeyhint="send" style="flex:1">
      <button id="saybtn">Parla</button>
    </div>
  </section>
  <section id="player">
    <div class="card">
      <p class="np-title" id="np-title">Nessun brano</p>
      <div class="muted" id="np-sub">—</div>
      <div class="row" style="margin-top:8px">
        <span class="time" id="t-pos">0:00</span>
        <input type="range" id="seek" min="0" max="1000" value="0">
        <span class="time" id="t-dur">--:--</span>
      </div>
      <div class="transport">
        <button data-p="prev" data-icon="prev" title="Precedente"></button>
        <button data-p="toggle" class="big" id="pp" data-icon="play" title="Play / Pausa"></button>
        <button data-p="stop" data-icon="stop" title="Stop"></button>
        <button data-p="next" data-icon="next" title="Successivo"></button>
      </div>
      <div class="row" style="margin-top:10px">
        <span class="muted">Volume</span>
        <input type="range" id="pvol" min="-600" max="120" step="5">
      </div>
    </div>
    <div class="card">
      <div class="row">
        <input type="text" id="addtext" placeholder="Link YouTube o cerca…" enterkeyhint="go">
        <button class="primary" id="addbtn">＋</button>
      </div>
      <div class="muted" id="addmsg" style="margin-top:6px"></div>
    </div>
    <div class="card"><ul class="queue" id="queue"></ul></div>
  </section>
  <section id="mixer">
    <div class="mixer" id="strips"></div>
    <div class="muted" style="margin:4px 2px 12px">Tocca un inserto per selezionarlo · ✓ = attivo (togli la spunta per il bypass) · ✎ parametri. L'interfaccia grafica dei plugin si apre solo sul PC.</div>
    <div class="card">
      <div class="row"><b style="flex:1">Bot Discord</b><span class="muted" id="botmsg"></span></div>
      <div class="botbtns">
        <button data-b="toggle" id="bot-toggle">⏻ Avvia</button>
        <button data-b="join">Entra</button>
        <button data-b="leave">Esci</button>
      </div>
    </div>
  </section>
</main>
<div class="offline" id="offline">Soundboard non raggiungibile…</div>
<div class="sheet" id="sheet"><div class="box"><h3><span id="sheet-title"></span><button id="sheet-close">✕</button></h3><div id="sheet-body"></div></div></div>
<script>
const $ = s => document.querySelector(s);
const ICON = {"play": "<path d=\"M7 4.5 19.5 12 7 19.5z\"/>", "pause": "<rect x=\"6\" y=\"5\" width=\"4.2\" height=\"14\" rx=\"1\"/><rect x=\"13.8\" y=\"5\" width=\"4.2\" height=\"14\" rx=\"1\"/>", "stop": "<rect x=\"6\" y=\"6\" width=\"12\" height=\"12\" rx=\"1.5\"/>", "prev": "<rect x=\"5\" y=\"5.5\" width=\"2.6\" height=\"13\" rx=\"1\"/><path d=\"M19 5.5 8.5 12 19 18.5z\"/>", "next": "<rect x=\"16.4\" y=\"5.5\" width=\"2.6\" height=\"13\" rx=\"1\"/><path d=\"M5 5.5 15.5 12 5 18.5z\"/>", "youtube": "<rect x=\"2\" y=\"5\" width=\"20\" height=\"14\" rx=\"4\" fill=\"#e5534b\"/><path d=\"M10 8.5 15.5 12 10 15.5z\" fill=\"#fff\"/>", "now": "<g fill=\"#f2a93b\"><rect x=\"5\" y=\"11\" width=\"3.4\" height=\"8\" rx=\"1\"/><rect x=\"10.3\" y=\"5\" width=\"3.4\" height=\"14\" rx=\"1\"/><rect x=\"15.6\" y=\"9\" width=\"3.4\" height=\"10\" rx=\"1\"/></g>"};
const svg = (n, sz = 26) => `<svg viewBox="0 0 24 24" width="${sz}" height="${sz}" fill="currentColor" aria-hidden="true">${ICON[n]}</svg>`;
document.querySelectorAll("[data-icon]").forEach(b => b.innerHTML = svg(b.dataset.icon, b.classList.contains("big") ? 32 : 26));
let S = null, page = null, seeking = false, dragging = {};
const fmt = s => { if (s == null) return "--:--"; s = Math.max(0, Math.floor(s));
  const h = Math.floor(s/3600), m = Math.floor(s%3600/60), x = String(s%60).padStart(2,"0");
  return h ? `${h}:${String(m).padStart(2,"0")}:${x}` : `${m}:${x}`; };
const fmtDb = d => d <= -60 ? "-∞ dB" : (d > 0 ? "+" : "") + d.toFixed(1) + " dB";
function luminance(hex){ const n = parseInt(hex.slice(1),16); const r=(n>>16&255)/255,g=(n>>8&255)/255,b=(n&255)/255;
  return .2126*r+.7152*g+.0722*b; }
function shade(hex, f){ const n = parseInt(hex.slice(1),16); let r=n>>16&255,g=n>>8&255,b=n&255;
  r=Math.round(r*f);g=Math.round(g*f);b=Math.round(b*f); return `rgb(${r},${g},${b})`; }

async function send(cmd){
  try { await fetch("/api/command", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(cmd)}); }
  catch(e){}
  setTimeout(poll, 120);
}

function selectTab(name){
  document.querySelectorAll("nav button").forEach(x => x.classList.toggle("sel", x.dataset.tab === name));
  document.querySelectorAll("section").forEach(s => s.classList.toggle("sel", s.id === name));
}
document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  selectTab(b.dataset.tab); history.replaceState(null, "", "#" + b.dataset.tab);
});
if (["pads", "player", "mixer"].includes(location.hash.slice(1))) selectTab(location.hash.slice(1));
$("#stopall").onclick = () => send({cmd:"stop_sounds"});
document.querySelectorAll("[data-p]").forEach(b => b.onclick = () => send({cmd:"player", action:b.dataset.p}));
document.querySelectorAll("[data-b]").forEach(b => b.onclick = () => send({cmd:"bot", action:b.dataset.b}));
$("#seek").oninput = () => seeking = true;
$("#seek").onchange = () => { seeking = false; const d = S && S.player.duration;
  if (d) send({cmd:"player", action:"seek", position: $("#seek").value/1000*d}); };
$("#pvol").oninput = e => { dragging.player = true; send({cmd:"strip", id:"player", gain_db: e.target.value/10}); };
$("#pvol").onchange = () => dragging.player = false;
function addTrack(){ const t = $("#addtext").value.trim(); if (!t) return;
  $("#addmsg").textContent = "Invio…"; send({cmd:"player_add", text:t}); $("#addtext").value = ""; }
$("#addbtn").onclick = addTrack;
function say(){ const t = $("#saytext").value.trim(); if (!t) return;
  send({cmd:"say", text:t}); $("#saytext").select(); }
$("#saybtn").onclick = say;
$("#saytext").onkeydown = e => { if (e.key === "Enter") say(); };
$("#addtext").onkeydown = e => { if (e.key === "Enter") addTrack(); };

function renderPads(){
  const pages = S.pads.pages;
  if (page == null || page >= pages.length) page = S.pads.current;
  const sig = JSON.stringify([page, pages.map(p => p.name)]);
  const pc = $("#pages");
  if (pc.dataset.sig !== sig){
    pc.dataset.sig = sig; pc.innerHTML = "";
    pages.forEach((p, i) => { const b = document.createElement("button"); b.textContent = p.name;
      b.className = i === page ? "sel" : ""; b.onclick = () => { page = i; render(); }; pc.appendChild(b); });
    pc.style.display = pages.length > 1 ? "flex" : "none";
  }
  const g = $("#grid");
  const width = g.clientWidth || document.documentElement.clientWidth;
  const cols = Math.max(2, Math.min(S.pads.cols, Math.floor((width + 7) / 92)));
  g.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  const pads = pages[page].pads;
  const gsig = JSON.stringify([page, cols, pads]);
  if (g.dataset.sig === gsig) return;
  g.dataset.sig = gsig; g.innerHTML = "";
  pads.forEach((p, i) => {
    const d = document.createElement("div"); d.className = "pad";
    if (!p){ d.classList.add("empty"); d.innerHTML = `<span class="n">${i+1}</span>`; g.appendChild(d); return; }
    if (p.color){ d.style.background = shade(p.color, p.playing ? 1.25 : .8);
      d.style.color = luminance(p.color) > .55 ? "#15171c" : "#f4f5f8"; }
    if (p.image){ d.classList.add("img"); d.style.backgroundImage = `url("/api/image/${encodeURIComponent(p.key)}")`; }
    if (p.playing) d.classList.add("playing");
    if (p.missing) d.classList.add("missing");
    const em = p.emoji && !p.image ? `<div class="em">${p.emoji}</div>` : "";
    d.innerHTML = `<span class="n">${i+1}</span>${em}<div class="lb"></div><i class="prog"></i><span class="vu"><i></i></span>`;
    d.querySelector(".lb").textContent = p.label;
    d.dataset.key = p.key;
    d.onclick = () => { send({cmd:"pad", page, index:i}); d.classList.add("playing"); };
    g.appendChild(d);
  });
}

function renderPlayer(){
  const P = S.player;
  $("#np-title").textContent = P.title || "Nessun brano";
  const st = {playing:"In riproduzione", loading:"Caricamento…", paused:"In pausa", stopped:"Fermo"}[P.state] || "";
  $("#np-sub").textContent = P.title ? `${st}${P.kind === "youtube" ? " · YouTube" : ""}` : "Aggiungi un link YouTube qui sotto";
  const ppIcon = (P.state === "playing" || P.state === "loading") ? "pause" : "play";
  if ($("#pp").dataset.icon !== ppIcon){ $("#pp").dataset.icon = ppIcon; $("#pp").innerHTML = svg(ppIcon, 32); }
  $("#t-pos").textContent = fmt(P.position); $("#t-dur").textContent = fmt(P.duration);
  if (!seeking) $("#seek").value = P.duration ? Math.round(P.position / P.duration * 1000) : 0;
  if (!dragging.player) $("#pvol").value = Math.round(P.volume_db * 10);
  if (P.message) $("#addmsg").textContent = P.message;
  const q = $("#queue"), qsig = JSON.stringify([P.index, P.queue]);
  if (q.dataset.sig !== qsig){
    q.dataset.sig = qsig; q.innerHTML = "";
    if (!P.queue.length) q.innerHTML = '<li class="muted">Coda vuota</li>';
    P.queue.forEach((t, i) => { const li = document.createElement("li"); if (i === P.index) li.className = "cur";
      li.innerHTML = `<i class="qi">${i === P.index ? svg("now", 18) : t.kind === "youtube" ? svg("youtube", 18) : ""}</i><span></span><span class="time">${fmt(t.duration)}</span>`;
      li.children[1].textContent = t.title;
      li.onclick = () => send({cmd:"player", action:"play", index:i}); q.appendChild(li); });
  }
}

const MIN_DB = -60, MAX_DB = 12, VU_MIN = -60, VU_MAX = 6;
let selected = {}, sheetFor = null;
const dbToFrac = d => (Math.max(MIN_DB, Math.min(MAX_DB, d)) - MIN_DB) / (MAX_DB - MIN_DB);
const vuFrac = d => Math.max(0, Math.min(1, (d - VU_MIN) / (VU_MAX - VU_MIN)));
const HEAR = [["hear_sounds","Suoni"],["hear_tts","Voce"],["hear_player","Player"]];
const fmtPan = v => { v = Math.round(v * 100); return v === 0 ? "C" : v < 0 ? "S " + (-v) : "D " + v; };
const inputOf = id => (S.inputs || []).find(x => x.id === id);

function buildStrip(s){
  const el = document.createElement("div"); el.className = "mstrip"; el.dataset.id = s.id;
  el.innerHTML = `<div class="mtitle"></div><div class="sect">INSERTI</div><ul class="ins"></ul>
    <div class="itools"><button data-a="add" title="Aggiungi">+</button><button data-a="remove" title="Togli">−</button>
    <button data-a="up" title="Su">▲</button><button data-a="down" title="Giù">▼</button><button data-a="edit" title="Parametri">✎</button></div>
    ${s.input ? `<div class="sect">INGRESSO <span class="chs"></span></div><select class="inp"></select>
      <label class="tobot"><input type="checkbox"> Anche al bot Discord</label>` : ""}
    ${s.id === "monitor" ? `<div class="sect">ASCOLTA</div><div class="hear">${HEAR.map(([k,l]) => `<label><input type="checkbox" data-h="${k}"> ${l}</label>`).join("")}${(S.inputs || []).map(i => `<label><input type="checkbox" data-in="${i.id}"> <span></span></label>`).join("")}</div>` : ""}
    <div class="pan"><span>PAN</span><input type="range" min="-100" max="100" step="1" value="0"><span class="pv">C</span></div>
    <div class="fm"><div class="fader"><div class="track"></div><div class="fill"></div><div class="thumb"></div></div><canvas class="vu" width="96" height="460"></canvas></div>
    <div class="db"></div><div class="btns"><button class="mute">MUTE</button>${s.soloable ? '<button class="solo">SOLO</button>' : ""}</div>`;
  el.querySelector(".mtitle").textContent = s.name;
  el.querySelector(".mute").onclick = () => send({cmd:"strip", id:s.id, mute: !strip(s.id).mute});
  if (s.soloable) el.querySelector(".solo").onclick = () => send({cmd:"strip", id:s.id, solo: !strip(s.id).solo});
  el.querySelectorAll("[data-h]").forEach(c => c.onchange = () => send({cmd:"monitor", [c.dataset.h]: c.checked}));
  el.querySelectorAll("[data-in]").forEach(c => { const i = inputOf(c.dataset.in); c.nextElementSibling.textContent = i ? i.name : c.dataset.in;
    c.onchange = () => send({cmd:"input", id:c.dataset.in, hear: c.checked}); });
  if (s.input){
    el.querySelector(".inp").onchange = e => send({cmd:"input", id:s.id, device: e.target.value});
    el.querySelector(".tobot input").onchange = e => send({cmd:"input", id:s.id, to_bot: e.target.checked});
  }
  const pan = el.querySelector(".pan input"), pk = "pan:" + s.id; let plast = 0;
  const setPan = (v, force) => { el.querySelector(".pv").textContent = fmtPan(v / 100); const now = Date.now();
    if (force || now - plast > 60){ plast = now; send({cmd:"strip", id:s.id, pan: v / 100}); } };
  pan.oninput = () => { dragging[pk] = true; setPan(+pan.value); };
  pan.onchange = () => { setPan(+pan.value, true); dragging[pk] = false; };
  pan.ondblclick = () => { pan.value = 0; setPan(0, true); dragging[pk] = false; };
  el.querySelectorAll("[data-a]").forEach(b => b.onclick = () => insertAction(s.id, b.dataset.a));
  setupFader(el, s.id);
  return el;
}
const strip = id => S.strips.find(x => x.id === id);

function setupFader(el, id){
  const f = el.querySelector(".fader");
  let last = 0;
  const at = e => { const r = f.getBoundingClientRect();
    const frac = 1 - Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
    return Math.round((MIN_DB + frac * (MAX_DB - MIN_DB)) * 2) / 2; };
  const set = (db, force) => { showFader(el, db); const now = Date.now();
    if (force || now - last > 60){ last = now; send({cmd:"strip", id, gain_db: db}); } };
  f.onpointerdown = e => { f.setPointerCapture(e.pointerId); dragging[id] = true; set(at(e)); };
  f.onpointermove = e => { if (dragging[id]) set(at(e)); };
  f.onpointerup = f.onpointercancel = e => { if (dragging[id]){ set(at(e), true); dragging[id] = false; } };
  f.ondblclick = () => set(0, true);
}
function showFader(el, db){
  const fr = dbToFrac(db);
  el.querySelector(".fill").style.height = (fr * 100) + "%";
  el.querySelector(".thumb").style.bottom = (fr * 100) + "%";
  el.querySelector(".db").textContent = fmtDb(db);
}

function renderMixer(){
  const box = $("#strips"), sig = JSON.stringify(S.strips.map(s => [s.id, s.name]));
  if (box.dataset.sig !== sig){
    box.dataset.sig = sig; box.innerHTML = "";
    S.strips.forEach(s => box.appendChild(buildStrip(s)));
  }
  S.strips.forEach(s => { const el = box.querySelector(`[data-id="${s.id}"]`); if (!el) return;
    if (!dragging[s.id]) showFader(el, s.gain_db);
    el.querySelector(".mute").classList.toggle("on", s.mute);
    if (s.soloable) el.querySelector(".solo").classList.toggle("on", !!s.solo);
    if (!dragging["pan:" + s.id]){ el.querySelector(".pan input").value = Math.round((s.pan || 0) * 100);
      el.querySelector(".pv").textContent = fmtPan(s.pan || 0); }
    const ul = el.querySelector(".ins"), isig = JSON.stringify([s.inserts, selected[s.id]]);
    if (ul.dataset.sig !== isig){
      ul.dataset.sig = isig; ul.innerHTML = "";
      if (selected[s.id] >= s.inserts.length) selected[s.id] = s.inserts.length - 1;
      s.inserts.forEach((ins, i) => { const li = document.createElement("li");
        li.className = (i === selected[s.id] ? "sel " : "") + (ins.bypass ? "off " : "") + (ins.failed ? "err" : "");
        li.innerHTML = `<input type="checkbox" ${ins.bypass ? "" : "checked"}><span></span>`;
        li.querySelector("span").textContent = ins.name + (ins.failed ? " (errore)" : "");
        li.querySelector("input").onclick = e => { e.stopPropagation();
          send({cmd:"insert", strip:s.id, action:"bypass", index:i, value: !e.target.checked}); };
        li.onclick = () => { selected[s.id] = i; renderMixer(); };
        li.ondblclick = () => { selected[s.id] = i; openParams(s.id, i); };
        ul.appendChild(li); });
    }
    if (s.id === "monitor" && S.monitor){ el.querySelectorAll("[data-h]").forEach(c => c.checked = !!S.monitor[c.dataset.h]);
      el.querySelectorAll("[data-in]").forEach(c => { const i = inputOf(c.dataset.in); c.checked = !!(i && i.hear); }); }
    const inp = s.input && inputOf(s.id);
    if (inp && S.mic){
      const sel = el.querySelector(".inp"), opts = JSON.stringify([S.mic.inputs, inp.device]);
      if (sel.dataset.sig !== opts && document.activeElement !== sel){
        sel.dataset.sig = opts; sel.innerHTML = "";
        const add = (v, t) => { const o = document.createElement("option"); o.value = v; o.textContent = t; sel.appendChild(o); };
        add("", "— nessuno —");
        S.mic.inputs.forEach(n => add(n, n));
        if (inp.device && !S.mic.inputs.includes(inp.device)) add(inp.device, inp.device + " (non trovato)");
        sel.value = inp.device || "";
      }
      el.querySelector(".chs").textContent = inp.device ? `· ${inp.mono ? "mono" : "stereo"} ${inp.channels}` : "";
      el.querySelector(".tobot input").checked = !!inp.to_bot;
    }
  });
  const B = S.bot, chip = $("#botchip");
  chip.textContent = !B.available ? "🤖 non disponibile" : B.channel ? `🤖 ${B.channel}` : B.online ? "🤖 online" : B.running ? "🤖 connessione…" : "🤖 spento";
  chip.classList.toggle("on", !!B.channel);
  $("#botmsg").textContent = B.message || "";
  $("#bot-toggle").textContent = B.running ? "⏻ Ferma" : "⏻ Avvia";
}

function insertAction(id, a){
  const i = selected[id], n = strip(id).inserts.length, ok = i != null && i >= 0 && i < n;
  if (a === "add") return openAdd(id);
  if (!ok) return;
  if (a === "remove") send({cmd:"insert", strip:id, action:"remove", index:i});
  if (a === "up" && i > 0){ send({cmd:"insert", strip:id, action:"move", index:i, delta:-1}); selected[id] = i - 1; }
  if (a === "down" && i < n - 1){ send({cmd:"insert", strip:id, action:"move", index:i, delta:1}); selected[id] = i + 1; }
  if (a === "edit") openParams(id, i);
}

function openSheet(title){ $("#sheet-title").textContent = title; $("#sheet-body").innerHTML = ""; $("#sheet").classList.add("open"); return $("#sheet-body"); }
function closeSheet(){ $("#sheet").classList.remove("open"); sheetFor = null; }
$("#sheet-close").onclick = closeSheet;
$("#sheet").onclick = e => { if (e.target.id === "sheet") closeSheet(); };

async function openAdd(id){
  const body = openSheet(`Aggiungi inserto — ${strip(id).name}`);
  body.innerHTML = '<div class="muted">Carico l\'elenco…</div>';
  let E; try { E = await (await fetch("/api/effects", {cache:"no-store"})).json(); } catch(e){ body.textContent = "Elenco non disponibile."; return; }
  body.innerHTML = '<div class="sect">EFFETTI INTEGRATI</div>';
  E.builtin.forEach(fx => { const b = document.createElement("button"); b.className = "opt"; b.textContent = fx.label;
    b.onclick = () => { send({cmd:"insert", strip:id, action:"add", type:fx.type}); selected[id] = strip(id).inserts.length; closeSheet(); };
    body.appendChild(b); });
  const h = document.createElement("div"); h.className = "sect"; h.style.marginTop = "12px"; h.textContent = "PLUGIN VST3"; body.appendChild(h);
  if (!E.vst.length){ const m = document.createElement("div"); m.className = "muted"; m.textContent = "Nessun plugin trovato nelle cartelle VST3."; body.appendChild(m); }
  E.vst.forEach(v => { const b = document.createElement("button"); b.className = "opt"; b.textContent = v.name; b.title = v.path;
    b.onclick = () => { send({cmd:"insert", strip:id, action:"add_vst", path:v.path}); selected[id] = strip(id).inserts.length; closeSheet(); };
    body.appendChild(b); });
  const rs = document.createElement("button"); rs.className = "opt"; rs.textContent = "↻ Riscansiona le cartelle VST3";
  rs.onclick = () => { send({cmd:"insert", strip:id, action:"rescan"}); setTimeout(() => openAdd(id), 800); };
  body.appendChild(rs);
}

const fmtVal = (v, u) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2)) + (u ? " " + u : "");
async function openParams(id, i){
  const body = openSheet("Parametri");
  sheetFor = [id, i];
  let P; try { P = await (await fetch(`/api/insert?strip=${encodeURIComponent(id)}&index=${i}`, {cache:"no-store"})).json(); }
  catch(e){ body.textContent = "Parametri non disponibili."; return; }
  if (P.error){ body.textContent = "Inserto non trovato."; return; }
  $("#sheet-title").textContent = `${P.name} — ${strip(id).name}`;
  if (!P.params.length){ body.innerHTML = '<div class="muted">Questo inserto non ha parametri regolabili da qui.</div>'; return; }
  if (P.params.length > 12){ const q = document.createElement("input"); q.type = "text"; q.placeholder = "Filtra parametri…";
    q.style.width = "100%"; q.oninput = () => body.querySelectorAll(".prm").forEach(r => r.style.display = r.dataset.n.includes(q.value.toLowerCase()) ? "" : "none");
    body.appendChild(q); }
  const timers = {};
  P.params.forEach(pr => { const r = document.createElement("div"); r.className = "prm"; r.dataset.n = pr.label.toLowerCase();
    const step = pr.raw ? 0.001 : (pr.max - pr.min) / 500;
    r.innerHTML = `<div class="row"><span></span><span class="val"></span></div><input type="range" min="${pr.min}" max="${pr.max}" step="${step}" value="${pr.value}">`;
    r.querySelector("span").textContent = pr.label;
    const val = r.querySelector(".val"), inp = r.querySelector("input");
    val.textContent = pr.raw ? pr.text : fmtVal(pr.value, pr.unit);
    inp.oninput = () => { const v = parseFloat(inp.value);
      if (!pr.raw) val.textContent = fmtVal(v, pr.unit);
      clearTimeout(timers[pr.name]);
      timers[pr.name] = setTimeout(async () => { await send({cmd:"insert", strip:id, action:"param", index:i, name:pr.name, value:v});
        if (pr.raw){ try { const Q = await (await fetch(`/api/insert?strip=${encodeURIComponent(id)}&index=${i}`, {cache:"no-store"})).json();
          const x = Q.params.find(q => q.name === pr.name); if (x) val.textContent = x.text; } catch(e){} } }, 70); };
    body.appendChild(r); });
}

// Meter: canali del mixer e pad, ~8 volte al secondo
const padAnim = {};
const VU_TICKS = [6, 0, -6, -12, -18, -24, -36, -48, -60];
function drawVu(cv, l, r, hl, hr){
  const c = cv.getContext("2d"), W = cv.width, H = cv.height, BW = 44, bw = BW/2 - 3;
  c.clearRect(0, 0, W, H);
  [[l, hl], [r, hr]].forEach(([lv, hd], k) => { const x = k * (bw + 6);
    c.fillStyle = "#15171c"; c.fillRect(x, 0, bw, H);
    const h = vuFrac(lv) * H, g = c.createLinearGradient(0, H, 0, 0);
    g.addColorStop(0, "#3ec7b2"); g.addColorStop(vuFrac(-12), "#3ec7b2"); g.addColorStop(vuFrac(-3), "#e3c84b"); g.addColorStop(vuFrac(0), "#e5534b");
    c.fillStyle = g; c.fillRect(x, H - h, bw, h);
    if (hd > VU_MIN + 1){ c.fillStyle = hd < 0 ? "#e6e8ee" : "#e5534b"; c.fillRect(x, H - vuFrac(hd) * H - 2, bw, 3); } });
  // scala in dB, come nel programma
  c.font = "18px ui-monospace,Consolas,monospace"; c.textBaseline = "middle";
  let lastY = -100;
  VU_TICKS.forEach(db => { const y = Math.round(H - vuFrac(db) * H);
    c.fillStyle = db === 0 ? "#8b92a3" : "rgba(38,42,51,.75)"; c.fillRect(0, y, BW, 2);
    c.fillStyle = "#8b92a3"; c.fillRect(BW + 2, y, 8, 2);
    if (Math.abs(y - lastY) >= 20){ c.fillStyle = db === 0 ? "#e6e8ee" : "#8b92a3";
      c.fillText(db <= VU_MIN ? "-∞" : (db > 0 ? "+" + db : String(db)), BW + 13, Math.min(Math.max(y, 10), H - 10)); lastY = y; } });
}
async function pollLevels(){
  if (document.hidden || !S) return;
  let L; try { L = await (await fetch("/api/levels", {cache:"no-store"})).json(); } catch(e){ return; }
  if ($("#mixer").classList.contains("sel"))
    Object.entries(L.strips || {}).forEach(([id, v]) => { const el = document.querySelector(`.mstrip[data-id="${id}"] canvas`); if (el) drawVu(el, ...v); });
  const now = performance.now();
  Object.entries(L.pads || {}).forEach(([key, [p, db, d]]) => { padAnim[key] = {p, d, t: now, db: Math.max(db, (padAnim[key] || {}).db ?? -99)}; });
  Object.keys(padAnim).forEach(k => { if (!(L.pads || {})[k]) padAnim[k].gone = true; });
}
function animatePads(){
  const now = performance.now();
  document.querySelectorAll(".pad[data-key]").forEach(el => { const a = padAnim[el.dataset.key];
    if (!a){ el.classList.remove("active"); return; }
    const dt = (now - a.t) / 1000;
    a.db = Math.max(-99, a.db - 36 * Math.min(dt, .05));            // caduta come sul PC
    const prog = a.gone ? 1 : Math.min(1, a.p + (a.d ? dt / a.d : 0));
    el.querySelector(".prog").style.width = (prog * 100) + "%";
    el.querySelector(".vu i").style.height = (Math.max(0, Math.min(1, (a.db + 48) / 48)) * 100) + "%";
    el.classList.toggle("active", a.db > -47 || !a.gone);
    if (a.gone && a.db <= -47){ delete padAnim[el.dataset.key]; el.classList.remove("active"); } });
  requestAnimationFrame(animatePads);
}
requestAnimationFrame(animatePads);
setInterval(pollLevels, 125);

function render(){ if (!S) return; renderPads(); renderPlayer(); renderMixer(); }

async function poll(){
  try {
    const r = await fetch("/api/state", {cache:"no-store"});
    if (r.status === 401){ document.body.innerHTML = "<p style='padding:24px'>Chiave non più valida: riapri il link aggiornato dalla soundboard.</p>"; return; }
    S = await r.json(); $("#offline").style.display = "none"; render();
  } catch(e){ $("#offline").style.display = "block"; }
}
poll(); setInterval(poll, 700);
window.addEventListener("resize", () => { $("#grid").dataset.sig = ""; render(); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
</script>
</body>
</html>
"""
