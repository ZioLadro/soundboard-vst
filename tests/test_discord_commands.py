import asyncio
import re
from types import SimpleNamespace

import discord
import pytest

from soundboard_vst.discord_bot import DiscordBot, invite_url
from soundboard_vst.discord_commands import (
    CHANNEL_PADS, PANEL_PADS, Commands, allowed, default_permissions, normalize_permissions,
    board_signature, button_label, channel_messages, color_style, page_pads, panel_positions,
    panel_view, resolve_sound, search_sounds,
)


def pad(key, label=None, emoji="", color="", missing=False):
    return {"key": key, "label": label or key.rsplit(".", 1)[0], "emoji": emoji, "color": color,
            "playing": False, "missing": missing}


def make_state(pages):
    """pages: [(nome, {slot: pad})], griglia da 48."""
    out = []
    for name, slots in pages:
        pads = [None] * 48
        for i, p in slots.items():
            pads[i] = p
        out.append({"name": name, "pads": pads})
    lib = [{"key": p["key"], "label": p["label"], "emoji": p["emoji"]}
           for _, slots in pages for p in slots.values()]
    return {"pads": {"pages": out, "current": 0, "cols": 8}, "library": lib}


# Funzioni pure ------------------------------------------------------------------------------
def test_permissions_groups_roles_users_and_blocks():
    roles = [SimpleNamespace(id=55, name="DJ")]
    perms = default_permissions()
    assert allowed("suoni", 2, [], 1, perms) and allowed("parla", 2, [], 1, perms)   # predefinito: tutti
    assert not allowed("musica", 2, roles, 1, perms) and allowed("musica", 1, [], 1, perms)  # il proprietario sì
    assert allowed("gestione", 2, [], 1, perms, is_admin=True)                       # amministratori
    perms["admins"] = False
    assert not allowed("gestione", 2, [], 1, perms, is_admin=True)
    perms["groups"]["musica"]["roles"] = ["55"]                                      # ruolo per ID
    perms["groups"]["controllo"]["roles"] = ["@dj"]                                  # o per nome
    perms["groups"]["gestione"]["users"] = ["7"]
    assert allowed("musica", 2, roles, 1, perms) and allowed("controllo", 2, roles, 1, perms)
    assert not allowed("musica", 2, [], 1, perms)
    assert allowed("gestione", 7, [], 1, perms) and not allowed("gestione", 8, [], 1, perms)
    perms["blocked"] = ["7"]
    assert not allowed("suoni", 7, [], 1, perms) and not allowed("gestione", 7, [], 1, perms)
    assert allowed("suoni", 1, [], 1, {**perms, "blocked": ["1"]})                   # il proprietario mai bloccato
    assert not allowed("suoni", 2, [], 0, {"groups": {}})                            # gruppo sconosciuto: no


def test_old_permission_settings_are_converted():
    old = {"enabled": True, "sounds_access": "role", "control_access": "everyone", "role": "@Amici"}
    p = normalize_permissions(None, old)
    assert p["groups"]["suoni"] == {"everyone": False, "roles": ["Amici"], "users": []}
    assert p["groups"]["parla"]["roles"] == ["Amici"]
    assert all(p["groups"][g]["everyone"] for g in ("musica", "controllo", "gestione"))
    assert p["admins"] is False                                       # come prima: niente diritti in più
    fresh = normalize_permissions(None, {"enabled": True})
    assert fresh == default_permissions()
    saved = normalize_permissions({"admins": False, "blocked": [9], "groups": {"suoni": {"users": [3]}, "x": {}}})
    assert saved["blocked"] == ["9"] and saved["groups"]["suoni"] == {"everyone": False, "roles": [], "users": ["3"]}


def test_button_label_and_colors():
    assert button_label("Applausi", "👏") == "👏 Applausi"
    assert button_label("", "") == "?"
    assert len(button_label("x" * 200)) == 80
    assert color_style("#e5534b") == "danger"      # rosso
    assert color_style("#57ab5a") == "success"     # verde
    assert color_style("#39a0ed") == "primary"     # azzurro
    assert color_style("#a371f7") == "primary"     # viola
    assert color_style("#8b949e") == "secondary"   # grigio
    assert color_style("") == "secondary" and color_style("zzz") == "secondary"


def test_page_pads_skip_empty_and_missing():
    st = make_state([("A", {3: pad("b.wav"), 0: pad("a.wav", emoji="🔥"), 5: pad("x.wav", missing=True)})])
    pads = page_pads(st, 0)
    assert [(p.index, p.label) for p in pads] == [(0, "🔥 a"), (3, "b")]
    assert page_pads(st, 7) == []


def test_panel_navigation_wraps_over_pages_and_chunks():
    big = {i: pad(f"s{i}.wav") for i in range(30)}            # 30 pad → 2 schermate
    st = make_state([("Uno", big), ("Vuota", {}), ("Tre", {0: pad("z.wav")})])
    assert panel_positions(st) == [(0, 0), (0, 1), (2, 0)]   # la pagina vuota è saltata
    v = panel_view(st, 0, 0)
    assert len(v["pads"]) == PANEL_PADS and v["title"] == "**Uno** · 1/2"
    assert v["prev"] == (2, 0) and v["next"] == (0, 1)
    v = panel_view(st, 1, 0)                                 # pagina vuota chiesta: si va alla prima
    assert (v["page"], v["chunk"]) == (0, 0)
    v = panel_view(st, 2, 5)                                 # blocco inesistente: primo della pagina
    assert (v["page"], v["chunk"]) == (2, 0) and v["next"] == (0, 0)
    empty = panel_view(make_state([("A", {})]), 0, 0)
    assert empty["pads"] == [] and not empty["multi"] and "Nessun suono" in empty["title"]


def test_channel_messages_and_signature():
    st = make_state([("Uno", {i: pad(f"s{i}.wav") for i in range(30)}), ("Due", {2: pad("d.wav")})])
    msgs = channel_messages(st)
    assert [len(m["pads"]) for m in msgs] == [CHANNEL_PADS, 5, 1, 0]
    assert msgs[1]["content"].endswith("(continua)") and msgs[-1].get("controls")
    sig = board_signature(msgs)
    st["pads"]["pages"][0]["pads"][0]["playing"] = True      # un suono che parte non cambia nulla
    assert board_signature(channel_messages(st)) == sig
    st["pads"]["pages"][0]["pads"][0]["label"] = "Nuovo"
    assert board_signature(channel_messages(st)) != sig


def test_search_and_resolve_sounds():
    st = {"library": [{"key": "applausi.wav", "label": "Applausi", "emoji": ""},
                      {"key": "risata finta.mp3", "label": "Risata", "emoji": "😂"},
                      {"key": "boom.wav", "label": "Grande applauso", "emoji": ""}]}
    assert [s["key"] for s in search_sounds(st, "appl")] == ["applausi.wav", "boom.wav"]
    assert resolve_sound(st, "risata finta.mp3")["label"] == "Risata"   # dai suggerimenti (chiave)
    assert resolve_sound(st, "risata")["key"] == "risata finta.mp3"     # scritto a mano
    assert resolve_sound(st, "grande")["key"] == "boom.wav"
    assert resolve_sound(st, "nulla") is None and resolve_sound(st, "") is None


def test_invite_includes_commands_scope_and_message_permissions():
    url = invite_url(42)
    perms = discord.Permissions(int(re.search(r"permissions=(\d+)", url).group(1)))
    assert "applications.commands" in url
    assert perms.connect and perms.speak and perms.send_messages and perms.view_channel
    assert not perms.administrator


# Con discord.py ------------------------------------------------------------------------------
class FakeBot:
    def __init__(self, state):
        self.state = state
        self.commands_cfg = {"enabled": True}
        self.permissions = default_permissions()
        self.greetings = {}
        self.known_users = {}
        self.owner_id = 1
        self.sent = []
        self.sent_full = []
        self.board_channel, self.board_messages = 0, []
        self.status = SimpleNamespace(message="")

    def get_state(self):
        return self.state

    def send_command(self, c):
        self.sent_full.append(c)
        self.sent.append({k: v for k, v in c.items() if k not in ("by", "_done")})
        if callable(c.get("_done")):
            c["_done"](True, f"ok {c['cmd']}")

    def remember_user(self, user):
        self.known_users[str(user.id)] = getattr(user, "display_name", "?")

    def set_board(self, cid, ids):
        self.board_channel, self.board_messages = cid, list(ids)

    def _set_status(self, **kw):
        self.status.message = kw.get("message", "")


@pytest.fixture
def cmds():
    st = make_state([("Uno", {i: pad(f"s{i}.wav", color="#57ab5a") for i in range(30)}),
                     ("Due", {0: pad("d.wav", emoji="🎺")})])
    client = discord.Client(intents=discord.Intents.none())
    return Commands(discord, client, FakeBot(st))


def test_slash_commands_build_valid_payloads(cmds):
    payloads = {c.name: c.to_dict(cmds.tree) for c in cmds.tree.get_commands()}
    assert set(payloads) == {"suona", "parla", "stop", "pulsantiera", "canale-pulsantiera", "entra", "esci",
                             "player", "riproduci", "volume", "aiuto", "aggiungi-suono", "mio-suono"}
    add = {o["name"]: o for o in payloads["aggiungi-suono"]["options"]}
    assert add["file"]["type"] == 11 and not add["file"]["required"] and not add["link"]["required"]
    mine = {o["name"]: o for o in payloads["mio-suono"]["options"]}
    assert mine["entrata"]["autocomplete"] and mine["utente"]["type"] == 6
    parla = payloads["parla"]["options"][0]
    assert parla["required"] and parla["max_length"] == 300
    for p in payloads.values():
        assert re.fullmatch(r"[-_\w]{1,32}", p["name"]) and 1 <= len(p["description"]) <= 100
    suona = payloads["suona"]["options"][0]
    assert suona["autocomplete"] and suona["required"]
    vol = {o["name"]: o for o in payloads["volume"]["options"]}
    assert vol["db"]["min_value"] == -60 and vol["db"]["max_value"] == 12
    assert {c["value"] for c in vol["canale"]["choices"]} == {"mic", "sounds", "tts", "player", "master", "monitor"}


def btn(item):
    return getattr(item, "item", item)        # i pulsanti persistenti avvolgono il Button vero


def _layout_ok(view):
    for item in view.children:
        assert len(btn(item).custom_id) <= 100 and 1 <= len(btn(item).label) <= 80
    assert len(view.children) <= 25
    view.to_components()       # discord.py valida righe e larghezze


def test_panel_view_buttons_and_persistent_ids(cmds):
    title, view = cmds.panel(0, 0)
    _layout_ok(view)
    ids = [i.custom_id for i in view.children]
    assert ids[:2] == ["sb:pad:0:0", "sb:pad:0:1"] and len([i for i in ids if i.startswith("sb:pad")]) == 20
    assert "sb:act:stop" in ids and "sb:nav:0:1:next" in ids and "sb:nav:1:0:prev" in ids
    assert btn(view.children[0]).style is discord.ButtonStyle.success       # pad verde
    assert view.timeout is None
    title, view = cmds.panel(1, 0)
    assert title.startswith("**Due**") and btn(view.children[0]).label == "🎺 d"
    # i pulsanti si riconoscono dal custom_id anche dopo un riavvio
    m = cmds.PadButton.__discord_ui_compiled_template__.fullmatch("sb:pad:1:0")
    item = asyncio.run(cmds.PadButton.from_custom_id(None, None, m))
    assert (item.page, item.index) == (1, 0)


class FakeResponse:
    def __init__(self):
        self.calls = []
        self._done = False

    def is_done(self):
        return self._done

    async def defer(self, **kw):
        self.calls.append(("defer", kw))
        self._done = True

    async def send_message(self, text=None, **kw):
        self.calls.append(("send", text, kw))
        self._done = True

    async def edit_message(self, **kw):
        self.calls.append(("edit", kw))
        self._done = True


def interaction(user_id, guild_in_voice=True, message=None, roles=()):
    vc = SimpleNamespace(is_connected=lambda: guild_in_voice)
    return SimpleNamespace(user=SimpleNamespace(id=user_id, roles=list(roles)), response=FakeResponse(),
                           guild=SimpleNamespace(voice_client=vc), message=message)


def test_press_pad_plays_and_checks_permissions(cmds):
    it = interaction(7)
    asyncio.run(cmds.press_pad(it, 0, 3))
    assert cmds.bot.sent == [{"cmd": "pad", "page": 0, "index": 3}]
    assert it.response.calls[0][0] == "defer"                 # nessun messaggio: suona e basta

    it = interaction(7, guild_in_voice=False)
    asyncio.run(cmds.press_pad(it, 0, 4))
    kind, text, kw = it.response.calls[0]
    assert kind == "send" and kw["ephemeral"] and "/entra" in text

    cmds.bot.permissions["groups"]["suoni"]["everyone"] = False
    cmds.bot.sent.clear()
    it = interaction(7)
    asyncio.run(cmds.press_pad(it, 0, 3))
    assert cmds.bot.sent == [] and "permesso" in it.response.calls[0][1]
    asyncio.run(cmds.press_pad(interaction(1), 0, 3))         # il proprietario può sempre
    assert cmds.bot.sent == [{"cmd": "pad", "page": 0, "index": 3}]


def test_player_buttons_need_control_access(cmds):
    it = interaction(7)
    asyncio.run(cmds.press_action(it, "player_toggle"))
    assert cmds.bot.sent == [] and "permesso" in it.response.calls[0][1]
    asyncio.run(cmds.press_action(interaction(1), "player_toggle"))
    asyncio.run(cmds.press_action(interaction(7), "stop"))
    assert cmds.bot.sent == [{"cmd": "player", "action": "toggle"}, {"cmd": "stop_sounds"}]


def test_navigate_edits_panel(cmds):
    it = interaction(7)
    asyncio.run(cmds.navigate(it, 0, 1))
    kind, kw = it.response.calls[0]
    assert kind == "edit" and kw["content"] == "**Uno** · 2/2"
    assert [c.custom_id for c in kw["view"].children][:10] == [f"sb:pad:0:{i}" for i in range(20, 30)]


class FakeChannel:
    def __init__(self):
        self.id = 99
        self.sent, self.edited, self.deleted = [], [], []
        self._next = 1000

    async def send(self, content, view=None):
        self._next += 1
        self.sent.append((self._next, content, view))
        return SimpleNamespace(id=self._next)

    def get_partial_message(self, mid):
        ch = self

        class P:
            async def edit(self, **kw):
                ch.edited.append((mid, kw["content"]))

            async def delete(self):
                ch.deleted.append(mid)
        return P()


def test_board_channel_publishes_then_edits_then_republishes(cmds):
    ch = FakeChannel()
    cmds.client.get_channel = lambda cid: ch if cid == 99 else None
    cmds.bot.board_channel = 99

    async def scenario():
        await cmds.sync_board(force=True)                      # primo avvio: pubblica
        assert [c for _, c, _ in ch.sent] == ["**Uno**", "**Uno** (continua)", "**Due**", "Comandi"]
        assert cmds.bot.board_messages == [1001, 1002, 1003, 1004]
        for _, _, view in ch.sent:
            _layout_ok(view)
        await cmds.sync_board()                                # niente di cambiato: nessuna chiamata
        assert ch.edited == []
        cmds.bot.state["pads"]["pages"][1]["pads"][0]["label"] = "Tromba"
        await cmds.sync_board()                                # stesso numero di messaggi: modifica
        assert len(ch.edited) == 4 and len(ch.sent) == 4
        cmds.bot.state["pads"]["pages"][1]["pads"][1] = pad("e.wav")
        cmds.bot.state["pads"]["pages"].append({"name": "Tre", "pads": [pad("t.wav")]})
        await cmds.sync_board()                                # un messaggio in più: ripubblica in ordine
        assert ch.deleted == [1001, 1002, 1003, 1004]
        assert [c for _, c, _ in ch.sent[4:]] == ["**Uno**", "**Uno** (continua)", "**Due**", "**Tre**", "Comandi"]
        await cmds.clear_board()
        assert cmds.bot.board_channel == 0 and cmds.bot.board_messages == []

    asyncio.run(scenario())


def test_bot_set_board_reports_to_gui():
    from soundboard_vst.audio.engine import AudioEngine
    seen = []
    bot = DiscordBot(AudioEngine(48000, 512), lambda st: None, on_board=lambda c, ids: seen.append((c, ids)))
    bot.set_board(5, [1, 2])
    assert bot.board_channel == 5 and seen == [(5, [1, 2])]


# Canale dedicato: resistenza agli errori ------------------------------------------------------
from soundboard_vst import discord_commands as dc


def http_error(cls, status, code=0):
    resp = SimpleNamespace(status=status, reason="x")
    return cls(resp, {"code": code, "message": "x"})


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(dc, "BOARD_REFRESH_S", 0.01)
    monkeypatch.setattr(dc, "BOARD_RETRY_MAX_S", 0.04)
    monkeypatch.setattr(dc, "BOARD_TIMEOUT_S", 0.2)


def run_loop(cmds, until, timeout=3.0):
    async def main():
        cmds.start_board_loop()
        t = asyncio.get_running_loop().time()
        while not until() and asyncio.get_running_loop().time() - t < timeout:
            await asyncio.sleep(0.01)
        cmds._board_task.cancel()
    asyncio.run(main())


def test_loop_survives_startup_error_and_recovers(cmds, fast):
    ch = FakeChannel()
    real_send, fails = ch.send, {"n": 2}

    async def flaky_send(content, view=None):
        if fails["n"]:
            fails["n"] -= 1
            raise http_error(discord.HTTPException, 503)
        return await real_send(content, view)

    ch.send = flaky_send
    cmds.client.get_channel = lambda cid: ch
    cmds.bot.board_channel = 99
    statuses = []
    cmds.bot._set_status = lambda **kw: statuses.append(kw["message"])
    run_loop(cmds, lambda: len(cmds.bot.board_messages) == 4 and not cmds.board_error)
    assert len(cmds.bot.board_messages) == 4 and cmds.board_error == ""
    assert "problema temporaneo" in statuses[0] and "di nuovo aggiornata" in statuses[-1]
    assert len(statuses) == 2                           # un solo avviso, non uno per tentativo
    assert cmds.bot.board_info["error"] == "" and cmds.bot.board_info["time"]


def test_hung_request_times_out_and_retries(cmds, fast):
    ch = FakeChannel()
    real_send, hang = ch.send, {"n": 1}

    async def hanging_send(content, view=None):
        if hang["n"]:
            hang["n"] -= 1
            await asyncio.sleep(3600)                   # come una connessione morta dopo lo standby
        return await real_send(content, view)

    ch.send = hanging_send
    cmds.client.get_channel = lambda cid: ch
    cmds.bot.board_channel = 99
    run_loop(cmds, lambda: len(cmds.bot.board_messages) == 4 and not cmds.board_error)
    assert len(cmds.bot.board_messages) == 4 and not cmds._board_lock.locked()


def test_channel_not_in_cache_and_archived_thread(cmds, fast):
    ch = FakeChannel()
    ch.archived, ch.locked, edits = True, False, []

    async def edit(**kw):
        edits.append(kw)
        ch.archived = kw.get("archived", ch.archived)

    ch.edit = edit
    cmds.client.get_channel = lambda cid: None          # thread archiviato: non è più in cache

    async def fetch(cid):
        return ch

    cmds.client.fetch_channel = fetch
    cmds.bot.board_channel = 99
    asyncio.run(cmds.sync_board(force=True))
    assert edits == [{"archived": False}] and len(cmds.bot.board_messages) == 4


def test_deleted_channel_is_forgotten_with_clear_message(cmds, fast):
    cmds.client.get_channel = lambda cid: None

    async def fetch(cid):
        raise http_error(discord.NotFound, 404, 10003)

    cmds.client.fetch_channel = fetch
    cmds.bot.board_channel, cmds.bot.board_messages = 99, [1, 2]
    with pytest.raises(dc.BoardError, match="eliminato"):
        asyncio.run(cmds.sync_board(force=True))
    assert cmds.bot.board_channel == 0 and cmds.bot.board_messages == []


def test_interrupted_republish_keeps_track_of_sent_messages(cmds):
    ch = FakeChannel()
    real_send, count = ch.send, {"n": 0}

    async def send_two_then_fail(content, view=None):
        count["n"] += 1
        if count["n"] == 3:
            raise http_error(discord.HTTPException, 500)
        return await real_send(content, view)

    ch.send = send_two_then_fail
    cmds.client.get_channel = lambda cid: ch
    cmds.bot.board_channel = 99
    with pytest.raises(discord.HTTPException):
        asyncio.run(cmds.sync_board(force=True))
    assert cmds.bot.board_messages == [1001, 1002]      # i due già inviati: verranno sostituiti, non duplicati
    asyncio.run(cmds.sync_board(force=True))
    assert ch.deleted == [1001, 1002] and len(cmds.bot.board_messages) == 4


def test_refresh_button_restarts_dead_loop(cmds, fast):
    ch = FakeChannel()
    cmds.client.get_channel = lambda cid: ch
    cmds.bot.board_channel = 99
    asyncio.run(cmds.sync_board(force=True))
    msg = SimpleNamespace(id=cmds.bot.board_messages[0])
    it = interaction(7, message=msg)

    async def press():
        await cmds.navigate(it, 0, 0)
        started = cmds._board_task is not None and not cmds._board_task.done()
        cmds._board_task.cancel()
        return started

    assert asyncio.run(press()) and it.response.calls[0][0] == "defer"


def test_describe_error_messages():
    assert "permesso" in dc.describe_error(http_error(discord.Forbidden, 403, 50013))
    assert "archiviato" in dc.describe_error(http_error(discord.HTTPException, 400, 50083))
    assert "non risponde" in dc.describe_error(asyncio.TimeoutError())
    assert "connessione" in dc.describe_error(type("ClientConnectorError", (Exception,), {})("x"))
