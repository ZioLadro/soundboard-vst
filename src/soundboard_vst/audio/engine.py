"""Motore audio.

Flusso del segnale::

    Ingressi ───► [Microfono] [Ingresso 2] … ──┐
                                               ├──► [Master → Discord] ──► uscita virtuale (VB-Cable)
    Suoni ──────► [Canale Soundboard] ─────────┤
    Frasi TTS ──► [Canale Sintesi vocale] ─────┤
    Player ─────► [Canale Player] ─────────────┘
                        │      │
                        └──────┴──(selezionabili)──► [Monitor] ──► cuffie

Ogni ingresso ha un nome, un dispositivo e i suoi canali (mono = un canale, stereo = due).
Ogni canale ha fader, pan, mute e (gli ingressi e le sorgenti) solo.

Lo stream di uscita "virtuale" fa da clock: nella sua callback viene
calcolato tutto il mix. Ingressi e cuffie stanno su stream separati
(spesso schede diverse, con clock diversi) collegati da ring buffer, letti con
``DriftReader`` che compensa la differenza di velocità tra le schede.

Con ASIO tutto passa da un unico stream full-duplex sullo stesso dispositivo (i driver ASIO
non si possono aprire più volte): ingressi, uscita verso Discord e cuffie sono coppie di
canali diverse della stessa scheda, con lo stesso clock e senza ring buffer.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field

import numpy as np

from . import devices
from .mixer import ChannelStrip, InputStrip, pan_gains
from .player import Player
from .ringbuffer import DriftReader, RingBuffer


# Buffer tra schede con clock diversi (microfono → mix, mix → cuffie), in blocchi audio:
# livello a cui li tiene DriftReader e massimo prima di scartare audio.
RING_TARGET_BLOCKS = 3
RING_MAX_BLOCKS = 8
MAX_INPUTS = 16
DUPLEX = "__duplex__"          # sorgente degli ingressi nello stream full-duplex (ASIO)


@dataclass
class _InputSource:
    """Uno stream d'ingresso (un dispositivo, uno o più canali) con il suo ring buffer."""
    ring: RingBuffer
    reader: DriftReader


@dataclass
class Voice:
    key: str
    data: np.ndarray       # (2, n) float32
    gain: float = 1.0
    pan: float = 0.0        # -1 sinistra … +1 destra
    pos: int = 0
    loop: bool = False
    preview: bool = False   # anteprima: solo in cuffia, non arriva a Discord
    strip: str = "sounds"   # canale del mixer: "sounds" o "tts" (sintesi vocale)
    level: float = 0.0      # picco dell'ultimo blocco suonato (con il volume del pad), per i meter dei pad

    @property
    def done(self) -> bool:
        return self.pos >= self.data.shape[1] and not self.loop

    @property
    def progress(self) -> float:
        n = self.data.shape[1]
        return min(1.0, self.pos / n) if n else 1.0


@dataclass
class EngineStatus:
    running: bool = False
    message: str = "Audio fermo"
    warnings: list[str] = field(default_factory=list)


class AudioEngine:
    def __init__(self, sample_rate: int = 48000, block_size: int = 512):
        self.sample_rate = sample_rate
        self.block_size = block_size

        self.inputs: list[InputStrip] = [InputStrip("mic", "Microfono")]
        self.sounds = ChannelStrip("sounds", "Soundboard", gain_db=-6.0)
        self.tts = ChannelStrip("tts", "Sintesi vocale", gain_db=-3.0)
        self.monitor_hear_tts = True
        self.player_strip = ChannelStrip("player", "Player", gain_db=-12.0)
        self.player = Player(sample_rate)
        self.monitor_hear_player = True
        self.master = ChannelStrip("master", "Master → Discord")
        self.monitor = ChannelStrip("monitor", "Monitor (cuffie)", gain_db=-6.0)
        self.monitor_hear_sounds = True

        # Uscita per il bot Discord: i suoni (dopo il canale Soundboard) vanno in questo buffer
        self.bot_streaming = False        # True mentre il bot sta trasmettendo
        self.sounds_to_master = True      # False = i suoni arrivano a Discord solo tramite il bot
        self.bot_ring = RingBuffer(2, sample_rate, max_latency=int(sample_rate * 0.12))

        self._voices: list[Voice] = []
        self._voices_lock = threading.Lock()

        self._monitor_ring = RingBuffer(2, sample_rate, max_latency=block_size * RING_MAX_BLOCKS)
        self._monitor_reader = DriftReader(self._monitor_ring, block_size * RING_TARGET_BLOCKS)

        self._streams: list = []
        self._sources: dict[str, _InputSource] = {}       # dispositivo → stream d'ingresso
        self._input_map: dict[str, tuple[str, list[int]]] = {}   # ingresso → (sorgente, colonne)
        self._duplex_in: np.ndarray | None = None
        self._out_routes: list[tuple[str, list[int]]] = []      # ("master"|"monitor", colonne) dello stream clock
        self._has_monitor_stream = False
        self._monitor_cols: list[int] = [0, 1]
        self.status = EngineStatus()
        self.xruns = 0
        self._render_error_logged = False

    # Canali -------------------------------------------------------------------------
    @property
    def mic(self) -> InputStrip:
        """Il primo ingresso (non si può togliere)."""
        return self.inputs[0]

    @property
    def mic_to_bot(self) -> bool:
        return self.mic.to_bot

    @mic_to_bot.setter
    def mic_to_bot(self, value: bool) -> None:
        self.mic.to_bot = bool(value)

    @property
    def monitor_hear_mic(self) -> bool:
        return self.mic.hear

    @monitor_hear_mic.setter
    def monitor_hear_mic(self, value: bool) -> None:
        self.mic.hear = bool(value)

    @property
    def inputs_to_bot(self) -> bool:
        """Almeno un ingresso va anche al bot Discord."""
        return any(s.to_bot for s in self.inputs)

    @property
    def strips(self) -> list[ChannelStrip]:
        return [*self.inputs, self.sounds, self.tts, self.player_strip, self.master, self.monitor]

    @property
    def source_strips(self) -> list[ChannelStrip]:
        """Canali che si possono mettere in solo (ingressi e sorgenti, non Master e Monitor)."""
        return [*self.inputs, self.sounds, self.tts, self.player_strip]

    def add_input(self, name: str = "", device: str = "", channel: int = 0, mono: bool = True) -> InputStrip:
        """Nuovo canale d'ingresso (id ``in2``, ``in3``…). Per aprirne il dispositivo va riavviato l'audio."""
        if len(self.inputs) >= MAX_INPUTS:
            raise ValueError(f"Al massimo {MAX_INPUTS} ingressi")
        used = {s.id for s in self.inputs}
        n = 2
        while f"in{n}" in used:
            n += 1
        strip = InputStrip(f"in{n}", (name or f"Ingresso {n}").strip()[:40], device=device,
                           channel=channel, mono=mono)
        self.inputs = [*self.inputs, strip]          # nuova lista: il thread audio legge sempre una lista intera
        return strip

    def remove_input(self, strip_id: str) -> bool:
        """Toglie un ingresso aggiunto (il Microfono resta)."""
        if strip_id == "mic" or strip_id not in {s.id for s in self.inputs}:
            return False
        self.inputs = [s for s in self.inputs if s.id != strip_id]
        return True

    def input_strip(self, strip_id: str) -> InputStrip | None:
        return next((s for s in self.inputs if s.id == strip_id), None)

    def strip(self, strip_id: str) -> ChannelStrip:
        return next(s for s in self.strips if s.id == strip_id)

    # Suoni -------------------------------------------------------------------
    def play(self, key: str, data: np.ndarray, gain: float = 1.0, overlap: bool = True,
             preview: bool = False, strip: str = "sounds", pan: float = 0.0) -> None:
        """``pan``: posizione del suono (-1 sinistra … +1 destra), oltre al pan del canale."""
        with self._voices_lock:
            if not overlap or preview:
                self._voices = [v for v in self._voices if v.key != key]
            self._voices.append(Voice(key, data, gain, max(-1.0, min(1.0, float(pan or 0.0))), preview=preview,
                                      strip="tts" if strip == "tts" else "sounds"))

    def stop_sounds(self, key: str | None = None) -> None:
        with self._voices_lock:
            self._voices = [] if key is None else [v for v in self._voices if v.key != key]

    def has_active_sounds(self) -> bool:
        if any(s.to_bot for s in self.inputs):
            return True                   # un ingresso è sempre «attivo»: il bot non va in pausa
        with self._voices_lock:
            if any(not v.preview for v in self._voices):
                return True
        return self.player.is_active

    def playing_keys(self) -> set[str]:
        with self._voices_lock:
            return {v.key for v in self._voices}

    def voice_info(self) -> dict[str, tuple[float, float, float]]:
        """Per ogni suono che sta suonando: (avanzamento 0..1, picco attuale, durata in secondi).

        Se lo stesso suono è sovrapposto più volte, l'avanzamento è quello dell'ultimo partito
        e il picco il più alto.
        """
        with self._voices_lock:
            voices = list(self._voices)
        out: dict[str, tuple[float, float, float]] = {}
        sr = float(self.sample_rate)
        for v in voices:                       # in ordine di partenza: l'ultimo vince sull'avanzamento
            if v.preview:
                continue
            prev = out.get(v.key)
            level = max(v.level, prev[1]) if prev else v.level
            out[v.key] = (v.progress, level, v.data.shape[1] / sr)
        return out

    def _mix_voices(self, frames: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(suoni, anteprime solo cuffia, sintesi vocale)."""
        main = np.zeros((2, frames), dtype=np.float32)
        prev = np.zeros((2, frames), dtype=np.float32)
        speech = np.zeros((2, frames), dtype=np.float32)
        with self._voices_lock:
            voices = list(self._voices)
        if not voices:
            return main, prev, speech
        for v in voices:
            out = prev if v.preview else speech if v.strip == "tts" else main
            n_total = v.data.shape[1]
            written = 0
            peak = 0.0
            if v.pan:
                left, right = pan_gains(v.pan)
                gains = np.array([[v.gain * left], [v.gain * right]], dtype=np.float32)
            else:
                gains = np.float32(v.gain)
            while written < frames and (v.pos < n_total or v.loop):
                if v.pos >= n_total:
                    v.pos = 0
                n = min(frames - written, n_total - v.pos)
                chunk = v.data[:, v.pos:v.pos + n]
                out[:, written:written + n] += chunk * gains
                if n:
                    peak = max(peak, float(np.abs(chunk).max()))
                v.pos += n
                written += n
            v.level = peak * v.gain
        with self._voices_lock:
            self._voices = [v for v in self._voices if not v.done]
        return main, prev, speech

    # Rendering (thread audio) ------------------------------------------------
    def _input_blocks(self, frames: int) -> dict[str, np.ndarray]:
        """Blocco stereo (2, frames) di ogni ingresso aperto, letto una volta sola per dispositivo."""
        out: dict[str, np.ndarray] = {}
        if not self._input_map:
            return out
        raws = {key: src.reader.read(frames) for key, src in list(self._sources.items())}
        if self._duplex_in is not None:
            raws[DUPLEX] = self._duplex_in
        for sid, (key, cols) in list(self._input_map.items()):
            raw = raws.get(key)
            if raw is None or raw.shape[1] != frames or max(cols) >= raw.shape[0]:
                continue
            if len(cols) == 1:
                out[sid] = np.repeat(raw[cols[0]:cols[0] + 1], 2, axis=0).astype(np.float32, copy=False)
            else:
                out[sid] = raw[cols].astype(np.float32, copy=False)
        return out

    def render(self, frames: int, mic_block: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Calcola un blocco: restituisce (uscita verso Discord, uscita monitor).

        ``mic_block``: blocco del Microfono già pronto (prove); senza, gli ingressi si leggono
        dai dispositivi aperti.
        """
        sr = self.sample_rate
        blocks = {"mic": mic_block} if mic_block is not None else self._input_blocks(frames)
        inputs = list(self.inputs)
        soloing = any(s.solo for s in (*inputs, self.sounds, self.tts, self.player_strip))

        def silenced(strip: ChannelStrip) -> bool:
            return soloing and not strip.solo

        zero = lambda: np.zeros((2, frames), dtype=np.float32)
        ins = zero()
        to_bot = zero()
        hear = zero()
        for strip in inputs:
            out = strip.process(blocks.get(strip.id, zero()), sr, silenced(strip))
            ins += out
            if strip.to_bot:
                to_bot += out
            if strip.hear:
                hear += out
        voices, preview, speech = self._mix_voices(frames)
        snd = self.sounds.process(voices, sr, silenced(self.sounds))
        say = self.tts.process(speech, sr, silenced(self.tts))
        ply = self.player_strip.process(self.player.read(frames), sr, silenced(self.player_strip))
        if self.bot_streaming:
            self.bot_ring.write(snd + say + ply + to_bot)
        master = self.master.process(ins + snd + say + ply if self.sounds_to_master else ins, sr)

        mon_in = hear
        if self.monitor_hear_sounds:
            mon_in += snd
        if self.monitor_hear_tts:
            mon_in += say
        if self.monitor_hear_player:
            mon_in += ply
        mon_in += preview
        monitor = self.monitor.process(mon_in, sr)

        return np.clip(master, -1.0, 1.0), np.clip(monitor, -1.0, 1.0)

    # Callback PortAudio --------------------------------------------------------
    def _make_input_cb(self, ring: RingBuffer):
        def cb(indata, frames, time, status):
            if status:
                self.xruns += 1
            ring.write(indata.T.astype(np.float32, copy=False))
        return cb

    def _write_outputs(self, outdata: np.ndarray, master: np.ndarray, monitor: np.ndarray) -> None:
        outdata.fill(0)
        for what, cols in self._out_routes:
            _write_cols(outdata, master if what == "master" else monitor, cols)

    def _render_safe(self, frames: int):
        try:
            return self.render(frames)
        except Exception as exc:
            if not self._render_error_logged:
                print(f"[engine] errore nel rendering: {exc}", file=sys.stderr)
                self._render_error_logged = True
            return None

    def _clock_cb(self, outdata, frames, time, status):
        if status:
            self.xruns += 1
        res = self._render_safe(frames)
        if res is None:
            outdata.fill(0)
            return
        master, monitor = res
        self._write_outputs(outdata, master, monitor)
        if self._has_monitor_stream:
            self._monitor_ring.write(monitor)

    def _duplex_cb(self, indata, outdata, frames, time, status):
        """Stream full-duplex (ASIO): ingressi e uscite con lo stesso clock."""
        if status:
            self.xruns += 1
        self._duplex_in = indata.T
        try:
            res = self._render_safe(frames)
        finally:
            self._duplex_in = None
        if res is None:
            outdata.fill(0)
            return
        self._write_outputs(outdata, *res)

    def _monitor_cb(self, outdata, frames, time, status):
        if status:
            self.xruns += 1
        outdata.fill(0)
        _write_cols(outdata, self._monitor_reader.read(frames), self._monitor_cols)

    # Avvio / arresto ---------------------------------------------------------------
    def start(self, host_api: str, input_name: str | None = None, virtual_name: str = "",
              monitor_name: str = "", virtual_channel: int = 0, monitor_channel: int = 0) -> EngineStatus:
        """Apre i dispositivi. ``input_name`` (se dato) diventa il dispositivo del Microfono;
        gli altri ingressi usano il proprio. ``*_channel``: primo canale della coppia in uscita
        (0 = canali 1-2, 2 = canali 3-4…)."""
        self.stop()
        if input_name is not None:
            self.mic.device = input_name
        warnings: list[str] = []
        try:
            sd = devices.sd()
        except RuntimeError as exc:
            self.status = EngineStatus(False, str(exc))
            return self.status

        asio = devices.is_asio(host_api)
        virt = devices.find(virtual_name, host_api, "output")
        mon = devices.find(monitor_name, host_api, "output")
        if virtual_name and not virt:
            warnings.append(f"Uscita virtuale non trovata: {virtual_name}")
        if monitor_name and not mon:
            warnings.append(f"Uscita monitor non trovata: {monitor_name}")

        clock_dev = virt or mon
        if clock_dev is None:
            self.status = EngineStatus(False, "Scegli almeno un'uscita (virtuale o monitor).", warnings)
            return self.status

        def pair(dev, first: int, label: str) -> list[int]:
            first = max(0, int(first or 0))
            if first >= dev.max_out:
                warnings.append(f"{label}: il dispositivo ha solo {dev.max_out} canali, uso i canali 1-2.")
                first = 0
            return [first, first + 1] if first + 1 < dev.max_out else [first]

        routes: list[tuple[str, list[int]]] = []
        mon_cols: list[int] | None = None
        if virt:
            routes.append(("master", pair(virt, virtual_channel, "Uscita verso Discord")))
        if mon:
            cols = pair(mon, monitor_channel, "Monitor")
            if virt and mon.index == virt.index:
                if set(cols) & set(routes[0][1]):
                    warnings.append("Uscita virtuale e monitor coincidono: uso solo l'uscita virtuale.")
                else:
                    routes.append(("monitor", cols))       # stessa scheda, altri canali: stesso stream
            elif virt and asio:
                warnings.append(f"Con ASIO si usa un solo dispositivo: monitor «{mon.name}» ignorato. "
                                f"Scegli per le cuffie altri canali di «{virt.name}».")
            elif virt:
                mon_cols = cols                            # altra scheda: stream separato
            else:
                routes.append(("monitor", cols))

        # Ingressi: dispositivo e canali di ciascuno
        wanted: dict[int, tuple] = {}                      # indice dispositivo → (Device, [ingressi])
        for strip in self.inputs:
            if not strip.device:
                continue
            dev = devices.find(strip.device, host_api, "input")
            if dev is None:
                warnings.append(f"Ingresso non trovato: {strip.device} ({strip.name})")
                continue
            if asio and dev.index != clock_dev.index:
                warnings.append(f"Con ASIO si usa un solo dispositivo: «{strip.name}» ({dev.name}) ignorato.")
                continue
            if strip.channel >= dev.max_in:
                warnings.append(f"{strip.name}: «{dev.name}» ha solo {dev.max_in} canali d'ingresso.")
                continue
            wanted.setdefault(dev.index, (dev, []))[1].append(strip)

        self._sources = {}
        self._input_map = {}
        self._out_routes = []
        self._monitor_cols = mon_cols or [0, 1]
        self._has_monitor_stream = mon_cols is not None
        self._monitor_ring.clear()
        self._monitor_reader.reset()
        extra = devices.wasapi_extra(host_api)
        common = dict(samplerate=self.sample_rate, blocksize=self.block_size, dtype="float32", latency="low")

        def strip_cols(strip: InputStrip, avail: int) -> list[int]:
            c = strip.channel
            return [c] if strip.mono or c + 1 >= avail else [c, c + 1]

        opened: list[str] = []
        try:
            if asio:
                out_sel = sorted({c for _, cols in routes for c in cols})
                self._out_routes = [(w, [out_sel.index(c) for c in cols]) for w, cols in routes]
                in_strips = wanted.get(clock_dev.index, (None, []))[1]
                in_sel = sorted({c for s in in_strips for c in strip_cols(s, clock_dev.max_in)})
                for s in in_strips:
                    self._input_map[s.id] = (DUPLEX, [in_sel.index(c) for c in strip_cols(s, clock_dev.max_in)])
                    opened.append(f"{s.name}: {s.channel_label}")
                asio_out = sd.AsioSettings(channel_selectors=out_sel)
                if in_sel:
                    asio_in = sd.AsioSettings(channel_selectors=in_sel)
                    stream = sd.Stream(device=(clock_dev.index, clock_dev.index), channels=(len(in_sel), len(out_sel)),
                                       callback=self._duplex_cb, extra_settings=(asio_in, asio_out), **common)
                else:
                    stream = sd.OutputStream(device=clock_dev.index, channels=len(out_sel),
                                             callback=self._clock_cb, extra_settings=asio_out, **common)
                self._streams.append(stream)
            else:
                for idx, (dev, strips) in wanted.items():
                    need = max(max(strip_cols(s, dev.max_in)) + 1 for s in strips)
                    nch = max(need, min(2, dev.max_in))
                    ring = RingBuffer(nch, self.sample_rate, max_latency=self.block_size * RING_MAX_BLOCKS)
                    src = _InputSource(ring, DriftReader(ring, self.block_size * RING_TARGET_BLOCKS))
                    key = str(idx)
                    self._sources[key] = src
                    for s in strips:
                        self._input_map[s.id] = (key, strip_cols(s, nch))
                    self._streams.append(sd.InputStream(device=idx, channels=nch, callback=self._make_input_cb(ring),
                                                        extra_settings=extra, **common))
                    opened.append(dev.name)
                nout = min(clock_dev.max_out, max(max(cols) + 1 for _, cols in routes))
                self._out_routes = routes
                self._streams.append(sd.OutputStream(device=clock_dev.index, channels=max(nout, min(2, clock_dev.max_out)),
                                                     callback=self._clock_cb, extra_settings=extra, **common))
                if self._has_monitor_stream:
                    nmon = max(max(mon_cols) + 1, min(2, mon.max_out))
                    self._streams.append(sd.OutputStream(device=mon.index, channels=nmon,
                                                         callback=self._monitor_cb, extra_settings=extra, **common))
            for s in self._streams:
                s.start()
        except Exception as exc:
            self.stop()
            self.status = EngineStatus(False, f"Errore apertura audio: {exc}", warnings)
            return self.status

        def where(dev, cols) -> str:
            if not asio and dev.max_out <= 2:
                return dev.name
            return f"{dev.name} [{'-'.join(str(c + 1) for c in cols)}]"

        parts = []
        if asio:
            parts.append(f"ASIO: {clock_dev.name}")
            if opened:
                parts.append("In: " + ", ".join(opened))
            for w, cols in routes:
                parts.append(f"{'Discord' if w == 'master' else 'Cuffie'}: {'-'.join(str(c + 1) for c in cols)}")
        else:
            if opened:
                parts.append("In: " + ", ".join(opened))
            for w, cols in routes:
                parts.append(f"{'Discord' if w == 'master' else 'Cuffie'}: {where(clock_dev, cols)}")
            if self._has_monitor_stream:
                parts.append(f"Cuffie: {where(mon, mon_cols)}")
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
        self._sources = {}
        self._input_map = {}
        self._duplex_in = None
        self.status = EngineStatus()

    def set_format(self, sample_rate: int, block_size: int) -> None:
        """Da chiamare ad audio fermo."""
        self.sample_rate = int(sample_rate)
        if self.player.sample_rate != self.sample_rate:
            self.player.stop()
            self.player.sample_rate = self.sample_rate
        changed = int(block_size) != self.block_size or self._monitor_ring.capacity != self.sample_rate
        self.block_size = int(block_size)
        # stessi oggetti: il bot Discord tiene un riferimento al proprio buffer
        self._monitor_ring.reconfigure(self.sample_rate, self.block_size * RING_MAX_BLOCKS)
        self._monitor_reader.target = self.block_size * RING_TARGET_BLOCKS
        self._monitor_reader.reset()
        self.bot_ring.reconfigure(self.sample_rate, int(self.sample_rate * 0.12))
        if not changed:
            return
        for strip in self.strips:
            for slot in strip.inserts:
                try:
                    slot.plugin.reset()
                except Exception:
                    pass

    # Salvataggio -------------------------------------------------------------------
    def to_dict(self) -> dict:
        d = {s.id: s.to_dict() for s in self.strips if s not in self.inputs[1:]}
        d["inputs"] = [s.to_dict() for s in self.inputs[1:]]     # ingressi aggiunti, in ordine
        d["monitor"]["hear_sounds"] = self.monitor_hear_sounds
        d["monitor"]["hear_mic"] = self.monitor_hear_mic
        d["monitor"]["hear_player"] = self.monitor_hear_player
        d["monitor"]["hear_tts"] = self.monitor_hear_tts
        return d

    def load_dict(self, d: dict) -> list[str]:
        errors: list[str] = []
        extra: list[InputStrip] = []
        for item in d.get("inputs", [])[:MAX_INPUTS - 1]:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("id", ""))
            if not sid.startswith("in") or sid in {s.id for s in extra}:
                continue
            strip = InputStrip(sid, f"Ingresso {sid[2:]}")
            errors += strip.load_dict(item)
            extra.append(strip)
        self.inputs = [self.mic, *extra]
        for s in self.strips:
            if s.id in d and s not in extra:
                errors += s.load_dict(d[s.id])
        mon = d.get("monitor", {})
        self.monitor_hear_sounds = bool(mon.get("hear_sounds", True))
        self.monitor_hear_mic = bool(mon.get("hear_mic", d.get("mic", {}).get("hear", False)))
        self.monitor_hear_player = bool(mon.get("hear_player", True))
        self.monitor_hear_tts = bool(mon.get("hear_tts", True))
        return errors


def _write_cols(outdata: np.ndarray, block: np.ndarray, cols: list[int]) -> None:
    """Scrive il blocco stereo nelle colonne ``cols`` (una sola = mono)."""
    ch = outdata.shape[1]
    cols = [c for c in cols if c < ch]
    if not cols:
        return
    if len(cols) == 1:
        outdata[:, cols[0]] += block.mean(axis=0)
    else:
        outdata[:, cols[0]] += block[0]
        outdata[:, cols[1]] += block[1]
