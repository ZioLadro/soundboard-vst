"""Impostazioni persistenti (JSON nella cartella dati dell'utente)."""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

APP_DIR_NAME = "SoundboardVST"

DEFAULT_VST3_DIRS_WIN = [
    r"C:\Program Files\Common Files\VST3",
    r"C:\Program Files (x86)\Common Files\VST3",
]


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_DIR_NAME


def music_dir() -> Path:
    """Cartella Musica dell'utente (localizzata se possibile)."""
    try:
        from PySide6.QtCore import QStandardPaths

        loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation)
        if loc:
            return Path(loc)
    except Exception:
        pass
    for name in ("Musica", "Music"):
        p = Path.home() / name
        if p.is_dir():
            return p
    return Path.home() / "Music"


def default_sounds_dir() -> Path:
    return music_dir() / "Suoni"


def default_vst3_dirs() -> list[str]:
    if sys.platform == "win32":
        return list(DEFAULT_VST3_DIRS_WIN)
    if sys.platform == "darwin":
        return ["/Library/Audio/Plug-Ins/VST3", str(Path.home() / "Library/Audio/Plug-Ins/VST3")]
    return [str(Path.home() / ".vst3"), "/usr/lib/vst3", "/usr/local/lib/vst3"]


DEFAULTS: dict[str, Any] = {
    "sounds_dir": "",            # vuoto = default (Musica/Suoni)
    "audio": {
        "host_api": "",          # es. "Windows WASAPI"; vuoto = default del sistema
        "input_device": "",      # microfono / scheda audio
        "virtual_output": "",    # es. "CABLE Input (VB-Audio Virtual Cable)"
        "monitor_output": "",    # cuffie/casse per ascoltare
        "sample_rate": 48000,
        "block_size": 512,
    },
    "vst3_dirs": [],             # vuoto = cartelle standard
    "overlap_sounds": True,
    "midi": {"input": "", "velocity": False},
    "midi_map": {},              # destinazione (es. "strip:mic:gain") -> controllo MIDI
    "remote": {"enabled": False, "port": 8765, "token": ""},   # controllo da browser
    "player": {},                # coda, brano corrente, ripetizione, casuale
    "discord": {
        "token": "",             # token del bot (salvato in chiaro: non condividere il file)
        "owner_id": "",          # il tuo ID utente Discord: il bot ti segue nei canali vocali
        "autostart": False,
        "follow": True,
        "exclusive": True,       # con il bot in canale i suoni non passano dal cavo virtuale
        "continuous": True,      # trasmissione continua: latenza minima (il bot può risultare sempre attivo)
        "presence": True,        # stato del bot: «Ascolta <brano del player>»
        "shortcuts": {"toggle": "Ctrl+Alt+B", "join": "Ctrl+Alt+J", "leave": "Ctrl+Alt+L",
                      "follow": "Ctrl+Alt+F"},
        "commands": {                # comandi slash e pulsantiera su Discord
            "enabled": True,
            "sounds_access": "everyone",   # suonare e fermare i suoni: owner / role / everyone
            "control_access": "owner",     # entra/esci, player, volume, canale dedicato
            "role": "",                    # nome o ID del ruolo per il livello «role»
        },
        "board_channel": 0,          # canale dedicato alla pulsantiera (ID), 0 = nessuno
        "board_messages": [],        # messaggi della pulsantiera in quel canale
    },
    "tts": {                     # sintesi vocale
        "engine": "edge",        # "edge" (voci neurali Microsoft, online) o "system" (voci del sistema)
        "edge_voice": "it-IT-DiegoNeural",
        "system_voice": "",      # vuoto = voce predefinita del sistema
        "rate": 0,               # velocità in %, da -50 a +100
        "pitch": 0,              # tono in Hz, da -50 a +50 (solo voci neurali)
    },
    "phrases": {},               # "tts:<id>" -> {"text", "engine", "voice"}: frasi sui pad
    "sounds": {},                # nome file (o "tts:<id>") -> {"volume", "shortcut", "label", ...}
    "mixer": {},                 # id canale -> stato (fader, mute, inserti...)
    "window": {},
}


def _merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, path: Path | None = None):
        self.path = path or (config_dir() / "config.json")
        self.data: dict[str, Any] = deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self.data = _merge(DEFAULTS, raw)
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[config] impossibile leggere {self.path}: {exc}", file=sys.stderr)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    # Scorciatoie -----------------------------------------------------------
    @property
    def sounds_dir(self) -> Path:
        d = self.data.get("sounds_dir") or ""
        return Path(d) if d else default_sounds_dir()

    @sounds_dir.setter
    def sounds_dir(self, value: Path | str) -> None:
        self.data["sounds_dir"] = str(value)

    @property
    def vst3_dirs(self) -> list[str]:
        return self.data.get("vst3_dirs") or default_vst3_dirs()

    def sound_settings(self, name: str) -> dict:
        return self.data["sounds"].setdefault(name, {"volume": 1.0, "shortcut": ""})
