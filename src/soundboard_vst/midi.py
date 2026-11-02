"""Ingresso MIDI: note e controlli (CC) per far suonare i pad.

Usa ``python-rtmidi`` se installato; altrimenti il MIDI risulta non disponibile
e il resto del programma funziona normalmente.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

_rtmidi = None
_error: str | None = None


def _lib():
    global _rtmidi, _error
    if _rtmidi is None and _error is None:
        try:
            import rtmidi

            _rtmidi = rtmidi
        except Exception as exc:
            _error = str(exc) or exc.__class__.__name__
    return _rtmidi


def available() -> bool:
    return _lib() is not None


def unavailable_reason() -> str:
    _lib()
    return _error or ""


def note_name(number: int) -> str:
    """60 → C4 (convenzione MIDI standard, Do centrale = C4)."""
    return f"{NOTE_NAMES[number % 12]}{number // 12 - 1}"


@dataclass(frozen=True)
class MidiEvent:
    kind: str        # "note" | "cc"
    channel: int     # 1-16
    number: int      # nota o numero del controllo
    value: int       # velocity o valore del controllo

    @property
    def pressed(self) -> bool:
        return self.value > 0

    def binding(self) -> dict:
        return {"type": self.kind, "channel": self.channel, "number": self.number}


def parse(message: list[int]) -> MidiEvent | None:
    """Interpreta un messaggio MIDI grezzo: note on (velocity > 0) e tutti i CC (anche valore 0,
    che serve ai fader; per le azioni a pulsante si usa solo il valore > 0)."""
    if len(message) < 3:
        return None
    status, d1, d2 = message[0], message[1], message[2]
    kind, channel = status & 0xF0, (status & 0x0F) + 1
    if kind == 0x90 and d2 > 0:
        return MidiEvent("note", channel, d1, d2)
    if kind == 0xB0:
        return MidiEvent("cc", channel, d1, d2)
    return None


def matches(binding: dict | None, event: MidiEvent) -> bool:
    if not binding:
        return False
    return (binding.get("type") == event.kind and binding.get("number") == event.number
            and binding.get("channel") in (None, 0, event.channel))


def binding_label(binding: dict | None) -> str:
    if not binding:
        return ""
    n = int(binding.get("number", 0))
    ch = binding.get("channel")
    base = f"{note_name(n)}" if binding.get("type") == "note" else f"CC {n}"
    return f"{base} · ch {ch}" if ch else base


class MidiInput:
    """Una porta di ingresso MIDI aperta; ``callback(MidiEvent)`` gira nel thread di rtmidi."""

    def __init__(self):
        self._port = None
        self.name = ""

    @staticmethod
    def ports() -> list[str]:
        lib = _lib()
        if lib is None:
            return []
        m = lib.MidiIn()
        try:
            return list(m.get_ports())
        finally:
            m.delete()

    def open(self, name: str, callback: Callable[[MidiEvent], None]) -> bool:
        self.close()
        lib = _lib()
        if lib is None or not name:
            return False
        ports = self.ports()
        if name not in ports:
            # i nomi su Windows hanno spesso un numero finale che cambia ("Pad 1", "Pad 2")
            base = name.rstrip("0123456789 ")
            match = next((p for p in ports if p.rstrip("0123456789 ") == base), None)
            if match is None:
                return False
            name = match
        port = lib.MidiIn()
        port.ignore_types(sysex=True, timing=True, active_sense=True)

        def on_message(event, data=None):
            ev = parse(event[0])
            if ev is not None:
                callback(ev)

        port.set_callback(on_message)
        port.open_port(ports.index(name))
        self._port, self.name = port, name
        return True

    def close(self) -> None:
        if self._port is not None:
            try:
                self._port.cancel_callback()
                self._port.close_port()
                self._port.delete()
            except Exception:
                pass
        self._port, self.name = None, ""

    @property
    def is_open(self) -> bool:
        return self._port is not None
