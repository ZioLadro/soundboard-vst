import numpy as np
import pytest

from soundboard_vst.audio.engine import AudioEngine
from soundboard_vst.audio.mixer import ChannelStrip, db_to_gain
from soundboard_vst.audio.plugins import BUILTIN_EFFECTS, InsertSlot, create_builtin
from soundboard_vst.audio.ringbuffer import RingBuffer

SR = 48000
N = 512


def tone(seconds=0.1, freq=440.0, amp=0.5):
    t = np.arange(int(SR * seconds)) / SR
    x = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([x, x])


def test_ringbuffer_roundtrip_and_underrun():
    rb = RingBuffer(2, 1000)
    data = np.arange(1200, dtype=np.float32).reshape(2, 600)
    rb.write(data)
    out = rb.read(400)
    assert np.array_equal(out, data[:, :400])
    out = rb.read(400)  # solo 200 disponibili
    assert np.array_equal(out[:, :200], data[:, 400:])
    assert not out[:, 200:].any()
    assert rb.underruns == 1


def test_ringbuffer_bounds_latency():
    rb = RingBuffer(2, 1000, max_latency=300)
    rb.write(np.ones((2, 250), np.float32))
    rb.write(np.full((2, 250), 2, np.float32))
    assert len(rb) == 300
    assert rb.read(300)[0, -1] == 2


def test_sound_reaches_discord_and_monitor_but_mic_not_monitor():
    eng = AudioEngine(SR, N)
    for s in eng.strips:
        s.gain_db = 0.0
        s._current_gain = 1.0
    snd = tone(0.05)
    eng.play("ding", snd)
    mic = np.full((2, N), 0.1, np.float32)
    master, monitor = eng.render(N, mic_block=mic)
    np.testing.assert_allclose(master, np.clip(snd[:, :N] + mic, -1, 1), atol=1e-6)
    np.testing.assert_allclose(monitor, snd[:, :N], atol=1e-6)


def test_voice_finishes_and_overlap_modes():
    eng = AudioEngine(SR, N)
    snd = tone(0.02)  # 960 campioni < 2 blocchi
    eng.play("a", snd)
    eng.play("a", snd, overlap=False)
    assert len(eng.playing_keys()) == 1 and len(eng._voices) == 1
    eng.play("a", snd, overlap=True)
    assert len(eng._voices) == 2
    eng.render(N)
    eng.render(N)
    assert eng.playing_keys() == set()
    eng.play("a", snd)
    eng.play("b", snd)
    eng.stop_sounds("a")
    assert eng.playing_keys() == {"b"}
    eng.stop_sounds()
    assert eng.playing_keys() == set()


def test_mute_and_fader():
    strip = ChannelStrip("x", "x", gain_db=-6.0)
    strip._current_gain = db_to_gain(-6.0)
    out = strip.process(np.ones((2, N), np.float32), SR)
    np.testing.assert_allclose(out, db_to_gain(-6.0), rtol=1e-5)
    strip.mute = True
    strip.process(np.ones((2, N), np.float32), SR)  # rampa verso 0
    out = strip.process(np.ones((2, N), np.float32), SR)
    assert not out.any()


@pytest.mark.parametrize("name", list(BUILTIN_EFFECTS))
def test_builtin_effects_stream_in_blocks(name):
    slot = create_builtin(name)
    x = tone(0.1)
    for i in range(0, x.shape[1] - N, N):
        out = slot.process(np.ascontiguousarray(x[:, i:i + N]), SR)
        assert out.shape == (2, N) and out.dtype == np.float32
        assert np.isfinite(out).all()


def test_insert_chain_and_state_roundtrip():
    eng = AudioEngine(SR, N)
    gain = create_builtin("Gain")
    gain.plugin.gain_db = -12.0
    eng.mic.add_insert(gain)
    eng.mic.add_insert(create_builtin("Compressor"))
    eng.mic.inserts[1].bypass = True
    eng.monitor_hear_mic = True
    state = eng.to_dict()

    eng2 = AudioEngine(SR, N)
    errors = eng2.load_dict(state)
    assert errors == []
    assert [s.type_name for s in eng2.mic.inserts] == ["Gain", "Compressor"]
    assert eng2.mic.inserts[0].plugin.gain_db == pytest.approx(-12.0)
    assert eng2.mic.inserts[1].bypass is True
    assert eng2.monitor_hear_mic is True


def test_missing_vst_is_reported_not_fatal():
    eng = AudioEngine(SR, N)
    errors = eng.load_dict({"master": {"inserts": [{"kind": "vst3", "path": "C:/non/esiste.vst3"}]}})
    assert len(errors) == 1 and eng.master.inserts == ()


def test_broken_plugin_is_bypassed():
    class Boom:
        def process(self, *a, **k):
            raise RuntimeError("crash")

    slot = InsertSlot(Boom(), "builtin", type_name="Gain")
    x = np.ones((2, N), np.float32)
    assert slot.process(x, SR) is x and slot.failed


def test_preview_only_in_monitor():
    eng = AudioEngine(SR, N)
    for s in eng.strips:
        s.gain_db, s._current_gain = 0.0, 1.0
    eng.monitor_hear_sounds = False
    eng.play("p", np.full((2, N), 0.2, np.float32), preview=True)
    master, monitor = eng.render(N)
    assert not master.any()
    np.testing.assert_allclose(monitor, 0.2, atol=1e-6)
