"""Mappa MIDI dei controlli: volumi e mute del mixer, player, pad, pagine e bot.

Ogni destinazione ha un id stabile (salvato nelle impostazioni) e un tipo:
``continuous`` per i controlli che seguono il valore del CC (fader, potenziometri) e
``button`` per le azioni che scattano alla pressione (note o CC con valore > 0).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .audio.mixer import MAX_DB, MIN_DB
from .midi import MidiEvent, matches

STRIPS = [("mic", "Microfono"), ("sounds", "Soundboard"), ("tts", "Sintesi vocale"), ("player", "Player"),
          ("master", "Master → Discord"), ("monitor", "Monitor (cuffie)")]
PAD_SLOTS = 16


@dataclass(frozen=True)
class Target:
    id: str
    group: str
    label: str
    kind: str     # "continuous" | "button"


def _build_targets() -> list[Target]:
    t: list[Target] = []
    for sid, name in STRIPS:
        t.append(Target(f"strip:{sid}:gain", "Mixer", f"Volume {name}", "continuous"))
    for sid, name in STRIPS:
        t.append(Target(f"strip:{sid}:mute", "Mixer", f"Mute {name}", "button"))
    t += [
        Target("player:toggle", "Player", "Play / Pausa", "button"),
        Target("player:stop", "Player", "Stop", "button"),
        Target("player:next", "Player", "Brano successivo", "button"),
        Target("player:prev", "Player", "Brano precedente", "button"),
        Target("sounds:stop", "Soundboard", "Stop tutti i suoni", "button"),
        Target("pads:page_prev", "Soundboard", "Pagina precedente", "button"),
        Target("pads:page_next", "Soundboard", "Pagina successiva", "button"),
    ]
    for i in range(1, PAD_SLOTS + 1):
        t.append(Target(f"pads:slot:{i}", "Pad della pagina corrente", f"Pad {i}", "button"))
    t += [
        Target("bot:toggle", "Bot Discord", "Avvia / ferma il bot", "button"),
        Target("bot:join", "Bot Discord", "Entra nel mio canale", "button"),
        Target("bot:leave", "Bot Discord", "Esci dal canale", "button"),
        Target("bot:follow", "Bot Discord", "Segui me (attiva/disattiva)", "button"),
    ]
    return t


TARGETS: list[Target] = _build_targets()
TARGETS_BY_ID = {t.id: t for t in TARGETS}


def _note(n: int) -> dict:
    return {"type": "note", "channel": None, "number": n}


def _cc(n: int) -> dict:
    return {"type": "cc", "channel": None, "number": n}


# Nektar Impact LX25+, preset 1 «GM Instrument» (impostazione di fabbrica), canale MIDI globale.
# Fonte: manuale utente (fader CC 7; pot P1–P8 = CC 74, 71, 5, 84, 78, 76, 77, 10; pad = note 36–43).
# I tasti di trasporto non hanno CC documentati: si assegnano con «Impara».
PRESETS: dict[str, dict[str, dict]] = {
    "Nektar Impact LX25+ (preset 1, fabbrica)": {
        "strip:master:gain": _cc(7),       # fader
        "strip:mic:gain": _cc(74),         # pot 1
        "strip:sounds:gain": _cc(71),      # pot 2
        "strip:player:gain": _cc(5),       # pot 3
        "strip:monitor:gain": _cc(84),     # pot 4
        **{f"pads:slot:{i + 1}": _note(36 + i) for i in range(8)},   # pad 1–8
    },
}


def cc_to_db(value: int) -> float:
    """CC 0–127 → dB: 0 = silenzio, 100 = 0 dB, 127 ≈ +4 dB (curva simile a un fader)."""
    if value <= 0:
        return MIN_DB
    gain = (value / 100.0) ** 2
    return max(MIN_DB, min(MAX_DB, 20.0 * math.log10(gain)))


def targets_for(mapping: dict[str, dict], event: MidiEvent) -> list[Target]:
    found = []
    for tid, binding in mapping.items():
        t = TARGETS_BY_ID.get(tid)
        if t is not None and matches(binding, event):
            found.append(t)
    return found


def assign(mapping: dict[str, dict], target_id: str, binding: dict | None) -> None:
    """Assegna un controllo a una destinazione, togliendolo dalle altre che lo usavano."""
    if binding:
        probe = MidiEvent(binding["type"], binding.get("channel") or 1, binding["number"], 1)
        for tid in [k for k, b in mapping.items() if k != target_id and matches(b, probe)
                    and (b.get("channel") or probe.channel) == probe.channel]:
            del mapping[tid]
        mapping[target_id] = dict(binding)
    else:
        mapping.pop(target_id, None)
