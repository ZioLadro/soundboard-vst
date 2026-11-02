import os
import shutil
import threading
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from soundboard_vst import tts


class FakeEngine:
    """Scrive un WAV di 0,2 s; conta le chiamate; può fallire o essere lento."""

    name = "fake"
    ext = ".wav"

    def __init__(self):
        self.calls = []
        self.fail = None
        self.delay = 0.0
        self.gate = threading.Event()
        self.gate.set()

    def available(self):
        return ""

    def synthesize(self, spec, out):
        self.calls.append(spec)
        self.gate.wait(5)
        time.sleep(self.delay)
        if self.fail:
            raise tts.TTSError(self.fail)
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes((np.sin(np.arange(4800) / 10) * 12000).astype("<i2").tobytes())

    def voices(self):
        return [tts.Voice("a", "A")]


@pytest.fixture
def fake(monkeypatch, tmp_path):
    eng = FakeEngine()
    monkeypatch.setitem(tts.ENGINES, tts.ENGINE_EDGE, eng)
    monkeypatch.setattr(tts, "cache_dir", lambda: tmp_path / "tts")
    return eng


def test_spec_defaults_overrides_and_cache_name():
    s = tts.spec_for("  Ciao   a tutti ", {})
    assert s == tts.Spec("Ciao a tutti", "edge", tts.DEFAULT_EDGE_VOICE, 0, 0)
    settings = {"engine": "system", "system_voice": "Elsa", "rate": 500, "pitch": 30}
    s2 = tts.spec_for("x", settings)
    assert (s2.engine, s2.voice, s2.rate, s2.pitch) == ("system", "Elsa", 100, 0)   # tono solo per edge
    s3 = tts.spec_for("x", settings, voice="it-IT-ElsaNeural", engine="edge")       # voce della frase
    assert (s3.engine, s3.voice, s3.pitch) == ("edge", "it-IT-ElsaNeural", 30)
    assert tts.spec_for("x", {"engine": "boh"}).engine == "edge"
    assert s.cache_name() != tts.spec_for("Ciao a tutti", {"rate": 10}).cache_name()
    assert len(tts.clean_text("a" * 5000)) == tts.MAX_TEXT


def test_phrase_helpers():
    key = tts.new_phrase_key()
    assert tts.is_phrase(key) and not tts.is_phrase("applausi.wav")
    assert tts.phrase_label("Buonanotte a tutti quanti voi del canale") == "Buonanotte a tutti quanti v…"
    assert tts.phrase_spec({"text": "ok", "voice": "v", "engine": "system"}, {}).voice == "v"


def test_synthesis_is_cached_and_deduplicated(fake):
    spec = tts.spec_for("ciao", {})
    fake.gate.clear()
    f1, f2 = tts.synthesize_async(spec), tts.synthesize_async(spec)   # due pressioni insieme
    fake.gate.set()
    p1, p2 = f1.result(5), f2.result(5)
    assert p1 == p2 and p1.exists() and len(fake.calls) == 1
    hit = tts.synthesize_async(spec)
    assert hit.done() and hit.result() == p1 and len(fake.calls) == 1    # dalla cache: subito
    assert not list(p1.parent.glob("*.part*"))


def test_errors_are_reported_and_leave_nothing(fake):
    fake.fail = "voce inesistente"
    with pytest.raises(tts.TTSError, match="voce inesistente"):
        tts.synthesize(tts.spec_for("ciao", {}))
    assert not any((tts.cache_dir()).iterdir())
    fake.fail = None
    assert tts.synthesize(tts.spec_for("ciao", {})).exists()         # si può riprovare
    with pytest.raises(tts.TTSError):
        tts.synthesize(tts.spec_for("   ", {}))


def test_trim_cache(fake, monkeypatch):
    paths = []
    for i in range(4):
        paths.append(tts.synthesize(tts.spec_for(f"frase {i}", {})))
        os.utime(paths[-1], (time.time() - 100 + i, time.time() - 100 + i))
    monkeypatch.setattr(tts, "CACHE_LIMIT", 20000)               # ~2 frasi da 9,6 kB
    tts._trim_cache(keep=paths[0])
    left = sorted(p.name for p in tts.cache_dir().iterdir())
    assert paths[0].name in left and paths[-1].name in left and len(left) == 2


def test_windows_script_escapes_quotes_and_maps_rate():
    eng = tts.SystemEngine("win32")
    spec = tts.Spec("ciao", "system", "Microsoft Elsa's", 35, 0)
    script = eng.command(spec, Path(r"C:\Users\O'Neil\x.wav"), Path(r"C:\t\testo.txt"))
    assert "SelectVoice($v)" in script and "$v = 'Microsoft Elsa''s'" in script
    assert r"SetOutputToWaveFile('C:\Users\O''Neil\x.wav')" in script
    assert "$s.Rate = 4" in script and "ReadAllText('C:\\t\\testo.txt'" in script
    assert "ciao" not in script                                       # il testo passa da un file
    assert eng.ext == ".wav" and tts.SystemEngine("darwin").ext == ".aiff"


def test_mac_and_linux_commands():
    mac = tts.SystemEngine("darwin").command(tts.Spec("x", "system", "Alice", 0, 0), Path("o.aiff"), Path("t"))
    assert mac[:5] == ["say", "-o", "o.aiff", "-f", "t"] and mac[-2:] == ["-v", "Alice"]
    lin = tts.SystemEngine("linux").command(tts.Spec("x", "system", "it", -50, 0), Path("o.wav"), Path("t"))
    assert "-w" in lin and lin[lin.index("-s") + 1] == "85" and lin[-2:] == ["-v", "it"]


def test_edge_engine_arguments_and_errors(monkeypatch, tmp_path):
    import edge_tts

    seen = {}

    class Comm:
        def __init__(self, text, voice, **kw):
            seen.update(text=text, voice=voice, **kw)

        async def save(self, path):
            Path(path).write_bytes(b"ID3")

    monkeypatch.setattr(edge_tts, "Communicate", Comm)
    out = tmp_path / "x.mp3"
    tts.EdgeEngine().synthesize(tts.Spec("Ciao", "edge", "it-IT-ElsaNeural", -20, 5), out)
    assert out.exists() and seen["voice"] == "it-IT-ElsaNeural"
    assert seen["rate"] == "-20%" and seen["pitch"] == "+5Hz"

    class NoAudioReceived(Exception):
        pass

    class Broken(Comm):
        async def save(self, path):
            raise NoAudioReceived("x")

    monkeypatch.setattr(edge_tts, "Communicate", Broken)
    with pytest.raises(tts.TTSError, match="voce scelta"):
        tts.EdgeEngine().synthesize(tts.Spec("Ciao", "edge", "xx", 0, 0), out)


def test_edge_voice_list_offline_falls_back(monkeypatch):
    def boom():
        raise OSError("rete")

    monkeypatch.setattr(tts.ENGINES[tts.ENGINE_EDGE], "voices", boom)
    monkeypatch.setattr(tts, "_voice_cache", {})
    voices = tts.list_voices(tts.ENGINE_EDGE)
    assert voices[0].id.startswith("it-IT") and tts.cached_voices(tts.ENGINE_EDGE) is None


@pytest.mark.skipif(not (shutil.which("espeak-ng") or shutil.which("espeak")), reason="espeak-ng non installato")
def test_real_system_voice_with_espeak(monkeypatch, tmp_path):
    """Sintesi vera (Linux): frase → file → decodifica come un suono qualsiasi."""
    from soundboard_vst.audio.library import decode

    monkeypatch.setattr(tts, "cache_dir", lambda: tmp_path)
    path = tts.synthesize(tts.spec_for("Ciao a tutti", {"engine": "system", "system_voice": "it"}))
    audio = decode(path, 48000)
    assert audio.shape[0] == 2 and audio.shape[1] > 48000 * 0.5 and np.abs(audio).max() > 0.1
