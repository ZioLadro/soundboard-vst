import base64
import time
from types import SimpleNamespace

import numpy as np

from soundboard_vst.audio.engine import AudioEngine
from soundboard_vst.audio.ringbuffer import RingBuffer
from soundboard_vst.discord_bot import (
    FRAME, FRAME_BYTES, IDLE_FRAMES, SoundboardSource, application_id_from_token,
    find_user_channel, invite_url, to_pcm,
)


def test_application_id_from_token():
    first = base64.urlsafe_b64encode(b"123456789012345678").decode().rstrip("=")
    assert application_id_from_token(f"{first}.GhIjK.abcdef") == 123456789012345678
    assert application_id_from_token("non-valido") is None
    assert "client_id=42" in invite_url(42) and "permissions=3145728" in invite_url(42)


def test_to_pcm_interleaves_and_clips():
    block = np.array([[0.5, 2.0], [-0.5, -2.0]], np.float32)
    pcm = np.frombuffer(to_pcm(block), "<i2")
    assert list(pcm) == [16383, -16383, 32767, -32767]


def test_find_user_channel():
    ch_a = SimpleNamespace(name="A", voice_states={1: None})
    ch_b = SimpleNamespace(name="B", voice_states={42: None, 7: None})
    guilds = [SimpleNamespace(voice_channels=[ch_a], stage_channels=[]),
              SimpleNamespace(voice_channels=[], stage_channels=[ch_b])]
    assert find_user_channel(guilds, 42) is ch_b
    assert find_user_channel(guilds, 99) is None


def test_source_pauses_when_idle_instead_of_ending():
    ring = RingBuffer(2, 48000)
    active = {"on": True}
    idle = []
    src = SoundboardSource(ring, 48000, lambda: active["on"], on_idle=lambda: idle.append(1))
    ring.write(np.full((2, FRAME * 3), 0.25, np.float32))
    frame = src.read()
    assert len(frame) == FRAME_BYTES
    assert np.frombuffer(frame, "<i2")[0] == int(0.25 * 32767)
    active["on"] = False
    frames = [src.read() for _ in range(IDLE_FRAMES + 3)]
    assert b"" not in frames and idle == [1]          # pausa, non fine del flusso
    src.cleanup()
    assert src.read() == b""


def test_source_continuous_never_idles_and_resyncs_backlog():
    ring = RingBuffer(2, 48000)
    idle, lat = [], []
    src = SoundboardSource(ring, 48000, lambda: False, is_continuous=lambda: True,
                           on_idle=lambda: idle.append(1), on_latency=lat.append)
    for _ in range(IDLE_FRAMES * 2):
        src.read()
    assert idle == []
    ring.write(np.zeros((2, 4000), np.float32))        # silenzio accumulato (deriva dei clock)
    ring.write(np.full((2, 960), 0.5, np.float32))     # poi parte un suono
    src.mark(time.perf_counter())
    first = np.frombuffer(src.read(), "<i2")
    assert len(ring) <= SoundboardSource.KEEP          # ritardo scartato
    assert first.any() and len(lat) == 1 and lat[0] < 1000


def test_source_resamples_from_44100():
    ring = RingBuffer(2, 48000)
    ring.write(np.full((2, 44100), 0.1, np.float32))
    src = SoundboardSource(ring, 44100, lambda: True)
    frame = src.read()
    assert len(frame) == FRAME_BYTES


def test_engine_feeds_bot_and_can_remove_sounds_from_cable():
    eng = AudioEngine(48000, 512)
    for s in eng.strips:
        s.gain_db, s._current_gain = 0.0, 1.0
    eng.play("x", np.full((2, 2048), 0.2, np.float32))
    master, _ = eng.render(512)
    assert len(eng.bot_ring) == 0 and master.any()   # bot non in trasmissione
    eng.bot_streaming = True
    eng.sounds_to_master = False
    master, monitor = eng.render(512)
    assert len(eng.bot_ring) == 512
    assert not master.any() and monitor.any()        # i suoni vanno solo al bot (e in cuffia)
    assert eng.has_active_sounds()


def test_does_not_steal_bot_used_by_another_soundboard():
    import asyncio
    from soundboard_vst.discord_bot import DiscordBot, used_elsewhere

    other = SimpleNamespace(name="Gaming")
    target = SimpleNamespace(name="Generale")
    connects = []

    async def connect(**kw):
        connects.append(kw)

    target.connect = connect
    guild = SimpleNamespace(voice_client=None, me=SimpleNamespace(voice=SimpleNamespace(channel=other)))
    target.guild = guild
    assert used_elsewhere(guild) == "Gaming"

    statuses = []
    bot = DiscordBot(AudioEngine(48000, 512), statuses.append)
    asyncio.run(bot._connect(target))
    assert connects == [] and statuses[-1].conflict and "Gaming" in statuses[-1].message

    guild.me.voice = None                           # bot libero: entra normalmente
    asyncio.run(bot._connect(target))
    assert len(connects) == 1 and connects[0]["self_deaf"] is True


def test_restarting_audio_keeps_bot_ring_object():
    eng = AudioEngine(48000, 512)
    ring = eng.bot_ring
    src = SoundboardSource(ring, 48000, lambda: True)
    eng.set_format(48000, 512)          # come dopo «OK» nelle impostazioni
    eng.set_format(48000, 1024)
    assert eng.bot_ring is ring
    eng.bot_streaming = True
    eng.play("x", np.full((2, 4096), 0.3, np.float32))
    for _ in range(4):
        eng.render(1024)
    assert np.frombuffer(src.read(), "<i2").any()
