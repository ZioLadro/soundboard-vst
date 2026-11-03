"""Controllo remoto: collega il server web alla GUI e mostra link e QR code."""

from __future__ import annotations

import io
import math
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from .. import discord_bot, eventlog, importer, youtube
from ..audio.plugins import BUILTIN_EFFECTS, create_builtin, load_vst3, vst3_names_in_file
from ..eventlog import acting
from ..remote.server import RemoteServer, is_tailscale, local_addresses, new_token
from . import theme


class RemoteController(QObject):
    """Prepara l'istantanea dello stato sul thread della GUI ed esegue lì i comandi in arrivo.

    La usano sia la pagina web sia il bot Discord (comandi slash e pulsantiera).
    """

    command = Signal(object)
    status_changed = Signal()
    _query = Signal(object)

    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self._state: dict = {}
        self.levels: dict = {"strips": {}, "pads": {}}      # aggiornati dalla finestra ~30 volte al secondo
        self._inputs: tuple[float, list[str]] = (0.0, [])
        self.server = RemoteServer(lambda: self._state, self.command.emit, self._image_for,
                                   get_levels=lambda: self.levels, query=self.query)
        self.command.connect(self._run)
        self._query.connect(self._answer)
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

    @property
    def state(self) -> dict:
        return self._state

    def apply(self) -> None:
        """Avvia o ferma il server secondo le impostazioni."""
        if self.cfg.get("enabled"):
            token = self.ensure_token()
            port = int(self.cfg.get("port", 8765))
            if not (self.server.running and self.server.port == port and self.server.token == token):
                self._snapshot()
                self.server.start(port, token)
        else:
            self.server.stop()
        self.update_timer()
        self.status_changed.emit()

    def update_timer(self) -> None:
        """L'istantanea serve finché è attivo il controllo da browser o il bot Discord."""
        if self.cfg.get("enabled") or self.w.bot.running:
            if not self._timer.isActive():
                self._snapshot()
                self._timer.start()
        else:
            self._timer.stop()

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

    # Domande dal server (thread del server → thread dell'interfaccia) ----------------------
    def query(self, name: str, args: dict, timeout: float = 5.0) -> dict | None:
        """Bloccante: da chiamare fuori dal thread dell'interfaccia (lo fa il server)."""
        box: dict = {}
        done = threading.Event()
        self._query.emit((name, args, box, done))
        done.wait(timeout)
        return box.get("result")

    def _answer(self, job) -> None:
        name, args, box, done = job
        try:
            if name == "effects":
                box["result"] = self._effects()
            elif name == "insert":
                box["result"] = self._insert_info(str(args.get("strip")), int(args.get("index", -1)))
        except Exception:
            box["result"] = None
        finally:
            done.set()

    def _input_names(self, refresh: bool = False) -> list[str]:
        """Ingressi audio, ricordati per 10 s (interrogare la scheda audio 4 volte al secondo è inutile)."""
        t, names = self._inputs
        if refresh or time.monotonic() - t > 10:
            names = self.w.input_names()
            self._inputs = (time.monotonic(), names)
        return names

    def _effects(self) -> dict:
        return {"builtin": [{"type": t, "label": label} for t, (label, _) in BUILTIN_EFFECTS.items()],
                "vst": [{"path": str(p), "name": p.stem} for p in self.w.vst_plugins()]}

    def _insert_info(self, strip_id: str, index: int) -> dict | None:
        strip = self.w.engine.strip(strip_id)
        if not 0 <= index < len(strip.inserts):
            return None
        slot = strip.inserts[index]
        params = []
        if slot.kind == "builtin":
            for spec in slot.param_specs():
                params.append({"name": spec.attr, "label": spec.label, "min": spec.minimum, "max": spec.maximum,
                               "value": float(getattr(slot.plugin, spec.attr, spec.default)), "unit": spec.unit})
        else:
            try:
                items = list(slot.plugin.parameters.items())[:400]
            except Exception:
                items = []
            for key, param in items:
                try:
                    value = float(param.raw_value)
                    text = str(param.string_value)
                except Exception:
                    continue
                params.append({"name": key, "label": getattr(param, "name", key), "min": 0.0, "max": 1.0,
                               "value": value, "text": text, "raw": True})
        return {"strip": strip_id, "index": index, "name": slot.display_name, "kind": slot.kind,
                "bypass": slot.bypass, "params": params, "has_editor": slot.has_editor}

    # Stato --------------------------------------------------------------------------------
    def _image_for(self, key: str) -> Path | None:
        cfg = self.w.config.data["sounds"].get(key)        # solo immagini di suoni configurati
        img = cfg.get("image") if cfg else None
        return Path(img) if img else None

    def _snapshot(self) -> None:
        w = self.w
        eng, board = w.engine, w.board
        playing = eng.playing_keys()
        activity = eng.voice_info()
        sounds = w.config.data["sounds"]
        lay = board.layout_model
        pages = []
        for pg in lay.pages:
            pads: list = [None] * lay.size
            for i, key in pg.slots.items():
                if 0 <= i < lay.size:
                    c = sounds.get(key, {})
                    pads[i] = {
                        "key": key, "label": board.display_name(key), "emoji": board._emoji(key),
                        "color": c.get("color", ""), "image": bool(c.get("image")) and Path(c["image"]).is_file(),
                        "playing": key in playing, "missing": not board.exists(key),
                        "duration": round(activity[key][2], 2) if key in activity else None,
                    }
            pages.append({"name": pg.name, "pads": pads})
        library = [{"key": key, "label": board.display_name(key), "emoji": board._emoji(key),
                    "category": board.category_of(key)} for key in board.all_keys()]
        p = eng.player
        cur = p.current
        bot = w.bot
        soloable = set(eng.source_strips)
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
            "strips": [{"id": s.id, "name": s.name, "gain_db": s.gain_db, "mute": s.mute,
                        "pan": round(s.pan, 2), "solo": s.solo, "soloable": s in soloable,
                        "input": s in eng.inputs,
                        "inserts": [{"name": slot.display_name, "kind": slot.kind, "bypass": slot.bypass,
                                     "failed": slot.failed} for slot in s.inserts]} for s in eng.strips],
            "mic": {"inputs": self._input_names(), "input": w.config.data["audio"].get("input_device", ""),
                    "to_bot": eng.mic_to_bot},
            "inputs": [{"id": s.id, "name": s.name, "device": s.device, "to_bot": s.to_bot, "hear": s.hear,
                        "channels": s.channel_label, "mono": s.mono} for s in eng.inputs],
            "monitor": {"hear_sounds": eng.monitor_hear_sounds, "hear_tts": eng.monitor_hear_tts,
                        "hear_player": eng.monitor_hear_player, "hear_mic": eng.monitor_hear_mic},
            "bot": {"available": discord_bot.available(), "running": bot.running, "online": bot.status.online,
                    "channel": bot.status.channel, "message": bot.status.message},
            "audio": {"running": eng.status.running},
            "library": library,       # tutti i suoni della cartella (per /suona su Discord)
        }

    # Comandi --------------------------------------------------------------------------------
    def _run(self, c: dict) -> None:
        """Esegue un comando del telefono (``by`` assente) o del bot Discord (``by`` = utente)."""
        who = str(c.get("by") or "Telefono")[:80]
        with acting(who):
            self._execute(c)
        self._snapshot()

    def _execute(self, c: dict) -> None:
        w = self.w
        cmd = c.get("cmd")
        try:
            if cmd == "pad":
                w.board.play_page_slot(int(c.get("page", 0)), int(c.get("index", -1)))
            elif cmd == "page":
                w.board.pages.setCurrentIndex(int(c.get("index", 0)))
            elif cmd == "sound":
                key = str(c.get("key", ""))
                if w.board.exists(key):          # solo file della cartella o frasi esistenti
                    w.board.play_key(key, quiet=True)
            elif cmd == "import_sound":
                done = c.get("_done") if callable(c.get("_done")) else None
                local = bool(c.get("local"))
                source = str(c.get("source", ""))[:1000]
                if local and not importer.is_incoming(Path(source)):
                    return                            # file locali solo se arrivati da Discord
                w.import_sound(source, str(c.get("name") or "")[:80], str(c.get("start") or ""),
                               str(c.get("end") or ""), local=local, done=done, who=eventlog.current_actor())
            elif cmd == "set_greeting":
                done = c.get("_done") if callable(c.get("_done")) else None
                join, leave, mute, unmute = c.get("join"), c.get("leave"), c.get("mute"), c.get("unmute")
                for k in (join, leave, mute, unmute):
                    if k and not w.board.exists(k):
                        if done:
                            done(False, "❌ Suono non trovato nella soundboard.")
                        return
                entry = w.set_greeting(str(c.get("user")), str(c.get("name") or ""), join, leave, mute, unmute)
                describe = lambda k: f"**{w.board.display_name(k)}**" if k else "niente"
                plain = lambda k: w.board.display_name(k) if k else "—"
                eventlog.log(eventlog.DISCORD, f"Suoni di {entry['name']}: entrata {plain(entry['join'])}, uscita "
                             f"{plain(entry['leave'])}, muto {plain(entry['mute'])}, smuto {plain(entry['unmute'])}")
                if done:
                    done(True, f"Fatto, per {entry['name']}: entra → {describe(entry['join'])}, esce → "
                               f"{describe(entry['leave'])}, si muta → {describe(entry['mute'])}, "
                               f"si smuta → {describe(entry['unmute'])}.")
            elif cmd == "say":
                text = str(c.get("text", ""))[:300]
                if text.strip():
                    w.speak(text)
            elif cmd == "stop_sounds":
                w.engine.stop_sounds()
                eventlog.log(eventlog.SOUND, "■ Ferma tutti i suoni")
            elif cmd == "player":
                self._player(c)
            elif cmd == "player_add":
                text = str(c.get("text", ""))[:500]
                if youtube.is_youtube_url(text) or (text and "://" not in text):
                    eventlog.log(eventlog.PLAYER, f"Chiede di aggiungere: {text}")
                    w.player_view.add_from_text(text, remote=True, by=eventlog.current_actor())
            elif cmd == "strip":
                strip = w.engine.strip(str(c.get("id")))
                if "gain_db" in c:
                    strip.gain_db = max(-60.0, min(12.0, float(c["gain_db"])))
                    if c.get("by"):                   # dal telefono arrivano tanti valori mentre si trascina
                        eventlog.log(eventlog.DISCORD, f"Volume {strip.name}: {strip.gain_db:+.1f} dB")
                if "mute" in c:
                    strip.mute = bool(c["mute"])
                    eventlog.log(eventlog.SOUND, f"{'Muto' if strip.mute else 'Audio attivo'}: {strip.name}")
                if "pan" in c:
                    strip.pan = max(-1.0, min(1.0, float(c["pan"])))
                if "solo" in c and strip in w.engine.source_strips:
                    strip.solo = bool(c["solo"])
                    eventlog.log(eventlog.SOUND, f"{'Solo' if strip.solo else 'Fine solo'}: {strip.name}")
                w.mixer.sync_levels()
                w.schedule_save()
            elif cmd == "input":
                strip = w.engine.input_strip(str(c.get("id")))
                if strip is None:
                    return
                if "to_bot" in c:
                    ui = w.mixer._input_ui.get(strip.id)
                    if ui is not None:
                        ui["to_bot"].setChecked(bool(c["to_bot"]))   # come il clic nel mixer del PC
                if "hear" in c:
                    strip.hear = bool(c["hear"])
                    w.mixer.sync_from_model()
                    w.schedule_save()
                if "device" in c:
                    name = str(c["device"])
                    if name == "" or name in self._input_names(refresh=True):
                        if strip.id == "mic":
                            w.set_input_device(name)
                        else:
                            w.set_input_device(name, strip.id)
            elif cmd == "insert":
                self._insert(c)
            elif cmd == "mic":
                if "to_bot" in c and hasattr(w.mixer, "mic_to_bot"):
                    w.mixer.mic_to_bot.setChecked(bool(c["to_bot"]))   # come il clic nel mixer del PC
                if "input" in c:
                    name = str(c["input"])
                    if name == "" or name in self._input_names(refresh=True):
                        w.set_input_device(name)
            elif cmd == "monitor":
                for key in ("hear_sounds", "hear_tts", "hear_player", "hear_mic"):
                    if key in c:
                        setattr(w.engine, f"monitor_{key}", bool(c[key]))
                w.mixer.sync_from_model()
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

    def _insert(self, c: dict) -> None:
        """Inserti di un canale dal telefono: aggiungi, togli, sposta, bypass, parametri."""
        w = self.w
        strip = w.engine.strip(str(c.get("strip")))
        action = c.get("action")
        index = int(c.get("index", -1)) if "index" in c else -1
        slot = strip.inserts[index] if 0 <= index < len(strip.inserts) else None
        if action == "add":
            t = str(c.get("type"))
            if t in BUILTIN_EFFECTS:
                strip.add_insert(create_builtin(t))
                eventlog.log(eventlog.SOUND, f"Inserto {BUILTIN_EFFECTS[t][0]} aggiunto su {strip.name}")
        elif action == "add_vst":
            path = str(c.get("path", ""))
            if path not in {str(p) for p in w.vst_plugins()}:
                return                                    # solo plugin delle cartelle VST3 già analizzate
            names = vst3_names_in_file(path)
            try:
                new = load_vst3(path, names[0] if len(names) > 1 else None)
            except Exception as exc:
                eventlog.log(eventlog.ERROR, f"Plugin {Path(path).stem} non caricato: {exc}")
                return
            strip.add_insert(new)
            eventlog.log(eventlog.SOUND, f"Plugin {new.display_name} aggiunto su {strip.name}")
        elif action == "rescan":
            w.rescan_vst()
        elif slot is None:
            return
        elif action == "remove":
            strip.remove_insert(slot)
            eventlog.log(eventlog.SOUND, f"Inserto {slot.display_name} tolto da {strip.name}")
        elif action == "move":
            strip.move_insert(slot, -1 if int(c.get("delta", 0)) < 0 else 1)
        elif action == "bypass":
            slot.bypass = bool(c.get("value"))
            if not slot.bypass:
                slot.failed = False                       # riprova dopo un errore
        elif action == "param":
            name, value = str(c.get("name")), float(c.get("value"))
            if not math.isfinite(value):
                return
            if slot.kind == "builtin":
                spec = next((sp for sp in slot.param_specs() if sp.attr == name), None)
                if spec is not None:
                    setattr(slot.plugin, name, max(spec.minimum, min(spec.maximum, value)))
            else:
                param = slot.plugin.parameters.get(name)
                if param is not None:
                    param.raw_value = max(0.0, min(1.0, value))
        else:
            return
        w.mixer.sync_from_model()
        w.schedule_save()

    def _player(self, c: dict) -> None:
        p = self.w.engine.player
        action = c.get("action")
        names = {"toggle": "Play/Pausa", "stop": "Stop", "next": "Brano successivo", "prev": "Brano precedente",
                 "play": "Riproduci dalla coda"}
        if action in names:
            eventlog.log(eventlog.PLAYER, names[action])
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
