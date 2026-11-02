"""Programmi inclusi nel pacchetto: ffmpeg (decodifica audio) e Deno (richiesto da yt-dlp per YouTube)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


def _bundle_dir() -> Path | None:
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg")


@lru_cache(maxsize=1)
def deno_exe() -> str | None:
    bundle = _bundle_dir()
    if bundle is not None:
        for name in ("deno.exe", "deno"):
            p = bundle / "deno_bin" / name
            if p.exists():
                return str(p)
    try:
        import deno

        p = deno.find_deno_bin()
        if p and os.path.exists(p):
            return str(p)
    except Exception:
        pass
    return shutil.which("deno")


def no_window_kwargs() -> dict:
    """Su Windows evita che i sottoprocessi aprano una finestra di console."""
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}
