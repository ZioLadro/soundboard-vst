"""Canali del mixer: catena di inserti, fader, pan, mute/solo e meter."""

from __future__ import annotations

import sys
from typing import Any

import numpy as np

from .plugins import InsertSlot

MIN_DB = -60.0
MAX_DB = 12.0


def db_to_gain(db: float) -> float:
    return 0.0 if db <= MIN_DB else float(10.0 ** (db / 20.0))


def pan_gains(pan: float) -> tuple[float, float]:
    """Bilanciamento (-1 = tutto a sinistra, 0 = centro, +1 = tutto a destra).

    Al centro i due lati restano a volume pieno; spostandosi si abbassa solo il lato opposto.
    """
    pan = max(-1.0, min(1.0, float(pan)))
    return min(1.0, 1.0 - pan), min(1.0, 1.0 + pan)


def format_pan(pan: float) -> str:
    """«C», «S 30», «D 100» (sinistra / destra in percentuale)."""
    v = int(round(max(-1.0, min(1.0, pan)) * 100))
    return "C" if v == 0 else f"S {-v}" if v < 0 else f"D {v}"


class ChannelStrip:
    """Un canale stereo: inserti → fader → pan → mute/solo → meter.

    Gli inserti sono una tupla sostituita per intero quando cambia
    (copy-on-write), così il thread audio legge sempre una lista coerente.
    """

    def __init__(self, strip_id: str, name: str, gain_db: float = 0.0):
        self.id = strip_id
        self.name = name
        self.gain_db = gain_db
        self.mute = False
        self.solo = False                 # con un canale in solo, gli altri ingressi tacciono
        self.pan = 0.0                    # -1 sinistra … +1 destra
        self.inserts: tuple[InsertSlot, ...] = ()
        self.peak = np.zeros(2, dtype=np.float32)   # letto dalla GUI
        self._current = np.full((2, 1), db_to_gain(gain_db), dtype=np.float32)

    @property
    def _current_gain(self) -> float:
        """Guadagno attuale (il più alto dei due lati), per compatibilità."""
        return float(self._current.max())

    @_current_gain.setter
    def _current_gain(self, value: float) -> None:
        self._current = np.full((2, 1), float(value), dtype=np.float32) * \
            np.array(pan_gains(self.pan), dtype=np.float32).reshape(2, 1)

    def target_gains(self, silenced: bool = False) -> np.ndarray:
        """Guadagno di sinistra e destra (2, 1) con fader, pan, mute e solo."""
        g = 0.0 if (self.mute or silenced) else db_to_gain(self.gain_db)
        left, right = pan_gains(self.pan)
        return np.array([[g * left], [g * right]], dtype=np.float32)

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
    def process(self, block: np.ndarray, sample_rate: int, silenced: bool = False) -> np.ndarray:
        """``silenced``: un altro canale è in solo (il canale tace come se fosse muto)."""
        for slot in self.inserts:
            block = slot.process(block, sample_rate)
        target = self.target_gains(silenced)
        n = block.shape[1]
        if not np.array_equal(target, self._current):
            if n:
                t = np.linspace(0.0, 1.0, n, dtype=np.float32)
                block = block * (self._current + (target - self._current) * t)
            self._current = target
        elif not (target == 1.0).all():
            block = block * target
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
            "solo": self.solo,
            "pan": self.pan,
            "inserts": [s.to_dict() for s in self.inserts],
        }

    def load_dict(self, d: dict[str, Any]) -> list[str]:
        """Ripristina lo stato; restituisce gli errori dei plugin non caricati."""
        errors: list[str] = []
        self.gain_db = float(d.get("gain_db", self.gain_db))
        self.mute = bool(d.get("mute", False))
        self.solo = bool(d.get("solo", False))
        try:
            self.pan = max(-1.0, min(1.0, float(d.get("pan", 0.0))))
        except (TypeError, ValueError):
            self.pan = 0.0
        self._current = self.target_gains()
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


class InputStrip(ChannelStrip):
    """Canale d'ingresso (microfono, strumento, linea…): sceglie dispositivo e canali.

    ``channel`` è il primo canale del dispositivo (0 = canale 1); ``mono`` usa solo quello
    (duplicato a sinistra e a destra, da spostare con il pan), altrimenti ``channel`` e
    ``channel + 1``. Il nome si può cambiare.
    """

    kind = "input"

    def __init__(self, strip_id: str, name: str, gain_db: float = 0.0, device: str = "",
                 channel: int = 0, mono: bool = False):
        super().__init__(strip_id, name, gain_db)
        self.device = device
        self.channel = max(0, int(channel))
        self.mono = bool(mono)
        self.to_bot = False          # anche al bot Discord
        self.hear = False            # anche in cuffia (monitor)

    @property
    def channel_label(self) -> str:
        c = self.channel + 1
        return f"{c}" if self.mono else f"{c}-{c + 1}"

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(id=self.id, name=self.name, device=self.device, channel=self.channel, mono=self.mono,
                 to_bot=self.to_bot, hear=self.hear)
        return d

    def load_dict(self, d: dict[str, Any]) -> list[str]:
        errors = super().load_dict(d)
        name = d.get("name")
        if isinstance(name, str) and name.strip():
            self.name = name.strip()[:40]
        if isinstance(d.get("device"), str):
            self.device = d["device"]
        try:
            self.channel = max(0, min(255, int(d.get("channel", self.channel))))
        except (TypeError, ValueError):
            self.channel = 0
        self.mono = bool(d.get("mono", self.mono))
        self.to_bot = bool(d.get("to_bot", self.to_bot))
        self.hear = bool(d.get("hear", self.hear))
        return errors
