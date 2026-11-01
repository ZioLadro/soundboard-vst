import numpy as np
from pedalboard.io import AudioFile

from soundboard_vst.audio.library import SoundCache, list_sounds


def test_list_and_decode_with_resample(tmp_path):
    mono = (0.3 * np.sin(np.linspace(0, 200, 44100))).astype(np.float32)[np.newaxis, :]
    with AudioFile(str(tmp_path / "beep.wav"), "w", 44100, 1) as f:
        f.write(mono)
    (tmp_path / "note.txt").write_text("non audio")

    sounds = list_sounds(tmp_path)
    assert [s.key for s in sounds] == ["beep.wav"]

    data = SoundCache(48000).get(sounds[0].path)
    assert data.shape[0] == 2
    assert abs(data.shape[1] - 48000) < 100
    assert data.dtype == np.float32


def test_missing_folder_is_empty(tmp_path):
    assert list_sounds(tmp_path / "nope") == []
