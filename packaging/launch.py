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
