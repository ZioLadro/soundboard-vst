"""Inserti del mixer: effetti integrati di pedalboard e plugin VST3 esterni."""

from __future__ import annotations

import base64
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pedalboard

from .pitch import LowLatencyPitchShift


@dataclass(frozen=True)
class ParamSpec:
    attr: str
    label: str
    minimum: float
    maximum: float
    default: float
    unit: str = ""


# Effetti integrati (non serve installare nulla) --------------------------------
BUILTIN_EFFECTS: dict[str, tuple[str, list[ParamSpec]]] = {
    "Gain": ("Guadagno", [ParamSpec("gain_db", "Guadagno", -24, 24, 0, "dB")]),
    "NoiseGate": ("Noise gate", [
        ParamSpec("threshold_db", "Soglia", -80, 0, -45, "dB"),
        ParamSpec("ratio", "Rapporto", 1, 20, 10, ":1"),
        ParamSpec("attack_ms", "Attacco", 0.1, 100, 1, "ms"),
        ParamSpec("release_ms", "Rilascio", 5, 1000, 100, "ms"),
    ]),
    "Compressor": ("Compressore", [
        ParamSpec("threshold_db", "Soglia", -60, 0, -18, "dB"),
        ParamSpec("ratio", "Rapporto", 1, 20, 4, ":1"),
        ParamSpec("attack_ms", "Attacco", 0.1, 200, 5, "ms"),
        ParamSpec("release_ms", "Rilascio", 5, 2000, 100, "ms"),
    ]),
    "Limiter": ("Limiter", [
        ParamSpec("threshold_db", "Soglia", -30, 0, -1, "dB"),
        ParamSpec("release_ms", "Rilascio", 1, 1000, 100, "ms"),
    ]),
    "HighpassFilter": ("Filtro passa-alto", [
        ParamSpec("cutoff_frequency_hz", "Frequenza", 20, 2000, 80, "Hz"),
    ]),
    "LowpassFilter": ("Filtro passa-basso", [
        ParamSpec("cutoff_frequency_hz", "Frequenza", 500, 20000, 12000, "Hz"),
    ]),
    "PeakFilter": ("EQ a campana", [
        ParamSpec("cutoff_frequency_hz", "Frequenza", 40, 16000, 1000, "Hz"),
        ParamSpec("gain_db", "Guadagno", -18, 18, 0, "dB"),
        ParamSpec("q", "Q", 0.1, 10, 0.7),
    ]),
    "Reverb": ("Riverbero", [
        ParamSpec("room_size", "Stanza", 0, 1, 0.5),
        ParamSpec("damping", "Smorzamento", 0, 1, 0.5),
        ParamSpec("wet_level", "Effetto", 0, 1, 0.33),
        ParamSpec("dry_level", "Diretto", 0, 1, 0.4),
        ParamSpec("width", "Ampiezza", 0, 1, 1.0),
    ]),
    "Delay": ("Delay", [
        ParamSpec("delay_seconds", "Tempo", 0.01, 2, 0.25, "s"),
        ParamSpec("feedback", "Feedback", 0, 0.95, 0.3),
        ParamSpec("mix", "Mix", 0, 1, 0.3),
    ]),
    "Chorus": ("Chorus", [
        ParamSpec("rate_hz", "Velocità", 0.1, 10, 1, "Hz"),
        ParamSpec("depth", "Profondità", 0, 1, 0.25),
        ParamSpec("mix", "Mix", 0, 1, 0.5),
    ]),
    "Distortion": ("Distorsione", [ParamSpec("drive_db", "Drive", 0, 50, 20, "dB")]),
    "PitchShift": ("Pitch shifter", [
        ParamSpec("semitones", "Semitoni", -12, 12, 0, "st"),
        ParamSpec("mix", "Mix", 0, 1, 1.0),
        ParamSpec("window_ms", "Finestra", 15, 100, 40, "ms"),
    ]),
}

# Effetti scritti qui (non presi da pedalboard): il PitchShift di pedalboard ha ~1 s di latenza
CUSTOM_EFFECTS = {"PitchShift": LowLatencyPitchShift}


class InsertSlot:
    """Uno slot della catena di inserti di un canale."""

    def __init__(self, plugin: pedalboard.Plugin, kind: str, *, type_name: str = "",
                 path: str = "", plugin_name: str = "", bypass: bool = False):
        self.plugin = plugin
        self.kind = kind              # "builtin" | "vst3"
        self.type_name = type_name    # per i builtin, es. "Compressor"
        self.path = path              # per i VST3
        self.plugin_name = plugin_name
        self.bypass = bypass
        self.failed = False           # disattivato dopo un errore in elaborazione
        self._fifo: np.ndarray | None = None

    # Informazioni ------------------------------------------------------------
    @property
    def display_name(self) -> str:
        if self.kind == "builtin":
            return BUILTIN_EFFECTS.get(self.type_name, (self.type_name, []))[0]
        return self.plugin_name or getattr(self.plugin, "name", "") or Path(self.path).stem

    @property
    def has_editor(self) -> bool:
        return self.kind == "vst3" and hasattr(self.plugin, "show_editor")

    def param_specs(self) -> list[ParamSpec]:
        if self.kind == "builtin":
            return BUILTIN_EFFECTS.get(self.type_name, ("", []))[1]
        return []

    # Elaborazione ------------------------------------------------------------
    def process(self, block: np.ndarray, sample_rate: int) -> np.ndarray:
        if self.bypass or self.failed:
            return block
        try:
            out = self.plugin.process(block, sample_rate, buffer_size=block.shape[1], reset=False)
        except Exception as exc:  # un plugin rotto non deve fermare l'audio
            self.failed = True
            print(f"[insert] {self.display_name} disattivato: {exc}", file=sys.stderr)
            return block
        out = np.asarray(out, dtype=np.float32)
        if out.shape[0] != block.shape[0]:
            out = np.repeat(out[:1], block.shape[0], axis=0) if out.shape[0] == 1 else out[:block.shape[0]]
        n = block.shape[1]
        if out.shape[1] != n or self._fifo is not None:
            # plugin con latenza: restituisce meno campioni all'inizio; li riallineiamo con una coda
            if self._fifo is None:
                self._fifo = np.zeros((block.shape[0], 0), dtype=np.float32)
            self._fifo = np.concatenate([self._fifo, out], axis=1)
            if self._fifo.shape[1] >= n:
                out, self._fifo = self._fifo[:, :n], self._fifo[:, n:]
            else:
                out = np.zeros_like(block)   # riempimento iniziale (latenza del plugin)
        return out

    # Salvataggio ---------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "bypass": self.bypass}
        if self.kind == "builtin":
            d["type"] = self.type_name
            d["params"] = {s.attr: float(getattr(self.plugin, s.attr)) for s in self.param_specs()}
        else:
            d["path"] = self.path
            d["plugin_name"] = self.plugin_name
            state = _get_state(self.plugin)
            if state:
                d["state"] = base64.b64encode(state).decode("ascii")
            try:
                d["params"] = {n: float(p.raw_value) for n, p in self.plugin.parameters.items()}
            except Exception:
                pass
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "InsertSlot":
        if d.get("kind") == "builtin":
            slot = create_builtin(d["type"])
            for attr, value in (d.get("params") or {}).items():
                try:
                    setattr(slot.plugin, attr, value)
                except Exception:
                    pass
        else:
            slot = load_vst3(d["path"], d.get("plugin_name") or None)
            restored = False
            if d.get("state"):
                restored = _set_state(slot.plugin, base64.b64decode(d["state"]))
            if not restored:
                for name, raw in (d.get("params") or {}).items():
                    p = slot.plugin.parameters.get(name)
                    if p is not None:
                        try:
                            p.raw_value = raw
                        except Exception:
                            pass
        slot.bypass = bool(d.get("bypass", False))
        return slot


def _get_state(plugin) -> bytes | None:
    for attr in ("raw_state", "preset_data"):
        try:
            value = getattr(plugin, attr)
            if value:
                return bytes(value)
        except Exception:
            continue
    return None


def _set_state(plugin, data: bytes) -> bool:
    for attr in ("raw_state", "preset_data"):
        try:
            setattr(plugin, attr, data)
            return True
        except Exception:
            continue
    return False


def create_builtin(type_name: str) -> InsertSlot:
    if type_name not in BUILTIN_EFFECTS:
        raise ValueError(f"Effetto sconosciuto: {type_name}")
    factory = CUSTOM_EFFECTS.get(type_name) or getattr(pedalboard, type_name)
    plugin = factory()
    for spec in BUILTIN_EFFECTS[type_name][1]:
        setattr(plugin, spec.attr, spec.default)
    return InsertSlot(plugin, "builtin", type_name=type_name)


def vst3_names_in_file(path: str) -> list[str]:
    """Un file .vst3 può contenere più plugin (shell)."""
    try:
        return list(pedalboard.VST3Plugin.get_plugin_names_for_file(path))
    except Exception:
        return []


def load_vst3(path: str, plugin_name: str | None = None) -> InsertSlot:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Plugin non trovato: {path}")
    plugin = pedalboard.load_plugin(path, plugin_name=plugin_name) if plugin_name \
        else pedalboard.load_plugin(path)
    if getattr(plugin, "is_instrument", False) and not getattr(plugin, "is_effect", True):
        raise ValueError("È uno strumento virtuale, non un effetto: non si può usare come inserto.")
    return InsertSlot(plugin, "vst3", path=path, plugin_name=plugin_name or getattr(plugin, "name", ""))


def scan_vst3(dirs: list[str]) -> list[Path]:
    """Trova i plugin .vst3 (file o bundle) senza caricarli."""
    found: list[Path] = []
    seen: set[str] = set()
    for d in dirs:
        root = Path(d)
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # i bundle .vst3 sono cartelle: li prendiamo senza entrarci
            for dn in list(dirnames):
                if dn.lower().endswith(".vst3"):
                    p = Path(dirpath) / dn
                    if str(p).lower() not in seen:
                        seen.add(str(p).lower())
                        found.append(p)
                    dirnames.remove(dn)
            for fn in filenames:
                if fn.lower().endswith(".vst3"):
                    p = Path(dirpath) / fn
                    if str(p).lower() not in seen:
                        seen.add(str(p).lower())
                        found.append(p)
    return sorted(found, key=lambda p: p.stem.lower())
