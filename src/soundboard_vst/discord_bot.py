"""Bot Discord integrato: entra nel canale vocale dell'utente e trasmette i suoni della soundboard.

Il bot gira con discord.py in un thread separato con il suo event loop asyncio.
L'audio arriva dal motore (uscita del canale Soundboard del mixer) tramite un ring buffer:
il bot trasmette solo mentre ci sono suoni, così su Discord risulta «parlante» solo quando serve.

I comandi slash e la pulsantiera sono in ``discord_commands``.
"""

from __future__ import annotations

import asyncio
import base64
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import eventlog
from .audio.ringbuffer import DriftReader, RingBuffer

DISCORD_SR = 48000
FRAME = 960                          # 20 ms a 48 kHz
FRAME_BYTES = FRAME * 2 * 2          # stereo, int16
IDLE_FRAMES = 25                     # 0,5 s di silenzio prima di smettere di trasmettere
# Visualizza canale + Invia messaggi (pulsantiera nel canale dedicato) + Connetti + Parla
INVITE_PERMISSIONS = (1 << 10) | (1 << 11) | (1 << 20) | (1 << 21)

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


DAVE_INCOMPATIBLE = ("La libreria della crittografia vocale (davey) installata è più recente di quella supportata "
                     "da discord.py: il bot sembrerebbe parlare ma nessuno lo sentirebbe. Aggiorna la soundboard "
                     "o, da sorgente, esegui: pip install \"davey<0.2\".")


def _code_names(obj, seen=None) -> set[str]:
    """Nomi usati dal codice di un modulo o di una classe (anche nelle funzioni annidate)."""
    seen = set() if seen is None else seen
    names: set[str] = set()
    stack = []
    for value in vars(obj).values():
        func = getattr(value, "__func__", value)
        if hasattr(func, "__code__"):
            stack.append(func.__code__)
        elif isinstance(value, type) and value.__module__ == getattr(obj, "__name__", None) and value not in seen:
            seen.add(value)
            names |= _code_names(value, seen)
    while stack:
        code = stack.pop()
        names.update(code.co_names)
        stack.extend(c for c in code.co_consts if hasattr(c, "co_names"))
    return names


def dave_compatible(davey_mod=None, gateway_mod=None) -> bool:
    """davey 0.2 vuole che chi lo usa chiami ``prepare_transition``/``execute_transition`` dopo ogni
    commit: se discord.py non lo fa, la voce è cifrata senza chiave valida e il bot è muto."""
    try:
        if davey_mod is None:
            import davey as davey_mod
        if gateway_mod is None:
            from discord import gateway as gateway_mod
    except Exception:
        return True                       # senza davey/discord.py il problema è un altro
    if not hasattr(davey_mod.DaveSession, "prepare_transition"):
        return True                       # davey 0.1.x: il comportamento che discord.py si aspetta
    return "prepare_transition" in _code_names(gateway_mod)


# Stato del bot («Ascolta …») --------------------------------------------------------------------
PRESENCE_POLL_S = 2.0           # ogni quanto si guarda cosa suona il player
PRESENCE_MIN_INTERVAL_S = 15.0  # Discord limita i cambi di stato: al massimo uno ogni 15 s
PRESENCE_MAX = 128              # lunghezza massima del testo dello stato


def presence_text(state: dict) -> str | None:
    """Cosa mostrare nello stato del bot: il brano del player se sta suonando, altrimenti niente."""
    p = state.get("player") or {}
    if p.get("state") not in ("playing", "loading"):
        return None
    title = " ".join(str(p.get("title") or "").split())
    if not title:
        return None
    return title if len(title) <= PRESENCE_MAX else title[:PRESENCE_MAX - 1] + "…"


# Suoni di entrata e uscita -----------------------------------------------------------------------
GREETING_EVENTS = ("join", "leave", "mute", "unmute")   # entra, esce, si muta, si smuta


def default_greetings() -> dict:
    return {"enabled": True, "cooldown": 30, "users": {}, "default": {e: "" for e in GREETING_EVENTS},
            "announce": {"enabled": False, "join": "{nome} è entrato", "leave": "{nome} è uscito",
                         "mute": "", "unmute": ""}}


def normalize_greetings(g: dict | None) -> dict:
    out = default_greetings()
    if not isinstance(g, dict):
        return out
    out["enabled"] = bool(g.get("enabled", True))
    try:
        out["cooldown"] = max(0, min(3600, int(g.get("cooldown", 30))))
    except (TypeError, ValueError):
        pass
    for uid, u in (g.get("users") or {}).items():
        if isinstance(u, dict) and str(uid).strip():
            out["users"][str(uid)] = {"name": str(u.get("name", "")),
                                      **{e: str(u.get(e) or "") for e in GREETING_EVENTS}}
    d = g.get("default") or {}
    out["default"] = {e: str(d.get(e) or "") for e in GREETING_EVENTS}
    a = g.get("announce") or {}
    ann = {"enabled": bool(a.get("enabled", False))}
    for e in GREETING_EVENTS:
        # entrata/uscita hanno un testo predefinito; muto/smuto restano vuoti finché non li scrivi
        ann[e] = str(a[e]) if isinstance(a.get(e), str) else out["announce"][e]
        if e in ("join", "leave") and not ann[e]:
            ann[e] = out["announce"][e]
    out["announce"] = ann
    return out


def _muted(state) -> bool:
    """Microfono spento (da sé o dal server); chi si silenzia le cuffie è anche muto."""
    return any(bool(getattr(state, a, False)) for a in ("self_mute", "mute", "self_deaf", "deaf"))


def greeting_action(greetings: dict, user_id: int, name: str, event: str) -> dict | None:
    """Cosa fare quando un utente entra (``join``) o esce (``leave``) dal canale del bot:
    il suo suono, altrimenti quello per tutti, altrimenti l'annuncio con la sintesi vocale."""
    if not greetings.get("enabled", True):
        return None
    key = (greetings.get("users", {}).get(str(user_id)) or {}).get(event) or \
        (greetings.get("default") or {}).get(event)
    if key:
        return {"cmd": "sound", "key": key}
    ann = greetings.get("announce") or {}
    if ann.get("enabled") and ann.get(event):
        return {"cmd": "say", "text": ann[event].replace("{nome}", name)}
    return None


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
            f"?client_id={application_id}&scope=bot+applications.commands&permissions={INVITE_PERMISSIONS}")


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

    Il motore scrive con il clock della scheda audio, discord.py legge con quello del PC: un
    ``DriftReader`` tiene il buffer intorno a ``KEEP`` (e converte la frequenza se non è 48 kHz),
    così la musica lunga del player non fa scatti né buchi.
    """

    KEEP = FRAME * 2                   # audio tenuto nel buffer (40 ms a 48 kHz)
    QUIET_FRAMES = 3                   # si risincronizza solo dopo almeno 60 ms di silenzio

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
        self._quiet = self.QUIET_FRAMES          # frame silenziosi di fila (all'inizio: silenzio)
        self._reader = DriftReader(ring, self._keep(), self.sample_rate / DISCORD_SR)

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

    def _keep(self) -> int:
        return round(self.KEEP * self.sample_rate / DISCORD_SR)       # in campioni del motore

    def read(self) -> bytes:
        if self.finished:
            return b""
        reader = self._reader
        if self._resync:
            keep = self._keep()
            reader.target = keep
            reader.ratio = self.sample_rate / DISCORD_SR
            # se sta già suonando qualcosa (es. la musica del player) non si taglia niente: il buffer
            # è già al livello giusto e scartarne un pezzo farebbe uno scatto in mezzo alla musica
            if self._quiet >= self.QUIET_FRAMES:
                excess = len(self.ring) - keep
                if excess > 0:
                    self.ring.read(excess)       # scarta il ritardo accumulato (era silenzio)
                reader.reset()
            self._resync = False
        block = reader.read(FRAME)
        loud = np.abs(block).max(initial=0.0) >= 1e-4
        self._quiet = 0 if loud else self._quiet + 1
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
    sul proprio thread (es. con un segnale Qt). Lo stesso vale per i comandi da Discord:
    ``send_command(dict)`` (stesso formato del controllo remoto) e ``on_board(id, messaggi)``,
    che chiede alla GUI di salvare il canale dedicato. ``get_state()`` restituisce l'istantanea
    dello stato preparata dalla GUI.
    """

    def __init__(self, engine, on_status: Callable[[BotStatus], None],
                 get_state: Callable[[], dict] = dict,
                 send_command: Callable[[dict], None] = lambda c: None,
                 on_board: Callable[[int, list], None] = lambda cid, ids: None):
        self.engine = engine
        self.on_status = on_status
        self.get_state = get_state
        self.send_command = send_command
        self.on_board = on_board
        self.commands_cfg: dict = {"enabled": True, "sounds_access": "everyone",
                                   "control_access": "owner", "role": ""}
        self.board_channel: int = 0        # canale dedicato alla pulsantiera (0 = nessuno)
        self.board_messages: list[int] = []
        self.board_info: dict = {}          # ultimo aggiornamento del canale dedicato: {"time", "error", "channel"}
        self.show_presence = True           # stato del bot su Discord: «Ascolta <brano del player>»
        self.permissions: dict = {}         # vedi discord_commands.normalize_permissions
        self.greetings: dict = default_greetings()
        self.known_users: dict[str, str] = {}   # ID -> nome, di chi il bot ha visto (comandi, canali vocali)
        self.known_roles: list[dict] = []       # ruoli dei server: {"id", "name", "guild"}
        self._greeted: dict[tuple, float] = {}
        self._presence_task = None
        self._presence_dirty = True         # da rimandare (es. dopo una riconnessione)
        self._commands = None
        self.owner_id: int = 0
        self.follow = True
        self.application_id: int | None = None
        self._client = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._source: SoundboardSource | None = None
        self._vc = None
        self.dave_ok = True             # davey compatibile con discord.py (vedi dave_compatible)
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
    def set_board(self, channel_id: int, message_ids: list[int]) -> None:
        """Canale dedicato e messaggi della pulsantiera (dal thread del bot): li salva anche la GUI."""
        self.board_channel, self.board_messages = int(channel_id or 0), [int(m) for m in message_ids]
        self.on_board(self.board_channel, list(self.board_messages))

    def start(self, token: str, owner_id: int, follow: bool = True) -> None:
        discord = _lib()
        if discord is None:
            self._set_status(online=False, channel="", message=f"discord.py non disponibile: {_error}")
            return
        if self.running:
            self.stop()
        self.owner_id, self.follow = owner_id, follow
        self.application_id = application_id_from_token(token)
        self.dave_ok = dave_compatible()
        self._set_status(online=False, channel="", message="Connessione a Discord…"
                         if self.dave_ok else DAVE_INCOMPATIBLE)

        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        client = discord.Client(intents=intents)
        bot = self
        from .discord_commands import Commands

        self._commands = commands = Commands(discord, client, self)
        synced = set()

        @client.event
        async def on_ready():
            bot.application_id = client.application_id or bot.application_id
            bot._collect_directory()
            bot._set_status(online=True, message=f"Online come {client.user}" if bot.dave_ok
                            else DAVE_INCOMPATIBLE)
            if bot.follow:
                await bot._join_owner()
            # on_ready si ripete dopo ogni riconnessione: i comandi si registrano una volta sola
            todo = [g for g in client.guilds if g.id not in synced]
            synced.update(g.id for g in todo)
            await commands.sync(todo)
            commands.start_board_loop()
            bot._presence_dirty = True       # dopo una nuova sessione lo stato va rimandato
            bot._start_presence_loop()

        @client.event
        async def on_resumed():
            commands.start_board_loop()      # se dopo un'interruzione si fosse fermato, riparte
            bot._start_presence_loop()

        @client.event
        async def on_guild_role_create(role):
            bot._collect_directory()

        @client.event
        async def on_guild_role_update(before, after):
            bot._collect_directory()

        @client.event
        async def on_guild_role_delete(role):
            bot._collect_directory()

        @client.event
        async def on_guild_join(guild):
            bot._collect_directory()
            synced.add(guild.id)
            await commands.sync([guild])

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
                    if (bot.continuous or bot.engine.mic_to_bot) and before.channel is None:
                        await asyncio.sleep(0.5)          # attende che la connessione voce sia pronta
                        await bot._start_playing()
                return
            bot._on_member_voice(member, before, after)
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
        self._commands = None
        self._thread = None

    def _submit(self, coro) -> None:
        if self._loop is not None and self.running:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        else:
            coro.close()

    # Utenti, ruoli, entrate e uscite ------------------------------------------------------------
    def remember_user(self, user) -> None:
        if user is None or getattr(user, "bot", False):
            return
        name = getattr(user, "display_name", None) or getattr(user, "name", None)
        if name:
            self.known_users[str(user.id)] = str(name)

    def _collect_directory(self) -> None:
        """Ruoli dei server e utenti già nei canali vocali, per scegliere i permessi nella finestra."""
        client = self._client
        if client is None:
            return
        roles = []
        for guild in client.guilds:
            for r in getattr(guild, "roles", []):
                if r.id == guild.id or getattr(r, "managed", False):
                    continue                       # @everyone e ruoli dei bot
                roles.append({"id": str(r.id), "name": r.name, "guild": guild.name})
            for ch in list(getattr(guild, "voice_channels", [])) + list(getattr(guild, "stage_channels", [])):
                for m in getattr(ch, "members", []):
                    self.remember_user(m)
        self.known_roles = roles

    def _on_member_voice(self, member, before, after) -> None:
        """Un altro utente entra o esce dal canale in cui è il bot: registro e suono di entrata/uscita."""
        if getattr(member, "bot", False):
            return
        self.remember_user(member)
        vc = getattr(member.guild, "voice_client", None)
        channel = getattr(vc, "channel", None) if vc is not None and vc.is_connected() else None
        if channel is None:
            return
        name = member.display_name
        if before.channel == after.channel:
            if after.channel != channel or _muted(before) == _muted(after):
                return                              # altro canale, o è cambiato altro (video, stream…)
            event = "mute" if _muted(after) else "unmute"
            eventlog.log(eventlog.DISCORD, f"{name} {'si è mutato' if event == 'mute' else 'ha riattivato il microfono'}"
                         f" in #{channel.name}", "Bot")
        elif after.channel == channel:
            event = "join"
            eventlog.log(eventlog.DISCORD, f"{name} è entrato in #{channel.name}", "Bot")
        elif before.channel == channel:
            event = "leave"
            eventlog.log(eventlog.DISCORD, f"{name} è uscito da #{channel.name}", "Bot")
        else:
            return
        now = time.monotonic()
        key = (member.id, event)
        if now - self._greeted.get(key, -1e9) < self.greetings.get("cooldown", 30):
            return                                 # entra ed esce di continuo: niente raffica di suoni
        action = greeting_action(self.greetings, member.id, name, event)
        if action is not None:
            self._greeted[key] = now
            what = {"join": "entrata", "leave": "uscita", "mute": "muto", "unmute": "smuto"}[event]
            self.send_command({**action, "by": f"{name} ({what})"})

    # Stato su Discord ---------------------------------------------------------------------------
    def _start_presence_loop(self) -> None:
        if self._presence_task is None or self._presence_task.done():
            self._presence_task = asyncio.get_running_loop().create_task(self._presence_loop())

    async def _presence_loop(self) -> None:
        """Segue il player: «Ascolta <titolo>» mentre suona, niente quando è fermo o in pausa."""
        discord = _lib()
        client = self._client
        sent: str | None = None
        last = -PRESENCE_MIN_INTERVAL_S
        while client is not None and not client.is_closed():
            want = presence_text(self.get_state()) if self.show_presence else None
            now = time.monotonic()
            if (want != sent or self._presence_dirty) and now - last >= PRESENCE_MIN_INTERVAL_S:
                activity = discord.Activity(type=discord.ActivityType.listening, name=want) if want else None
                try:
                    await client.change_presence(activity=activity)
                    sent, last, self._presence_dirty = want, now, False
                except Exception:
                    last = now                      # riprova al prossimo giro utile
            await asyncio.sleep(PRESENCE_POLL_S)

    def refresh_board(self) -> None:
        """Ripubblica/aggiorna subito la pulsantiera nel canale dedicato (dal menu del bot)."""
        commands = self._commands
        if commands is not None and self._client is not None:
            async def run():
                commands.start_board_loop()
                commands._board_sig = None
            self._submit(run())

    def resync_commands(self) -> None:
        """Registra di nuovo i comandi (es. dopo averli attivati o disattivati) e aggiorna la pulsantiera."""
        commands = self._commands
        if commands is not None and self._client is not None:
            async def run():
                await commands.sync()
                await commands.sync_board(force=True)
            self._submit(run())

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
                                  is_continuous=lambda: self.continuous or self.engine.mic_to_bot,
                                  on_idle=self._on_idle,
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
