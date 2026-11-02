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
