"""Novità della 0.8.0: import di suoni, registro, /aggiungi-suono, /mio-suono, permessi, entrate/uscite."""

import asyncio
import os
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import discord
import numpy as np
import pytest

from soundboard_vst import eventlog, importer
from soundboard_vst.audio.library import decode
from soundboard_vst.discord_bot import DiscordBot, greeting_action, normalize_greetings

SR = 48000


def write_wav(path, seconds, sr=44100):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.sin(np.arange(int(sr * seconds)) / 9) * 12000).astype("<i2").tobytes())


# Import -----------------------------------------------------------------------------------------
def test_parse_time_and_classify():
    assert [importer.parse_time(t) for t in ("", None, "7", "1:05", "1:00:00", "2,5", "3.25s")] == \
        [0, 0, 7, 65, 3600, 2.5, 3.25]
    with pytest.raises(importer.ImportError_):
        importer.parse_time("dopo")
    assert importer.classify("https://www.youtube.com/watch?v=abcdefghijk") == "youtube"
    assert importer.classify("https://www.myinstants.com/en/instant/vine-boom-12/") == "myinstants"
    assert importer.classify("https://example.com/x.ogg") == "http"
    assert importer.classify("bruh sound effect") == "search"


def test_local_import_trims_converts_and_never_overwrites(tmp_path):
    src = tmp_path / "in.wav"
    write_wav(src, 3.0)
    folder = tmp_path / "Suoni"
    a = importer.import_source(str(src), folder, "Colpo", "0:00.5", "1.5", local=True)
    b = importer.import_source(str(src), folder, "Colpo", local=True)
    assert a.path.name == "Colpo.mp3" and b.path.name == "Colpo (1).mp3"
    assert abs(decode(a.path, SR).shape[1] / SR - 1.0) < 0.06 and abs(decode(b.path, SR).shape[1] / SR - 3.0) < 0.06
    assert src.exists()                                        # i file locali non vengono cancellati
    with pytest.raises(importer.ImportError_, match="dopo l'inizio"):
        importer.import_source(str(src), folder, "x", "2", "1", local=True)
    bad = tmp_path / "rotto.mp3"
    bad.write_bytes(b"non sono audio")
    with pytest.raises(importer.ImportError_):
        importer.import_source(str(bad), folder, "x", local=True)


def test_incoming_files_are_deleted_and_limited(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "incoming_dir", lambda: tmp_path / "in")
    f = importer.new_incoming(".wav")
    write_wav(f, 1.0)
    assert importer.is_incoming(f) and not importer.is_incoming(tmp_path / "altro.wav")
    importer.import_source(str(f), tmp_path / "Suoni", "Da Discord", local=True)
    assert not f.exists()                                      # allegato temporaneo: rimosso


class _Handler(BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self):
        body, ctype = self.routes.get(self.path, (b"", "text/plain"))
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def http(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", _Handler.routes
    srv.shutdown()


def test_import_from_direct_link_and_html_page(http, tmp_path, monkeypatch):
    base, routes = http
    monkeypatch.setattr(importer, "incoming_dir", lambda: tmp_path / "in")
    write_wav(tmp_path / "s.wav", 0.6)
    routes["/media/boom.wav"] = ((tmp_path / "s.wav").read_bytes(), "audio/wav")
    routes["/pagina"] = (b"<html>ciao</html>", "text/html")
    r = importer.import_source(base + "/media/boom.wav", tmp_path / "Suoni")
    assert r.path.name == "boom.mp3" and r.title == "boom"
    assert not list((tmp_path / "in").iterdir())              # download temporaneo rimosso
    with pytest.raises(importer.ImportError_, match="pagina web"):
        importer.import_source(base + "/pagina", tmp_path / "Suoni")


def test_import_from_myinstants_page(http, tmp_path, monkeypatch):
    base, routes = http
    monkeypatch.setattr(importer, "incoming_dir", lambda: tmp_path / "in")
    write_wav(tmp_path / "s.wav", 0.4)
    page = ('<a href="/en/instant/vine-boom-12/">Vine Boom</a>'
            "<button onclick=\"play('/media/sounds/vine.mp3', 'loader-1', 'vine-boom-12')\"></button>")
    monkeypatch.setattr(importer.myinstants, "_get", lambda url, limit=None: page.encode())
    monkeypatch.setattr(importer.myinstants, "download_bytes", lambda inst: (tmp_path / "s.wav").read_bytes())
    r = importer.import_source("https://www.myinstants.com/en/instant/vine-boom-12/", tmp_path / "Suoni")
    assert r.title == "Vine Boom" and r.path.name == "Vine Boom.mp3"


def test_import_from_youtube_uses_downloader(tmp_path, monkeypatch):
    from soundboard_vst.audio.player import Track

    write_wav(tmp_path / "video.wav", 2.0)
    monkeypatch.setattr(importer.youtube, "available", lambda: True)
    monkeypatch.setattr(importer.youtube, "search", lambda q, count: [Track("Risata epica", "u", "youtube", 2.0)])
    monkeypatch.setattr(importer.youtube, "download", lambda t: tmp_path / "video.wav")
    r = importer.import_source("risata epica", tmp_path / "Suoni", start="0.5")
    assert r.title == "Risata epica" and (tmp_path / "video.wav").exists()     # la cache di YouTube resta
    assert abs(decode(r.path, SR).shape[1] / SR - 1.5) < 0.06


# Entrate e uscite ---------------------------------------------------------------------------------
def test_greeting_rules():
    g = normalize_greetings({"users": {"5": {"name": "Ada", "join": "tromba.wav", "leave": ""}},
                             "default": {"join": "", "leave": "ciao.wav"},
                             "announce": {"enabled": True, "join": "Arriva {nome}!", "leave": ""}})
    assert greeting_action(g, 5, "Ada", "join") == {"cmd": "sound", "key": "tromba.wav"}
    assert greeting_action(g, 5, "Ada", "leave") == {"cmd": "sound", "key": "ciao.wav"}   # quello per tutti
    assert greeting_action(g, 9, "Bob", "join") == {"cmd": "say", "text": "Arriva Bob!"}  # annuncio
    g["announce"]["enabled"] = False
    assert greeting_action(g, 9, "Bob", "join") is None
    g["enabled"] = False
    assert greeting_action(g, 5, "Ada", "join") is None
    assert normalize_greetings({"cooldown": "boh"})["cooldown"] == 30


def test_voice_join_leave_plays_sounds_with_cooldown():
    from soundboard_vst.audio.engine import AudioEngine

    sent = []
    bot = DiscordBot(AudioEngine(48000, 512), lambda s: None, send_command=sent.append)
    bot.greetings = normalize_greetings({"cooldown": 60, "users": {"5": {"join": "tromba.wav"}},
                                         "default": {"leave": "ciao.wav"}})
    ch, other = SimpleNamespace(name="Generale"), SimpleNamespace(name="Altro")
    vc = SimpleNamespace(channel=ch, is_connected=lambda: True)
    ada = SimpleNamespace(id=5, bot=False, display_name="Ada", guild=SimpleNamespace(voice_client=vc))
    state = lambda c: SimpleNamespace(channel=c)
    bot._on_member_voice(ada, state(None), state(ch))           # entra
    bot._on_member_voice(ada, state(ch), state(other))          # esce (va in un altro canale)
    bot._on_member_voice(ada, state(other), state(ch))          # rientra subito: niente raffica
    bot._on_member_voice(ada, state(ch), state(ch))             # muto/smuto: niente
    assert [(c["cmd"], c["key"], c["by"]) for c in sent] == [("sound", "tromba.wav", "Ada (entrata)"),
                                                            ("sound", "ciao.wav", "Ada (uscita)")]
    assert bot.known_users["5"] == "Ada"
    texts = [e.text for e in eventlog.LOG.events()]
    assert "Ada è entrato in #Generale" in texts and "Ada è uscito da #Generale" in texts
    bot._on_member_voice(SimpleNamespace(id=6, bot=True, display_name="Bot", guild=ada.guild), state(None), state(ch))
    assert len(sent) == 2                                       # gli altri bot si ignorano


# Comandi Discord -----------------------------------------------------------------------------------
from test_discord_commands import FakeBot, cmds, interaction, make_state, pad  # noqa: E402,F401


def slash(cmds, name):
    return next(c for c in cmds.tree.get_commands() if c.name == name)


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, text, **kw):
        self.sent.append((text, kw))


def test_aggiungi_suono_with_attachment(cmds, tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "incoming_dir", lambda: tmp_path / "in")
    it = interaction(7)
    it.followup = FakeFollowup()
    it.user.mention = "@Mario"

    class Att:
        filename, size = "risata.ogg", 1000

        async def save(self, path):
            Path(path).write_bytes(b"x")

    asyncio.run(slash(cmds, "aggiungi-suono").callback(it, file=Att(), nome="Ridi"))
    cmd = cmds.bot.sent[-1]
    assert cmd["cmd"] == "import_sound" and cmd["local"] and cmd["name"] == "Ridi"
    assert Path(cmd["source"]).read_bytes() == b"x" and importer.is_incoming(Path(cmd["source"]))
    assert cmds.bot.sent_full[-1]["by"] == "? (Discord)"
    assert it.followup.sent[0][0].startswith("ok import_sound") and "@Mario" in it.followup.sent[0][0]

    it2 = interaction(7)
    asyncio.run(slash(cmds, "aggiungi-suono").callback(it2))  # né file né link
    assert "un** file" in it2.response.calls[0][1]
    it3 = interaction(7)
    asyncio.run(slash(cmds, "aggiungi-suono").callback(it3, link="x", inizio="5", fine="2"))
    assert "dopo l'inizio" in it3.response.calls[0][1]


def test_mio_suono_sets_own_and_needs_rights_for_others(cmds):
    it = interaction(7)
    it.followup = FakeFollowup()
    it.user.display_name = "Mario"
    cmds.bot.state["library"] = [{"key": "tromba.wav", "label": "Tromba", "emoji": ""}]
    asyncio.run(slash(cmds, "mio-suono").callback(it, entrata="Tromba", uscita="-"))
    assert cmds.bot.sent[-1] == {"cmd": "set_greeting", "user": "7", "name": "Mario", "join": "tromba.wav", "leave": ""}
    other = SimpleNamespace(id=8, display_name="Luigi", bot=False)
    it2 = interaction(7)
    asyncio.run(slash(cmds, "mio-suono").callback(it2, entrata="Tromba", utente=other))
    assert "permesso" in it2.response.calls[0][1]               # per altri serve «gestione»
    it3 = interaction(7)
    asyncio.run(slash(cmds, "mio-suono").callback(it3, entrata="sconosciuto"))
    assert "non trovato" in it3.response.calls[0][1]


def test_denials_and_commands_are_logged(cmds):
    it = interaction(7)
    it.user.display_name = "Mario"
    asyncio.run(cmds.press_action(it, "player_toggle"))       # «musica»: non permesso di default
    ev = eventlog.LOG.events()[-1]
    assert ev.category == eventlog.PERMISSION and ev.who == "Mario (Discord)" and "Musica" in ev.text
    asyncio.run(cmds.press_pad(interaction(7), 0, 1))
    assert cmds.bot.sent_full[-1]["by"] == "? (Discord)"


# Finestra: registro, import, comandi remoti --------------------------------------------------------
@pytest.fixture
def win(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from soundboard_vst.app import MainWindow
    from soundboard_vst.config import Config

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(importer, "incoming_dir", lambda: tmp_path / "in")
    (tmp_path / "Suoni").mkdir()
    write_wav(tmp_path / "Suoni" / "applausi.wav", 0.5)
    cfg = Config(tmp_path / "config.json")
    cfg.data["sounds_dir"] = str(tmp_path / "Suoni")
    w = MainWindow(cfg, autostart=False)
    w.app = app
    app.processEvents()
    yield w
    w.bot.stop()
    w.remote.stop()
    w.engine.player.close()
    w.close()


def wait_for(w, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        w.app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_log_shows_who_pressed_what(win):
    win.board.play_key("applausi.wav")                          # clic nella finestra
    win.remote._run({"cmd": "pad", "page": 0, "index": 0, "by": "Mario (Discord)"})   # pulsantiera
    win.remote._run({"cmd": "sound", "key": "applausi.wav"})   # telefono
    rows = [r for r in win.log_view.rows() if "Suoni" in r[0]]
    assert [(r[1], r[2]) for r in rows] == [("Tu", "applausi"), ("Mario (Discord)", "applausi"),
                                            ("Telefono", "applausi")]
    win.log_view.kind.setCurrentIndex(win.log_view.kind.findData(eventlog.PLAYER))
    assert win.log_view.rows() == []
    win.log_view.kind.setCurrentIndex(0)
    win.log_view.search.setText("mario")
    assert len(win.log_view.rows()) == 1


def test_playlist_additions_are_attributed(win):
    from soundboard_vst.audio.player import Track

    win.player_view.add_tracks([Track("Canzone A", "a.mp3"), Track("Canzone B", "b.mp3")], by="Luigi (Discord)")
    ev = [e for e in eventlog.LOG.events() if e.category == eventlog.PLAYER][0]
    assert ev.who == "Luigi (Discord)" and "«Canzone A», «Canzone B»" in ev.text


def test_import_through_remote_command_with_reply(win, tmp_path):
    f = importer.new_incoming(".wav")
    write_wav(f, 1.0)
    replies = []
    win.remote._run({"cmd": "import_sound", "source": str(f), "local": True, "name": "Da Discord",
                     "start": "", "end": "", "by": "Mario (Discord)", "_done": lambda ok, m: replies.append((ok, m))})
    assert wait_for(win, lambda: replies)
    ok, msg = replies[0]
    assert ok and "Da Discord" in msg and "pad 2" in msg
    assert win.board.layout_model.page.slots[1] == "Da Discord.mp3"
    ev = [e for e in eventlog.LOG.events() if e.category == eventlog.IMPORT][0]
    assert ev.who == "Mario (Discord)"
    # un file locale qualsiasi (non arrivato da Discord) viene rifiutato
    win.remote._run({"cmd": "import_sound", "source": str(tmp_path / "Suoni" / "applausi.wav"), "local": True,
                     "_done": lambda ok, m: replies.append((ok, m))})
    win.app.processEvents()
    assert len(replies) == 1
    win.remote._run({"cmd": "import_sound", "source": "https://127.0.0.1:1/x.mp3", "_done":
                     lambda ok, m: replies.append((ok, m))})
    assert wait_for(win, lambda: len(replies) == 2) and replies[1][0] is False


def test_set_greeting_command_updates_config_and_bot(win):
    replies = []
    win.remote._run({"cmd": "set_greeting", "user": "7", "name": "Mario", "join": "applausi.wav", "leave": None,
                     "_done": lambda ok, m: replies.append((ok, m))})
    assert replies[0][0] and "applausi" in replies[0][1]
    assert win.config.data["discord"]["greetings"]["users"]["7"]["join"] == "applausi.wav"
    assert win.bot.greetings["users"]["7"]["join"] == "applausi.wav"
    win.remote._run({"cmd": "set_greeting", "user": "7", "name": "Mario", "join": "", "leave": "",
                     "_done": lambda ok, m: replies.append((ok, m))})
    assert "7" not in win.bot.greetings["users"]
    win.remote._run({"cmd": "set_greeting", "user": "7", "join": "manca.wav",
                     "_done": lambda ok, m: replies.append((ok, m))})
    assert replies[-1][0] is False


def test_settings_tabs_for_permissions_and_greetings(win):
    from soundboard_vst.ui.settings_dialog import SettingsDialog

    win.bot.known_roles = [{"id": "55", "name": "DJ", "guild": "Amici"}]
    win.bot.known_users = {"7": "Mario"}
    dlg = SettingsDialog(win.config, win, directory=lambda: {"roles": win.bot.known_roles,
                                                            "users": win.bot.known_users},
                         sounds=win.sound_choices())
    titles = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    assert titles[-2:] == ["Permessi Discord", "Entrate e uscite"] and titles[2] == "Bot Discord"
    pe = dlg.perm_editor
    assert pe._buttons[("musica", "roles")].isEnabled() and not pe._buttons[("suoni", "roles")].isEnabled()
    pe.perms["groups"]["musica"]["roles"] = ["55"]
    pe._refresh("musica")
    assert pe._buttons[("musica", "roles")].text().startswith("@DJ")
    pe._everyone["controllo"].setChecked(True)
    ge = dlg.greet_editor
    ge._add_row("7", "Mario", "applausi.wav", "")
    ge.announce.setChecked(True)
    dlg._save()
    dc = win.config.data["discord"]
    assert dc["permissions"]["groups"]["musica"]["roles"] == ["55"]
    assert dc["permissions"]["groups"]["controllo"]["everyone"] is True
    assert dc["greetings"]["users"]["7"] == {"name": "Mario", "join": "applausi.wav", "leave": ""}
    assert dc["greetings"]["announce"]["enabled"] is True
    assert dc["commands"] == {"enabled": True}
    dlg.deleteLater()


def test_import_dialog_validation():
    from PySide6.QtWidgets import QApplication

    from soundboard_vst.ui.import_dialog import ImportDialog

    QApplication.instance() or QApplication([])
    d = ImportDialog()
    d._accept()
    assert "link" in d.error.text()
    d.source.setText("https://youtu.be/abcdefghijk")
    d.start.setText("0:10")
    d.end.setText("0:05")
    d._accept()
    assert "dopo" in d.error.text()
    d.end.setText("0:15")
    d._accept()
    assert d.result() == 1 and d.values()["start"] == "0:10"
