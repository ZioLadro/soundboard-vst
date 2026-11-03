"""Novità della 1.0.0: ASIO, ingressi mono e multipli (rinominabili), pan, solo, icona del programma."""

import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from soundboard_vst import eventlog
from soundboard_vst.audio import devices
from soundboard_vst.audio.engine import AudioEngine
from soundboard_vst.audio.mixer import ChannelStrip, InputStrip, format_pan, pan_gains

SR, N = 48000, 256


def unity(eng: AudioEngine) -> AudioEngine:
    for s in eng.strips:
        s.gain_db, s._current_gain = 0.0, 1.0
    return eng


# Pan ----------------------------------------------------------------------------------------
def test_pan_law_and_label():
    assert pan_gains(0) == (1.0, 1.0)
    assert pan_gains(-1) == (1.0, 0.0) and pan_gains(1) == (0.0, 1.0)
    assert pan_gains(-0.5) == (1.0, 0.5) and pan_gains(9) == (0.0, 1.0)
    assert [format_pan(v) for v in (0, -0.3, 1)] == ["C", "S 30", "D 100"]


def test_strip_pan_ramps_then_holds():
    s = ChannelStrip("x", "X")
    s.pan = 1.0
    block = np.ones((2, N), np.float32)
    out = s.process(block, SR)                     # rampa dal centro a destra
    assert out[0, 0] == pytest.approx(1.0) and out[0, -1] == pytest.approx(0.0, abs=1e-6)
    out = s.process(block, SR)
    assert np.allclose(out[0], 0.0) and np.allclose(out[1], 1.0)
    d = s.to_dict()
    s2 = ChannelStrip("x", "X")
    s2.load_dict(d)
    assert s2.pan == 1.0 and np.allclose(s2.process(block, SR)[0], 0.0)    # niente rampa dopo il caricamento


def test_sound_pan_per_voice():
    eng = unity(AudioEngine(SR, N))
    eng.play("a", np.full((2, N * 2), 0.5, np.float32), pan=-1.0)
    master, monitor = eng.render(N)
    assert np.allclose(master[0], 0.5) and np.allclose(master[1], 0.0)
    assert np.allclose(monitor[1], 0.0)


# Solo ----------------------------------------------------------------------------------------
def test_solo_silences_other_sources_but_not_master():
    eng = unity(AudioEngine(SR, N))
    eng.sounds.solo = True
    eng.sounds._current_gain = 1.0
    mic = np.full((2, N), 0.2, np.float32)
    eng.play("a", np.full((2, N * 8), 0.1, np.float32))
    eng.render(N, mic)                             # rampa del microfono verso il silenzio
    master, _ = eng.render(N, mic)
    assert np.allclose(master, 0.1, atol=1e-6)     # solo il suono, niente microfono
    eng.sounds.solo = False
    eng.render(N, mic)
    master, _ = eng.render(N, mic)
    assert np.allclose(master, 0.3, atol=1e-6)
    assert eng.master not in eng.source_strips and eng.monitor not in eng.source_strips
    assert eng.to_dict()["sounds"]["solo"] is False


# Ingressi --------------------------------------------------------------------------------------
def test_add_rename_remove_inputs_and_save():
    eng = AudioEngine(SR, N)
    a = eng.add_input("Chitarra", device="Scheda", channel=2, mono=True)
    b = eng.add_input()
    assert (a.id, b.id, b.name) == ("in2", "in3", "Ingresso 3")
    assert [s.id for s in eng.strips][:3] == ["mic", "in2", "in3"]
    assert not eng.remove_input("mic") and eng.remove_input("in3")
    a.to_bot, a.hear, a.pan = True, True, 0.5
    eng.mic.name = "Voce"
    d = eng.to_dict()
    assert [i["id"] for i in d["inputs"]] == ["in2"] and d["mic"]["name"] == "Voce"
    eng2 = AudioEngine(SR, N)
    eng2.load_dict(d)
    c = eng2.input_strip("in2")
    assert (c.name, c.device, c.channel, c.mono, c.to_bot, c.hear, c.pan) == ("Chitarra", "Scheda", 2, True, True, True, 0.5)
    assert eng2.mic.name == "Voce" and eng2.inputs_to_bot and eng2.has_active_sounds()
    assert eng2.add_input().id == "in3"
    with pytest.raises(ValueError):
        for _ in range(20):
            eng2.add_input()


def test_old_config_still_loads():
    eng = AudioEngine(SR, N)
    eng.load_dict({"mic": {"gain_db": -3, "mute": False, "inserts": [], "to_bot": True},
                   "monitor": {"gain_db": -6, "hear_mic": True}})
    assert eng.mic.gain_db == -3 and eng.mic_to_bot and eng.monitor_hear_mic and eng.mic.name == "Microfono"
    assert len(eng.inputs) == 1


def test_input_strip_to_bot_and_monitor():
    eng = unity(AudioEngine(SR, N))
    extra = eng.add_input("Linea")
    extra.hear = True
    extra.to_bot = True
    eng.bot_streaming = True
    eng._input_map = {"in2": ("x", [0])}
    eng._sources = {"x": type("S", (), {"reader": type("R", (), {"read": lambda self, n: np.full((1, n), 0.25, np.float32)})()})()}
    master, monitor = eng.render(N)
    assert np.allclose(master, 0.25) and np.allclose(monitor, 0.25)      # mono duplicato a sinistra e destra
    assert np.allclose(eng.bot_ring.read(N), 0.25)


# Stream (sounddevice finto) -----------------------------------------------------------------------
class FakeStream:
    def __init__(self, **kw):
        self.kw = kw
        self.device, self.channels, self.callback = kw.get("device"), kw.get("channels"), kw.get("callback")

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


class FakeSD:
    def __init__(self, api="Windows WASAPI"):
        self.api = api
        self.streams = []

    def query_hostapis(self):
        return [{"name": self.api, "default_input_device": 0, "default_output_device": 1}]

    def query_devices(self):
        return [
            {"name": "Scheda 8 in", "hostapi": 0, "max_input_channels": 8, "max_output_channels": 8, "default_samplerate": SR},
            {"name": "CABLE Input", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": SR},
            {"name": "Cuffie", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": SR},
            {"name": "Microfono USB", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": SR},
        ]

    def WasapiSettings(self, **kw):
        return ("wasapi", kw)

    def AsioSettings(self, channel_selectors):
        return ("asio", list(channel_selectors))

    def _add(self, kind, kw):
        s = FakeStream(**kw)
        s.kind = kind
        self.streams.append(s)
        return s

    def InputStream(self, **kw):
        return self._add("in", kw)

    def OutputStream(self, **kw):
        return self._add("out", kw)

    def Stream(self, **kw):
        return self._add("duplex", kw)


def test_mono_inputs_on_the_same_device_share_one_stream(monkeypatch):
    fake = FakeSD()
    monkeypatch.setattr(devices, "_sd", fake)
    eng = unity(AudioEngine(SR, N))
    eng.mic.mono, eng.mic.channel = True, 0
    gtr = eng.add_input("Chitarra", device="Scheda 8 in", channel=3, mono=True)
    gtr.pan = -1.0
    gtr._current_gain = 1.0
    usb = eng.add_input("USB", device="Microfono USB")       # dispositivo mono: duplicato
    st = eng.start("Windows WASAPI", "Scheda 8 in", "CABLE Input", "Cuffie")
    assert st.running, st.message
    ins = [s for s in fake.streams if s.kind == "in"]
    assert [(s.device, s.channels) for s in ins] == [(0, 4), (3, 1)]          # un solo stream per la scheda
    assert eng._input_map == {"mic": ("0", [0]), "in2": ("0", [3]), "in3": ("3", [0])}
    block = np.zeros((N, 4), np.float32)
    block[:, 0], block[:, 3] = 0.1, 0.2
    ins[0].callback(block, N, None, None)
    ins[1].callback(np.full((N, 1), 0.05, np.float32), N, None, None)
    clock = next(s for s in fake.streams if s.kind == "out" and s.device == 1)
    out = np.zeros((N, 2), np.float32)
    clock.callback(out, N, None, None)
    np.testing.assert_allclose(out[:, 0], 0.1 + 0.2 + 0.05, atol=1e-6)        # chitarra tutta a sinistra
    np.testing.assert_allclose(out[:, 1], 0.1 + 0.05, atol=1e-6)
    assert "Chitarra" not in st.message and "Scheda 8 in" in st.message
    usb.channel = 5                                                            # canale inesistente: avviso
    st = eng.start("Windows WASAPI", None, "CABLE Input", "Cuffie")
    assert any("USB" in w for w in st.warnings)
    eng.stop()


def test_output_channel_pairs_on_a_multichannel_device(monkeypatch):
    fake = FakeSD()
    monkeypatch.setattr(devices, "_sd", fake)
    eng = unity(AudioEngine(SR, N))
    st = eng.start("Windows WASAPI", "", "Scheda 8 in", "Scheda 8 in", virtual_channel=0, monitor_channel=4)
    assert st.running and len(fake.streams) == 1                                  # stessa scheda: un solo stream
    out = fake.streams[0]
    assert out.channels == 6
    eng.play("x", np.full((2, N * 2), 0.1, np.float32))
    buf = np.zeros((N, 6), np.float32)
    out.callback(buf, N, None, None)
    assert np.allclose(buf[:, :2], 0.1) and np.allclose(buf[:, 4:6], 0.1) and not buf[:, 2:4].any()
    st = eng.start("Windows WASAPI", "", "Scheda 8 in", "Scheda 8 in", 0, 0)
    assert any("coincidono" in w for w in st.warnings)
    eng.stop()


def test_asio_uses_one_duplex_stream_with_channel_selectors(monkeypatch):
    fake = FakeSD(api="ASIO")
    monkeypatch.setattr(devices, "_sd", fake)
    eng = unity(AudioEngine(SR, N))
    eng.mic.mono, eng.mic.channel = True, 1
    keys = eng.add_input("Tastiera", device="Scheda 8 in", channel=4, mono=False)   # stereo 5-6
    keys._current_gain = 1.0
    eng.add_input("Altro driver", device="Microfono USB")                        # un secondo driver ASIO: ignorato
    st = eng.start("ASIO", "Scheda 8 in", "Scheda 8 in", "Scheda 8 in", virtual_channel=2, monitor_channel=0)
    assert st.running, st.message
    assert len(fake.streams) == 1
    s = fake.streams[0]
    assert s.kind == "duplex" and s.device == (0, 0) and s.channels == (3, 4)
    assert s.kw["extra_settings"] == (("asio", [1, 4, 5]), ("asio", [0, 1, 2, 3]))
    assert any("Altro driver" in w for w in st.warnings)
    eng.monitor_hear_mic = True
    ind = np.zeros((N, 3), np.float32)
    ind[:, 0], ind[:, 1], ind[:, 2] = 0.1, 0.2, 0.3
    outd = np.zeros((N, 4), np.float32)
    s.callback(ind, outd, N, None, None)
    np.testing.assert_allclose(outd[:, 2], 0.1 + 0.2, atol=1e-6)       # verso Discord: canali 3-4
    np.testing.assert_allclose(outd[:, 3], 0.1 + 0.3, atol=1e-6)
    np.testing.assert_allclose(outd[:, 0], 0.1, atol=1e-6)             # cuffie: canali 1-2, solo il microfono
    assert eng._duplex_in is None
    assert st.message.startswith("ASIO: Scheda 8 in")
    eng.stop()


def test_asio_output_only_and_monitor_on_other_driver(monkeypatch):
    fake = FakeSD(api="ASIO")
    monkeypatch.setattr(devices, "_sd", fake)
    eng = AudioEngine(SR, N)
    st = eng.start("ASIO", "", "Scheda 8 in", "Cuffie")
    assert st.running and [s.kind for s in fake.streams] == ["out"]
    assert fake.streams[0].kw["extra_settings"] == ("asio", [0, 1])
    assert any("Cuffie" in w and "ASIO" in w for w in st.warnings)
    eng.stop()


def test_channel_pairs_and_asio_flag():
    assert devices.channel_pairs(1) == [(0, "1")]
    assert devices.channel_pairs(2) == [(0, "1-2")]
    assert devices.channel_pairs(5) == [(0, "1-2"), (2, "3-4"), (4, "5")]
    assert devices.is_asio("ASIO") and not devices.is_asio("Windows WASAPI")


def test_echo_risks_accepts_all_inputs(monkeypatch):
    fake = FakeSD()
    devs = fake.query_devices() + [{"name": "Stereo Mix", "hostapi": 0, "max_input_channels": 2,
                                     "max_output_channels": 0, "default_samplerate": SR}]
    monkeypatch.setattr(fake, "query_devices", lambda: devs)
    monkeypatch.setattr(devices, "_sd", fake)
    risks = devices.echo_risks("Windows WASAPI", ["Microfono USB", "Stereo Mix"], "CABLE Input", "Cuffie")
    assert "Stereo Mix" in risks[0] and not any("Microfono USB" in r for r in risks)


# Interfaccia ----------------------------------------------------------------------------------------
@pytest.fixture
def win(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from soundboard_vst.app import MainWindow
    from soundboard_vst.config import Config

    app = QApplication.instance() or QApplication([])
    (tmp_path / "Suoni").mkdir()
    cfg = Config(tmp_path / "config.json")
    cfg.data["sounds_dir"] = str(tmp_path / "Suoni")
    monkeypatch.setattr(MainWindow, "input_devices", lambda self: [("Scheda 8 in", 8), ("Microfono USB", 1)])
    monkeypatch.setattr(MainWindow, "input_names", lambda self: ["Scheda 8 in", "Microfono USB"])
    w = MainWindow(cfg, autostart=False)
    app.processEvents()
    yield w
    w.bot.stop()
    w.remote.stop()
    w.engine.player.close()
    w.close()


def test_mixer_adds_renames_and_removes_inputs(win, monkeypatch):
    restarted = []
    monkeypatch.setattr(win, "start_audio", lambda: restarted.append(1))
    win.engine.status.running = True
    m = win.mixer
    strip = m.add_input()
    assert [w.strip.id for w in m.strips][:2] == ["mic", "in2"] and "in2" in m._input_ui
    m.rename_input("in2", "  Chitarra   acustica ")
    assert win.engine.input_strip("in2").name == "Chitarra acustica"
    assert m.strips[1].title.text() == "Chitarra acustica" and m._hear_inputs["in2"].text() == "Chitarra acustica"
    combo = m._input_ui["in2"]["device"]
    combo.setCurrentIndex(combo.findData("Scheda 8 in"))
    combo.activated.emit(combo.currentIndex())
    assert strip.device == "Scheda 8 in" and restarted
    ch = m._input_ui["in2"]["channels"]
    labels = [ch.itemText(i) for i in range(ch.count())]
    assert labels[:4] == ["Stereo 1-2", "Stereo 3-4", "Stereo 5-6", "Stereo 7-8"] and "Mono 8" in labels
    i = labels.index("Mono 3")
    ch.setCurrentIndex(i)
    ch.activated.emit(i)
    assert (strip.channel, strip.mono) == (2, True)
    win.save()
    saved = win.config.data["mixer"]["inputs"][0]
    assert saved["name"] == "Chitarra acustica" and saved["channel"] == 2 and saved["mono"] is True
    m._input_ui["in2"]["to_bot"].setChecked(True)
    assert "Chitarra acustica inviato anche al bot" in [e.text for e in eventlog.LOG.events()]
    m.remove_input("in2", confirm=False)
    assert len(win.engine.inputs) == 1 and "in2" not in m._input_ui
    m.remove_input("mic", confirm=False)
    assert len(win.engine.inputs) == 1
    win.engine.status.running = False


def test_mixer_pan_and_solo_widgets(win):
    w = win.mixer.strips[[s.strip.id for s in win.mixer.strips].index("sounds")]
    w.pan.setValue(-50)
    assert win.engine.sounds.pan == -0.5 and w.pan_value.text() == "S 50"
    w.solo.setChecked(True)
    assert win.engine.sounds.solo
    master = next(x for x in win.mixer.strips if x.strip is win.engine.master)
    assert master.solo is None                                   # Master e Monitor non hanno SOLO
    win.engine.tts.pan, win.engine.tts.solo = 0.25, True         # da MIDI o pagina web
    win.mixer.sync_levels()
    t = next(x for x in win.mixer.strips if x.strip is win.engine.tts)
    assert t.pan.value() == 25 and t.solo.isChecked()


def test_web_pan_solo_and_inputs(win, monkeypatch):
    chosen = []
    monkeypatch.setattr(win, "set_input_device", lambda *a: chosen.append(a))
    win.mixer.add_input()
    r = win.remote
    r._run({"cmd": "strip", "id": "player", "pan": -3, "solo": True})
    r._run({"cmd": "strip", "id": "master", "solo": True})                 # non si può: ignorato
    assert win.engine.player_strip.pan == -1.0 and win.engine.player_strip.solo and not win.engine.master.solo
    r._run({"cmd": "input", "id": "in2", "hear": True, "to_bot": True})
    r._run({"cmd": "input", "id": "in2", "device": "Microfono USB"})
    r._run({"cmd": "input", "id": "mic", "device": "Scheda 8 in"})
    r._run({"cmd": "input", "id": "in2", "device": "Inventato"})
    r._run({"cmd": "input", "id": "nessuno", "hear": True})
    s = win.engine.input_strip("in2")
    assert s.hear and s.to_bot and win.mixer._hear_inputs["in2"].isChecked()
    assert chosen == [("Microfono USB", "in2"), ("Scheda 8 in",)]
    st = r.state
    assert [i["id"] for i in st["inputs"]] == ["mic", "in2"]
    player = next(x for x in st["strips"] if x["id"] == "player")
    assert player["pan"] == -1.0 and player["solo"] and player["soloable"]
    assert next(x for x in st["strips"] if x["id"] == "in2")["input"]


def test_sound_pan_reaches_engine(win, tmp_path, monkeypatch):
    import wave

    p = tmp_path / "Suoni" / "beep.wav"
    with wave.open(str(p), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((np.ones(SR // 10) * 8000).astype("<i2").tobytes())
    played = []
    monkeypatch.setattr(win.engine, "play", lambda *a, **kw: played.append(kw))
    win.config.data["sounds"]["beep.wav"] = {"pan": 0.7}
    win.play_sound("beep.wav", p)
    assert played[0]["pan"] == pytest.approx(0.7)


def test_sound_dialog_pan():
    from PySide6.QtWidgets import QApplication

    from soundboard_vst.ui.sound_dialog import SoundSettingsDialog

    QApplication.instance() or QApplication([])
    previews = []
    audio = np.zeros((2, SR // 10), np.float32)
    dlg = SoundSettingsDialog("x", {"pan": -0.4}, audio=audio, preview=lambda *a: previews.append(a))
    assert dlg.pan.value() == -40 and dlg.values()["pan"] == pytest.approx(-0.4)
    dlg._listen()
    assert previews[-1][1:] == (1.0, -0.4)
    dlg.pan.setValue(0)
    dlg._listen()
    assert len(previews[-1]) == 2                                  # al centro: come prima


# Icona --------------------------------------------------------------------------------------------
def test_app_icon_and_ico_file():
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from soundboard_vst.ui.icons import app_icon, app_icon_image, ico_bytes

    QApplication.instance() or QApplication([])
    assert not app_icon().isNull() and len(app_icon().availableSizes()) >= 8
    img = app_icon_image(64)
    assert img.pixelColor(32, 32).alpha() == 255 and img.pixelColor(0, 0).alpha() == 0   # angoli trasparenti
    data = ico_bytes((16, 32, 256))
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, 3)
    w, h = data[6], data[7]
    assert (w, h) == (16, 16) and data[6 + 32] == 0                # 256 px si scrive come 0
    committed = Path(__file__).resolve().parent.parent / "packaging" / "icon.ico"
    assert committed.is_file() and committed.read_bytes()[:4] == b"\x00\x00\x01\x00"


def test_version():
    from soundboard_vst import __version__

    assert __version__ == "1.0.0"
