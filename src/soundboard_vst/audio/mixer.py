"""Canali del mixer: catena di inserti, fader, mute e meter."""

from __future__ import annotations

import sys
from typing import Any

import numpy as np

from .plugins import InsertSlot

MIN_DB = -60.0
MAX_DB = 12.0


def db_to_gain(db: float) -> float:
    return 0.0 if db <= MIN_DB else float(10.0 ** (db / 20.0))


class ChannelStrip:
    """Un canale stereo: inserti → fader → mute → meter.

    Gli inserti sono una tupla sostituita per intero quando cambia
    (copy-on-write), così il thread audio legge sempre una lista coerente.
    """

    def __init__(self, strip_id: str, name: str, gain_db: float = 0.0):
        self.id = strip_id
        self.name = name
        self.gain_db = gain_db
        self.mute = False
        self.inserts: tuple[InsertSlot, ...] = ()
        self.peak = np.zeros(2, dtype=np.float32)   # letto dalla GUI
        self._current_gain = db_to_gain(gain_db)

    # Inserti ---------------------------------------------------------------
    def add_insert(self, slot: InsertSlot, index: int | None = None) -> None:
        items = list(self.inserts)
        items.insert(len(items) if index is None else index, slot)
        self.inserts = tuple(items)

    def remove_insert(self, slot: InsertSlot) -> None:
        self.inserts = tuple(s for s in self.inserts if s is not slot)

    def move_insert(self, slot: InsertSlot, delta: int) -> None:
        items = list(self.inserts)
        i = items.index(slot)
        j = max(0, min(len(items) - 1, i + delta))
        items.insert(j, items.pop(i))
        self.inserts = tuple(items)

    # Audio -------------------------------------------------------------------
    def process(self, block: np.ndarray, sample_rate: int) -> np.ndarray:
        for slot in self.inserts:
            block = slot.process(block, sample_rate)
        target = 0.0 if self.mute else db_to_gain(self.gain_db)
        if target != self._current_gain:
            ramp = np.linspace(self._current_gain, target, block.shape[1], dtype=np.float32)
            block = block * ramp
            self._current_gain = target
        elif target != 1.0:
            block = block * np.float32(target)
        if block.shape[1]:
            np.maximum(self.peak, np.abs(block).max(axis=1), out=self.peak)
        return block

    def take_peak(self) -> tuple[float, float]:
        """Restituisce il picco dall'ultima lettura e lo azzera (per la GUI)."""
        left, right = float(self.peak[0]), float(self.peak[1])
        self.peak[:] = 0.0
        return left, right

    # Salvataggio -------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "gain_db": self.gain_db,
            "mute": self.mute,
            "inserts": [s.to_dict() for s in self.inserts],
        }

    def load_dict(self, d: dict[str, Any]) -> list[str]:
        """Ripristina lo stato; restituisce gli errori dei plugin non caricati."""
        errors: list[str] = []
        self.gain_db = float(d.get("gain_db", self.gain_db))
        self.mute = bool(d.get("mute", False))
        self._current_gain = 0.0 if self.mute else db_to_gain(self.gain_db)
        slots = []
        for sd in d.get("inserts", []):
            try:
                slots.append(InsertSlot.from_dict(sd))
            except Exception as exc:
                label = sd.get("path") or sd.get("type") or "?"
                errors.append(f"{self.name}: {label} — {exc}")
                print(f"[mixer] {errors[-1]}", file=sys.stderr)
        self.inserts = tuple(slots)
        return errors
