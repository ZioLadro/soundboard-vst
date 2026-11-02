"""Punto di ingresso per PyInstaller.

``SoundboardVST --selftest`` verifica che le librerie native siano incluse ed esce
con codice 0 (usato dalla build automatica).
"""

import sys


def selftest() -> int:
    import numpy as np
    import pedalboard
    from PySide6 import QtWidgets  # noqa: F401

    import soundboard_vst.app  # noqa: F401
    from soundboard_vst.audio import devices

    out = pedalboard.Compressor()(np.zeros((2, 512), np.float32), 48000)
    assert out.shape == (2, 512)

    from soundboard_vst import discord_bot

    assert discord_bot.available(), f"discord.py non incluso: {discord_bot.unavailable_reason()}"
    import davey  # noqa: F401  crittografia DAVE per la voce
    import discord

    assert discord_bot.dave_compatible(), "davey non compatibile con discord.py: il bot sarebbe muto"
    import nacl  # noqa: F401

    if sys.platform == "win32":
        discord.opus._load_default()
        assert discord.opus.is_loaded(), "libopus non inclusa"
    import subprocess

    import yt_dlp  # noqa: F401
    import yt_dlp_ejs  # noqa: F401  componente JavaScript di yt-dlp per YouTube
    from soundboard_vst import binaries

    ffmpeg = binaries.ffmpeg_exe()
    assert ffmpeg, "ffmpeg non incluso"
    subprocess.run([ffmpeg, "-version"], check=True, capture_output=True, **binaries.no_window_kwargs())
    deno = binaries.deno_exe()
    assert deno, "Deno non incluso"
    subprocess.run([deno, "--version"], check=True, capture_output=True, **binaries.no_window_kwargs())

    import segno  # noqa: F401  QR code del controllo remoto
    from aiohttp import web  # noqa: F401  server del controllo remoto
    from soundboard_vst.remote.server import RemoteServer  # noqa: F401

    import sounddevice  # PortAudio deve essere incluso

    from soundboard_vst import midi

    if sys.platform == "win32":
        assert midi.available(), f"MIDI non incluso: {midi.unavailable_reason()}"
    print("sounddevice", sounddevice.__version__, "devices:", len(devices.list_devices()),
          "midi:", midi.available())
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    from soundboard_vst.app import main

    main()
