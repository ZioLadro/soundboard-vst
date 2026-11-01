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


class SoundCache:
    """Cache dei suoni decodificati, invalidata se il file cambia."""

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate
        self._cache: dict[Path, tuple[float, np.ndarray]] = {}
        self._lock = threading.Lock()

    def set_sample_rate(self, sample_rate: int) -> None:
        if sample_rate != self.sample_rate:
            with self._lock:
                self.sample_rate = sample_rate
                self._cache.clear()

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

    def forget(self, path: Path) -> None:
        with self._lock:
            self._cache.pop(path, None)
