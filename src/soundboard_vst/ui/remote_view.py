"""Controllo remoto: collega il server web alla GUI e mostra link e QR code."""

from __future__ import annotations

import io
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from .. import discord_bot, youtube
from ..remote.server import RemoteServer, is_tailscale, local_addresses, new_token
from . import theme


class RemoteController(QObject):
    """Prepara l'istantanea dello stato sul thread della GUI ed esegue lì i comandi in arrivo."""

    command = Signal(object)
    status_changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self._state: dict = {}
        self.server = RemoteServer(lambda: self._state, self.command.emit, self._image_for)
        self.command.connect(self._run)
        self._timer = QTimer(self, interval=250)
        self._timer.timeout.connect(self._snapshot)

    # Configurazione ----------------------------------------------------------------------
    @property
    def cfg(self) -> dict:
        return self.w.config.data["remote"]

    def ensure_token(self) -> str:
        if not self.cfg.get("token"):
            self.cfg["token"] = new_token()
            try:
                self.w.config.save()      # i link già condivisi devono restare validi al prossimo avvio
            except OSError:
                pass
        return self.cfg["token"]

    def apply(self) -> None:
        """Avvia o ferma il server secondo le impostazioni."""
        if self.cfg.get("enabled"):
            token = self.ensure_token()
            port = int(self.cfg.get("port", 8765))
            if not (self.server.running and self.server.port == port and self.server.token == token):
                self._snapshot()
                self.server.start(port, token)
            self._timer.start()
        else:
            self.server.stop()
            self._timer.stop()
        self.status_changed.emit()

    def urls(self) -> list[tuple[str, str]]:
        """(descrizione, link completo di chiave) per ogni indirizzo del PC."""
        token, port = self.ensure_token(), int(self.cfg.get("port", 8765))
        out = []
        for ip in local_addresses():
            label = "Tailscale (da ovunque)" if is_tailscale(ip) else "Rete di casa"
            out.append((label, f"http://{ip}:{port}/?k={token}"))
        return out

    def stop(self) -> None:
        self._timer.stop()
        self.server.stop()

    # Stato --------------------------------------------------------------------------------
    def _image_for(self, key: str) -> Path | None:
        cfg = self.w.config.data["sounds"].get(key)        # solo immagini di suoni configurati
        img = cfg.get("image") if cfg else None
        return Path(img) if img else None

    def _snapshot(self) -> None:
        w = self.w
        eng, board = w.engine, w.board
        playing = eng.playing_keys()
        sounds = w.config.data["sounds"]
        existing = set(board._keys)
        lay = board.layout_model
        pages = []
        for pg in lay.pages:
            pads: list = [None] * lay.size
            for i, key in pg.slots.items():
                if 0 <= i < lay.size:
                    c = sounds.get(key, {})
                    pads[i] = {
                        "key": key, "label": c.get("label") or Path(key).stem, "emoji": c.get("emoji", ""),
                        "color": c.get("color", ""), "image": bool(c.get("image")) and Path(c["image"]).is_file(),
                        "playing": key in playing, "missing": key not in existing,
                    }
            pages.append({"name": pg.name, "pads": pads})
        p = eng.player
        cur = p.current
        bot = w.bot
        self._state = {
            "pads": {"pages": pages, "current": lay.current, "cols": lay.cols},
            "player": {
                "state": p.state, "title": cur.title if cur else "", "kind": cur.kind if cur else "",
                "position": p.position if p.state != "stopped" else 0.0,
                "duration": cur.duration if cur else None, "index": p.index,
                "repeat": p.repeat, "shuffle": p.shuffle, "volume_db": eng.player_strip.gain_db,
                "message": w.player_view.last_message,
                "queue": [{"title": t.title, "duration": t.duration, "kind": t.kind} for t in p.tracks[:300]],
            },
            "strips": [{"id": s.id, "name": s.name, "gain_db": s.gain_db, "mute": s.mute} for s in eng.strips],
            "bot": {"available": discord_bot.available(), "running": bot.running, "online": bot.status.online,
                    "channel": bot.status.channel, "message": bot.status.message},
            "audio": {"running": eng.status.running},
        }

    # Comandi --------------------------------------------------------------------------------
    def _run(self, c: dict) -> None:
        w = self.w
        cmd = c.get("cmd")
        try:
            if cmd == "pad":
                w.board.play_page_slot(int(c.get("page", 0)), int(c.get("index", -1)))
            elif cmd == "page":
                w.board.pages.setCurrentIndex(int(c.get("index", 0)))
            elif cmd == "stop_sounds":
                w.engine.stop_sounds()
            elif cmd == "player":
                self._player(c)
            elif cmd == "player_add":
                text = str(c.get("text", ""))[:500]
                if youtube.is_youtube_url(text) or (text and "://" not in text):
                    w.player_view.add_from_text(text, remote=True)
            elif cmd == "strip":
                strip = w.engine.strip(str(c.get("id")))
                if "gain_db" in c:
                    strip.gain_db = max(-60.0, min(12.0, float(c["gain_db"])))
                if "mute" in c:
                    strip.mute = bool(c["mute"])
                w.mixer.sync_levels()
                w.schedule_save()
            elif cmd == "bot":
                action = c.get("action")
                if action == "toggle":
                    w.toggle_bot()
                elif action == "join":
                    w.join_bot()
                elif action == "leave":
                    w.leave_bot()
        except (StopIteration, ValueError, TypeError, KeyError):
            pass      # comando malformato: ignorato
        self._snapshot()

    def _player(self, c: dict) -> None:
        p = self.w.engine.player
        action = c.get("action")
        if action == "toggle" and p.tracks:
            p.toggle()
        elif action == "stop":
            p.stop()
        elif action == "next":
            p.next()
        elif action == "prev":
            p.prev()
        elif action == "play":
            p.play(int(c.get("index", 0)))
        elif action == "seek":
            p.seek(max(0.0, float(c.get("position", 0))))


def qr_pixmap(text: str, scale: int = 6) -> QPixmap | None:
    try:
        import segno
    except Exception:
        return None
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=scale, border=3, dark="#000000", light="#ffffff")
    pix = QPixmap()
    pix.loadFromData(buf.getvalue(), "PNG")
    return pix


class RemoteDialog(QDialog):
    """Link e QR code da aprire sul telefono."""

    def __init__(self, controller: RemoteController, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Controllo remoto")
        self.c = controller
        lay = QVBoxLayout(self)
        srv = controller.server
        if not controller.cfg.get("enabled"):
            msg = QLabel("Il controllo remoto è spento. Attivalo in Impostazioni → Controllo remoto.")
            msg.setWordWrap(True)
            lay.addWidget(msg)
        elif srv.error:
            err = QLabel(srv.error)
            err.setStyleSheet(f"color: {theme.DANGER};")
            err.setWordWrap(True)
            lay.addWidget(err)
        else:
            urls = controller.urls()
            pix = qr_pixmap(urls[0][1])
            if pix is not None:
                qr = QLabel()
                qr.setPixmap(pix)
                qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lay.addWidget(qr)
            hint = QLabel("Inquadra il QR code con il telefono collegato alla stessa rete, oppure apri uno di questi link:")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: {theme.MUTED};")
            lay.addWidget(hint)
            for label, url in urls:
                row = QHBoxLayout()
                text = QLabel(f"<b>{label}</b><br><span style='font-family:Consolas,monospace'>{url}</span>")
                text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                row.addWidget(text, 1)
                copy = QPushButton("Copia")
                copy.clicked.connect(lambda _=False, u=url: QGuiApplication.clipboard().setText(u))
                row.addWidget(copy)
                lay.addLayout(row)
            warn = QLabel("Il link contiene la chiave di accesso: chi lo ha può controllare la soundboard. "
                          "Se lo condividi per sbaglio, genera una nuova chiave nelle impostazioni.")
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
            lay.addWidget(warn)
            open_btn = QPushButton("Apri qui nel browser")
            open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
                f"http://127.0.0.1:{srv.port}/?k={srv.token}")))
            lay.addWidget(open_btn)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
