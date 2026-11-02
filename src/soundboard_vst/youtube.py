"""YouTube tramite yt-dlp: video, playlist e ricerca, riprodotti solo come audio.

yt-dlp richiede un motore JavaScript per YouTube: usiamo Deno incluso nel pacchetto
(vedi ``binaries.deno_exe``) e il componente ``yt-dlp-ejs``.
"""

from __future__ import annotations

import re
import urllib.parse

from . import binaries
from .audio.player import Track

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


def stream(track: Track) -> tuple[str, dict]:
    """URL diretto dell'audio (scade dopo qualche ora: va chiesto al momento di riprodurre)."""
    info = _extract(track.source, format="bestaudio/best", noplaylist=True)
    if info.get("_type") == "playlist":
        entries = [e for e in info.get("entries") or [] if e]
        if not entries:
            raise RuntimeError("Video non disponibile")
        info = entries[0]
    url = info.get("url")
    if not url:
        formats = [f for f in info.get("formats") or [] if f.get("url")]
        if not formats:
            raise RuntimeError("Nessun flusso audio disponibile")
        url = formats[-1]["url"]
        headers = formats[-1].get("http_headers") or {}
    else:
        headers = info.get("http_headers") or {}
    if info.get("duration") and not track.duration:
        track.duration = float(info["duration"])
    return url, dict(headers)
