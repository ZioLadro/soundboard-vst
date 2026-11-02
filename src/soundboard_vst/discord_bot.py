"""Bot Discord integrato: entra nel canale vocale dell'utente e trasmette i suoni della soundboard.

Il bot gira con discord.py in un thread separato con il suo event loop asyncio.
L'audio arriva dal motore (uscita del canale Soundboard del mixer) tramite un ring buffer:
il bot trasmette solo mentre ci sono suoni, così su Discord risulta «parlante» solo quando serve.
"""

from __future__ import annotations

import asyncio
import base64
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .audio.ringbuffer import RingBuffer

DISCORD_SR = 48000
FRAME = 960                          # 20 ms a 48 kHz
FRAME_BYTES = FRAME * 2 * 2          # stereo, int16
IDLE_FRAMES = 25                     # 0,5 s di silenzio prima di smettere di trasmettere
INVITE_PERMISSIONS = (1 << 20) | (1 << 21)   # Connect + Speak

_discord = None
_error: str | None = None


def _lib():
    global _discord, _error
    if _discord is None and _error is None:
        try:
            import discord

            _discord = discord
        except Exception as exc:
            _error = str(exc) or exc.__class__.__name__
    return _discord


def available() -> bool:
    return _lib() is not None


def unavailable_reason() -> str:
    _lib()
    return _error or ""


def application_id_from_token(token: str) -> int | None:
    """La prima parte del token di un bot è l'ID del bot (che coincide con l'ID dell'applicazione)."""
    try:
        part = token.strip().split(".")[0]
        part += "=" * (-len(part) % 4)
        return int(base64.urlsafe_b64decode(part).decode())
    except Exception:
        return None


def invite_url(application_id: int) -> str:
    return ("https://discord.com/oauth2/authorize"
            f"?client_id={application_id}&scope=bot&permissions={INVITE_PERMISSIONS}")


def find_user_channel(guilds, user_id: int):
    """Canale vocale (o stage) in cui si trova l'utente, cercando in tutti i server del bot."""
    for guild in guilds:
        channels = list(getattr(guild, "voice_channels", [])) + list(getattr(guild, "stage_channels", []))
        for ch in channels:
            if user_id in getattr(ch, "voice_states", {}):
                return ch
    return None


def to_pcm(block: np.ndarray) -> bytes:
    """(2, n) float32 → PCM s16le stereo interleaved."""
    pcm = np.clip(block.T, -1.0, 1.0) * 32767.0
    return pcm.astype("<i2").tobytes()


class SoundboardSource:
    """Sorgente audio per discord.py (stessa interfaccia di ``discord.AudioSource``).

    Il lettore di discord.py resta sempre aperto finché il bot è in canale: riavviarlo a ogni suono
    costa centinaia di millisecondi. Quando non suona niente:
    - in modalità continua trasmette silenzio (latenza minima, il bot può risultare sempre «attivo»);
    - altrimenti, dopo mezzo secondo di silenzio, chiama ``on_idle`` (che mette in pausa il lettore).
    All'inizio di ogni suono scarta l'audio accumulato nel buffer, così il ritardo resta minimo.
    """

    KEEP = FRAME + FRAME // 2          # audio lasciato nel buffer dopo la risincronizzazione (30 ms)

    def __init__(self, ring: RingBuffer, sample_rate, has_sounds: Callable[[], bool],
                 is_continuous: Callable[[], bool] = lambda: False,
                 on_idle: Callable[[], None] = lambda: None,
                 on_latency: Callable[[float], None] = lambda ms: None):
        self.ring = ring
        self._sample_rate = sample_rate      # int o funzione (segue i cambi di frequenza del motore)
        self.has_sounds = has_sounds
        self.is_continuous = is_continuous
        self.on_idle = on_idle
        self.on_latency = on_latency
        self._idle = 0
        self._resync = True
        self._pending: float | None = None
        self.finished = False

    @property
    def sample_rate(self) -> int:
        return int(self._sample_rate() if callable(self._sample_rate) else self._sample_rate)

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        self.finished = True

    def mark(self, t0: float | None = None) -> None:
        """Un suono è appena partito: risincronizza e misura quando arriva il primo audio."""
        self._pending = t0
        self._resync = True
        self._idle = 0

    def _read_block(self) -> np.ndarray:
        if self.sample_rate == DISCORD_SR:
            return self.ring.read(FRAME)
        n = max(1, round(FRAME * self.sample_rate / DISCORD_SR))
        src = self.ring.read(n)
        x_old = np.linspace(0.0, 1.0, n, endpoint=False)
        x_new = np.linspace(0.0, 1.0, FRAME, endpoint=False)
        return np.stack([np.interp(x_new, x_old, src[c]) for c in range(2)]).astype(np.float32)

    def read(self) -> bytes:
        if self.finished:
            return b""
        if self._resync:
            keep = round(self.KEEP * self.sample_rate / DISCORD_SR)
            excess = len(self.ring) - keep
            if excess > 0:
                self.ring.read(excess)       # scarta il ritardo accumulato
            self._resync = False
        block = self._read_block()
        loud = np.abs(block).max(initial=0.0) >= 1e-4
        if loud and self._pending is not None:
            self.on_latency((time.perf_counter() - self._pending) * 1000.0)
            self._pending = None
        if not loud and not self.has_sounds() and not self.is_continuous():
            self._idle += 1
            if self._idle >= IDLE_FRAMES:
                self._idle = 0
                self.on_idle()
        else:
            self._idle = 0
        return to_pcm(block)


@dataclass
class BotStatus:
    online: bool = False
    channel: str = ""          # "Server › canale" se in voce
    message: str = "Bot spento"
    conflict: bool = False     # lo stesso bot è usato da un'altra soundboard (token condiviso)

CONFLICT_MESSAGE = ("Il bot è già nel canale «{channel}» per un'altra soundboard. Un bot può stare in un "
                    "solo canale alla volta: se più persone usano la soundboard, ognuno deve creare il "
                    "proprio bot con il proprio token.")


def used_elsewhere(guild) -> str | None:
    """Se il bot è in voce in questo server ma non tramite questa soundboard, restituisce il canale."""
    me = getattr(guild, "me", None)
    voice = getattr(me, "voice", None) if me is not None else None
    channel = getattr(voice, "channel", None) if voice is not None else None
    if channel is not None and getattr(guild, "voice_client", None) is None:
        return channel.name
    return None


class DiscordBot:
    """Gestisce il client discord.py in un thread; i metodi pubblici si chiamano dal thread della GUI.

    ``on_status(BotStatus)`` viene chiamato dal thread del bot: la GUI deve rimbalzarlo
    sul proprio thread (es. con un segnale Qt).
    """

    def __init__(self, engine, on_status: Callable[[BotStatus], None]):
        self.engine = engine
        self.on_status = on_status
        self.owner_id: int = 0
        self.follow = True
        self.application_id: int | None = None
        self._client = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._source: SoundboardSource | None = None
        self._vc = None
        self.continuous = True          # trasmissione continua: latenza minima
        self.last_latency_ms: float | None = None
        self.status = BotStatus()

    # Stato ------------------------------------------------------------------------
    def _set_status(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self.status, k, v)
        self.on_status(BotStatus(**self.status.__dict__))

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # Avvio / arresto ------------------------------------------------------------------
    def start(self, token: str, owner_id: int, follow: bool = True) -> None:
        discord = _lib()
        if discord is None:
            self._set_status(online=False, channel="", message=f"discord.py non disponibile: {_error}")
            return
        if self.running:
            self.stop()
        self.owner_id, self.follow = owner_id, follow
        self.application_id = application_id_from_token(token)
        self._set_status(online=False, channel="", message="Connessione a Discord…")

        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        client = discord.Client(intents=intents)
        bot = self

        @client.event
        async def on_ready():
            bot.application_id = client.application_id or bot.application_id
            bot._set_status(online=True, message=f"Online come {client.user}")
            if bot.follow:
                await bot._join_owner()

        @client.event
        async def on_voice_state_update(member, before, after):
            if member.id == client.user.id:
                guild = (after.channel or before.channel).guild
                if guild.voice_client is None:
                    # il bot si è mosso ma non per noi: è un'altra soundboard con lo stesso token
                    if after.channel is not None:
                        bot._stop_streaming()
                        bot._set_status(channel="", conflict=True,
                                        message=CONFLICT_MESSAGE.format(channel=after.channel.name))
                    return
                if after.channel is None:
                    bot._stop_streaming()
                    bot._set_status(channel="", message=f"Online come {client.user}")
                else:
                    bot._set_status(channel=f"{after.channel.guild.name} › {after.channel.name}",
                                    conflict=False, message=f"Nel canale {after.channel.name}")
                    if bot.continuous and before.channel is None:
                        await asyncio.sleep(0.5)          # attende che la connessione voce sia pronta
                        await bot._start_playing()
                return
            if member.id != bot.owner_id or not bot.follow:
                return
            if after.channel is not None and after.channel != before.channel:
                await bot._connect(after.channel)
            elif after.channel is None and before.channel is not None:
                vc = before.channel.guild.voice_client
                if vc is not None:
                    await vc.disconnect(force=False)

        self._client = client
        self._loop = asyncio.new_event_loop()

        async def runner():
            async with client:          # chiude sempre la sessione, anche dopo un errore
                await client.start(token)

        def run():
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(runner())
            except discord.LoginFailure:
                self._set_status(online=False, channel="", message="Token non valido")
            except discord.PrivilegedIntentsRequired:
                self._set_status(online=False, channel="", message="Intent mancanti nel portale sviluppatori")
            except Exception as exc:
                self._set_status(online=False, channel="", message=f"Errore del bot: {exc}")
            else:
                self._set_status(online=False, channel="", message="Bot spento")
            finally:
                self.engine.bot_streaming = False
                try:
                    self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                finally:
                    self._loop.close()

        self._thread = threading.Thread(target=run, name="discord-bot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._client is not None and self._loop is not None and self.running:
            fut = asyncio.run_coroutine_threadsafe(self._client.close(), self._loop)
            try:
                fut.result(timeout=5)
            except Exception:
                pass
            self._thread.join(timeout=5)
        self.engine.bot_streaming = False
        self._client = None
        self._thread = None

    def _submit(self, coro) -> None:
        if self._loop is not None and self.running:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        else:
            coro.close()

    # Canali vocali -----------------------------------------------------------------
    def join_owner(self) -> None:
        self._submit(self._join_owner())

    def leave(self) -> None:
        self._submit(self._leave())

    async def _join_owner(self) -> None:
        if not self._client or not self.owner_id:
            self._set_status(message="Imposta il tuo ID utente Discord nelle impostazioni")
            return
        ch = find_user_channel(self._client.guilds, self.owner_id)
        if ch is None:
            self._set_status(message="Non sei in un canale vocale di un server in cui c'è il bot")
            return
        await self._connect(ch)

    async def _connect(self, channel) -> None:
        busy = used_elsewhere(channel.guild)
        if busy is not None:
            self._set_status(conflict=True, message=CONFLICT_MESSAGE.format(channel=busy))
            return
        try:
            vc = channel.guild.voice_client
            if vc is not None and vc.is_connected():
                if vc.channel != channel:
                    await vc.move_to(channel)
            else:
                await channel.connect(self_deaf=True, timeout=20)
        except Exception as exc:
            self._set_status(message=f"Impossibile entrare in {channel.name}: {exc}")

    async def _leave(self) -> None:
        for vc in list(self._client.voice_clients if self._client else []):
            await vc.disconnect(force=False)

    # Trasmissione ------------------------------------------------------------------------
    def notify_sound(self) -> None:
        """Chiamato quando parte un suono: avvia o riprende la trasmissione se il bot è in un canale."""
        if not self.running or not self.status.channel:
            return
        t0 = time.perf_counter()
        source, vc = self._source, self._vc
        if source is not None and not source.finished and vc is not None:
            source.mark(t0)
            if not self.engine.bot_streaming:
                self.engine.bot_streaming = True
                self._call(vc.resume)            # il lettore era in pausa: riparte subito
            return
        self.engine.bot_ring.clear()
        self.engine.bot_streaming = True
        self._submit(self._start_playing(t0))

    def _call(self, fn) -> None:
        if self._loop is not None and self.running:
            self._loop.call_soon_threadsafe(fn)

    def _on_idle(self) -> None:
        # chiamato dal thread del lettore: pausa (manda 5 frame di silenzio e smette di «parlare»)
        self.engine.bot_streaming = False
        vc = self._vc
        if vc is not None:
            vc.pause()

    def _on_latency(self, ms: float) -> None:
        self.last_latency_ms = ms

    async def _start_playing(self, t0: float | None = None) -> None:
        vc = next((v for v in (self._client.voice_clients if self._client else []) if v.is_connected()), None)
        if vc is None:
            self.engine.bot_streaming = False
            return
        if vc.is_playing() or vc.is_paused():
            self._vc = vc
            return
        source = SoundboardSource(self.engine.bot_ring, lambda: self.engine.sample_rate, self.engine.has_active_sounds,
                                  is_continuous=lambda: self.continuous, on_idle=self._on_idle,
                                  on_latency=self._on_latency)
        source.mark(t0)
        self._source, self._vc = source, vc
        self.engine.bot_streaming = True

        def after(err):
            if self._source is source:
                self.engine.bot_streaming = False
                self._source = None
            if err:
                self._set_status(message=f"Errore audio del bot: {err}")

        try:
            # «lowdelay» riduce il ritardo dell'encoder Opus; poca perdita attesa = meno ridondanza
            vc.play(_wrap(source), after=after, application="lowdelay", bitrate=128,
                    expected_packet_loss=0.05)
        except Exception as exc:
            self.engine.bot_streaming = False
            self._source = None
            self._set_status(message=f"Errore audio del bot: {exc}")

    def _stop_streaming(self) -> None:
        self.engine.bot_streaming = False
        if self._source is not None:
            self._source.finished = True
        self._source, self._vc = None, None


def _wrap(source: SoundboardSource):
    """Adatta la sorgente alla classe base di discord.py (richiesta da ``VoiceClient.play``)."""
    discord = _lib()

    class _Source(discord.AudioSource):
        def read(self) -> bytes:
            return source.read()

        def is_opus(self) -> bool:
            return False

        def cleanup(self) -> None:
            source.cleanup()

    return _Source()
