"""Inizio/fine e dissolvenze dei suoni: calcolo, cache, finestra e riproduzione."""

import os
import time
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from soundboard_vst.audio.library import ANTICLICK_S, SoundCache, shape, shape_params

SR = 48000


def ones(seconds):
    return np.ones((2, int(SR * seconds)), np.float32)


def test_trim_and_no_copy_when_nothing_to_do():
    data = ones(2.0)
    assert shape(data, SR) is data or np.shares_memory(shape(data, SR), data)
    out = shape(data, SR, start=0.5, end=1.5)
    assert out.shape[1] == SR                                # 1 secondo esatto
    assert shape(data, SR, end=0).shape[1] == 2 * SR         # 0 = fino alla fine
    assert shape(data, SR, start=5.0).shape[1] == 0          # oltre la fine: niente
    assert shape(data, SR, start=1.0, end=0.5).shape[1] == 0 # fine prima dell'inizio: niente
    assert data.min() == 1.0                                 # l'originale non viene toccato


def test_fades_are_smooth_and_reach_zero():
    out = shape(ones(2.0), SR, fade_in=0.5, fade_out=0.25)
    fi, fo = int(0.5 * SR), int(0.25 * SR)
    assert out[0, 0] == 0.0 and out[0, -1] == pytest.approx(0.0, abs=1e-6)
    assert out[0, fi // 2] == pytest.approx(0.5, abs=0.01)   # a metà dissolvenza: metà volume
    assert np.all(np.diff(out[0, :fi]) >= -1e-7)             # sale sempre
    assert np.all(np.diff(out[0, -fo:]) <= 1e-7)             # scende sempre
    assert np.all(out[:, fi:-fo] == 1.0)                     # in mezzo intatto


def test_anticlick_only_where_cut_mid_sound():
    out = shape(ones(1.0), SR, start=0.2, end=0.8)
    k = round(ANTICLICK_S * SR)
    assert out[0, 0] == 0.0 and out[0, k] == 1.0 and out[0, -1] == pytest.approx(0.0, abs=1e-6)
    whole = shape(ones(1.0), SR, fade_in=0.0)
    assert whole[0, 0] == 1.0                                # suono intero: nessuna modifica


def test_params_from_settings():
    assert shape_params({}) == (0.0, 0.0, 0.0, 0.0)
    assert shape_params({"start": "1.5", "end": 3, "fade_in": None, "fade_out": -2}) == (1.5, 3.0, 0.0, 0.0)
    assert shape_params({"start": "boh"}) == (0.0, 0.0, 0.0, 0.0)


def write_wav(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.full(int(SR * seconds), 16000)).astype("<i2").tobytes())


def test_cache_reuses_and_invalidates(tmp_path):
    p = tmp_path / "a.wav"
    write_wav(p, 1.0)
    cache = SoundCache(SR)
    params = (0.1, 0.6, 0.05, 0.05)
    a = cache.get_shaped(p, params)
    assert a.shape[1] == int(0.5 * SR) and cache.get_shaped(p, params) is a
    assert cache.get_shaped(p, (0, 0, 0, 0)) is cache.get(p)
    time.sleep(0.01)
    write_wav(p, 2.0)
    os.utime(p, (time.time() + 5, time.time() + 5))         # file cambiato: si ricalcola
    b = cache.get_shaped(p, (0.1, 0.0, 0.0, 0.0))
    assert b.shape[1] == int(1.9 * SR)
    cache.forget(p)
    assert not cache._shaped


def test_dialog_waveform_boxes_and_preview():
    from PySide6.QtWidgets import QApplication

    from soundboard_vst.ui.sound_dialog import SoundSettingsDialog

    QApplication.instance() or QApplication([])
    previews = []
    audio = ones(4.0) * 0.5
    dlg = SoundSettingsDialog("prova", {"start": 1.0, "fade_out": 0.5}, audio=audio, sample_rate=SR,
                              preview=lambda d, g: previews.append((d, g)))
    assert dlg.wave.duration == pytest.approx(4.0) and dlg.wave.start == 1.0 and dlg.wave.end == pytest.approx(4.0)
    assert dlg.t_end.value() == 0.0 and dlg.t_end.text() == "fine"
    dlg.t_end.setValue(3.0)                                  # dai campi alla forma d'onda
    assert dlg.wave.end == pytest.approx(3.0)
    dlg.wave.fade_in = 0.25                                  # dalla forma d'onda ai campi
    dlg.wave.changed.emit()
    assert dlg.t_in.value() == pytest.approx(0.25)
    dlg.t_out.setValue(10.0)                                 # più lunga del suono tagliato: limitata
    assert dlg.wave.fade_out == pytest.approx(2.0)
    dlg.volume.setValue(150)
    dlg._listen()
    data, gain = previews[-1]
    assert data.shape[1] == 2 * SR and gain == 1.5 and data[0, 0] == 0.0
    v = dlg.values()
    assert (v["start"], v["end"], v["fade_in"], v["fade_out"]) == (1.0, 3.0, 0.25, 2.0)
    dlg._reset_shape()
    assert dlg.shape_values() == {"start": 0.0, "end": 0.0, "fade_in": 0.0, "fade_out": 0.0}
    dlg.reject()
    assert previews[-1] == (None, 0.0)                       # chiudendo l'anteprima si ferma


def test_dialog_without_audio_still_edits_times():
    from PySide6.QtWidgets import QApplication

    from soundboard_vst.ui.sound_dialog import SoundSettingsDialog

    QApplication.instance() or QApplication([])
    dlg = SoundSettingsDialog("frase", {"end": 2.5, "fade_in": 0.2})
    assert dlg.wave.duration == 0 and dlg.shape_values()["end"] == 2.5 and dlg.shape_values()["fade_in"] == 0.2
    dlg.wave.grab()                                          # disegna «non disponibile» senza errori


def test_pad_plays_trimmed_and_faded(tmp_path):
    from PySide6.QtWidgets import QApplication

    from soundboard_vst.app import MainWindow
    from soundboard_vst.config import Config

    app = QApplication.instance() or QApplication([])
    (tmp_path / "Suoni").mkdir()
    write_wav(tmp_path / "Suoni" / "colpo.wav", 3.0)
    cfg = Config(tmp_path / "config.json")
    cfg.data["sounds_dir"] = str(tmp_path / "Suoni")
    w = MainWindow(cfg, autostart=False)
    try:
        app.processEvents()
        cfg.sound_settings("colpo.wav").update({"start": 0.5, "end": 2.0, "fade_in": 0.1, "fade_out": 0.2})
        w.board.play_key("colpo.wav")
        voice = next(v for v in w.engine._voices if v.key == "colpo.wav")
        assert voice.data.shape[1] == int(1.5 * SR) and voice.data[0, 0] == 0.0
        assert voice.data[0, int(0.75 * SR)] == pytest.approx(16000 / 32768, abs=1e-3)
        w.board.grab()
    finally:
        w.bot.stop()
        w.remote.stop()
        w.engine.player.close()
        w.close()
