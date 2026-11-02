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
.queue li span:first-child{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.strip{display:grid;grid-template-columns:1fr auto;gap:2px 10px;align-items:center;padding:10px 0;border-bottom:1px solid var(--panel2)}
.strip .db{font:12px ui-monospace,Consolas,monospace;color:var(--muted)}
.strip button.mute{padding:6px 10px;font-weight:700;font-size:12px}
.strip button.mute.on{background:var(--danger);color:#fff;border:none}
.strip input{grid-column:1/3}
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
        <button data-p="prev">⏮</button>
        <button data-p="toggle" class="big" id="pp">▶</button>
        <button data-p="stop">⏹</button>
        <button data-p="next">⏭</button>
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
    <div class="card" id="strips"></div>
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
<script>
const $ = s => document.querySelector(s);
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
    d.innerHTML = `<span class="n">${i+1}</span>${em}<div class="lb"></div>`;
    d.querySelector(".lb").textContent = p.label;
    d.onclick = () => { send({cmd:"pad", page, index:i}); d.classList.add("playing"); };
    g.appendChild(d);
  });
}

function renderPlayer(){
  const P = S.player;
  $("#np-title").textContent = P.title || "Nessun brano";
  const st = {playing:"In riproduzione", loading:"Caricamento…", paused:"In pausa", stopped:"Fermo"}[P.state] || "";
  $("#np-sub").textContent = P.title ? `${st}${P.kind === "youtube" ? " · YouTube" : ""}` : "Aggiungi un link YouTube qui sotto";
  $("#pp").textContent = (P.state === "playing" || P.state === "loading") ? "⏸" : "▶";
  $("#t-pos").textContent = fmt(P.position); $("#t-dur").textContent = fmt(P.duration);
  if (!seeking) $("#seek").value = P.duration ? Math.round(P.position / P.duration * 1000) : 0;
  if (!dragging.player) $("#pvol").value = Math.round(P.volume_db * 10);
  if (P.message) $("#addmsg").textContent = P.message;
  const q = $("#queue"), qsig = JSON.stringify([P.index, P.queue]);
  if (q.dataset.sig !== qsig){
    q.dataset.sig = qsig; q.innerHTML = "";
    if (!P.queue.length) q.innerHTML = '<li class="muted">Coda vuota</li>';
    P.queue.forEach((t, i) => { const li = document.createElement("li"); if (i === P.index) li.className = "cur";
      li.innerHTML = `<span></span><span class="time">${fmt(t.duration)}</span>`;
      li.firstChild.textContent = (i === P.index ? "▶ " : "") + (t.kind === "youtube" ? "📺 " : "") + t.title;
      li.onclick = () => send({cmd:"player", action:"play", index:i}); q.appendChild(li); });
  }
}

function renderMixer(){
  const box = $("#strips"), sig = S.strips.map(s => s.id).join();
  if (box.dataset.sig !== sig){
    box.dataset.sig = sig; box.innerHTML = "";
    S.strips.forEach(s => { const el = document.createElement("div"); el.className = "strip"; el.dataset.id = s.id;
      el.innerHTML = `<div><b></b> <span class="db"></span></div><button class="mute">MUTE</button>
        <input type="range" min="-600" max="120" step="5">`;
      el.querySelector("b").textContent = s.name;
      const r = el.querySelector("input");
      r.oninput = () => { dragging[s.id] = true; el.querySelector(".db").textContent = fmtDb(r.value/10);
        send({cmd:"strip", id:s.id, gain_db:r.value/10}); };
      r.onchange = () => dragging[s.id] = false;
      el.querySelector(".mute").onclick = () => send({cmd:"strip", id:s.id, mute: !S.strips.find(x => x.id === s.id).mute});
      box.appendChild(el); });
  }
  S.strips.forEach(s => { const el = box.querySelector(`[data-id="${s.id}"]`); if (!el) return;
    if (!dragging[s.id]){ el.querySelector("input").value = Math.round(s.gain_db*10); el.querySelector(".db").textContent = fmtDb(s.gain_db); }
    el.querySelector(".mute").classList.toggle("on", s.mute); });
  const B = S.bot, chip = $("#botchip");
  chip.textContent = !B.available ? "🤖 non disponibile" : B.channel ? `🤖 ${B.channel}` : B.online ? "🤖 online" : B.running ? "🤖 connessione…" : "🤖 spento";
  chip.classList.toggle("on", !!B.channel);
  $("#botmsg").textContent = B.message || "";
  $("#bot-toggle").textContent = B.running ? "⏻ Ferma" : "⏻ Avvia";
}

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
