"""Verifica apertura stream e routing con un sounddevice simulato."""

import numpy as np

from soundboard_vst.audio import devices
from soundboard_vst.audio.engine import AudioEngine

N = 256


class FakeStream:
    def __init__(self, device, channels, callback, **kw):
        self.device, self.channels, self.callback, self.kw = device, channels, callback, kw
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        pass


class FakeSD:
    def __init__(self):
        self.streams = []

    def query_hostapis(self):
        return [{"name": "Windows WASAPI", "default_input_device": 0, "default_output_device": 2}]

    def query_devices(self):
        return [
            {"name": "Microfono (USB)", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 48000},
            {"name": "CABLE Input (VB-Audio Virtual Cable)", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000},
            {"name": "Cuffie (Realtek)", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000},
        ]

    def WasapiSettings(self, **kw):
        return ("wasapi", kw)

    def InputStream(self, **kw):
        s = FakeStream(**kw)
        s.kind = "in"
        self.streams.append(s)
        return s

    def OutputStream(self, **kw):
        s = FakeStream(**kw)
        s.kind = "out"
        self.streams.append(s)
        return s


def setup_fake(monkeypatch):
    fake = FakeSD()
    monkeypatch.setattr(devices, "_sd", fake)
    return fake


def test_device_helpers(monkeypatch):
    setup_fake(monkeypatch)
    assert devices.default_host_api() == "Windows WASAPI"
    assert devices.guess_virtual_output("Windows WASAPI").name.startswith("CABLE Input")
    assert devices.default_device("Windows WASAPI", "output").name == "Cuffie (Realtek)"
    assert devices.find("CABLE Input", "Windows WASAPI", "output") is not None  # nome troncato


def test_full_routing(monkeypatch):
    fake = setup_fake(monkeypatch)
    eng = AudioEngine(48000, N)
    for s in eng.strips:
        s.gain_db, s._current_gain = 0.0, 1.0
    st = eng.start("Windows WASAPI", "Microfono (USB)", "CABLE Input (VB-Audio Virtual Cable)", "Cuffie (Realtek)")
    assert st.running, st.message
    inp, clock, mon = fake.streams
    assert all(s.started for s in fake.streams)
    assert clock.device == 1 and mon.device == 2
    assert clock.kw["extra_settings"][1] == {"auto_convert": True}

    # il microfono mono arriva, viene duplicato in stereo
    inp.callback(np.full((N, 1), 0.2, np.float32), N, None, None)
    eng.play("x", np.full((2, N * 4), 0.1, np.float32))
    out_cable = np.zeros((N, 2), np.float32)
    clock.callback(out_cable, N, None, None)
    np.testing.assert_allclose(out_cable, 0.3, atol=1e-6)        # voce + suono verso Discord

    out_mon = np.zeros((N, 2), np.float32)
    mon.callback(out_mon, N, None, None)
    np.testing.assert_allclose(out_mon, 0.1, atol=1e-6)          # in cuffia solo il suono

    eng.stop()
    assert not eng._streams


def test_monitor_only_when_no_cable(monkeypatch):
    fake = setup_fake(monkeypatch)
    eng = AudioEngine(48000, N)
    st = eng.start("Windows WASAPI", "", "", "Cuffie (Realtek)")
    assert st.running and len(fake.streams) == 1
    assert any("Discord" in w for w in st.warnings)


def test_no_output_is_an_error(monkeypatch):
    setup_fake(monkeypatch)
    st = AudioEngine(48000, N).start("Windows WASAPI", "Microfono (USB)", "", "")
    assert not st.running


def test_echo_risks(monkeypatch):
    fake = setup_fake(monkeypatch)
    api = "Windows WASAPI"
    assert devices.echo_risks(api, "Microfono (USB)", "CABLE Input (VB-Audio Virtual Cable)", "Cuffie (Realtek)") == []

    devs = fake.query_devices()
    devs.append({"name": "CABLE Output (VB-Audio Virtual Cable)", "hostapi": 0, "max_input_channels": 2,
                 "max_output_channels": 0, "default_samplerate": 48000})
    monkeypatch.setattr(fake, "query_devices", lambda: devs)
    risks = devices.echo_risks(api, "CABLE Output (VB-Audio Virtual Cable)", "CABLE Input", "CABLE Input")
    assert len(risks) == 2  # ingresso loopback + monitor sul cavo

    # Windows usa il cavo come riproduzione predefinita
    monkeypatch.setattr(fake, "query_hostapis",
                        lambda: [{"name": api, "default_input_device": 3, "default_output_device": 1}])
    risks = devices.echo_risks(api, "Microfono (USB)", "CABLE Input", "Cuffie (Realtek)")
    assert len(risks) == 1 and "predefinito" in risks[0]
    # il microfono predefinito che è un loopback viene scartato al primo avvio
    assert devices.default_device(api, "input").name == "Microfono (USB)"
