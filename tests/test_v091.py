"""v0.9.1: la rotella del pitch bend si può assegnare a parametri e volumi."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from soundboard_vst import midi, midi_map
from tests.test_v090 import win  # noqa: F401  (stessa finestra di prova)


def test_parse_pitch_bend_14_bit():
    assert midi.parse([0xE0, 0x00, 0x40]) == midi.MidiEvent("pitch", 1, 0, 8192)     # centro
    top = midi.parse([0xE3, 0x7F, 0x7F])
    assert top.kind == "pitch" and top.channel == 4 and top.value == 16383
    assert top.normalized == 1.0 and top.continuous
    assert midi.parse([0xE0, 0x00, 0x00]).normalized == 0.0
    assert abs(midi.parse([0xE0, 0x00, 0x40]).normalized - 0.5) < 0.001


def test_cc_and_note_normalized_unchanged():
    assert midi.parse([0xB0, 7, 127]).normalized == 1.0
    assert not midi.parse([0x90, 36, 100]).continuous


def test_pitch_binding_label_and_matching():
    ev = midi.parse([0xE0, 0, 64])
    b = ev.binding()
    assert midi.binding_label({**b, "channel": None}) == "Pitch bend"
    assert midi.binding_label({**b, "channel": 2}) == "Pitch bend · ch 2"
    mapping = {}
    tid = midi_map.param_target("abcd1234", "Semitoni")
    midi_map.assign(mapping, tid, b)
    assert [t.id for t in midi_map.targets_for(mapping, midi.parse([0xE0, 5, 90]))] == [tid]
    # un CC 0 non si confonde con la rotella
    assert midi_map.targets_for(mapping, midi.parse([0xB0, 0, 64])) == []


def test_pitch_wheel_learns_and_drives_parameter_and_volume(win):
    from soundboard_vst.audio.plugins import create_builtin

    slot = create_builtin("Compressor")
    win.engine.mic.add_insert(slot)
    tid = midi_map.param_target(slot.uid, "threshold_db")
    labels = []
    win.midi_in.name = "Impact LX25+"
    win.midi_learn(tid, labels.append)
    win._on_midi(midi.parse([0xE0, 0x00, 0x50]))                   # si muove la rotella
    assert labels == ["Pitch bend · ch 1"]
    win._on_midi(midi.parse([0xE0, 0x7F, 0x7F]))
    assert slot.plugin.threshold_db == pytest.approx(0)
    win._on_midi(midi.parse([0xE0, 0x00, 0x00]))
    assert slot.plugin.threshold_db == pytest.approx(-60)
    win._on_midi(midi.parse([0xE0, 0x00, 0x40]))                   # rotella al centro (molla)
    assert slot.plugin.threshold_db == pytest.approx(-30, abs=0.1)
    # anche un volume del mixer
    midi_map.assign(win.config.data["midi_map"], "strip:player:gain", {"type": "pitch", "channel": None, "number": 0})
    win._on_midi(midi.parse([0xE0, 0x00, 0x00]))
    assert win.engine.strip("player").gain_db == midi_map.MIN_DB


def test_pitch_wheel_never_triggers_pads(win, monkeypatch):
    hits = []
    monkeypatch.setattr(win, "trigger", lambda *a, **k: hits.append(a))
    key = next(iter(win.config.data["sounds"]), None)
    if key:
        win.config.data["sounds"][key]["midi"] = {"type": "pitch", "channel": None, "number": 0}
    win._on_midi(midi.parse([0xE0, 0x00, 0x60]))
    assert hits == []
