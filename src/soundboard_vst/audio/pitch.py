"""Pitch shifter a bassa latenza (linea di ritardo con due testine e dissolvenza incrociata).

Ogni testina legge la linea di ritardo a velocità ``r = 2^(semitoni/12)``; quando arriva al bordo
della finestra riparte, e l'altra testina (sfasata di mezza finestra) copre il salto con una
dissolvenza sin²/cos². Latenza media: mezza finestra (≈ 20 ms con la finestra predefinita).
"""

from __future__ import annotations

import numpy as np


class LowLatencyPitchShift:
    """Stessa interfaccia minima di un plugin pedalboard (``process``, ``reset``)."""

    is_effect = True
    is_instrument = False

    def __init__(self, semitones: float = 0.0, window_ms: float = 40.0, mix: float = 1.0):
        self.semitones = semitones
        self.window_ms = window_ms
        self.mix = mix
        self._buf: np.ndarray | None = None
        self._wp = 0
        self._phase = 0.0
        self._sr = 0

    def reset(self) -> None:
        self._buf = None
        self._wp = 0
        self._phase = 0.0

    def _ensure(self, channels: int, sr: int, n: int, window: int) -> None:
        size = 1
        while size < window + n + 8:
            size <<= 1
        if self._buf is None or self._buf.shape[0] != channels or self._buf.shape[1] < size or self._sr != sr:
            self._buf = np.zeros((channels, size), dtype=np.float32)
            self._wp = 0
            self._phase = 0.0
            self._sr = sr

    def process(self, block: np.ndarray, sample_rate: float, buffer_size: int | None = None,
                reset: bool = False) -> np.ndarray:
        if reset:
            self.reset()
        block = np.asarray(block, dtype=np.float32)
        ch, n = block.shape
        sr = int(sample_rate)
        window = max(64, int(sr * self.window_ms / 1000.0))
        self._ensure(ch, sr, n, window)
        buf = self._buf
        size = buf.shape[1]
        mask = size - 1

        # scrive l'ingresso nella linea di ritardo
        idx_w = (self._wp + np.arange(n)) & mask
        buf[:, idx_w] = block

        ratio = 2.0 ** (float(self.semitones) / 12.0)
        if abs(ratio - 1.0) < 1e-6 or n == 0:
            self._wp = (self._wp + n) & mask
            return block

        # ritardo delle due testine: cresce di (1 - r) a ogni campione, avvolto nella finestra
        steps = np.arange(n, dtype=np.float64)
        d1 = np.mod(self._phase + (1.0 - ratio) * steps, window)
        d2 = np.mod(d1 + window / 2.0, window)
        self._phase = float(np.mod(self._phase + (1.0 - ratio) * n, window))

        out = np.zeros_like(block)
        base = (self._wp + steps)
        for d in (d1, d2):
            pos = base - d - 1.0
            i0 = np.floor(pos).astype(np.int64)
            frac = (pos - i0).astype(np.float32)
            a = buf[:, i0 & mask]
            b = buf[:, (i0 + 1) & mask]
            weight = np.sin(np.pi * d / window).astype(np.float32) ** 2
            out += (a + (b - a) * frac) * weight

        self._wp = (self._wp + n) & mask
        mix = float(np.clip(self.mix, 0.0, 1.0))
        if mix < 1.0:
            out = out * mix + block * (1.0 - mix)
        return out
