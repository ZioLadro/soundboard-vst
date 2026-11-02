"""Nuovi suoni per la soundboard da YouTube, MyInstants, link a file audio o file caricati.

Tutto passa da ffmpeg, che converte qualunque formato (anche l'audio dei video) in mp3 nella
cartella dei suoni, tenendo solo il pezzo tra ``start`` e ``end`` se indicati. Il modulo non
dipende da Qt: le funzioni sono bloccanti e vanno chiamate fuori dal thread dell'interfaccia.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import binaries, myinstants, youtube
from .config import config_dir

MAX_SECONDS = 600                 # un suono più lungo di 10 minuti viene tagliato
MAX_DOWNLOAD = 25 * 1024 * 1024   # file da link o da Discord
TIMEOUT = 120
_TIME_RE = re.compile(r"^\s*(?:(\d+):)?(?:(\d+):)?(\d+(?:[.,]\d+)?)\s*s?\s*$")
# formati provati in ordine: se ffmpeg non ha l'encoder mp3 si ripiega su ogg, poi wav
_FORMATS = [(".mp3", ["-c:a", "libmp3lame", "-q:a", "2"]), (".ogg", ["-c:a", "libvorbis", "-q:a", "5"]),
            (".wav", ["-c:a", "pcm_s16le"])]


class ImportError_(RuntimeError):
    """Errore da mostrare così com'è."""


@dataclass
class Result:
    path: Path
    title: str
    truncated: bool = False


def parse_time(text: str | float | int | None) -> float:
    """«12», «1:23», «1:02:03», «1:23.5», «83,2s» → secondi. Vuoto = 0."""
    if text is None:
        return 0.0
    if isinstance(text, (int, float)):
        return max(0.0, float(text))
    text = str(text).strip()
    if not text:
        return 0.0
    m = _TIME_RE.match(text)
    if not m:
        raise ImportError_(f"tempo non valido: «{text}» (usa per esempio 12, 1:23 o 1:02:03)")
    a, b, c = m.groups()
    secs = float(c.replace(",", "."))
    if a is not None and b is not None:          # h:m:s
        return int(a) * 3600 + int(b) * 60 + secs
    if a is not None:                            # m:s
        return int(a) * 60 + secs
    return secs


def format_time(seconds: float) -> str:
    m, s = divmod(max(0.0, seconds), 60)
    return f"{int(m)}:{s:04.1f}".replace(".0", "") if m else f"{s:g} s"


def incoming_dir() -> Path:
    """File arrivati da fuori (es. allegati di Discord) in attesa di essere importati."""
    return config_dir() / "cache" / "import"


def is_incoming(path: Path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(incoming_dir().resolve())
    except (OSError, ValueError):
        return False


def new_incoming(suffix: str) -> Path:
    folder = incoming_dir()
    folder.mkdir(parents=True, exist_ok=True)
    suffix = re.sub(r"[^A-Za-z0-9.]", "", suffix)[:10] or ".bin"
    return folder / f"{secrets.token_hex(6)}{suffix}"


def classify(source: str) -> str:
    """«youtube», «myinstants» (pagina di un suono), «http» (link a un file) o «search» (testo)."""
    s = source.strip()
    if youtube.is_youtube_url(s):
        return "youtube"
    u = urllib.parse.urlparse(s)
    if u.scheme in ("http", "https") and u.netloc:
        host = (u.hostname or "").lower()
        if (host == "myinstants.com" or host.endswith(".myinstants.com")) and "/instant/" in u.path:
            return "myinstants"
        return "http"
    return "search"


def _download(url: str) -> tuple[Path, str]:
    req = urllib.request.Request(url, headers={"User-Agent": myinstants.USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read(MAX_DOWNLOAD + 1)
        ctype = resp.headers.get("Content-Type", "")
    if len(data) > MAX_DOWNLOAD:
        raise ImportError_(f"file troppo grande (massimo {MAX_DOWNLOAD // 1024 // 1024} MB)")
    if "text/html" in ctype:
        raise ImportError_("il link porta a una pagina web, non a un file audio")
    name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name
    dest = new_incoming(Path(name).suffix or ".bin")
    dest.write_bytes(data)
    return dest, Path(name).stem or "suono"


def _myinstants(url: str) -> tuple[Path, str]:
    page = myinstants._get(url).decode("utf-8", "replace")
    found = myinstants.parse_results(page)
    if not found:
        raise ImportError_("non trovo il suono in questa pagina di MyInstants")
    slug = [p for p in urllib.parse.urlparse(url).path.split("/") if p][-1]
    inst = next((i for i in found if i.slug == slug), found[0])
    dest = new_incoming(Path(urllib.parse.urlparse(inst.url).path).suffix or ".mp3")
    dest.write_bytes(myinstants.download_bytes(inst))
    return dest, inst.name


def _youtube(source: str, search: bool) -> tuple[Path, str]:
    if not youtube.available():
        raise ImportError_(f"YouTube non disponibile: {youtube.unavailable_reason()}")
    tracks = youtube.search(source, count=1) if search else youtube.resolve(source)
    if not tracks:
        raise ImportError_("nessun risultato su YouTube" if search else "video non trovato")
    track = tracks[0]
    if track.duration and track.duration > 3 * 3600:
        raise ImportError_("video troppo lungo per un suono")
    return youtube.download(track), track.title


def fetch(source: str, local: bool = False) -> tuple[Path, str, bool]:
    """Scarica (o trova) il file da importare: (percorso, titolo, da cancellare dopo)."""
    if local:
        p = Path(source)
        if not p.is_file():
            raise ImportError_("file non trovato")
        return p, p.stem, is_incoming(p)
    kind = classify(source)
    if kind in ("youtube", "search"):
        path, title = _youtube(source, search=kind == "search")
        return path, title, False                 # resta nella cache di YouTube
    if kind == "myinstants":
        path, title = _myinstants(source)
    else:
        path, title = _download(source)
    return path, title, True


def unique_dest(folder: Path, name: str, ext: str) -> Path:
    base = myinstants.safe_filename(name)
    dest = folder / f"{base}{ext}"
    n = 1
    while dest.exists():
        dest = folder / f"{base} ({n}){ext}"
        n += 1
    return dest


def convert(src: Path, folder: Path, name: str, start: float = 0.0, end: float = 0.0) -> tuple[Path, bool]:
    """Converte ``src`` in un file della soundboard, solo tra ``start`` ed ``end``: (file, tagliato)."""
    exe = binaries.ffmpeg_exe()
    if not exe:
        raise ImportError_("ffmpeg non disponibile")
    if end and end <= start:
        raise ImportError_("la fine deve venire dopo l'inizio")
    length = (end - start) if end else MAX_SECONDS
    truncated = length > MAX_SECONDS
    length = min(length, MAX_SECONDS)
    folder.mkdir(parents=True, exist_ok=True)
    last_err = ""
    for ext, codec in _FORMATS:
        dest = unique_dest(folder, name, ext)
        tmp = dest.with_name(dest.stem + ".part" + ext)
        cmd = [exe, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
        if start:
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-i", str(src), "-t", f"{length:.3f}", "-vn", "-ac", "2", "-ar", "48000", *codec, str(tmp)]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL,
                               **binaries.no_window_kwargs())
        except subprocess.TimeoutExpired:
            raise ImportError_("la conversione ci sta mettendo troppo") from None
        if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, dest)
            return dest, truncated and not end
        last_err = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        last_err = last_err[-1] if last_err else f"codice {r.returncode}"
        try:
            tmp.unlink()
        except OSError:
            pass
        if not any(k in last_err.lower() for k in ("encoder", "unknown", "not found")):
            break                                  # errore del file, non del formato: inutile riprovare
    if "Invalid data" in last_err or "could not find codec" in last_err.lower():
        raise ImportError_("il file non contiene audio leggibile")
    raise ImportError_(f"conversione non riuscita ({last_err})")


def import_source(source: str, folder: Path, name: str = "", start=0.0, end=0.0,
                  local: bool = False) -> Result:
    """Importa un suono nella cartella: YouTube (link o ricerca), MyInstants, link o file locale."""
    source = (source or "").strip()
    if not source:
        raise ImportError_("indica un file, un link o cosa cercare su YouTube")
    start, end = parse_time(start), parse_time(end)
    path, title, temporary = fetch(source, local)
    try:
        dest, truncated = convert(path, folder, name.strip() or title, start, end)
    finally:
        if temporary:
            try:
                path.unlink()
            except OSError:
                pass
    return Result(dest, title, truncated)
