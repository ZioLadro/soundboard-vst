"""Libreria dei suoni: elenco file nella cartella e decodifica con cache."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac", ".aif", ".aiff"}


@dataclass(frozen=True)
class SoundFile:
    path: Path

    @property
    def name(self) -> str:
        """Nome usato come chiave (percorso relativo alla cartella, senza estensione)."""
        return self.path.stem

    @property
    def key(self) -> str:
        return self.path.name


def list_sounds(folder: Path) -> list[SoundFile]:
    if not folder.is_dir():
        return []
    files = [
        SoundFile(p)
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(files, key=lambda s: s.name.lower())


def decode(path: Path, sample_rate: int) -> np.ndarray:
    """Decodifica un file audio in float32 stereo (2, n) al sample rate indicato."""
    from pedalboard.io import AudioFile

    with AudioFile(str(path)) as f:
        if int(f.samplerate) != int(sample_rate):
            with f.resampled_to(sample_rate) as r:
                data = r.read(r.frames)
        else:
            data = f.read(f.frames)
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data[np.newaxis, :]
    if data.shape[0] == 1:
        data = np.repeat(data, 2, axis=0)
    elif data.shape[0] > 2:
        data = data[:2]
    return np.ascontiguousarray(data)


ANTICLICK_S = 0.003          # micro-dissolvenza quando il taglio cade in mezzo al suono (evita il «clic»)
SHAPE_KEYS = ("start", "end", "fade_in", "fade_out")


def shape_params(settings: dict) -> tuple[float, float, float, float]:
    """(inizio, fine, dissolvenza in entrata, in uscita) in secondi dalle impostazioni di un suono."""
    out = []
    for k in SHAPE_KEYS:
        try:
            out.append(max(0.0, round(float(settings.get(k) or 0.0), 4)))
        except (TypeError, ValueError):
            out.append(0.0)
    return tuple(out)


def shape(data: np.ndarray, sample_rate: int, start: float = 0.0, end: float = 0.0,
          fade_in: float = 0.0, fade_out: float = 0.0) -> np.ndarray:
    """Taglia il suono tra ``start`` e ``end`` (0 = fino alla fine) e applica le dissolvenze.

    Le dissolvenze seguono una curva a coseno rialzato (più naturale di una rampa lineare).
    Senza nulla da fare restituisce ``data`` così com'è (nessuna copia).
    """
    n = data.shape[1]
    a = min(n, max(0, round(start * sample_rate)))
    b = n if end <= 0 else min(n, max(a, round(end * sample_rate)))
    out = data[:, a:b]
    length = out.shape[1]
    fi = round(fade_in * sample_rate)
    fo = round(fade_out * sample_rate)
    if fi == 0 and a > 0:
        fi = round(ANTICLICK_S * sample_rate)
    if fo == 0 and b < n:
        fo = round(ANTICLICK_S * sample_rate)
    fi, fo = min(fi, length), min(fo, length)
    if length == 0 or (fi == 0 and fo == 0):
        return out
    out = out.copy()
    if fi:
        out[:, :fi] *= (np.sin(np.linspace(0.0, np.pi / 2, fi)) ** 2).astype(np.float32)
    if fo:
        out[:, length - fo:] *= (np.cos(np.linspace(0.0, np.pi / 2, fo)) ** 2).astype(np.float32)
    return out


class SoundCache:
    """Cache dei suoni decodificati, invalidata se il file cambia."""

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate
        self._cache: dict[Path, tuple[float, np.ndarray]] = {}
        self._shaped: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}   # (path, parametri) -> (originale, risultato)
        self._lock = threading.Lock()

    def set_sample_rate(self, sample_rate: int) -> None:
        if sample_rate != self.sample_rate:
            with self._lock:
                self.sample_rate = sample_rate
                self._cache.clear()
                self._shaped.clear()

    def get(self, path: Path) -> np.ndarray:
        mtime = path.stat().st_mtime
        with self._lock:
            hit = self._cache.get(path)
            if hit and hit[0] == mtime:
                return hit[1]
        data = decode(path, self.sample_rate)
        with self._lock:
            self._cache[path] = (mtime, data)
        return data

    def get_shaped(self, path: Path, params: tuple[float, float, float, float]) -> np.ndarray:
        """Come ``get``, ma tagliato e con le dissolvenze (calcolato una volta e ricordato)."""
        data = self.get(path)
        if not any(params):
            return data
        key = (path, tuple(params))
        with self._lock:
            hit = self._shaped.get(key)
            if hit is not None and hit[0] is data:        # stesso file decodificato: ancora valido
                return hit[1]
        out = shape(data, self.sample_rate, *params)
        with self._lock:
            if len(self._shaped) >= 128:
                self._shaped.pop(next(iter(self._shaped)))
            self._shaped[key] = (data, out)
        return out

    def forget(self, path: Path) -> None:
        with self._lock:
            self._cache.pop(path, None)
            for k in [k for k in self._shaped if k[0] == path]:
                del self._shaped[k]
