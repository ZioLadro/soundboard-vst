"""Sintesi vocale (text to speech) e frasi sui pad.

Due motori:
- ``edge``: voci neurali di Microsoft Edge (molto naturali, tante lingue), tramite edge-tts. Serve Internet.
- ``system``: voci installate nel sistema, senza Internet. Su Windows le voci SAPI (es. «Microsoft Elsa»)
  tramite PowerShell, su macOS il comando ``say``, su Linux espeak-ng.

Ogni frase sintetizzata finisce in una cache su disco (il nome del file dipende da testo, motore, voce,
velocità e tono): la seconda volta parte subito. Il modulo non dipende da Qt.

Le frasi sui pad hanno chiavi ``tts:<id>``: nel resto del programma si comportano come i file della
cartella (nome, colore, emoji, volume, scorciatoia, nota MIDI…), ma il loro audio viene da qui.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from . import binaries
from .config import config_dir

ENGINE_EDGE, ENGINE_SYSTEM = "edge", "system"
ENGINE_LABELS = {ENGINE_EDGE: "Voci neurali Microsoft (online, molto naturali)",
                 ENGINE_SYSTEM: "Voci del sistema (offline)"}
DEFAULT_EDGE_VOICE = "it-IT-DiegoNeural"
MAX_TEXT = 1000                       # caratteri per frase
CACHE_LIMIT = 200 * 1024 * 1024       # 200 MB, poi si cancellano le frasi usate meno di recente
PHRASE_PREFIX = "tts:"
LIVE_KEY = "__tts__"                  # chiave delle frasi scritte al volo (non sui pad)
SYNTH_TIMEOUT = 60

# Usate se l'elenco completo non si può scaricare (es. senza Internet).
FALLBACK_EDGE_VOICES = [
    ("it-IT-DiegoNeural", "Diego · italiano · M"), ("it-IT-ElsaNeural", "Elsa · italiano · F"),
    ("it-IT-IsabellaNeural", "Isabella · italiano · F"),
    ("en-US-GuyNeural", "Guy · inglese (USA) · M"), ("en-US-JennyNeural", "Jenny · inglese (USA) · F"),
    ("en-US-AriaNeural", "Aria · inglese (USA) · F"), ("en-GB-RyanNeural", "Ryan · inglese (UK) · M"),
    ("en-GB-SoniaNeural", "Sonia · inglese (UK) · F"), ("es-ES-AlvaroNeural", "Álvaro · spagnolo · M"),
    ("fr-FR-HenriNeural", "Henri · francese · M"), ("de-DE-ConradNeural", "Conrad · tedesco · M"),
    ("ja-JP-KeitaNeural", "Keita · giapponese · M"),
]

_LANGS = {"it": "italiano", "en": "inglese", "es": "spagnolo", "fr": "francese", "de": "tedesco",
          "pt": "portoghese", "ja": "giapponese", "zh": "cinese", "ru": "russo", "nl": "olandese",
          "pl": "polacco", "ko": "coreano", "ar": "arabo", "tr": "turco", "sv": "svedese"}


class TTSError(RuntimeError):
    pass


@dataclass(frozen=True)
class Voice:
    id: str        # quello che si passa al motore
    label: str     # quello che si mostra


@dataclass(frozen=True)
class Spec:
    """Tutto ciò che determina l'audio di una frase (e quindi il file in cache)."""
    text: str
    engine: str = ENGINE_EDGE
    voice: str = ""
    rate: int = 0        # velocità in %, da -50 a +100
    pitch: int = 0       # tono in Hz, da -50 a +50 (solo voci neurali)

    def cache_name(self) -> str:
        raw = "\x1f".join([self.engine, self.voice, str(self.rate), str(self.pitch), self.text])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:MAX_TEXT]


# Frasi --------------------------------------------------------------------------------------
def is_phrase(key: str) -> bool:
    return str(key).startswith(PHRASE_PREFIX)


def new_phrase_key() -> str:
    return PHRASE_PREFIX + secrets.token_hex(4)


def phrase_label(text: str, limit: int = 28) -> str:
    text = clean_text(text)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def spec_for(text: str, settings: dict, voice: str = "", engine: str = "") -> Spec:
    """Unisce le impostazioni generali con la voce scelta per una frase (vuota = predefinita)."""
    engine = engine or settings.get("engine") or ENGINE_EDGE
    if engine not in ENGINE_LABELS:
        engine = ENGINE_EDGE
    if not voice:
        if engine == ENGINE_EDGE:
            voice = settings.get("edge_voice") or DEFAULT_EDGE_VOICE
        else:
            voice = settings.get("system_voice", "")
    rate = max(-50, min(100, int(settings.get("rate", 0) or 0)))
    pitch = max(-50, min(50, int(settings.get("pitch", 0) or 0))) if engine == ENGINE_EDGE else 0
    return Spec(clean_text(text), engine, voice, rate, pitch)


def phrase_spec(phrase: dict, settings: dict) -> Spec:
    return spec_for(phrase.get("text", ""), settings, phrase.get("voice", ""), phrase.get("engine", ""))


# Motori ---------------------------------------------------------------------------------------
class EdgeEngine:
    name = ENGINE_EDGE
    ext = ".mp3"

    def available(self) -> str:
        """Stringa vuota se si può usare, altrimenti il motivo."""
        try:
            import edge_tts  # noqa: F401
        except Exception as exc:
            return f"edge-tts non installato ({exc})"
        return ""

    def synthesize(self, spec: Spec, out: Path) -> None:
        import edge_tts

        async def run():
            com = edge_tts.Communicate(spec.text, spec.voice or DEFAULT_EDGE_VOICE,
                                       rate=f"{spec.rate:+d}%", pitch=f"{spec.pitch:+d}Hz",
                                       connect_timeout=10, receive_timeout=SYNTH_TIMEOUT)
            await com.save(str(out))

        try:
            asyncio.run(run())
        except Exception as exc:
            name = exc.__class__.__name__
            if "NoAudioReceived" in name:
                raise TTSError("nessun audio ricevuto: la voce scelta potrebbe non esistere") from exc
            if any(s in name for s in ("Connector", "Connection", "Timeout", "ClientError", "gaierror")):
                raise TTSError("servizio vocale Microsoft non raggiungibile: controlla la connessione "
                               "o usa le voci del sistema") from exc
            raise TTSError(str(exc) or name) from exc

    def voices(self) -> list[Voice]:
        import edge_tts

        raw = asyncio.run(edge_tts.list_voices())
        out = []
        for v in raw:
            short = v.get("ShortName", "")
            if not short:
                continue
            locale = v.get("Locale", "")
            lang = _LANGS.get(locale.split("-")[0], locale)
            region = locale.split("-")[1] if "-" in locale else ""
            name = short.split("-", 2)[-1].replace("Neural", "").replace("Multilingual", " multilingue")
            gender = {"Male": "M", "Female": "F"}.get(v.get("Gender", ""), "")
            out.append(Voice(short, f"{name} · {lang} ({region}) · {gender}".replace(" ()", "")))
        # italiano prima, poi le altre lingue in ordine
        out.sort(key=lambda v: (not v.id.startswith("it-"), v.id))
        return out


_PS_SPEAK = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = '{voice}'
if ($v) {{ try {{ $s.SelectVoice($v) }} catch {{ }} }}
$s.Rate = {rate}
$s.SetOutputToWaveFile('{out}')
$s.Speak([IO.File]::ReadAllText('{text}', [Text.Encoding]::UTF8))
$s.Dispose()
"""

_PS_VOICES = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object {
  $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture.Name + '|' + $_.VoiceInfo.Gender }
"""


def _ps_quote(value: str) -> str:
    """Testo dentro apici singoli di PowerShell (l'apice si raddoppia)."""
    return str(value).replace("'", "''")


def _powershell(script: str, timeout: float = SYNTH_TIMEOUT) -> subprocess.CompletedProcess:
    import base64

    exe = shutil.which("powershell") or shutil.which("powershell.exe") or "powershell.exe"
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    return subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-EncodedCommand", encoded], capture_output=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, **binaries.no_window_kwargs())


class SystemEngine:
    name = ENGINE_SYSTEM

    def __init__(self, platform: str | None = None):
        self.platform = platform or sys.platform

    @property
    def ext(self) -> str:
        return ".aiff" if self.platform == "darwin" else ".wav"

    def _linux_exe(self) -> str | None:
        return shutil.which("espeak-ng") or shutil.which("espeak")

    def available(self) -> str:
        if self.platform == "win32" or self.platform == "darwin":
            return ""
        return "" if self._linux_exe() else "installa espeak-ng per avere le voci del sistema"

    def command(self, spec: Spec, out: Path, text_file: Path) -> list[str] | str:
        """Comando da eseguire (su Windows lo script PowerShell)."""
        if self.platform == "win32":
            rate = max(-10, min(10, round(spec.rate / 10)))
            return _PS_SPEAK.format(voice=_ps_quote(spec.voice), rate=rate, out=_ps_quote(out),
                                    text=_ps_quote(text_file))
        if self.platform == "darwin":
            cmd = ["say", "-o", str(out), "-f", str(text_file), "-r", str(round(180 * (1 + spec.rate / 100)))]
            return cmd + (["-v", spec.voice] if spec.voice else [])
        exe = self._linux_exe() or "espeak-ng"
        cmd = [exe, "-w", str(out), "-f", str(text_file), "-s", str(round(170 * (1 + spec.rate / 100)))]
        return cmd + (["-v", spec.voice] if spec.voice else [])

    def synthesize(self, spec: Spec, out: Path) -> None:
        reason = self.available()
        if reason:
            raise TTSError(reason)
        with tempfile.TemporaryDirectory(prefix="sbtts") as tmp:
            text_file = Path(tmp) / "testo.txt"
            text_file.write_text(spec.text, encoding="utf-8")
            cmd = self.command(spec, out, text_file)
            try:
                if isinstance(cmd, str):
                    r = _powershell(cmd)
                else:
                    r = subprocess.run(cmd, capture_output=True, timeout=SYNTH_TIMEOUT,
                                       stdin=subprocess.DEVNULL, **binaries.no_window_kwargs())
            except FileNotFoundError as exc:
                raise TTSError(f"programma per la voce non trovato: {exc.filename}") from exc
            except subprocess.TimeoutExpired as exc:
                raise TTSError("la sintesi vocale non ha risposto in tempo") from exc
        if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            err = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            raise TTSError(err[-1] if err else f"sintesi non riuscita (codice {r.returncode})")

    def voices(self) -> list[Voice]:
        if self.platform == "win32":
            r = _powershell(_PS_VOICES, timeout=20)
            out = []
            for line in r.stdout.decode("utf-8", "replace").splitlines():
                parts = line.strip().split("|")
                if len(parts) == 3 and parts[0]:
                    lang = _LANGS.get(parts[1].split("-")[0], parts[1])
                    out.append(Voice(parts[0], f"{parts[0]} · {lang}"))
            return out
        if self.platform == "darwin":
            r = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=20)
            out = []
            for line in r.stdout.splitlines():
                m = re.match(r"^(.+?)\s+([a-z]{2})[_-][A-Z]{2}\s+#", line)
                if m:
                    out.append(Voice(m.group(1).strip(), f"{m.group(1).strip()} · {_LANGS.get(m.group(2), m.group(2))}"))
            return out
        return [Voice(code, f"espeak · {name}") for code, name in _LANGS.items()]


ENGINES = {ENGINE_EDGE: EdgeEngine(), ENGINE_SYSTEM: SystemEngine()}


def unavailable_reason(engine: str) -> str:
    eng = ENGINES.get(engine)
    return "motore sconosciuto" if eng is None else eng.available()


_voice_cache: dict[str, list[Voice]] = {}


def list_voices(engine: str, refresh: bool = False) -> list[Voice]:
    """Voci del motore (ricordate per la sessione). Per le voci neurali, se non si può scaricare
    l'elenco, un elenco ridotto (che non viene ricordato, così si riprova la volta dopo)."""
    if not refresh and engine in _voice_cache:
        return list(_voice_cache[engine])
    eng = ENGINES[engine]
    try:
        voices = eng.voices()
        if voices:
            _voice_cache[engine] = voices
            return list(voices)
    except Exception:
        pass
    if engine == ENGINE_EDGE:
        return [Voice(i, label) for i, label in FALLBACK_EDGE_VOICES]
    return []


def cached_voices(engine: str) -> list[Voice] | None:
    return list(_voice_cache[engine]) if engine in _voice_cache else None


# Cache e sintesi in background ---------------------------------------------------------------
_lock = threading.Lock()
_inflight: dict[str, Future] = {}
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tts")


def cache_dir() -> Path:
    return config_dir() / "cache" / "tts"


def cached_file(spec: Spec) -> Path | None:
    p = cache_dir() / (spec.cache_name() + ENGINES[spec.engine].ext)
    return p if p.is_file() and p.stat().st_size > 0 else None


def _do_synthesize(spec: Spec) -> Path:
    folder = cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    eng = ENGINES[spec.engine]
    reason = eng.available()
    if reason:
        raise TTSError(reason)
    dest = folder / (spec.cache_name() + eng.ext)
    tmp = folder / (spec.cache_name() + ".part" + eng.ext)
    try:
        eng.synthesize(spec, tmp)
        os.replace(tmp, dest)            # il file completo compare solo alla fine
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    _trim_cache(keep=dest)
    return dest


def synthesize_async(spec: Spec) -> Future:
    """File audio della frase: dalla cache, oppure sintetizzato in background (una volta sola)."""
    if not spec.text:
        fut: Future = Future()
        fut.set_exception(TTSError("testo vuoto"))
        return fut
    hit = cached_file(spec)
    if hit is not None:
        try:
            os.utime(hit, None)          # usata di recente: non va cancellata per prima
        except OSError:
            pass
        fut = Future()
        fut.set_result(hit)
        return fut
    name = spec.engine + spec.cache_name()
    with _lock:
        fut = _inflight.get(name)
        if fut is None or fut.done():
            fut = _pool.submit(_do_synthesize, spec)
            _inflight[name] = fut
            fut.add_done_callback(lambda f, n=name: _inflight.pop(n, None) if _inflight.get(n) is f else None)
    return fut


def synthesize(spec: Spec, timeout: float | None = SYNTH_TIMEOUT + 5) -> Path:
    return synthesize_async(spec).result(timeout)


def _trim_cache(keep: Path | None = None) -> None:
    try:
        files = [p for p in cache_dir().iterdir() if p.is_file() and ".part" not in p.name]
    except OSError:
        return
    total = sum(p.stat().st_size for p in files)
    for p in sorted(files, key=lambda f: f.stat().st_mtime):
        if total <= CACHE_LIMIT:
            break
        if keep is not None and p == keep:
            continue
        try:
            size = p.stat().st_size
            p.unlink()
            total -= size
        except OSError:
            pass
