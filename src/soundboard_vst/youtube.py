"""YouTube tramite yt-dlp: video, playlist e ricerca, riprodotti solo come audio.

yt-dlp richiede un motore JavaScript per YouTube: usiamo Deno incluso nel pacchetto
(vedi ``binaries.deno_exe``) e il componente ``yt-dlp-ejs``.
"""

from __future__ import annotations

import glob
import hashlib
import os
import re
import threading
import urllib.parse
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from . import binaries
from .audio.player import Track
from .config import config_dir

_YT_HOSTS = ("youtube.com", "youtu.be", "music.youtube.com", "m.youtube.com", "www.youtube.com")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_error: str | None = None
_ydl_cls = None


def _lib():
    global _ydl_cls, _error
    if _ydl_cls is None and _error is None:
        try:
            from yt_dlp import YoutubeDL

            _ydl_cls = YoutubeDL
        except Exception as exc:
            _error = str(exc) or exc.__class__.__name__
    return _ydl_cls


def available() -> bool:
    return _lib() is not None


def unavailable_reason() -> str:
    _lib()
    return _error or ""


def is_youtube_url(text: str) -> bool:
    try:
        u = urllib.parse.urlparse(text.strip())
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme in ("http", "https") and any(host == h or host.endswith("." + h) for h in _YT_HOSTS)


def _options(**extra) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "socket_timeout": 15,
    }
    deno = binaries.deno_exe()
    opts["js_runtimes"] = {"deno": {"path": deno}} if deno else {"deno": {}}
    opts.update(extra)
    return opts


def _entry_url(entry: dict) -> str:
    url = entry.get("webpage_url") or entry.get("url") or ""
    if url.startswith("http"):
        return url
    vid = entry.get("id") or url
    return f"https://www.youtube.com/watch?v={vid}" if _ID_RE.match(vid or "") else url


def _to_track(entry: dict) -> Track | None:
    url = _entry_url(entry)
    if not url:
        return None
    title = entry.get("title") or url
    if title in ("[Private video]", "[Deleted video]"):
        return None
    dur = entry.get("duration")
    return Track(str(title), url, "youtube", float(dur) if dur else None)


def _extract(target: str, **extra) -> dict:
    ydl_cls = _lib()
    if ydl_cls is None:
        raise RuntimeError(f"yt-dlp non disponibile: {_error}")
    with ydl_cls(_options(**extra)) as ydl:
        return ydl.extract_info(target, download=False)


def resolve(url: str) -> list[Track]:
    """Un link a un video restituisce un brano; un link a una playlist tutti i suoi brani."""
    info = _extract(url, extract_flat="in_playlist")
    if info.get("_type") in ("playlist", "multi_video") or "entries" in info:
        return [t for t in (_to_track(e) for e in (info.get("entries") or []) if e) if t]
    t = _to_track(info)
    return [t] if t else []


def search(query: str, count: int = 15) -> list[Track]:
    info = _extract(f"ytsearch{count}:{query}", extract_flat="in_playlist")
    return [t for t in (_to_track(e) for e in (info.get("entries") or []) if e) if t]


# Download e cache -------------------------------------------------------------------------
# YouTube rifiuta (403) le richieste dirette di ffmpeg ai suoi server: l'audio lo scarica yt-dlp,
# che sa come farlo, in una cache locale; poi ffmpeg lo legge dal file.
CACHE_LIMIT = 1536 * 1024 * 1024          # 1,5 GB, poi si cancellano i file usati meno di recente
_TEMP_SUFFIXES = (".part", ".ytdl", ".temp", ".tmp")
_lock = threading.Lock()
_inflight: dict[str, Future] = {}
_progress: dict[str, list[Callable[[float], None]]] = {}
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="youtube-dl")


def cache_dir() -> Path:
    return config_dir() / "cache" / "youtube"


def video_id(url: str) -> str:
    u = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(u.query)
    if q.get("v"):
        return q["v"][0]
    parts = [p for p in u.path.split("/") if p]
    if (u.hostname or "").endswith("youtu.be") and parts:
        return parts[0]
    if len(parts) >= 2 and parts[0] in ("shorts", "live", "embed"):
        return parts[1]
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def cached_file(url: str) -> Path | None:
    vid = video_id(url)
    folder = cache_dir()
    if not folder.is_dir():
        return None
    for p in folder.glob(f"{glob.escape(vid)}.*"):
        if p.suffix.lower() not in _TEMP_SUFFIXES and p.stat().st_size > 0:
            return p
    return None


def _notify(vid: str, fraction: float) -> None:
    for cb in list(_progress.get(vid, [])):
        try:
            cb(fraction)
        except Exception:
            pass


def _do_download(track: Track, vid: str) -> Path:
    folder = cache_dir()
    folder.mkdir(parents=True, exist_ok=True)

    def hook(d: dict) -> None:
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                _notify(vid, min(1.0, d.get("downloaded_bytes", 0) / total))

    ydl_cls = _lib()
    if ydl_cls is None:
        raise RuntimeError(f"yt-dlp non disponibile: {_error}")
    opts = _options(
        skip_download=False,
        format="bestaudio/best",
        noplaylist=True,
        outtmpl=str(folder / f"{vid}.%(ext)s"),
        progress_hooks=[hook],
        fixup="never",              # nessuna post-elaborazione: il file lo legge ffmpeg così com'è
        retries=5,
        fragment_retries=5,
        http_chunk_size=10 * 1024 * 1024,
        overwrites=False,
        continuedl=True,
    )
    with ydl_cls(opts) as ydl:
        info = ydl.extract_info(track.source, download=True)
        if info.get("_type") == "playlist":
            entries = [e for e in info.get("entries") or [] if e]
            if not entries:
                raise RuntimeError("Video non disponibile")
            info = entries[0]
        path = None
        for d in info.get("requested_downloads") or []:
            if d.get("filepath"):
                path = Path(d["filepath"])
        if path is None:
            path = Path(ydl.prepare_filename(info))
    if not path.exists():
        found = cached_file(track.source)
        if found is None:
            raise RuntimeError("Download non riuscito")
        path = found
    if info.get("duration") and not track.duration:
        track.duration = float(info["duration"])
    _trim_cache(keep=path)
    return path


def _get_future(track: Track) -> tuple[str, Future]:
    vid = video_id(track.source)
    with _lock:
        fut = _inflight.get(vid)
        if fut is None or fut.done():
            fut = _pool.submit(_do_download, track, vid)
            _inflight[vid] = fut
            fut.add_done_callback(lambda f, v=vid: _inflight.pop(v, None) if _inflight.get(v) is f else None)
    return vid, fut


def download(track: Track, progress: Callable[[float], None] | None = None) -> Path:
    """Restituisce il file audio del video (dalla cache o scaricandolo ora)."""
    hit = cached_file(track.source)
    if hit is not None:
        os.utime(hit, None)          # usato di recente: non va cancellato per primo
        return hit
    vid, fut = _get_future(track)
    if progress is not None:
        _progress.setdefault(vid, []).append(progress)
    try:
        return fut.result()
    finally:
        if progress is not None and progress in _progress.get(vid, []):
            _progress[vid].remove(progress)


def prefetch(track: Track) -> None:
    """Scarica in anticipo (es. il brano successivo della coda) senza aspettare."""
    if track.kind == "youtube" and cached_file(track.source) is None:
        _get_future(track)


def resolver(track: Track, progress: Callable[[float], None] | None = None) -> tuple[str, dict]:
    """Per il player: il «sorgente» da dare a ffmpeg è il file in cache."""
    return str(download(track, progress)), {}


def _trim_cache(keep: Path | None = None) -> None:
    folder = cache_dir()
    try:
        files = [p for p in folder.iterdir() if p.is_file()]
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
