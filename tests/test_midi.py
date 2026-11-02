from soundboard_vst import midi
from soundboard_vst.midi import MidiEvent, binding_label, matches, note_name, parse


def test_note_names():
    assert note_name(60) == "C4"
    assert note_name(61) == "C#4"
    assert note_name(21) == "A0"


def test_parse_note_on_off_and_cc():
    assert parse([0x90, 60, 100]) == MidiEvent("note", 1, 60, 100)
    assert parse([0x99, 36, 1]) == MidiEvent("note", 10, 36, 1)
    assert parse([0x90, 60, 0]) is None        # note on con velocity 0 = note off
    assert parse([0x80, 60, 64]) is None       # note off
    assert parse([0xB2, 20, 127]) == MidiEvent("cc", 3, 20, 127)
    assert parse([0xB2, 20, 0]) == MidiEvent("cc", 3, 20, 0)   # fader a zero / rilascio
    assert not parse([0xB2, 20, 0]).pressed
    assert parse([0xF8]) is None


def test_matches_and_labels():
    ev = MidiEvent("note", 10, 36, 90)
    b = ev.binding()
    assert matches(b, ev)
    assert not matches(b, MidiEvent("note", 1, 36, 90))
    assert matches({"type": "note", "channel": None, "number": 36}, MidiEvent("note", 1, 36, 90))
    assert not matches({"type": "cc", "channel": 10, "number": 36}, ev)
    assert not matches(None, ev)
    assert binding_label(b) == "C2 · ch 10"
    assert binding_label({"type": "cc", "channel": 1, "number": 20}) == "CC 20 · ch 1"


def test_without_rtmidi_is_graceful(monkeypatch):
    monkeypatch.setattr(midi, "_rtmidi", None)
    monkeypatch.setattr(midi, "_error", "No module named 'rtmidi'")
    assert not midi.available()
    assert midi.MidiInput.ports() == []
    assert midi.MidiInput().open("x", lambda e: None) is False
