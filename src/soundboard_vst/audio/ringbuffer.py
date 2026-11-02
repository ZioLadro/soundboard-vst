"""Ring buffer stereo per passare audio tra stream con clock diversi."""

from __future__ import annotations

import threading

import numpy as np


class RingBuffer:
    """Buffer circolare (canali, campioni) thread-safe.

    Se lo scrittore va più veloce del lettore, i campioni più vecchi vengono
    scartati per tenere la latenza sotto ``max_latency`` campioni.
    """

    def __init__(self, channels: int = 2, capacity: int = 48000, max_latency: int | None = None):
        self.channels = channels
        self.capacity = capacity
        self.max_latency = max_latency or capacity
        self._buf = np.zeros((channels, capacity), dtype=np.float32)
        self._read = 0
        self._count = 0
        self._lock = threading.Lock()
        self.underruns = 0
        self.overruns = 0

    def __len__(self) -> int:
        return self._count

    def reconfigure(self, capacity: int, max_latency: int | None = None) -> None:
        """Cambia dimensioni restando lo stesso oggetto (chi lo usa continua a vederlo)."""
        with self._lock:
            if capacity != self.capacity:
                self._buf = np.zeros((self.channels, capacity), dtype=np.float32)
                self.capacity = capacity
            self.max_latency = max_latency or capacity
            self._read = 0
            self._count = 0

    def clear(self) -> None:
        with self._lock:
            self._read = 0
            self._count = 0

    def write(self, data: np.ndarray) -> None:
        n = data.shape[1]
        if n == 0:
            return
        with self._lock:
            if n >= self.capacity:
                data = data[:, -self.capacity:]
                n = self.capacity
            write_pos = (self._read + self._count) % self.capacity
            first = min(n, self.capacity - write_pos)
            self._buf[:, write_pos:write_pos + first] = data[:, :first]
            if first < n:
                self._buf[:, : n - first] = data[:, first:]
            self._count += n
            limit = min(self.capacity, self.max_latency)
            if self._count > limit:
                drop = self._count - limit
                self._read = (self._read + drop) % self.capacity
                self._count = limit
                self.overruns += 1

    def read(self, n: int) -> np.ndarray:
        """Legge ``n`` campioni; se non bastano completa con silenzio."""
        out = np.zeros((self.channels, n), dtype=np.float32)
        with self._lock:
            avail = min(n, self._count)
            if avail < n:
                self.underruns += 1
            first = min(avail, self.capacity - self._read)
            out[:, :first] = self._buf[:, self._read:self._read + first]
            if first < avail:
                out[:, first:avail] = self._buf[:, : avail - first]
            self._read = (self._read + avail) % self.capacity
            self._count -= avail
        return out


class DriftReader:
    """Legge da un ``RingBuffer`` riempito da un altro clock, senza scatti né buchi.

    Due schede audio (o una scheda e il timer di Discord) non vanno mai esattamente alla stessa
    velocità: un buffer semplice prima o poi si riempie (e scarta un pezzo: «clic») o si svuota
    (buco di silenzio). Qui il buffer viene tenuto intorno a ``target`` campioni ricampionando di
    pochissimo (al massimo ±0,2%, cioè circa 3 centesimi di semitono: inudibile): se si sta
    riempiendo si legge un po' più in fretta, se si sta svuotando un po' più piano.

    ``ratio`` è il rapporto fisso tra frequenza di chi scrive e di chi legge (es. 44100/48000);
    il ricampionamento è lineare e continuo tra una lettura e l'altra.
    Con ``ratio`` 1 e buffer già al livello giusto i campioni passano invariati.
    """

    MAX_ADJUST = 0.002

    def __init__(self, ring: RingBuffer, target: int, ratio: float = 1.0,
                 max_adjust: float = MAX_ADJUST, smoothing: float = 0.02):
        self.ring = ring
        self.target = max(1, int(target))
        self.ratio = float(ratio)
        self.max_adjust = max_adjust
        self.smoothing = smoothing
        self.adjust = 0.0               # correzione attuale (per diagnostica)
        self.reset()

    def reset(self) -> None:
        """Da chiamare quando il flusso riparte da capo (es. dopo aver svuotato il buffer)."""
        self._buf: np.ndarray | None = None      # [:, 0] = ultimo campione usato; None = non ancora partito
        self._frac = 0.0
        self._fill: float | None = None
        self.adjust = 0.0

    def read(self, n: int) -> np.ndarray:
        if self._buf is None:
            if len(self.ring) == 0:
                return np.zeros((self.ring.channels, n), dtype=np.float32)
            self._buf = self.ring.read(1)          # parte dal primo campione vero, senza ritardo
        fill = len(self.ring) + self._buf.shape[1] - 1
        if self._fill is None:
            self._fill = float(fill)
        else:
            self._fill += self.smoothing * (fill - self._fill)
        err = (self._fill - self.target) / self.target
        self.adjust = float(np.clip(err * self.max_adjust, -self.max_adjust, self.max_adjust))
        step = self.ratio * (1.0 + self.adjust)

        end = self._frac + n * step                    # posizione dopo l'ultimo campione in uscita
        consumed = int(end)
        need = max(int(self._frac + (n - 1) * step) + 2, consumed + 1)
        buf = self._buf
        if need > buf.shape[1]:
            buf = np.concatenate([buf, self.ring.read(need - buf.shape[1])], axis=1)
        t = self._frac + np.arange(n) * step
        i0 = t.astype(np.int64)
        w = (t - i0).astype(np.float32)
        out = buf[:, i0] * (1.0 - w) + buf[:, i0 + 1] * w
        self._buf = buf[:, consumed:]
        self._frac = end - consumed
        return out.astype(np.float32, copy=False)
