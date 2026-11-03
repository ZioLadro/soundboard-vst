"""Elenco dispositivi audio tramite sounddevice (PortAudio).

Su Windows sounddevice (dalla 0.5) include anche una versione di PortAudio con i driver
**ASIO**: si sceglie con la variabile d'ambiente ``SD_ENABLE_ASIO`` prima dell'import. Qui
la si attiva (se ``ASIO_ENABLED``) e, se quella libreria non si carica, si torna a quella normale.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

_sd = None
_sd_error: str | None = None
ASIO_ENABLED = True          # da impostare prima del primo uso (si applica all'avvio del programma)
ASIO_API = "ASIO"
asio_loaded = False          # True se è stata caricata la PortAudio con ASIO


def sd():
    """Importa sounddevice solo quando serve (PortAudio può mancare)."""
    global _sd, _sd_error, asio_loaded
    if _sd is None and _sd_error is None:
        want_asio = ASIO_ENABLED and sys.platform == "win32"
        if want_asio:
            os.environ["SD_ENABLE_ASIO"] = "1"
        try:
            import sounddevice

            _sd = sounddevice
            asio_loaded = want_asio
        except Exception as exc:  # OSError se manca la libreria PortAudio
            _sd_error = str(exc)
            if want_asio:                     # PortAudio con ASIO assente o difettosa: quella normale
                os.environ.pop("SD_ENABLE_ASIO", None)
                sys.modules.pop("sounddevice", None)
                try:
                    import sounddevice

                    _sd, _sd_error = sounddevice, None
                except Exception as exc2:
                    _sd_error = str(exc2)
    if _sd is None:
        raise RuntimeError(f"sounddevice/PortAudio non disponibile: {_sd_error}")
    return _sd


def is_asio(host_api: str) -> bool:
    return host_api == ASIO_API


def audio_available() -> bool:
    try:
        sd()
        return True
    except RuntimeError:
        return False


# Nomi tipici dei cavi audio virtuali che Discord vede come microfono
VIRTUAL_CABLE_HINTS = ("cable input", "vb-audio", "voicemeeter input", "voicemeeter aux input",
                       "blackhole", "soundboard_sink")

# Ingressi che registrano l'audio del PC invece di un microfono
LOOPBACK_INPUT_HINTS = ("cable output", "stereo mix", "missaggio stereo", "mix stereo", "stereomix",
                        "what u hear", "voicemeeter out", "loopback", "blackhole", "monitor of")


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

    @property
    def looks_loopback(self) -> bool:
        n = self.name.lower()
        return self.looks_virtual or any(h in n for h in LOOPBACK_INPUT_HINTS)


def host_apis() -> list[str]:
    try:
        return [h["name"] for h in sd().query_hostapis()]
    except RuntimeError:
        return []


def default_host_api() -> str:
    """Su Windows WASAPI dà nomi completi e latenza migliore di MME (ASIO si sceglie a mano)."""
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


def channel_pairs(max_channels: int) -> list[tuple[int, str]]:
    """Coppie di canali in uscita di un dispositivo: [(0, "1-2"), (2, "3-4"), …] (una sola se mono)."""
    if max_channels <= 1:
        return [(0, "1")]
    out = [(c, f"{c + 1}-{c + 2}") for c in range(0, max_channels - 1, 2)]
    if max_channels % 2:
        out.append((max_channels - 1, f"{max_channels}"))
    return out


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
    if kind == "input" and found and found.looks_loopback:
        found = next((d for d in pool if not d.looks_loopback), None)
    return found


def system_default_output(host_api: str) -> Device | None:
    """Dispositivo di riproduzione predefinito di Windows (senza filtri)."""
    try:
        api = next((h for h in sd().query_hostapis() if h["name"] == host_api), None)
    except RuntimeError:
        return None
    idx = api["default_output_device"] if api else -1
    return next((d for d in outputs(host_api) if d.index == idx), None)


def echo_risks(host_api: str, input_name, virtual_name: str, monitor_name: str) -> list[str]:
    """Configurazioni che fanno sentire agli altri la propria voce (eco) su Discord.

    ``input_name``: un nome o un elenco di nomi (tutti gli ingressi del mixer)."""
    risks: list[str] = []
    names = [input_name] if isinstance(input_name, str) else list(input_name or [])
    for name in dict.fromkeys(names):
        inp = find(name, host_api, "input")
        if inp and inp.looks_loopback and not is_asio(host_api):
            risks.append(
                f"L'ingresso «{inp.name}» registra l'audio del PC, non il microfono: anche le voci "
                "degli altri finiscono nel mix e tornano a loro come eco. Scegli il tuo microfono come ingresso.")
    mon = find(monitor_name, host_api, "output")
    if mon and mon.looks_virtual and not is_asio(host_api):    # con ASIO conta la coppia di canali
        risks.append(
            f"Il monitor è impostato su «{mon.name}»: quello che dovresti sentire tu finisce nel cavo "
            "e arriva a Discord. Imposta le cuffie come monitor.")
    default = system_default_output(host_api)
    if default and default.looks_virtual:
        risks.append(
            f"Il dispositivo di riproduzione predefinito di Windows è «{default.name}»: tutto l'audio "
            "del PC, compreso Discord se usa «Predefinito», entra nel cavo e torna agli altri come eco. "
            "Imposta le cuffie come predefinite (Impostazioni di Windows → Sistema → Audio) e in Discord "
            "scegli le cuffie come dispositivo di output.")
    return risks


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
