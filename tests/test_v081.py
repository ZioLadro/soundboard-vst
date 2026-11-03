"""Novità della 0.8.1: avanzamento e meter dei pad, inserti dalla pagina web, adattamento allo schermo."""

import asyncio
import json
import os
import time
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QSize

from soundboard_vst.audio.engine import AudioEngine

SR = 48000


def test_voice_info_reports_progress_level_and_duration():
    eng = AudioEngine(SR, 512)
    assert eng.voice_info() == {}
    eng.play("a", np.full((2, SR), 0.5, np.float32), gain=0.5)
    eng.play("prova", np.full((2, SR), 0.9, np.float32), preview=True)      # le anteprime non contano
    eng.render(512)
    p, level, d = eng.voice_info()["a"]
    assert p == pytest.approx(512 / SR) and level == pytest.approx(0.25) and d == pytest.approx(1.0)
    assert "prova" not in eng.voice_info()
    for _ in range(int(SR / 512) + 2):
        eng.render(512)
    assert "a" not in eng.voice_info()                          # finito: sparisce


def test_overlapping_sound_reports_latest_progress_and_loudest_level():
    eng = AudioEngine(SR, 512)
    eng.play("a", np.full((2, SR), 0.8, np.float32))
    for _ in range(40):
        eng.render(512)
    eng.play("a", np.full((2, SR), 0.2, np.float32))           # seconda pressione, sovrapposta
    eng.render(512)
    p, level, _ = eng.voice_info()["a"]
    assert p == pytest.approx(512 / SR) and level == pytest.approx(0.8)


def test_pad_paints_progress_and_meter():
    from PySide6.QtWidgets import QApplication

    from soundboard_vst.ui.soundboard_view import PAD_METER_MIN_DB, PadButton

    QApplication.instance() or QApplication([])
    pad = PadButton(0)
    pad.set_sound("a.wav", "Applausi", "", False, color="#a371f7")
    pad.resize(160, 110)
    pad.set_activity((0.5, 0.5, 2.0))
    assert pad.playing and pad.progress == 0.5 and pad.level_db == pytest.approx(-6.0, abs=0.1)
    img = pad.grab().toImage()
    bottom = [img.pixelColor(x, 104).lightness() for x in range(10, 150)]
    assert abs(sum(bottom[:60]) / 60 - sum(bottom[80:]) / 60) > 30   # metà sinistra piena, destra no
    pad.set_activity(None)                                       # fermo: il meter scende piano
    assert not pad.playing and PAD_METER_MIN_DB < pad.level_db < -6.0
    for _ in range(80):
        pad.set_activity(None)
    assert pad.level_db == PAD_METER_MIN_DB


def test_screen_helpers():
    from PySide6.QtWidgets import QApplication, QLabel

    from soundboard_vst.ui import screen, theme

    QApplication.instance() or QApplication([])
    lbl = screen.ElidedLabel()
    lbl.setText("x" * 400)
    assert lbl.minimumSizeHint().width() == 40 and lbl.toolTip() == "x" * 400
    tabs = screen.SideTabs()
    for name in ("Audio", "Permessi Discord"):
        tabs.addTab(QLabel(name), name)
    tabs.setCurrentIndex(1)
    assert tabs.count() == 2 and tabs.tabText(1) == "Permessi Discord" and tabs.currentIndex() == 1
    assert tabs.stack.currentIndex() == 1
    size = screen.initial_window_size()
    avail = screen.available()
    assert size.width() <= avail.width() and size.height() <= avail.height()
    assert theme.text_scale_for(2560, 1400) > 1.0 and theme.text_scale_for(1920, 1040) == 1.0
    assert "font-size: 11.2pt" in theme.stylesheet(1.12)


def write_wav(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.sin(np.arange(int(SR * seconds)) / 7) * 20000).astype("<i2").tobytes())


@pytest.fixture
def win(tmp_path):
    from PySide6.QtWidgets import QApplication

    from soundboard_vst.app import MainWindow
    from soundboard_vst.config import Config

    app = QApplication.instance() or QApplication([])
    (tmp_path / "Suoni").mkdir()
    write_wav(tmp_path / "Suoni" / "tromba.wav", 2.0)
    cfg = Config(tmp_path / "config.json")
    cfg.data["sounds_dir"] = str(tmp_path / "Suoni")
    w = MainWindow(cfg, autostart=False)
    w.app = app
    app.processEvents()
    yield w
    w.bot.stop()
    w.remote.stop()
    w.engine.player.close()
    w.close()


def test_window_fits_small_screens(win):
    # 1920×1080 al 150% = 1280×720 logici: la finestra deve poterci stare anche con nomi lunghissimi
    win.route_label.setText("In: " + "Microfono molto lungo " * 10)
    win.config.sounds_dir = "/" + "cartella/" * 40
    win.board.folder_label.setText(str(win.config.sounds_dir))
    win.app.processEvents()
    hint = win.minimumSizeHint()
    assert hint.width() <= 1000 and hint.height() <= 640


def test_dialogs_fit_screen(win):
    from soundboard_vst.ui.settings_dialog import SettingsDialog
    from soundboard_vst.ui.sound_dialog import SoundSettingsDialog

    from soundboard_vst.ui import screen

    avail = screen.available(win)
    for dlg in (SettingsDialog(win.config, win), SoundSettingsDialog("x", {}, parent=win)):
        assert dlg.width() <= avail.width() and dlg.height() <= avail.height()
        assert dlg.minimumSizeHint().height() < 640
        dlg.deleteLater()


def test_pad_activity_reaches_board_and_web_levels(win):
    win.remote.server.error = ""
    win.board.play_key("tromba.wav")
    for _ in range(20):
        win.engine.render(512)
    win._tick()
    assert win.board._pads[0].playing and 0 < win.board._pads[0].progress < 1
    win.remote._snapshot()
    pad = win.remote.state["pads"]["pages"][0]["pads"][0]
    assert pad["playing"] and pad["duration"] == pytest.approx(2.0)


def test_inserts_from_web(win):
    r = win.remote
    r._run({"cmd": "insert", "strip": "mic", "action": "add", "type": "Compressor"})
    r._run({"cmd": "insert", "strip": "mic", "action": "add", "type": "Reverb"})
    r._run({"cmd": "insert", "strip": "mic", "action": "add", "type": "Boh"})        # sconosciuto: ignorato
    mic = win.engine.mic
    assert [s.type_name for s in mic.inserts] == ["Compressor", "Reverb"]
    assert [i["name"] for i in r.state["strips"][0]["inserts"]] == ["Compressore", "Riverbero"]
    r._run({"cmd": "insert", "strip": "mic", "action": "move", "index": 1, "delta": -1})
    assert [s.type_name for s in mic.inserts] == ["Reverb", "Compressor"]
    r._run({"cmd": "insert", "strip": "mic", "action": "bypass", "index": 1, "value": True})
    assert mic.inserts[1].bypass and r.state["strips"][0]["inserts"][1]["bypass"]
    r._run({"cmd": "insert", "strip": "mic", "action": "param", "index": 1, "name": "threshold_db", "value": -999})
    assert mic.inserts[1].plugin.threshold_db == pytest.approx(-60)                  # limitato all'intervallo
    r._run({"cmd": "insert", "strip": "mic", "action": "param", "index": 1, "name": "__class__", "value": 1})
    info = r._insert_info("mic", 1)
    assert info["name"] == "Compressore" and [p["name"] for p in info["params"]][:2] == ["threshold_db", "ratio"]
    assert info["params"][0]["value"] == pytest.approx(-60)
    r._run({"cmd": "insert", "strip": "mic", "action": "remove", "index": 0})
    assert [s.type_name for s in mic.inserts] == ["Compressor"]
    assert win.mixer.strips[0].inserts.count() == 1                                  # il mixer del PC segue
    r._run({"cmd": "insert", "strip": "mic", "action": "add_vst", "path": "/tmp/maligno.vst3"})
    assert len(mic.inserts) == 1                                                    # solo plugin già trovati
    eff = r._effects()
    assert any(e["type"] == "PitchShift" for e in eff["builtin"]) and isinstance(eff["vst"], list)


def test_monitor_options_from_web(win):
    win.remote._run({"cmd": "monitor", "hear_tts": False, "hear_mic": True, "altro": True})
    assert win.engine.monitor_hear_tts is False and win.engine.monitor_hear_mic is True
    assert win.mixer.hear_tts.isChecked() is False and win.remote.state["monitor"]["hear_mic"] is True


def test_server_endpoints_for_levels_effects_and_insert(win):
    """Endpoint veri (aiohttp), con le domande eseguite nel thread dell'interfaccia."""
    import threading
    import urllib.request

    win.remote._run({"cmd": "insert", "strip": "sounds", "action": "add", "type": "Delay"})
    win.remote.levels = {"strips": {"sounds": [-10, -12, -3, -4]}, "pads": {}}
    srv = win.remote.server
    assert srv.start(0 or 18765, "k")
    base = f"http://127.0.0.1:{srv.port}"
    results = {}

    def fetch():
        for name, url in (("levels", "/api/levels"), ("effects", "/api/effects"),
                          ("insert", "/api/insert?strip=sounds&index=0"), ("missing", "/api/insert?strip=sounds&index=9")):
            req = urllib.request.Request(base + url, headers={"X-Soundboard-Key": "k"})
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    results[name] = json.loads(resp.read())
            except Exception as exc:
                results[name] = getattr(exc, "code", str(exc))

    t = threading.Thread(target=fetch)
    t.start()
    end = time.time() + 10
    while t.is_alive() and time.time() < end:
        win.app.processEvents()                                  # risponde alle domande del server
        time.sleep(0.01)
    srv.stop()
    assert results["levels"]["strips"]["sounds"] == [-10, -12, -3, -4]
    assert any(e["label"] == "Delay" for e in results["effects"]["builtin"])
    assert results["insert"]["name"] == "Delay" and len(results["insert"]["params"]) == 3
    assert results["missing"] == 404
