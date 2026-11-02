import pytest

from soundboard_vst.midi import MidiEvent
from soundboard_vst.midi_map import PRESETS, TARGETS_BY_ID, assign, cc_to_db, targets_for


def test_cc_to_db_curve():
    assert cc_to_db(0) == -60.0
    assert cc_to_db(100) == pytest.approx(0.0)
    assert cc_to_db(127) == pytest.approx(4.16, abs=0.01)
    assert cc_to_db(50) == pytest.approx(-12.04, abs=0.01)


def test_lx25_preset_targets_exist_and_match():
    preset = PRESETS["Nektar Impact LX25+ (preset 1, fabbrica)"]
    assert all(t in TARGETS_BY_ID for t in preset)
    mapping = dict(preset)
    [t] = targets_for(mapping, MidiEvent("cc", 1, 7, 64))
    assert t.id == "strip:master:gain"
    [t] = targets_for(mapping, MidiEvent("note", 1, 38, 100))
    assert t.id == "pads:slot:3"
    assert targets_for(mapping, MidiEvent("cc", 1, 99, 1)) == []


def test_assign_removes_duplicates():
    mapping = {"player:next": {"type": "cc", "channel": 1, "number": 115}}
    assign(mapping, "player:toggle", {"type": "cc", "channel": 1, "number": 115})
    assert "player:next" not in mapping and mapping["player:toggle"]["number"] == 115
    assign(mapping, "player:toggle", None)
    assert mapping == {}
