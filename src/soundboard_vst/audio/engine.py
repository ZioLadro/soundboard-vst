"""Motore audio.

Flusso del segnale::

    Microfono ──► [Canale Microfono] ──┐
                                       ├──► [Master → Discord] ──► uscita virtuale (VB-Cable)
    Suoni ──────► [Canale Soundboard] ─┘
                        │      │
                        └──────┴──(selezionabili)──► [Monitor] ──► cuffie

Lo stream di uscita "virtuale" fa da clock: nella sua callback viene
calcolato tutto il mix. Microfono e cuffie stanno su stream separati
(spesso schede diverse, con clock diversi) collegati da ring buffer.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field

import numpy as np

from . import devices
from .mixer import ChannelStrip
from .player import Player
from .ringbuffer import RingBuffer


@dataclass
class Voice:
    key: str
    data: np.ndarray       # (2, n) float32
    gain: float = 1.0
    pos: int = 0
    loop: bool = False
    preview: bool = False   # anteprima: solo in cuffia, non arriva a Discord

    @property
    def done(self) -> bool:
        return self.pos >= self.data.shape[1] and not self.loop


@dataclass
class EngineStatus:
    running: bool = False
    message: str = "Audio fermo"
    warnings: list[str] = field(default_factory=list)


class AudioEngine:
    def __init__(self, sample_rate: int = 48000, block_size: int = 512):
        self.sample_rate = sample_rate
        self.block_size = block_size

        self.mic = ChannelStrip("mic", "Microfono")
        self.sounds = ChannelStrip("sounds", "Soundboard", gain_db=-6.0)
        self.player_strip = ChannelStrip("player", "Player", gain_db=-12.0)
        self.player = Player(sample_rate)
        self.monitor_hear_player = True
        self.master = ChannelStrip("master", "Master → Discord")
        self.monitor = ChannelStrip("monitor", "Monitor (cuffie)", gain_db=-6.0)
        self.monitor_hear_sounds = True
        self.monitor_hear_mic = False

        # Uscita per il bot Discord: i suoni (dopo il canale Soundboard) vanno in questo buffer
        self.bot_streaming = False        # True mentre il bot sta trasmettendo
        self.sounds_to_master = True      # False = i suoni arrivano a Discord solo tramite il bot
        self.bot_ring = RingBuffer(2, sample_rate, max_latency=int(sample_rate * 0.25))

        self._voices: list[Voice] = []
        self._voices_lock = threading.Lock()

        latency = block_size * 4
        self._mic_ring = RingBuffer(2, sample_rate, max_latency=latency)
        self._monitor_ring = RingBuffer(2, sample_rate, max_latency=latency)

        self._streams: list = []
        self._clock_is_virtual = True
        self._has_input = False
        self._has_monitor_stream = False
        self.status = EngineStatus()
        self.xruns = 0
        self._render_error_logged = False

    @property
    def strips(self) -> list[ChannelStrip]:
        return [self.mic, self.sounds, self.player_strip, self.master, self.monitor]

    def strip(self, strip_id: str) -> ChannelStrip:
        return next(s for s in self.strips if s.id == strip_id)

    # Suoni -------------------------------------------------------------------
    def play(self, key: str, data: np.ndarray, gain: float = 1.0, overlap: bool = True,
             preview: bool = False) -> None:
        with self._voices_lock:
            if not overlap or preview:
                self._voices = [v for v in self._voices if v.key != key]
            self._voices.append(Voice(key, data, gain, preview=preview))

    def stop_sounds(self, key: str | None = None) -> None:
        with self._voices_lock:
            self._voices = [] if key is None else [v for v in self._voices if v.key != key]

    def has_active_sounds(self) -> bool:
        with self._voices_lock:
            if any(not v.preview for v in self._voices):
                return True
        return self.player.is_active

    def playing_keys(self) -> set[str]:
        with self._voices_lock:
            return {v.key for v in self._voices}

    def _mix_voices(self, frames: int) -> tuple[np.ndarray, np.ndarray]:
        main = np.zeros((2, frames), dtype=np.float32)
        prev = np.zeros((2, frames), dtype=np.float32)
        with self._voices_lock:
            voices = list(self._voices)
        if not voices:
            return main, prev
        for v in voices:
            out = prev if v.preview else main
            n_total = v.data.shape[1]
            written = 0
            while written < frames and (v.pos < n_total or v.loop):
                if v.pos >= n_total:
                    v.pos = 0
                n = min(frames - written, n_total - v.pos)
                out[:, written:written + n] += v.data[:, v.pos:v.pos + n] * v.gain
                v.pos += n
                written += n
        with self._voices_lock:
            self._voices = [v for v in self._voices if not v.done]
        return main, prev

    # Rendering (thread audio) ------------------------------------------------
    def render(self, frames: int, mic_block: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Calcola un blocco: restituisce (uscita verso Discord, uscita monitor)."""
        sr = self.sample_rate
        if mic_block is None:
            mic_block = self._mic_ring.read(frames) if self._has_input \
                else np.zeros((2, frames), dtype=np.float32)

        mic = self.mic.process(mic_block, sr)
        voices, preview = self._mix_voices(frames)
        snd = self.sounds.process(voices, sr)
        ply = self.player_strip.process(self.player.read(frames), sr)
        if self.bot_streaming:
            self.bot_ring.write(snd + ply)
        master = self.master.process(mic + snd + ply if self.sounds_to_master else mic, sr)

        mon_in = np.zeros((2, frames), dtype=np.float32)
        if self.monitor_hear_sounds:
            mon_in += snd
        if self.monitor_hear_player:
            mon_in += ply
        if self.monitor_hear_mic:
            mon_in += mic
        mon_in += preview
        monitor = self.monitor.process(mon_in, sr)

        return np.clip(master, -1.0, 1.0), np.clip(monitor, -1.0, 1.0)

    # Callback PortAudio --------------------------------------------------------
    def _input_cb(self, indata, frames, time, status):
        if status:
            self.xruns += 1
        block = indata.T.astype(np.float32, copy=False)
        if block.shape[0] == 1:
            block = np.repeat(block, 2, axis=0)
        self._mic_ring.write(block[:2])

    def _clock_cb(self, outdata, frames, time, status):
        if status:
            self.xruns += 1
        try:
            master, monitor = self.render(frames)
        except Exception as exc:
            if not self._render_error_logged:
                print(f"[engine] errore nel rendering: {exc}", file=sys.stderr)
                self._render_error_logged = True
            outdata.fill(0)
            return
        main = master if self._clock_is_virtual else monitor
        _write_out(outdata, main)
        if self._clock_is_virtual and self._has_monitor_stream:
            self._monitor_ring.write(monitor)

    def _monitor_cb(self, outdata, frames, time, status):
        if status:
            self.xruns += 1
        _write_out(outdata, self._monitor_ring.read(frames))

    # Avvio / arresto ---------------------------------------------------------------
    def start(self, host_api: str, input_name: str, virtual_name: str, monitor_name: str) -> EngineStatus:
        self.stop()
        warnings: list[str] = []
        try:
            sd = devices.sd()
        except RuntimeError as exc:
            self.status = EngineStatus(False, str(exc))
            return self.status

        inp = devices.find(input_name, host_api, "input")
        virt = devices.find(virtual_name, host_api, "output")
        mon = devices.find(monitor_name, host_api, "output")
        if input_name and not inp:
            warnings.append(f"Ingresso non trovato: {input_name}")
        if virtual_name and not virt:
            warnings.append(f"Uscita virtuale non trovata: {virtual_name}")
        if monitor_name and not mon:
            warnings.append(f"Uscita monitor non trovata: {monitor_name}")
        if virt and mon and virt.index == mon.index:
            warnings.append("Uscita virtuale e monitor coincidono: uso solo l'uscita virtuale.")
            mon = None

        clock_dev = virt or mon
        if clock_dev is None:
            self.status = EngineStatus(False, "Scegli almeno un'uscita (virtuale o monitor).", warnings)
            return self.status

        self._clock_is_virtual = virt is not None
        self._has_input = inp is not None
        self._has_monitor_stream = virt is not None and mon is not None
        self._mic_ring.clear()
        self._monitor_ring.clear()
        extra = devices.wasapi_extra(host_api)
        common = dict(samplerate=self.sample_rate, blocksize=self.block_size,
                      dtype="float32", latency="low", extra_settings=extra)
        try:
            if inp:
                s = sd.InputStream(device=inp.index, channels=min(2, inp.max_in),
                                   callback=self._input_cb, **common)
                self._streams.append(s)
            s = sd.OutputStream(device=clock_dev.index, channels=min(2, clock_dev.max_out),
                                callback=self._clock_cb, **common)
            self._streams.append(s)
            if self._has_monitor_stream:
                s = sd.OutputStream(device=mon.index, channels=min(2, mon.max_out),
                                    callback=self._monitor_cb, **common)
                self._streams.append(s)
            for s in self._streams:
                s.start()
        except Exception as exc:
            self.stop()
            self.status = EngineStatus(False, f"Errore apertura audio: {exc}", warnings)
            return self.status

        parts = []
        if inp:
            parts.append(f"In: {inp.name}")
        if virt:
            parts.append(f"Discord: {virt.name}")
        if mon:
            parts.append(f"Cuffie: {mon.name}")
        if not virt:
            warnings.append("Nessuna uscita virtuale: Discord non riceverà l'audio.")
        self.status = EngineStatus(True, " · ".join(parts), warnings)
        return self.status

    def stop(self) -> None:
        for s in self._streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self._streams = []
        self.status = EngineStatus()

    def set_format(self, sample_rate: int, block_size: int) -> None:
        """Da chiamare ad audio fermo."""
        self.sample_rate = int(sample_rate)
        if self.player.sample_rate != self.sample_rate:
            self.player.stop()
            self.player.sample_rate = self.sample_rate
        self.block_size = int(block_size)
        latency = self.block_size * 4
        self._mic_ring = RingBuffer(2, self.sample_rate, max_latency=latency)
        self._monitor_ring = RingBuffer(2, self.sample_rate, max_latency=latency)
        self.bot_ring = RingBuffer(2, self.sample_rate, max_latency=int(self.sample_rate * 0.25))
        for strip in self.strips:
            for slot in strip.inserts:
                try:
                    slot.plugin.reset()
                except Exception:
                    pass

    # Salvataggio -------------------------------------------------------------------
    def to_dict(self) -> dict:
        d = {s.id: s.to_dict() for s in self.strips}
        d["monitor"]["hear_sounds"] = self.monitor_hear_sounds
        d["monitor"]["hear_mic"] = self.monitor_hear_mic
        d["monitor"]["hear_player"] = self.monitor_hear_player
        return d

    def load_dict(self, d: dict) -> list[str]:
        errors: list[str] = []
        for s in self.strips:
            if s.id in d:
                errors += s.load_dict(d[s.id])
        mon = d.get("monitor", {})
        self.monitor_hear_sounds = bool(mon.get("hear_sounds", True))
        self.monitor_hear_mic = bool(mon.get("hear_mic", False))
        self.monitor_hear_player = bool(mon.get("hear_player", True))
        return errors


def _write_out(outdata: np.ndarray, block: np.ndarray) -> None:
    ch = outdata.shape[1]
    if ch == 1:
        outdata[:, 0] = block.mean(axis=0)
    else:
        outdata[:, :2] = block.T
        if ch > 2:
            outdata[:, 2:] = 0
