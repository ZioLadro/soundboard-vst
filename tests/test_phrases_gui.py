"""Frasi sui pad con la finestra vera (offscreen): pad, MIDI, telefono, Discord, barra «Parla»."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from soundboard_vst import discord_commands, midi, tts
from soundboard_vst.config import Config

from test_tts import FakeEngine


@pytest.fixture
def win(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    eng = FakeEngine()
    monkeypatch.setitem(tts.ENGINES, tts.ENGINE_EDGE, eng)
    monkeypatch.setattr(tts, "cache_dir", lambda: tmp_path / "tts")
    from soundboard_vst.app import MainWindow

    cfg = Config(tmp_path / "config.json")
    cfg.data["sounds_dir"] = str(tmp_path / "Suoni")
    w = MainWindow(cfg, autostart=False)
    w.fake, w.app = eng, app
    yield w
    w.bot.stop()
    w.remote.stop()
    w.engine.player.close()
    w.close()


def wait_for(w, cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        w.app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_phrase_pad_plays_everywhere(win):
    board = win.board
    key = board.add_phrase({"text": "Buonanotte a tutti!", "engine": "", "voice": ""})
    assert board.layout_model.page.slots[0] == key
    assert board.display_name(key) == "Buonanotte a tutti!" and board.exists(key)
    assert board._pads[0].label == "Buonanotte a tutti!" and board._pads[0].emoji == "💬"
    from soundboard_vst.ui.soundboard_view import KEY_ROLE
    items = [board.library.item(i) for i in range(board.library.count())]
    assert [(it.data(KEY_ROLE), it.text()) for it in items] == [(key, "💬  Buonanotte a tutti!")]
    assert wait_for(win, lambda: len(win.fake.calls) == 1)        # sintetizzata subito, in anticipo

    board.play_key(key)                                           # clic sul pad
    assert wait_for(win, lambda: key in win.engine.playing_keys())
    win.engine.stop_sounds()

    # nota MIDI assegnata alla frase
    win.config.sound_settings(key)["midi"] = {"type": "note", "channel": 10, "number": 36}
    win._on_midi(midi.MidiEvent("note", 10, 36, 100))
    assert wait_for(win, lambda: key in win.engine.playing_keys())
    win.engine.stop_sounds()

    # telefono: la frase compare tra i pad e nella libreria, e si può suonare
    win.remote._snapshot()
    st = win.remote.state
    pad = st["pads"]["pages"][0]["pads"][0]
    assert pad["key"] == key and pad["label"] == "Buonanotte a tutti!" and not pad["missing"]
    assert any(s["key"] == key for s in st["library"])
    win.remote._run({"cmd": "sound", "key": key})
    assert wait_for(win, lambda: key in win.engine.playing_keys())
    win.engine.stop_sounds()

    # Discord: nella pulsantiera e in /suona
    assert [p.key for p in discord_commands.page_pads(st, 0)] == [key]
    assert discord_commands.resolve_sound(st, "buonanotte")["key"] == key
    assert len(win.fake.calls) == 1                               # sempre dalla cache


def test_say_bar_phone_and_discord_text(win):
    win.board.say_edit.setText("Ehi, ci sono!")
    win.board._say()
    assert wait_for(win, lambda: tts.LIVE_KEY in win.engine.playing_keys())
    assert win.fake.calls[-1].text == "Ehi, ci sono!"
    win.engine.stop_sounds()
    win.remote._run({"cmd": "say", "text": "Dal telefono"})       # anche /parla su Discord
    assert wait_for(win, lambda: tts.LIVE_KEY in win.engine.playing_keys())
    assert win.fake.calls[-1].text == "Dal telefono"


def test_errors_go_to_status_bar(win):
    win.fake.fail = "servizio non raggiungibile"
    win.speak("Ciao")
    assert wait_for(win, lambda: "non riuscita" in win.statusBar().currentMessage())
    assert tts.LIVE_KEY not in win.engine.playing_keys()


def test_preview_only_in_headphones(win):
    win.speak("Anteprima", preview=True)
    assert wait_for(win, lambda: "__anteprima__" in win.engine.playing_keys())
    assert tts.LIVE_KEY not in win.engine.playing_keys()


def test_save_from_bar_edit_and_delete(win, monkeypatch):
    board = win.board
    board.say_edit.setText("Salvami")
    board._save_said_phrase()
    key = board.layout_model.page.slots[0]
    assert tts.is_phrase(key) and board.phrases[key]["text"] == "Salvami" and board.say_edit.text() == ""
    board.phrases[key]["text"] = "Cambiata"
    board._after_phrase_change(key)
    assert board._pads[0].label == "Cambiata"
    assert wait_for(win, lambda: any(c.text == "Cambiata" for c in win.fake.calls))
    win.config.sound_settings(key)["label"] = "Saluto"
    board._refresh_pads()
    assert board._pads[0].label == "Saluto"
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    board.delete_phrase(key)
    assert key not in board.phrases and key not in win.config.data["sounds"]
    assert not board.layout_model.contains(key) and board._pads[0].key is None


def test_settings_tab_saves_tts(win):
    from soundboard_vst.ui.settings_dialog import SettingsDialog

    previews = []
    dlg = SettingsDialog(win.config, win, preview_tts=lambda text, s: previews.append((text, s)))
    titles = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    assert titles[-1] == "Sintesi vocale" and titles[2] == "Bot Discord"
    assert dlg.tts_values()["engine"] == "edge" and dlg.tts_values()["edge_voice"] == tts.DEFAULT_EDGE_VOICE
    dlg.tts_rate.setValue(20)
    dlg._test_tts()
    assert previews and previews[0][1]["rate"] == 20
    dlg.tts_engine.setCurrentIndex(dlg.tts_engine.findData("system"))
    assert not dlg.tts_pitch.isEnabled()
    dlg._save()
    t = win.config.data["tts"]
    assert t["engine"] == "system" and t["rate"] == 20 and t["edge_voice"] == tts.DEFAULT_EDGE_VOICE
    dlg.deleteLater()
