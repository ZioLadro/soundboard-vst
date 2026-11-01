"""Elenco dispositivi audio tramite sounddevice (PortAudio)."""

from __future__ import annotations

from dataclasses import dataclass

_sd = None
_sd_error: str | None = None


def sd():
    """Importa sounddevice solo quando serve (PortAudio può mancare)."""
    global _sd, _sd_error
    if _sd is None and _sd_error is None:
        try:
            import sounddevice

            _sd = sounddevice
        except Exception as exc:  # OSError se manca la libreria PortAudio
            _sd_error = str(exc)
    if _sd is None:
        raise RuntimeError(f"sounddevice/PortAudio non disponibile: {_sd_error}")
    return _sd


def audio_available() -> bool:
    try:
        sd()
        return True
    except RuntimeError:
        return False


# Nomi tipici dei cavi audio virtuali che Discord vede come microfono
VIRTUAL_CABLE_HINTS = ("cable input", "vb-audio", "voicemeeter input", "voicemeeter aux input",
                       "blackhole", "soundboard_sink")


@dataclass(frozen=True)
class Device:
    index: int
    name: str
    host_api: str
    max_in: int
    max_out: int
    default_sr: float

    @property
    def label(self) -> str:
        return self.name

    @property
    def looks_virtual(self) -> bool:
        n = self.name.lower()
        return any(h in n for h in VIRTUAL_CABLE_HINTS)


def host_apis() -> list[str]:
    try:
        return [h["name"] for h in sd().query_hostapis()]
    except RuntimeError:
        return []


def default_host_api() -> str:
    """Su Windows WASAPI dà nomi completi e latenza migliore di MME."""
    apis = host_apis()
    for preferred in ("Windows WASAPI", "Core Audio", "PulseAudio", "ALSA"):
        if preferred in apis:
            return preferred
    return apis[0] if apis else ""


def list_devices(host_api: str = "") -> list[Device]:
    try:
        s = sd()
    except RuntimeError:
        return []
    apis = s.query_hostapis()
    out = []
    for i, d in enumerate(s.query_devices()):
        api_name = apis[d["hostapi"]]["name"]
        if host_api and api_name != host_api:
            continue
        out.append(Device(i, d["name"], api_name, d["max_input_channels"],
                          d["max_output_channels"], d["default_samplerate"]))
    return out


def inputs(host_api: str = "") -> list[Device]:
    return [d for d in list_devices(host_api) if d.max_in > 0]


def outputs(host_api: str = "") -> list[Device]:
    return [d for d in list_devices(host_api) if d.max_out > 0]


def find(name: str, host_api: str, kind: str) -> Device | None:
    if not name:
        return None
    pool = inputs(host_api) if kind == "input" else outputs(host_api)
    for d in pool:
        if d.name == name:
            return d
    for d in pool:  # nome troncato o leggermente diverso
        if d.name.startswith(name) or name.startswith(d.name):
            return d
    return None


def default_device(host_api: str, kind: str) -> Device | None:
    """Dispositivo predefinito di sistema per quella host API."""
    try:
        s = sd()
        api = next((h for h in s.query_hostapis() if h["name"] == host_api), None)
        idx = api[f"default_{kind}_device"] if api else -1
    except (RuntimeError, KeyError):
        return None
    pool = inputs(host_api) if kind == "input" else outputs(host_api)
    found = next((d for d in pool if d.index == idx), None)
    if kind == "output" and found and found.looks_virtual:
        found = next((d for d in pool if not d.looks_virtual), None)
    return found


def guess_virtual_output(host_api: str = "") -> Device | None:
    for d in outputs(host_api):
        if d.looks_virtual:
            return d
    return None


def wasapi_extra(host_api: str):
    """Su WASAPI condiviso lascia che Windows converta il sample rate."""
    if host_api != "Windows WASAPI":
        return None
    try:
        return sd().WasapiSettings(auto_convert=True)
    except Exception:
        return None
