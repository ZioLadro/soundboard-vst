import numpy as np
import pytest

from soundboard_vst.audio.ringbuffer import DriftReader, RingBuffer

SR, B = 48000, 512


def sine(n, freq, sr, start=0):
    t = (np.arange(n) + start) / sr
    s = np.sin(2 * np.pi * freq * t).astype(np.float32)
    return np.stack([s, s])


def run(ppm, seconds, target=B * 3, writer_sr=SR, reader_block=B, freq=440.0, ratio=1.0):
    """Lo scrittore va a ``writer_sr * (1 + ppm)``, il lettore a SR: restituisce l'uscita e il buffer."""
    ring = RingBuffer(2, SR, max_latency=B * 8)
    reader = DriftReader(ring, target, ratio=ratio)
    w_period = B / (writer_sr * (1 + ppm * 1e-6))
    r_period = reader_block / SR
    tw = tr = 0.0
    pos = 0
    out, fills = [], []
    while tr < seconds:
        if tw <= tr:
            ring.write(sine(B, freq, writer_sr, pos))
            pos += B
            tw += w_period
        else:
            fills.append(len(ring))                   # livello visto dal lettore, prima di leggere
            out.append(reader.read(reader_block))
            tr += r_period
    return np.concatenate(out, axis=1), ring, np.array(fills), reader


def max_step(x):
    return float(np.abs(np.diff(x[0])).max())


@pytest.mark.parametrize("ppm", [-500, -100, 0, 100, 500])
def test_long_run_with_clock_drift_has_no_drops_or_gaps(ppm):
    out, ring, fills, reader = run(ppm, 120.0)
    assert ring.overruns == 0                         # mai scartato audio
    steady = out[:, SR:]                              # dopo il primo secondo
    # sinusoide continua: nessun salto più grande della pendenza massima della sinusoide
    slope = 2 * np.pi * 440 / SR
    assert max_step(steady) < slope * 1.05
    assert np.abs(steady).max() > 0.99                # nessun buco di silenzio
    tail = fills[len(fills) // 2:]
    # il buffer resta intorno al livello scelto (con una deriva forte un po' sotto o sopra, per costruzione)
    allowed = B / 2 + abs(ppm) * 1e-6 / DriftReader.MAX_ADJUST * B * 3
    assert abs(tail.mean() - B * 3) < allowed
    assert abs(reader.adjust) <= DriftReader.MAX_ADJUST


def test_converts_44100_to_48000_without_seams():
    # come il bot: il motore a 44,1 kHz, Discord legge 960 campioni a 48 kHz
    out, ring, fills, _ = run(0, 30.0, target=1764, writer_sr=44100, reader_block=960, freq=1000.0,
                              ratio=44100 / 48000)
    steady = out[:, SR:]
    slope = 2 * np.pi * 1000 / SR
    assert ring.overruns == 0 and max_step(steady) < slope * 1.1
    spectrum = np.abs(np.fft.rfft(steady[0, :SR]))
    assert abs(np.argmax(spectrum) - 1000) <= 2       # stessa altezza, non accelerato né rallentato


def test_passes_samples_unchanged_when_balanced():
    ring = RingBuffer(2, SR)
    # livello già quello voluto e non aggiornato (smoothing 0): nessuna correzione
    reader = DriftReader(ring, target=B * 2 - 1, smoothing=0.0)
    data = np.random.default_rng(0).uniform(-1, 1, (2, B * 6)).astype(np.float32)
    ring.write(data[:, :B * 2])
    first = reader.read(B)
    np.testing.assert_array_equal(first, data[:, :B])     # parte subito, senza ritardo
    ring.write(data[:, B * 2:B * 3])
    np.testing.assert_array_equal(reader.read(B), data[:, B:B * 2])


def test_waits_for_data_and_resets():
    ring = RingBuffer(2, SR)
    reader = DriftReader(ring, target=B)
    assert not reader.read(B).any() and len(ring) == 0
    ring.write(np.full((2, B * 2), 0.5, np.float32))
    assert np.allclose(reader.read(B), 0.5)
    ring.clear()
    reader.reset()
    ring.write(np.full((2, B * 2), -0.5, np.float32))
    assert np.allclose(reader.read(B), -0.5)              # niente residui del flusso precedente
