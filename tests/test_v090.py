"""Novità della 0.9.0: categorie, muto/smuto, icone del player, scala dei meter, MIDI sui parametri,
ingresso e microfono al bot dal mixer."""

import os
import time
import wave
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from soundboard_vst import eventlog, midi, midi_map
from soundboard_vst.audio.engine import AudioEngine
from soundboard_vst.discord_bot import DiscordBot, greeting_action, normalize_greetings

SR = 48000


# Microfono al bot ------------------------------------------------------------------------------
def test_mic_goes_to_bot_only_when_asked():
    eng = AudioEngine(SR, 512)
    for s in eng.strips:
        s.gain_db, s._current_gain = 0.0, 1.0
    mic = np.full((2, 512), 0.3, np.float32)
    eng.bot_streaming = True
    eng.render(512, mic)
    assert not eng.bot_ring.read(512).any() and not eng.has_active_sounds()
    eng.mic_to_bot = True
    eng.render(512, mic)
    assert np.allclose(eng.bot_ring.read(512), 0.3) and eng.has_active_sounds()   # il bot non va in pausa
    d = eng.to_dict()
    assert d["mic"]["to_bot"] is True
    eng2 = AudioEngine(SR, 512)
    eng2.load_dict(d)
    assert eng2.mic_to_bot is True


# Greetings: muto / smuto -------------------------------------------------------------------------
def test_mute_and_unmute_play_sounds_or_announce():
    sent = []
    bot = DiscordBot(AudioEngine(SR, 512), lambda s: None, send_command=sent.append)
    bot.greetings = normalize_greetings({"cooldown": 0, "users": {"5": {"mute": "shh.wav"}},
                                         "announce": {"enabled": True, "unmute": "{nome} è tornato"}})
    ch = SimpleNamespace(name="Generale")
    vc = SimpleNamespace(channel=ch, is_connected=lambda: True)
    ada = SimpleNamespace(id=5, bot=False, display_name="Ada", guild=SimpleNamespace(voice_client=vc))
    st = lambda **kw: SimpleNamespace(channel=ch, **{"self_mute": False, "mute": False, "self_deaf": False,
                                                     "deaf": False, **kw})
    bot._on_member_voice(ada, st(), st(self_mute=True))
    bot._on_member_voice(ada, st(self_mute=True), st())
    bot._on_member_voice(ada, st(), st(self_deaf=True))          # cuffie silenziate = muto
    bot._on_member_voice(ada, st(), st(self_video=True))          # altro cambiamento: niente
    assert [(c["cmd"], c.get("key") or c.get("text"), c["by"]) for c in sent] == [
        ("sound", "shh.wav", "Ada (muto)"), ("say", "Ada è tornato", "Ada (smuto)"), ("sound", "shh.wav", "Ada (muto)")]
    texts = [e.text for e in eventlog.LOG.events()]
    assert "Ada si è mutato in #Generale" in texts and "Ada ha riattivato il microfono in #Generale" in texts


def test_greetings_defaults_keep_mute_announce_off():
    g = normalize_greetings({"announce": {"enabled": True}})
    assert g["announce"]["join"] and g["announce"]["mute"] == "" and g["default"]["unmute"] == ""
    assert greeting_action(g, 1, "Bob", "mute") is None            # nessun testo: nessun annuncio
    old = normalize_greetings({"users": {"5": {"join": "a.wav", "leave": "b.wav"}}})  # file della 0.8
    assert old["users"]["5"] == {"name": "", "join": "a.wav", "leave": "b.wav", "mute": "", "unmute": ""}


# MIDI sui parametri degli inserti ------------------------------------------------------------------
def test_insert_uid_and_normalized_params():
    from soundboard_vst.audio.plugins import InsertSlot, create_builtin

    slot = create_builtin("Compressor")
    assert len(slot.uid) == 8
    assert slot.set_normalized("threshold_db", 0.5) and slot.plugin.threshold_db == pytest.approx(-30)
    assert slot.get_normalized("threshold_db") == pytest.approx(0.5)
    assert slot.set_normalized("ratio", 7) and slot.plugin.ratio == pytest.approx(20)     # limitato a 1
    assert not slot.set_normalized("inesistente", 0.5) and slot.param_label("ratio") == "Rapporto"
    again = InsertSlot.from_dict(slot.to_dict())
    assert again.uid == slot.uid and again.plugin.threshold_db == pytest.approx(-30)


def test_param_targets_in_midi_map():
    tid = midi_map.param_target("abcd1234", "threshold_db")
    assert midi_map.parse_param_target(tid) == ("abcd1234", "threshold_db")
    assert midi_map.parse_param_target("strip:mic:gain") is None
    ev = midi.MidiEvent("cc", 1, 20, 64)
    found = midi_map.targets_for({tid: {"type": "cc", "channel": 1, "number": 20}}, ev)
    assert [t.id for t in found] == [tid] and found[0].kind == "continuous"


# Finestra --------------------------------------------------------------------------------------------
def write_wav(path, seconds=1.0):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.sin(np.arange(int(SR * seconds)) / 7) * 20000).astype("<i2").tobytes())


@pytest.fixture
def win(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from soundboard_vst.app import MainWindow
    from soundboard_vst.config import Config

    app = QApplication.instance() or QApplication([])
    (tmp_path / "Suoni").mkdir()
    for n in ("applausi", "risata", "tromba", "boom"):
        write_wav(tmp_path / "Suoni" / f"{n}.wav")
    cfg = Config(tmp_path / "config.json")
    cfg.data["sounds_dir"] = str(tmp_path / "Suoni")
    monkeypatch.setattr(MainWindow, "input_names", lambda self: ["Microfono USB", "Line In"])
    w = MainWindow(cfg, autostart=False)
    w.app = app
    app.processEvents()
    yield w
    w.bot.stop()
    w.remote.stop()
    w.engine.player.close()
    w.close()


def test_mixer_mic_input_and_bot_toggle(win, monkeypatch):
    chosen, notified = [], []
    monkeypatch.setattr(win, "set_input_device", lambda name: chosen.append(name))
    win.mixer._set_input = win.set_input_device
    monkeypatch.setattr(win.bot, "notify_sound", lambda: notified.append(1))
    combo = win.mixer.input_combo
    win.mixer.refresh_inputs()
    assert [combo.itemText(i) for i in range(combo.count())] == ["— nessuno —", "Microfono USB", "Line In"]
    combo.setCurrentIndex(2)
    combo.activated.emit(2)
    assert chosen == ["Line In"]
    win.mixer.mic_to_bot.setChecked(True)
    assert win.engine.mic_to_bot and notified == [1]
    assert "Microfono inviato anche al bot" in [e.text for e in eventlog.LOG.events()]


def test_set_input_device_saves_and_restarts(win, monkeypatch):
    restarted = []
    monkeypatch.setattr(win, "start_audio", lambda: restarted.append(1))
    win.engine.status.running = True
    win.set_input_device("Line In")
    assert win.config.data["audio"]["input_device"] == "Line In" and restarted == [1]
    win.engine.status.running = False


def test_mic_options_from_web(win, monkeypatch):
    chosen = []
    monkeypatch.setattr(win, "set_input_device", lambda name: chosen.append(name))
    win.remote._snapshot()
    assert win.remote.state["mic"] == {"inputs": ["Microfono USB", "Line In"], "input": "", "to_bot": False}
    win.remote._run({"cmd": "mic", "input": "Line In"})
    win.remote._run({"cmd": "mic", "input": "Dispositivo inventato"})       # non nell'elenco: ignorato
    win.remote._run({"cmd": "mic", "to_bot": True})
    assert chosen == ["Line In"] and win.engine.mic_to_bot and win.mixer.mic_to_bot.isChecked()


def test_midi_moves_insert_parameter_and_learn(win):
    from soundboard_vst.audio.plugins import create_builtin

    slot = create_builtin("Compressor")
    win.engine.mic.add_insert(slot)
    tid = midi_map.param_target(slot.uid, "threshold_db")
    labels = []
    win.midi_in.name = "Controller finto"
    win.midi_learn(tid, labels.append)
    win._on_midi(midi.MidiEvent("cc", 1, 21, 10))                  # «Impara»: il primo controllo mosso
    assert labels == [midi.binding_label({"type": "cc", "channel": 1, "number": 21})]
    assert win.config.data["midi_map"][tid]["number"] == 21
    win._on_midi(midi.MidiEvent("cc", 1, 21, 127))
    assert slot.plugin.threshold_db == pytest.approx(0)
    win._on_midi(midi.MidiEvent("cc", 1, 21, 0))
    assert slot.plugin.threshold_db == pytest.approx(-60)
    win.midi_clear(tid)
    win._on_midi(midi.MidiEvent("cc", 1, 21, 127))
    assert slot.plugin.threshold_db == pytest.approx(-60)          # tolto: non lo muove più


def test_param_dialog_has_midi_buttons_and_follows_changes(win):
    from soundboard_vst.audio.plugins import create_builtin
    from soundboard_vst.ui.plugin_dialogs import STEPS, BuiltinParamsDialog, MidiParamButton

    slot = create_builtin("Gain")
    dlg = BuiltinParamsDialog(slot)
    buttons = dlg.findChildren(MidiParamButton)
    assert len(buttons) == 1 and buttons[0].learn.text() == "MIDI"
    from PySide6.QtWidgets import QSlider

    slider = dlg.findChildren(QSlider)[0]
    slot.set_normalized("gain_db", 1.0)                            # come da un controller MIDI
    end = time.time() + 2
    while slider.value() != STEPS and time.time() < end:
        win.app.processEvents()
        time.sleep(0.02)
    assert slider.value() == STEPS
    dlg.deleteLater()


def test_categories_group_filter_and_page(win):
    b = win.board
    b.set_category(["applausi.wav", "risata.wav"], "Risate")
    b.set_category(["tromba.wav"], "Musica")
    win.config.sound_settings("boom.wav")["emoji"] = "💥"
    win.config.sound_settings("tromba.wav")["emoji"] = "💥"
    b._refresh_library()
    from soundboard_vst.ui.soundboard_view import HEADER_ROLE, KEY_ROLE

    rows = [(b.library.item(i).data(HEADER_ROLE), b.library.item(i).data(KEY_ROLE)) for i in range(b.library.count())]
    assert rows == [("Musica", None), (None, "tromba.wav"), ("Risate", None), (None, "applausi.wav"),
                    (None, "risata.wav"), ("Senza categoria", None), (None, "boom.wav")]
    combo = b.category_filter
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert labels[0] == "Tutte le categorie (4)" and "Risate (2)" in labels and "Senza categoria (1)" in labels
    assert "💥  (2)" in labels
    combo.setCurrentIndex(combo.findData("emoji:💥"))
    keys = [b.library.item(i).data(KEY_ROLE) for i in range(b.library.count())]
    assert keys == ["boom.wav", "tromba.wav"] and b.count_label.text() == "2/4"
    combo.setCurrentIndex(0)
    b.search.setText("risat")                                     # cerca anche nel nome della categoria
    visible = [b.library.item(i).data(KEY_ROLE) for i in range(b.library.count()) if not b.library.item(i).isHidden()]
    assert visible == [None, "applausi.wav", "risata.wav"]
    b.search.clear()
    b.page_from_category("Risate")
    page = b.layout_model.pages[-1]
    assert page.name == "Risate" and sorted(page.slots.values()) == ["applausi.wav", "risata.wav"]
    win.remote._snapshot()
    from soundboard_vst.discord_commands import search_sounds

    assert {s["key"] for s in search_sounds(win.remote.state, "musica")} == {"tromba.wav"}


def test_sound_dialog_category_field():
    from PySide6.QtWidgets import QApplication

    from soundboard_vst.ui.sound_dialog import SoundSettingsDialog

    QApplication.instance() or QApplication([])
    dlg = SoundSettingsDialog("x", {"category": "Meme"}, categories=["Risate", "Meme"])
    assert dlg.category.currentText() == "Meme" and dlg.category.findText("Risate") >= 0
    dlg.category.setCurrentText("  Nuova   categoria ")
    assert dlg.values()["category"] == "Nuova categoria"


def test_greetings_editor_mute_columns(win):
    from soundboard_vst.ui.discord_settings import GreetingsEditor

    ed = GreetingsEditor({"users": {"7": {"name": "Mario", "mute": "boom.wav"}}}, {"users": {}}, win.sound_choices())
    assert ed.table.columnCount() == 6
    v = ed.values()
    assert v["users"]["7"]["mute"] == "boom.wav" and v["users"]["7"]["unmute"] == ""
    ed.texts["mute"].setText("{nome} si è mutato")
    assert ed.values()["announce"]["mute"] == "{nome} si è mutato"


# Icone e meter -------------------------------------------------------------------------------------
def test_player_uses_drawn_icons_not_emoji(win):
    from soundboard_vst.ui import icons

    for name in icons.NAMES:
        img = icons.icon(name).pixmap(24, 24).toImage()
        assert any(img.pixelColor(x, y).alpha() > 0 for x in range(24) for y in range(24)), name
    pv = win.player_view
    for b in (pv.prev_btn, pv.play_btn, pv.stop_btn, pv.next_btn, pv.repeat_btn, pv.shuffle_btn):
        assert b.text() == "" and not b.icon().isNull()
    from soundboard_vst.remote.page import PAGE_HTML

    for ch in "⏮⏭⏹⏸📺🔁🔀":
        assert ch not in PAGE_HTML
    assert 'data-icon="prev"' in PAGE_HTML and "const ICON" in PAGE_HTML


def test_meter_has_db_scale(win):
    from soundboard_vst.ui.meter import BARS_W, LevelMeter

    m = LevelMeter()
    m.resize(m.width(), 240)
    img = m.grab().toImage()
    scale = [img.pixelColor(x, y).lightness() for x in range(BARS_W + 6, m.width()) for y in range(240)]
    assert m.width() > BARS_W and max(scale) > 100                # etichette disegnate a destra
