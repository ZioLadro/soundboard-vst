import time

import numpy as np
import pytest
from pedalboard.io import AudioFile

from soundboard_vst import binaries
from soundboard_vst.audio.engine import AudioEngine
from soundboard_vst.audio.player import Player, Track, format_time, probe_duration, read_m3u, write_m3u

SR = 48000
pytestmark = pytest.mark.skipif(binaries.ffmpeg_exe() is None, reason="ffmpeg non disponibile")


def make_tone(path, seconds, value):
    data = np.full((2, int(SR * seconds)), value, np.float32)
    with AudioFile(str(path), "w", SR, 2) as f:
        f.write(data)
    return Track.from_file(path)


def pump(player, seconds, frames=512):
    """Simula la callback audio per ``seconds`` secondi; restituisce l'audio letto."""
    out = []
    end = time.time() + seconds
    while time.time() < end:
        out.append(player.read(frames))
        time.sleep(frames / SR / 4)
    return np.concatenate(out, axis=1) if out else np.zeros((2, 0), np.float32)


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_probe_and_format(tmp_path):
    t = make_tone(tmp_path / "a.wav", 1.5, 0.1)
    assert probe_duration(t.source) == pytest.approx(1.5, abs=0.05)
    assert format_time(75) == "1:15" and format_time(3725) == "1:02:05" and format_time(None) == "--:--"


def test_plays_queue_and_advances(tmp_path):
    a = make_tone(tmp_path / "a.wav", 0.3, 0.25)
    b = make_tone(tmp_path / "b.wav", 0.3, -0.5)
    events = []
    p = Player(SR, events.append)
    p.add([a, b])
    p.play(0)
    assert wait_for(lambda: p.state == "playing")
    audio = pump(p, 2.0)
    vals = set(np.round(audio[0][np.abs(audio[0]) > 0.01], 2))
    assert 0.25 in vals and -0.5 in vals            # entrambi i brani suonati
    assert wait_for(lambda: p.state == "stopped")   # fine coda senza ripetizione
    assert "track" in events
    p.close()


def test_pause_seek_repeat_one(tmp_path):
    a = make_tone(tmp_path / "a.wav", 1.0, 0.2)
    p = Player(SR)
    p.add([a])
    p.repeat = "one"
    p.play(0)
    assert wait_for(lambda: p.state == "playing")
    pump(p, 0.2)
    p.pause()
    assert not p.read(512).any()
    p.seek(0.5)
    assert p.state == "paused" and p.position == pytest.approx(0.5)
    p.play()
    assert wait_for(lambda: len(p._ring) > 0)
    pump(p, 1.5)
    assert p.state in ("playing", "loading")        # ripete lo stesso brano
    p.stop()
    assert p.state == "stopped"
    p.close()


def test_missing_file_reports_error(tmp_path):
    p = Player(SR)
    p.add([Track("manca", str(tmp_path / "nope.mp3"))])
    p.play(0)
    assert wait_for(lambda: p.error != "")
    assert wait_for(lambda: p.state == "stopped")
    p.close()


def test_queue_edit_keeps_current(tmp_path):
    tracks = [Track(str(i), f"/x/{i}.mp3") for i in range(4)]
    p = Player(SR)
    p.add(tracks)
    p.index = 2
    p.move(2, 0)
    assert p.current.title == "2" and p.index == 0
    p.remove(3)
    assert len(p.tracks) == 3 and p.current.title == "2"
    p.close()


def test_m3u_roundtrip(tmp_path):
    tracks = [Track("Uno", str(tmp_path / "1.mp3"), "file", 61.0),
              Track("Video", "https://www.youtube.com/watch?v=abc", "youtube", None)]
    m3u = tmp_path / "lista.m3u"
    write_m3u(m3u, tracks)
    back = read_m3u(m3u)
    assert [(t.title, t.source, t.kind) for t in back] == [(t.title, t.source, t.kind) for t in tracks]


def test_engine_player_channel_routing(tmp_path):
    eng = AudioEngine(SR, 512)
    for s in eng.strips:
        s.gain_db, s._current_gain = 0.0, 1.0
    eng.player.add([make_tone(tmp_path / "m.wav", 1.0, 0.3)])
    eng.player.play(0)
    assert wait_for(lambda: len(eng.player._ring) >= 512)
    assert eng.has_active_sounds()
    eng.bot_streaming = True
    master, monitor = eng.render(512)
    assert np.allclose(master, 0.3, atol=1e-3) and np.allclose(monitor, 0.3, atol=1e-3) and len(eng.bot_ring) == 512
    eng.monitor_hear_player = False
    eng.sounds_to_master = False
    master, monitor = eng.render(512)
    assert not master.any() and not monitor.any()
    eng.player.close()
