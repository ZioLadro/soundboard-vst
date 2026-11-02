"""Comandi slash e pulsantiera del bot Discord.

Due modi per suonare da Discord:
- ``/pulsantiera``: un messaggio con i pad come pulsanti (20 per volta) e le frecce per scorrere pagine;
- ``/canale-pulsantiera qui``: un canale dedicato dove il bot tiene tutti i pad, sempre aggiornati.

I pulsanti sono «persistenti»: il loro ``custom_id`` contiene pagina e slot, quindi continuano a
funzionare anche dopo un riavvio della soundboard, senza dover ripubblicare i messaggi.

Il bot non tocca mai direttamente interfaccia e motore: legge lo stato da ``bot.get_state()``
(l'istantanea del controllo remoto) e manda i comandi con ``bot.send_command(dict)``, che la GUI
esegue sul proprio thread, esattamente come per la pagina del telefono.

Le funzioni in cima al file non dipendono da discord.py, così si possono testare.

Niente ``from __future__ import annotations`` qui: discord.py legge le annotazioni dei parametri
dei comandi slash (``Choice[str]``, ``Range[...]``) a runtime, e devono essere già valutate.
"""

import asyncio
import colorsys
import time
from dataclasses import dataclass
from typing import Any, Iterable

PANEL_PADS = 20          # pulsantiera con navigazione: 4 righe di pad + 1 riga di comandi
CHANNEL_PADS = 25        # canale dedicato: 5 righe da 5 per messaggio
BOARD_REFRESH_S = 3.0    # ogni quanto il canale dedicato controlla se i pad sono cambiati
BOARD_TIMEOUT_S = 30.0   # oltre questo tempo un aggiornamento si considera bloccato (es. dopo lo standby)
BOARD_RETRY_MAX_S = 60.0 # dopo un errore si riprova a intervalli crescenti, fino a questo
LABEL_MAX = 80           # limite di Discord per il testo di un pulsante

ACCESS_OWNER, ACCESS_ROLE, ACCESS_EVERYONE = "owner", "role", "everyone"
ACCESS_LABELS = {ACCESS_OWNER: "Solo io", ACCESS_ROLE: "Io e chi ha il ruolo indicato",
                 ACCESS_EVERYONE: "Chiunque nel server"}

STRIP_CHOICES = [("Microfono", "mic"), ("Soundboard", "sounds"), ("Player", "player"),
                 ("Master → Discord", "master"), ("Monitor", "monitor")]

PLAYER_CHOICES = [("Play / Pausa", "toggle"), ("Stop", "stop"), ("Successivo", "next"),
                  ("Precedente", "prev")]

DENIED = "Non hai il permesso di usare questo comando della soundboard."
NOT_OWNER_SET = "Il proprietario della soundboard deve impostare il suo ID utente nelle impostazioni del bot."


class BoardError(RuntimeError):
    """Problema del canale dedicato da mostrare così com'è."""


def describe_error(exc: BaseException) -> str:
    """Messaggio breve e comprensibile per un errore di Discord o di rete."""
    if isinstance(exc, BoardError):
        return str(exc)
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "Discord non risponde (connessione persa o PC appena uscito dallo standby)"
    name = exc.__class__.__name__
    status = getattr(exc, "status", None)
    code = getattr(exc, "code", None)
    if name == "Forbidden" or status == 403:
        return "mi manca un permesso nel canale (servono «Visualizza canale» e «Invia messaggi»)"
    if code == 50083:
        return "il thread è archiviato"
    if status is not None and status >= 500:
        return "Discord ha un problema temporaneo"
    if any(k in name for k in ("Connector", "Connection", "ClientOS", "ServerDisconnected", "gaierror")):
        return "connessione a Discord non disponibile"
    text = str(exc).strip().splitlines()
    return (text[0] if text else name)[:200]


# Permessi ---------------------------------------------------------------------------------
def allowed(level: str, user_id: int, roles: Iterable[Any], owner_id: int, role: str = "") -> bool:
    """Chi può usare un comando: il proprietario sempre; poi secondo il livello scelto.

    ``role`` può essere il nome del ruolo (senza distinzione di maiuscole, con o senza @) o il suo ID.
    """
    if owner_id and user_id == owner_id:
        return True
    if level == ACCESS_EVERYONE:
        return True
    if level == ACCESS_ROLE:
        want = (role or "").strip().lstrip("@").strip().lower()
        if not want:
            return False
        return any(str(getattr(r, "id", "")) == want or str(getattr(r, "name", "")).lower() == want
                   for r in roles)
    return False


# Pad ----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Pad:
    page: int
    index: int
    key: str
    label: str
    color: str = ""

    @property
    def text(self) -> str:
        return button_label(self.label, "")


def button_label(label: str, emoji: str = "") -> str:
    """Testo del pulsante: l'emoji va nel testo (un'emoji non valida nel campo apposito farebbe
    rifiutare a Discord l'intero messaggio)."""
    text = f"{emoji} {label}".strip() if emoji else (label or "").strip()
    text = text or "?"
    return text if len(text) <= LABEL_MAX else text[:LABEL_MAX - 1] + "…"


def page_pads(state: dict, page: int) -> list[Pad]:
    """Pad assegnati (e con il file presente) di una pagina, in ordine di slot."""
    pages = (state.get("pads") or {}).get("pages") or []
    if not 0 <= page < len(pages):
        return []
    out = []
    for i, p in enumerate(pages[page].get("pads") or []):
        if p and not p.get("missing"):
            out.append(Pad(page, i, p.get("key", ""), button_label(p.get("label", ""), p.get("emoji", "")),
                           p.get("color", "")))
    return out


def page_names(state: dict) -> list[str]:
    return [pg.get("name") or f"Pagina {i + 1}"
            for i, pg in enumerate((state.get("pads") or {}).get("pages") or [])]


def chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)] or [[]]


def color_style(color: str) -> str:
    """Il colore del pad ridotto ai quattro stili dei pulsanti di Discord."""
    c = (color or "").lstrip("#")
    if len(c) != 6:
        return "secondary"
    try:
        r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return "secondary"
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    deg = h * 360
    if s < 0.25 or l < 0.2 or l > 0.9:
        return "secondary"
    if deg < 40 or deg >= 315:
        return "danger"          # rosso, arancio, rosa
    if 75 <= deg < 175:
        return "success"         # verde, acqua
    if 185 <= deg < 315:
        return "primary"         # azzurro, blu, viola
    return "secondary"           # giallo, marrone…


def panel_positions(state: dict) -> list[tuple[int, int]]:
    """Tutte le schermate (pagina, blocco) della pulsantiera, saltando le pagine vuote."""
    out = []
    for p in range(len(page_names(state))):
        pads = page_pads(state, p)
        for c in range(len(chunks(pads, PANEL_PADS))) if pads else ():
            out.append((p, c))
    return out or [(0, 0)]


def panel_view(state: dict, page: int, chunk: int) -> dict:
    """Contenuto di una schermata della pulsantiera: titolo, pad e destinazioni delle frecce."""
    positions = panel_positions(state)
    if (page, chunk) not in positions:
        same_page = [pos for pos in positions if pos[0] == page]
        page, chunk = same_page[0] if same_page else positions[0]
    pos = positions.index((page, chunk))
    names = page_names(state)
    blocks = chunks(page_pads(state, page), PANEL_PADS)
    title = f"**{names[page]}**" if names else "**Soundboard**"
    if len(blocks) > 1:
        title += f" · {chunk + 1}/{len(blocks)}"
    if not blocks[0]:
        title += "\nNessun suono sui pad: assegnali dalla soundboard."
    return {"title": title, "pads": blocks[min(chunk, len(blocks) - 1)], "page": page, "chunk": chunk,
            "prev": positions[(pos - 1) % len(positions)], "next": positions[(pos + 1) % len(positions)],
            "multi": len(positions) > 1}


def channel_messages(state: dict) -> list[dict]:
    """Messaggi del canale dedicato: tutti i pad, 25 per messaggio, più uno con i comandi."""
    out = []
    names = page_names(state)
    for p, name in enumerate(names):
        pads = page_pads(state, p)
        if not pads:
            continue
        for c, block in enumerate(chunks(pads, CHANNEL_PADS)):
            out.append({"content": f"**{name}**" + (" (continua)" if c else ""), "pads": block})
    if not out:
        out.append({"content": "Nessun suono sui pad: assegnali dalla soundboard.", "pads": []})
    out.append({"content": "Comandi", "pads": [], "controls": True})
    return out


def board_signature(messages: list[dict]) -> tuple:
    """Cambia solo quando cambia qualcosa di visibile nel canale (non a ogni suono che parte)."""
    return tuple((m["content"], bool(m.get("controls")),
                  tuple((p.page, p.index, p.label, p.color) for p in m["pads"])) for m in messages)


def library(state: dict) -> list[dict]:
    """Tutti i suoni della cartella (anche quelli non sui pad)."""
    return list(state.get("library") or [])


def search_sounds(state: dict, text: str, limit: int = 25) -> list[dict]:
    t = (text or "").strip().lower()
    items = library(state)
    if not t:
        return items[:limit]
    starts = [s for s in items if s["label"].lower().startswith(t) or s["key"].lower().startswith(t)]
    inside = [s for s in items if s not in starts and (t in s["label"].lower() or t in s["key"].lower())]
    return (starts + inside)[:limit]


def resolve_sound(state: dict, text: str) -> dict | None:
    """Trova il suono scritto dall'utente (o scelto dai suggerimenti, che usano la chiave)."""
    t = (text or "").strip()
    items = library(state)
    for s in items:
        if s["key"] == t:
            return s
    low = t.lower()
    for s in items:
        if s["label"].lower() == low or s["key"].lower() == low:
            return s
    found = search_sounds(state, t, 1)
    return found[0] if found and t else None


# Discord -------------------------------------------------------------------------------------
class Commands:
    """Comandi slash, pulsanti persistenti e canale dedicato. Vive nel thread del bot."""

    def __init__(self, discord, client, bot):
        from discord import app_commands

        self.discord = discord
        self.client = client
        self.bot = bot
        self.tree = app_commands.CommandTree(client)
        self._board_task: asyncio.Task | None = None
        self._board_sig: tuple | None = None
        self.board_error = ""
        self._board_lock = asyncio.Lock()
        self._define_commands(app_commands)
        client.add_dynamic_items(*self._dynamic_items())

    # Impostazioni --------------------------------------------------------------------------
    @property
    def cfg(self) -> dict:
        return self.bot.commands_cfg

    def can(self, interaction, level_key: str) -> bool:
        user = interaction.user
        return allowed(self.cfg.get(level_key, ACCESS_OWNER), user.id, getattr(user, "roles", []),
                       self.bot.owner_id, self.cfg.get("role", ""))

    async def deny(self, interaction) -> None:
        text = DENIED
        if not self.bot.owner_id and self.cfg.get("control_access", ACCESS_OWNER) == ACCESS_OWNER:
            text += "\n" + NOT_OWNER_SET
        await self._reply(interaction, text)

    async def _reply(self, interaction, text: str, **kw) -> None:
        kw.setdefault("ephemeral", True)
        if interaction.response.is_done():
            await interaction.followup.send(text, **kw)
        else:
            await interaction.response.send_message(text, **kw)

    def _in_voice(self, guild) -> bool:
        vc = getattr(guild, "voice_client", None)
        return vc is not None and vc.is_connected()

    # Sincronizzazione dei comandi ----------------------------------------------------------
    async def sync(self, guilds=None) -> None:
        """Registra i comandi in ogni server (in un server compaiono subito, a livello globale no)."""
        errors = []
        for guild in list(guilds if guilds is not None else self.client.guilds):
            try:
                if self.cfg.get("enabled", True):
                    self.tree.copy_global_to(guild=guild)
                else:
                    self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
            except self.discord.Forbidden:
                errors.append(guild.name)
            except Exception as exc:
                errors.append(f"{guild.name} ({exc})")
        if errors:
            self.bot._set_status(message="Comandi non registrati in: " + ", ".join(errors)
                                 + ". Invita di nuovo il bot con il pulsante «Invita il bot nel server…».")

    # Pulsanti persistenti ----------------------------------------------------------------
    def _dynamic_items(self):
        discord = self.discord
        cmds = self

        class PadButton(discord.ui.DynamicItem[discord.ui.Button],
                        template=r"sb:pad:(?P<page>\d+):(?P<index>\d+)"):
            def __init__(self, page: int, index: int, label: str = "?", style=discord.ButtonStyle.secondary):
                super().__init__(discord.ui.Button(label=label, style=style,
                                                   custom_id=f"sb:pad:{page}:{index}"))
                self.page, self.index = page, index

            @classmethod
            async def from_custom_id(cls, interaction, item, match):
                return cls(int(match["page"]), int(match["index"]))

            async def callback(self, interaction):
                await cmds.press_pad(interaction, self.page, self.index)

        class NavButton(discord.ui.DynamicItem[discord.ui.Button],
                        template=r"sb:nav:(?P<page>\d+):(?P<chunk>\d+):(?P<arrow>[a-z]+)"):
            def __init__(self, page: int, chunk: int, arrow: str):
                super().__init__(discord.ui.Button(
                    label="◀" if arrow == "prev" else "▶" if arrow == "next" else "↻",
                    style=discord.ButtonStyle.secondary, custom_id=f"sb:nav:{page}:{chunk}:{arrow}"))
                self.page, self.chunk = page, chunk

            @classmethod
            async def from_custom_id(cls, interaction, item, match):
                return cls(int(match["page"]), int(match["chunk"]), match["arrow"])

            async def callback(self, interaction):
                await cmds.navigate(interaction, self.page, self.chunk)

        class ActionButton(discord.ui.DynamicItem[discord.ui.Button],
                           template=r"sb:act:(?P<action>[a-z_]+)"):
            LOOK = {"stop": ("■ Stop suoni", discord.ButtonStyle.danger),
                    "player_prev": ("⏮", discord.ButtonStyle.secondary),
                    "player_toggle": ("⏯", discord.ButtonStyle.secondary),
                    "player_next": ("⏭", discord.ButtonStyle.secondary)}

            def __init__(self, action: str):
                label, style = self.LOOK.get(action, (action, discord.ButtonStyle.secondary))
                super().__init__(discord.ui.Button(label=label, style=style, custom_id=f"sb:act:{action}"))
                self.action = action

            @classmethod
            async def from_custom_id(cls, interaction, item, match):
                return cls(match["action"])

            async def callback(self, interaction):
                await cmds.press_action(interaction, self.action)

        self.PadButton, self.NavButton, self.ActionButton = PadButton, NavButton, ActionButton
        return PadButton, NavButton, ActionButton

    def _style(self, color: str):
        return getattr(self.discord.ButtonStyle, color_style(color))

    def _pad_view(self, pads: list[Pad]):
        view = self.discord.ui.View(timeout=None)
        for n, pad in enumerate(pads):
            view.add_item(self.PadButton(pad.page, pad.index, pad.label, self._style(pad.color)))
        return view

    def panel(self, page: int, chunk: int) -> tuple[str, Any]:
        spec = panel_view(self.bot.get_state(), page, chunk)
        view = self._pad_view(spec["pads"])
        if spec["multi"]:
            view.add_item(self.NavButton(*spec["prev"], "prev"))
        view.add_item(self.ActionButton("stop"))
        if spec["multi"]:
            view.add_item(self.NavButton(*spec["next"], "next"))
        view.add_item(self.NavButton(spec["page"], spec["chunk"], "refresh"))
        return spec["title"], view

    def _controls_view(self):
        view = self.discord.ui.View(timeout=None)
        for action in ("stop", "player_prev", "player_toggle", "player_next"):
            view.add_item(self.ActionButton(action))
        return view

    # Azioni dei pulsanti -------------------------------------------------------------------
    async def press_pad(self, interaction, page: int, index: int) -> None:
        if not self.cfg.get("enabled", True):
            return await self._reply(interaction, "I comandi da Discord sono disattivati nella soundboard.")
        if not self.can(interaction, "sounds_access"):
            return await self.deny(interaction)
        self.bot.send_command({"cmd": "pad", "page": page, "index": index})
        if interaction.guild is not None and not self._in_voice(interaction.guild):
            await self._reply(interaction, "Suono avviato, ma il bot non è in un canale vocale di questo "
                                           "server: usa /entra per farlo sentire qui.")
        else:
            await interaction.response.defer()          # nessun messaggio: il suono parte e basta

    async def navigate(self, interaction, page: int, chunk: int) -> None:
        if not self.can(interaction, "sounds_access"):
            return await self.deny(interaction)
        if self._is_board_message(interaction.message):
            # nel canale dedicato non si sfoglia: si aggiorna tutto (e si riavvia l'aggiornamento automatico)
            await interaction.response.defer()
            self.start_board_loop()
            try:
                await asyncio.wait_for(self.sync_board(force=True), BOARD_TIMEOUT_S)
            except Exception as exc:
                await self._reply(interaction, f"Non riesco ad aggiornare la pulsantiera: {describe_error(exc)}")
            return
        title, view = self.panel(page, chunk)
        await interaction.response.edit_message(content=title, view=view)

    async def press_action(self, interaction, action: str) -> None:
        if action == "stop":
            if not self.can(interaction, "sounds_access"):
                return await self.deny(interaction)
            self.bot.send_command({"cmd": "stop_sounds"})
        elif action.startswith("player_"):
            if not self.can(interaction, "control_access"):
                return await self.deny(interaction)
            self.bot.send_command({"cmd": "player", "action": action.split("_", 1)[1]})
        await interaction.response.defer()

    # Comandi slash ---------------------------------------------------------------------------
    def _define_commands(self, app_commands) -> None:
        tree, cmds = self.tree, self
        Choice = app_commands.Choice

        def needs(level_key: str):
            async def predicate(interaction) -> bool:
                if not cmds.cfg.get("enabled", True):
                    await cmds._reply(interaction, "I comandi da Discord sono disattivati nella soundboard.")
                    return False
                if not cmds.can(interaction, level_key):
                    await cmds.deny(interaction)
                    return False
                return True
            return app_commands.check(predicate)

        @tree.error
        async def on_error(interaction, error):
            if isinstance(error, app_commands.CheckFailure):
                if not interaction.response.is_done():
                    await cmds.deny(interaction)
                return
            try:
                await cmds._reply(interaction, f"Errore: {getattr(error, 'original', error)}")
            except Exception:
                pass

        async def sound_autocomplete(interaction, current: str):
            return [Choice(name=button_label(s["label"], s.get("emoji", ""))[:100], value=s["key"][:100])
                    for s in search_sounds(cmds.bot.get_state(), current)]

        @tree.command(name="suona", description="Riproduce un suono della soundboard")
        @app_commands.describe(suono="Nome del suono (scrivi per cercare)")
        @app_commands.autocomplete(suono=sound_autocomplete)
        @needs("sounds_access")
        async def suona(interaction, suono: str):
            s = resolve_sound(cmds.bot.get_state(), suono)
            if s is None:
                return await cmds._reply(interaction, f"Nessun suono trovato per «{suono[:100]}».")
            cmds.bot.send_command({"cmd": "sound", "key": s["key"]})
            note = "" if interaction.guild is None or cmds._in_voice(interaction.guild) else \
                " (il bot non è in un canale vocale: usa /entra)"
            await cmds._reply(interaction, f"▶ {button_label(s['label'], s.get('emoji', ''))}{note}")

        @tree.command(name="stop", description="Ferma tutti i suoni della soundboard")
        @needs("sounds_access")
        async def stop(interaction):
            cmds.bot.send_command({"cmd": "stop_sounds"})
            await cmds._reply(interaction, "■ Suoni fermati.")

        @tree.command(name="parla", description="Fa dire una frase alla sintesi vocale della soundboard")
        @app_commands.describe(testo="La frase da dire (fino a 300 caratteri)")
        @needs("sounds_access")
        async def parla(interaction, testo: app_commands.Range[str, 1, 300]):
            cmds.bot.send_command({"cmd": "say", "text": testo})
            note = "" if interaction.guild is None or cmds._in_voice(interaction.guild) else \
                " (il bot non è in un canale vocale: usa /entra)"
            await cmds._reply(interaction, f"💬 {testo[:200]}{note}")

        @tree.command(name="pulsantiera", description="Mostra i pad della soundboard come pulsanti")
        @app_commands.describe(pagina="Pagina dei pad da mostrare (da 1)",
                               privata="Visibile solo a te (predefinito: visibile a tutti nel canale)")
        @needs("sounds_access")
        async def pulsantiera(interaction, pagina: app_commands.Range[int, 1, 999] = 1, privata: bool = False):
            title, view = cmds.panel(pagina - 1, 0)
            await interaction.response.send_message(title, view=view, ephemeral=privata)

        @tree.command(name="canale-pulsantiera",
                      description="Usa questo canale come pulsantiera fissa della soundboard, sempre aggiornata")
        @app_commands.describe(azione="«qui» per usare questo canale, «rimuovi» per smettere")
        @app_commands.choices(azione=[Choice(name="Usa questo canale", value="qui"),
                                      Choice(name="Rimuovi la pulsantiera fissa", value="rimuovi")])
        @needs("control_access")
        async def canale_pulsantiera(interaction, azione: Choice[str]):
            if azione.value == "rimuovi":
                await interaction.response.defer(ephemeral=True, thinking=True)
                await cmds.clear_board()
                return await cmds._reply(interaction, "Pulsantiera fissa rimossa.")
            channel = interaction.channel
            guild = interaction.guild
            perms = channel.permissions_for(guild.me) if guild is not None else None
            if perms is None or not (perms.view_channel and perms.send_messages):
                return await cmds._reply(interaction, "Non ho il permesso di scrivere in questo canale: "
                                                      "dammi «Visualizza canale» e «Invia messaggi».")
            await interaction.response.defer(ephemeral=True, thinking=True)
            if cmds.bot.board_channel and cmds.bot.board_channel != channel.id:
                await cmds.clear_board()
            cmds.bot.set_board(channel.id, [])
            await cmds.sync_board(force=True)
            await cmds._reply(interaction, f"Fatto: in {channel.mention} trovi tutti i pad. I messaggi si "
                                           "aggiornano da soli quando cambi i pad nella soundboard.")

        @tree.command(name="entra", description="Fa entrare il bot nel tuo canale vocale")
        @needs("control_access")
        async def entra(interaction):
            voice = getattr(interaction.user, "voice", None)
            channel = getattr(voice, "channel", None)
            if channel is None:
                return await cmds._reply(interaction, "Entra prima in un canale vocale di questo server.")
            await interaction.response.defer(ephemeral=True, thinking=True)
            await cmds.bot._connect(channel)
            ok = cmds._in_voice(channel.guild)
            await cmds._reply(interaction, f"Sono in {channel.mention}." if ok else cmds.bot.status.message)

        @tree.command(name="esci", description="Fa uscire il bot dal canale vocale")
        @needs("control_access")
        async def esci(interaction):
            vc = interaction.guild.voice_client if interaction.guild else None
            if vc is None:
                return await cmds._reply(interaction, "Non sono in un canale vocale.")
            await vc.disconnect(force=False)
            await cmds._reply(interaction, "Uscito dal canale.")

        @tree.command(name="player", description="Comandi del player musicale della soundboard")
        @app_commands.choices(azione=[Choice(name=n, value=v) for n, v in PLAYER_CHOICES])
        @needs("control_access")
        async def player(interaction, azione: Choice[str]):
            cmds.bot.send_command({"cmd": "player", "action": azione.value})
            await cmds._reply(interaction, f"Player: {azione.name}.")

        @tree.command(name="riproduci", description="Aggiunge al player un link o una ricerca di YouTube")
        @app_commands.describe(cerca="Link di YouTube (video o playlist) o testo da cercare")
        @needs("control_access")
        async def riproduci(interaction, cerca: app_commands.Range[str, 1, 500]):
            cmds.bot.send_command({"cmd": "player_add", "text": cerca})
            await cmds._reply(interaction, f"Aggiunto al player: {cerca[:200]}")

        @tree.command(name="volume", description="Regola il volume di un canale del mixer")
        @app_commands.describe(canale="Canale del mixer", db="Volume in dB (da -60 a +12; 0 = invariato)")
        @app_commands.choices(canale=[Choice(name=n, value=v) for n, v in STRIP_CHOICES])
        @needs("control_access")
        async def volume(interaction, canale: Choice[str], db: app_commands.Range[float, -60.0, 12.0]):
            cmds.bot.send_command({"cmd": "strip", "id": canale.value, "gain_db": float(db)})
            await cmds._reply(interaction, f"{canale.name}: {db:+.1f} dB")

        @tree.command(name="aiuto", description="Elenco dei comandi della soundboard")
        async def aiuto(interaction):
            await cmds._reply(interaction, (
                "**Suoni**\n"
                "`/suona` riproduce un suono · `/parla` sintesi vocale · `/stop` ferma tutto · "
                "`/pulsantiera` pad come pulsanti\n"
                "**Controllo**\n"
                "`/entra` · `/esci` · `/player` · `/riproduci` (YouTube) · `/volume`\n"
                "`/canale-pulsantiera` tiene tutti i pad in un canale dedicato"))

    # Canale dedicato ---------------------------------------------------------------------------
    def _is_board_message(self, message) -> bool:
        return message is not None and message.id in set(self.bot.board_messages)

    def start_board_loop(self) -> None:
        """Avvia (o riavvia, se si era fermato) l'aggiornamento automatico del canale dedicato."""
        if self._board_task is None or self._board_task.done():
            self._board_task = asyncio.get_running_loop().create_task(self._board_loop())

    async def _board_loop(self) -> None:
        """Non si ferma mai da solo: ogni errore viene mostrato e si riprova, risincronizzando tutto."""
        force, delay = True, BOARD_REFRESH_S         # all'avvio: ripristina etichette e pad cambiati
        while not self.client.is_closed():
            try:
                await asyncio.wait_for(self.sync_board(force=force), BOARD_TIMEOUT_S)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                msg = describe_error(exc)
                delay = min(BOARD_RETRY_MAX_S, delay * 2)
                if msg != self.board_error:
                    self.bot._set_status(message=f"Pulsantiera nel canale: {msg}. Riprovo da solo.")
                self.board_error = msg
                self._board_sig = None
                force = True
                self.bot.board_info = {"time": None, "error": msg}
            else:
                if self.board_error:
                    self.bot._set_status(message="Pulsantiera nel canale di nuovo aggiornata.")
                self.board_error = ""
                if self.bot.board_channel:            # controllata ora (anche se non c'era niente da cambiare)
                    self.bot.board_info = {**self.bot.board_info, "time": time.time(), "error": ""}
                force, delay = False, BOARD_REFRESH_S
            await asyncio.sleep(delay)

    async def _resolve_board_channel(self):
        """Il canale dedicato, anche se non è nella cache (es. un thread) o è un thread archiviato."""
        cid = self.bot.board_channel
        if not cid:
            return None
        discord = self.discord
        channel = self.client.get_channel(cid)
        if channel is None:
            try:
                channel = await self.client.fetch_channel(cid)
            except discord.NotFound:
                self.bot.set_board(0, [])            # canale eliminato: non c'è più niente da aggiornare
                self._board_sig = None
                raise BoardError("il canale della pulsantiera è stato eliminato: usa di nuovo /canale-pulsantiera")
            except discord.Forbidden:
                raise BoardError("non ho più accesso al canale della pulsantiera")
        if getattr(channel, "archived", False):      # thread archiviato dopo un periodo di inattività
            if getattr(channel, "locked", False):
                raise BoardError("il thread della pulsantiera è bloccato")
            await channel.edit(archived=False)
        return channel

    async def sync_board(self, force: bool = False) -> None:
        """Allinea i messaggi del canale dedicato ai pad attuali (solo se sono cambiati)."""
        async with self._board_lock:
            if not self.bot.board_channel or not self.cfg.get("enabled", True):
                return
            messages = channel_messages(self.bot.get_state())
            sig = board_signature(messages)
            if not force and sig == self._board_sig:
                return
            channel = await self._resolve_board_channel()
            if channel is None:
                return
            ids = list(self.bot.board_messages)
            discord = self.discord
            done = False
            if len(ids) == len(messages):
                try:
                    for mid, m in zip(ids, messages):
                        await channel.get_partial_message(mid).edit(content=m["content"], view=self._view_for(m))
                    done = True
                except discord.NotFound:
                    pass             # qualcuno ha cancellato un messaggio: si ripubblica tutto
            if not done:
                # numero di messaggi cambiato: per mantenerli in ordine si ripubblicano
                await self._delete_messages(channel, ids)
                new_ids: list[int] = []
                self.bot.set_board(channel.id, new_ids)
                for m in messages:
                    msg = await channel.send(m["content"], view=self._view_for(m))
                    new_ids.append(msg.id)
                    self.bot.set_board(channel.id, new_ids)   # salvati man mano: niente doppioni se si interrompe
            self._board_sig = sig
            self.bot.board_info = {"time": time.time(), "error": "",
                                   "channel": getattr(channel, "name", "")}

    def _view_for(self, m: dict):
        return self._controls_view() if m.get("controls") else self._pad_view(m["pads"])

    async def _delete_messages(self, channel, ids) -> None:
        for mid in ids:
            try:
                await channel.get_partial_message(mid).delete()
            except Exception:
                pass

    async def clear_board(self) -> None:
        async with self._board_lock:
            try:
                channel = await self._resolve_board_channel()
            except Exception:
                channel = None                       # canale sparito: basta dimenticarlo
            if channel is not None:
                await self._delete_messages(channel, self.bot.board_messages)
            self.bot.set_board(0, [])
            self._board_sig = None
