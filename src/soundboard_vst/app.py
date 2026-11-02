"""Finestra principale."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QTabWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from . import APP_NAME, __version__, discord_bot, midi, midi_map
from .audio import devices
from .audio.engine import AudioEngine
from .audio.library import SoundCache, decode
from .audio.plugins import scan_vst3
from .discord_bot import DiscordBot
from .config import Config, config_dir
from .ui import theme
from .ui.mixer_view import MixerView
from .ui.player_view import PlayerView
from .ui.remote_view import RemoteController, RemoteDialog
from .ui.myinstants_dialog import MyInstantsDialog
from .ui.settings_dialog import SettingsDialog
from .ui.sound_dialog import MidiBridge
from .ui.soundboard_view import SoundboardView


class BotSignals(QObject):
    """Riporta gli stati del bot (thread di discord.py) nel thread dell'interfaccia."""
    status = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self, config: Config, autostart: bool = True):
        super().__init__()
        self.config = config
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 760)

        a = config.data["audio"]
        self.engine = AudioEngine(a.get("sample_rate", 48000), a.get("block_size", 512))
        self.cache = SoundCache(self.engine.sample_rate)
        self._vst_cache: list[Path] | None = None
        self._echo_warned: tuple = ()
        self._save_timer = QTimer(self, singleShot=True, interval=800)
        self._save_timer.timeout.connect(self.save)

        # Barra superiore ---------------------------------------------------------
        title = QLabel(APP_NAME)
        title.setStyleSheet("font-size: 14pt; font-weight: 700;")
        self.audio_btn = QPushButton("Avvia audio")
        self.audio_btn.setObjectName("primary")
        self.audio_btn.clicked.connect(self.toggle_audio)
        settings_btn = QPushButton("Impostazioni")
        settings_btn.clicked.connect(self.open_settings)
        self.route_label = QLabel()
        self.route_label.setStyleSheet(f"color: {theme.MUTED};")
        header = QHBoxLayout()
        header.addWidget(title)
        header.addSpacing(16)
        header.addWidget(self.route_label, 1)
        self.bot_btn = QToolButton()
        self.bot_btn.setText("🤖  Bot spento")
        self.bot_btn.setToolTip("Bot Discord")
        self.bot_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._bot_menu = QMenu(self)
        self._bot_menu.aboutToShow.connect(self._build_bot_menu)
        self.bot_btn.setMenu(self._bot_menu)
        header.addWidget(self.bot_btn)
        self.bot_power = QToolButton(text="⏻")
        self.bot_power.clicked.connect(self.toggle_bot)
        self.bot_join = QToolButton(text="Entra")
        self.bot_join.clicked.connect(self.join_bot)
        self.bot_leave = QToolButton(text="Esci")
        self.bot_leave.clicked.connect(self.leave_bot)
        for b in (self.bot_power, self.bot_join, self.bot_leave):
            header.addWidget(b)
        header.addSpacing(8)
        self.remote_btn = QToolButton(text="📱")
        self.remote_btn.setToolTip("Controllo remoto: link e QR code per il telefono")
        self.remote_btn.clicked.connect(self.show_remote)
        header.addWidget(self.remote_btn)
        header.addWidget(settings_btn)
        header.addWidget(self.audio_btn)

        # Tab: Soundboard e Mixer ----------------------------------------------------
        self.board = SoundboardView(config, self.cache)
        self.board.play_requested.connect(self.play_sound)
        self.board.stop_requested.connect(self.engine.stop_sounds)
        self.board.myinstants_requested.connect(self.open_myinstants)
        self.board.changed.connect(self.schedule_save)
        self.board.sounds_reloaded.connect(self.preload_sounds)

        self.mixer = MixerView(self.engine, self.vst_plugins, self.rescan_vst)
        self.mixer.changed.connect(self.schedule_save)
        mixer_page = QWidget()
        mp = QVBoxLayout(mixer_page)
        mp.setContentsMargins(0, 8, 0, 0)
        mp.addWidget(self.mixer, 1)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        self.engine.player.load_dict(config.data.get("player", {}))
        self.player_view = PlayerView(self.engine.player, self.engine.player_strip)
        self.player_view.changed.connect(self.schedule_save)
        self.player_view.level_changed.connect(lambda: (self.mixer.sync_levels(), self.schedule_save()))

        self.tabs.addTab(self.board, "Soundboard")
        self.tabs.addTab(self.player_view, "Player")
        self.tabs.addTab(mixer_page, "Mixer")
        self.tabs.currentChanged.connect(lambda _: self.schedule_save())
        self._myinstants: MyInstantsDialog | None = None

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(12, 10, 12, 8)
        lay.addLayout(header)
        lay.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self.status_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_label)

        # Stato salvato -------------------------------------------------------------
        errors = self.engine.load_dict(config.data.get("mixer", {}))
        self.mixer.sync_from_model()
        self._restore_window()

        self._ui_timer = QTimer(self, interval=33)
        self._ui_timer.timeout.connect(self._tick)
        self._ui_timer.start()

        if errors:
            QTimer.singleShot(300, lambda: QMessageBox.warning(
                self, "Plugin non caricati", "Alcuni inserti non sono stati ripristinati:\n\n" + "\n".join(errors)))
        self._bot_conflict_shown = False
        self.bot_signals = BotSignals()
        self.bot_signals.status.connect(self._on_bot_status)
        self.bot = DiscordBot(self.engine, self.bot_signals.status.emit)
        self.player_view.started.connect(self.bot.notify_sound)
        self._settings_dialog = None
        self._shortcuts: list[QShortcut] = []
        self.apply_bot_shortcuts()
        self._update_bot_buttons()
        self.remote = RemoteController(self)
        self.remote.status_changed.connect(self._update_remote_button)
        self.remote.apply()
        self.midi_bridge = MidiBridge()
        self.midi_bridge.event.connect(self._on_midi)
        self.midi_in = midi.MidiInput()
        self.board.midi_bridge = self.midi_bridge
        QTimer.singleShot(0, self.preload_sounds)
        if autostart:
            QTimer.singleShot(0, self.first_start)
            QTimer.singleShot(0, self.open_midi)
            if config.data["discord"].get("autostart") and config.data["discord"].get("token"):
                QTimer.singleShot(0, self.start_bot)

    # Audio --------------------------------------------------------------------------
    def first_start(self) -> None:
        a = self.config.data["audio"]
        if not devices.audio_available():
            self._show_status("PortAudio non disponibile: l'audio non può partire.")
            return
        if not a.get("host_api"):
            a["host_api"] = devices.default_host_api()
        api = a["host_api"]
        if not (a.get("input_device") or a.get("virtual_output") or a.get("monitor_output")):
            inp = devices.default_device(api, "input")
            mon = devices.default_device(api, "output")
            virt = devices.guess_virtual_output(api)
            a["input_device"] = inp.name if inp else ""
            a["monitor_output"] = mon.name if mon else ""
            a["virtual_output"] = virt.name if virt else ""
            self.config.save()
            if not virt:
                QMessageBox.information(
                    self, "Cavo audio virtuale",
                    "Non ho trovato un cavo audio virtuale.\n\n"
                    "Per far arrivare i suoni a Discord installa VB-Audio Virtual Cable, riavvia "
                    "e scegli «CABLE Input» in Impostazioni → Uscita verso Discord.\n\n"
                    "Nel frattempo puoi ascoltare i suoni in cuffia.")
        self.start_audio()

    def start_audio(self) -> None:
        a = self.config.data["audio"]
        self.engine.set_format(a.get("sample_rate", 48000), a.get("block_size", 512))
        self.cache.set_sample_rate(self.engine.sample_rate)
        st = self.engine.start(a.get("host_api", ""), a.get("input_device", ""),
                               a.get("virtual_output", ""), a.get("monitor_output", ""))
        self._update_audio_ui()
        if st.warnings:
            self.statusBar().showMessage(" · ".join(st.warnings), 10000)
        if not st.running:
            QMessageBox.warning(self, "Audio", st.message)
            return
        self.check_echo()

    def check_echo(self) -> None:
        """Avvisa se la configurazione fa sentire agli altri la propria voce su Discord."""
        a = self.config.data["audio"]
        risks = devices.echo_risks(a.get("host_api", ""), a.get("input_device", ""),
                                   a.get("virtual_output", ""), a.get("monitor_output", ""))
        key = tuple(risks)
        if not risks or key == self._echo_warned:
            return
        self._echo_warned = key
        QMessageBox.warning(
            self, "Possibile eco su Discord",
            "Con questa configurazione chi è in canale potrebbe sentire la propria voce:\n\n• "
            + "\n\n• ".join(risks))

    def toggle_audio(self) -> None:
        if self.engine.status.running:
            self.engine.stop()
            self._update_audio_ui()
        else:
            self.start_audio()

    def _update_audio_ui(self) -> None:
        st = self.engine.status
        self.audio_btn.setText("Ferma audio" if st.running else "Avvia audio")
        self.audio_btn.setObjectName("" if st.running else "primary")
        self.audio_btn.style().unpolish(self.audio_btn)
        self.audio_btn.style().polish(self.audio_btn)
        self.route_label.setText(st.message)

    def _show_status(self, text: str) -> None:
        self.route_label.setText(text)

    def preload_sounds(self) -> None:
        """Decodifica in anticipo i suoni dei pad, così la prima pressione non aspetta la decodifica."""
        paths = [self.board.path_for(k) for pg in self.board.layout_model.pages for k in pg.slots.values()]
        cache = self.cache

        def run():
            for p in paths:
                try:
                    if p.exists():
                        cache.get(p)
                except Exception:
                    pass

        threading.Thread(target=run, name="preload-sounds", daemon=True).start()

    def play_sound(self, key: str, path: Path, scale: float = 1.0) -> None:
        if not self.engine.status.running:
            self.statusBar().showMessage("Audio fermo: premi «Avvia audio».", 4000)
        try:
            data = self.cache.get(path)
        except Exception as exc:
            QMessageBox.warning(self, "Suono", f"Impossibile leggere {path.name}:\n{exc}")
            return
        vol = float(self.config.data["sounds"].get(key, {}).get("volume", 1.0))
        self.engine.play(key, data, vol * scale, overlap=self.board.overlap.isChecked())
        self.bot.notify_sound()

    # Bot Discord ------------------------------------------------------------------------
    def start_bot(self) -> None:
        dc = self.config.data["discord"]
        if not dc.get("token"):
            QMessageBox.information(self, "Bot Discord",
                                    "Inserisci il token del bot in Impostazioni → Bot Discord.")
            self.open_settings(tab=2)
            return
        try:
            owner = int(dc.get("owner_id") or 0)
        except ValueError:
            owner = 0
        self.bot.continuous = bool(dc.get("continuous", True))
        self.bot.start(dc["token"], owner, dc.get("follow", True))

    def toggle_bot(self) -> None:
        if self.bot.running:
            self.bot.stop()
            self._update_bot_buttons()
        else:
            self.start_bot()

    def join_bot(self) -> None:
        if not self.bot.running:
            self.start_bot()        # con «Segui me» entra da solo appena è online
            if not self.config.data["discord"].get("follow", True):
                QTimer.singleShot(4000, self.bot.join_owner)
        else:
            self.bot.join_owner()

    def leave_bot(self) -> None:
        if self.bot.running:
            self.bot.leave()

    def toggle_follow(self) -> None:
        dc = self.config.data["discord"]
        dc["follow"] = not dc.get("follow", True)
        self.bot.follow = dc["follow"]
        self.statusBar().showMessage("Bot: «Segui me» " + ("attivo" if dc["follow"] else "disattivato"), 4000)
        if dc["follow"] and self.bot.running:
            self.bot.join_owner()
        self.schedule_save()

    def apply_bot_shortcuts(self) -> None:
        for sc in self._shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts = []
        keys = self.config.data["discord"].get("shortcuts", {})
        actions = {"toggle": self.toggle_bot, "join": self.join_bot, "leave": self.leave_bot,
                   "follow": self.toggle_follow}
        for name, fn in actions.items():
            seq = keys.get(name, "")
            if seq:
                sc = QShortcut(QKeySequence(seq), self)
                sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
                sc.activated.connect(fn)
                self._shortcuts.append(sc)
        tip = lambda text, name: text + (f"  ({keys[name]})" if keys.get(name) else "")
        self.bot_power.setToolTip(tip("Avvia / ferma il bot", "toggle"))
        self.bot_join.setToolTip(tip("Fai entrare il bot nel tuo canale vocale", "join"))
        self.bot_leave.setToolTip(tip("Fai uscire il bot dal canale", "leave"))

    def _update_bot_buttons(self) -> None:
        running = self.bot.running
        self.bot_power.setStyleSheet(f"color: {theme.ACCENT_2};" if running else "")
        self.bot_leave.setEnabled(bool(running and self.bot.status.channel))

    def show_remote(self) -> None:
        if not self.config.data["remote"].get("enabled"):
            if QMessageBox.question(self, "Controllo remoto",
                                    "Il controllo remoto è spento. Vuoi attivarlo adesso?") \
                    != QMessageBox.StandardButton.Yes:
                return
            self.config.data["remote"]["enabled"] = True
            self.remote.apply()
            self.config.save()
        RemoteDialog(self.remote, self).exec()

    def _update_remote_button(self) -> None:
        srv = self.remote.server
        on = self.config.data["remote"].get("enabled") and srv.running
        self.remote_btn.setStyleSheet(f"color: {theme.ACCENT_2};" if on else "")
        self.remote_btn.setToolTip(f"Controllo remoto attivo sulla porta {srv.port}" if on else
                                   srv.error or "Controllo remoto spento")

    def _build_bot_menu(self) -> None:
        m = self._bot_menu
        m.clear()
        st = self.bot.status
        if not discord_bot.available():
            a = m.addAction(f"discord.py non disponibile: {discord_bot.unavailable_reason()}")
            a.setEnabled(False)
        elif self.bot.running:
            m.addAction("Entra nel mio canale", self.bot.join_owner)
            follow = m.addAction("Segui me", self.toggle_follow)
            follow.setCheckable(True)
            follow.setChecked(bool(self.config.data["discord"].get("follow", True)))
            leave = m.addAction("Esci dal canale", self.bot.leave)
            leave.setEnabled(bool(st.channel))
            m.addSeparator()
            m.addAction("Ferma il bot", self.bot.stop)
            if self.bot.last_latency_ms is not None:
                info = m.addAction(f"Ultima latenza interna: {self.bot.last_latency_ms:.0f} ms "
                                   "(+ rete e Discord di chi ascolta)")
                info.setEnabled(False)
        else:
            m.addAction("Avvia il bot", self.start_bot)
        m.addSeparator()
        app_id = self.bot.application_id or discord_bot.application_id_from_token(
            self.config.data["discord"].get("token", ""))
        inv = m.addAction("Invita il bot nel server…",
                          lambda: QDesktopServices.openUrl(QUrl(discord_bot.invite_url(app_id))))
        inv.setEnabled(app_id is not None)
        m.addAction("Impostazioni del bot…", lambda: self.open_settings(tab=2))

    def _on_bot_status(self, st) -> None:
        if st.channel:
            text = f"🤖  {st.channel}"
        elif st.online:
            text = "🤖  Bot online"
        elif self.bot.running:
            text = "🤖  Connessione…"
        else:
            text = "🤖  Bot spento"
        if st.conflict:
            text = "🤖  Bot già in uso"
        self.bot_btn.setText(text)
        self.bot_btn.setToolTip(st.message)
        self._update_bot_buttons()
        if st.conflict and not self._bot_conflict_shown:
            self._bot_conflict_shown = True
            QMessageBox.warning(self, "Bot già in uso", st.message)
        elif not st.conflict:
            self._bot_conflict_shown = False
        self.statusBar().showMessage(f"Bot: {st.message}", 6000)
        self._update_exclusive()

    def _update_exclusive(self) -> None:
        exclusive = bool(self.config.data["discord"].get("exclusive", True))
        self.engine.sounds_to_master = not (exclusive and self.bot.status.channel)

    # MIDI ----------------------------------------------------------------------------
    def open_midi(self) -> None:
        name = self.config.data["midi"].get("input", "")
        self.midi_in.close()
        self.board.midi_port = ""
        if not name:
            return
        if not midi.available():
            self.statusBar().showMessage(f"MIDI non disponibile: {midi.unavailable_reason()}", 8000)
            return
        try:
            ok = self.midi_in.open(name, self.midi_bridge.event.emit)
        except Exception as exc:
            ok = False
            self.statusBar().showMessage(f"Errore MIDI: {exc}", 8000)
        if ok:
            self.board.midi_port = self.midi_in.name
            self.statusBar().showMessage(f"Controller MIDI: {self.midi_in.name}", 5000)
        else:
            self.statusBar().showMessage(f"Controller MIDI non trovato: {name}", 8000)

    def _on_midi(self, ev) -> None:
        if self.board.is_learning or (self._settings_dialog is not None and self._settings_dialog.learning):
            return
        targets = midi_map.targets_for(self.config.data.get("midi_map", {}), ev)
        if targets:
            for t in targets:
                self._run_target(t, ev)
            return
        if ev.kind == "cc" and not ev.pressed:
            return
        key = self.board.key_for_midi(ev)
        if key is None:
            return
        path = self.board.path_for(key)
        if not path.exists():
            return
        scale = ev.value / 127.0 if self.config.data["midi"].get("velocity") else 1.0
        self.play_sound(key, path, scale)

    def _run_target(self, target, ev) -> None:
        """Esegue un'azione della mappa MIDI."""
        tid = target.id
        if target.kind == "continuous":
            if ev.kind != "cc":
                return
            _, sid, _ = tid.split(":")
            self.engine.strip(sid).gain_db = midi_map.cc_to_db(ev.value)
            self.mixer.sync_levels()
            self.schedule_save()
            return
        if not ev.pressed:
            return
        player = self.engine.player
        if tid.startswith("strip:") and tid.endswith(":mute"):
            strip = self.engine.strip(tid.split(":")[1])
            strip.mute = not strip.mute
            self.mixer.sync_levels()
            self.schedule_save()
        elif tid == "player:toggle":
            player.toggle() if player.tracks else None
        elif tid == "player:stop":
            player.stop()
        elif tid == "player:next":
            player.next()
        elif tid == "player:prev":
            player.prev()
        elif tid == "sounds:stop":
            self.engine.stop_sounds()
        elif tid.startswith("pads:slot:"):
            self.board.play_slot(int(tid.rsplit(":", 1)[1]))
        elif tid == "pads:page_next":
            self.board.change_page(1)
        elif tid == "pads:page_prev":
            self.board.change_page(-1)
        elif tid == "bot:toggle":
            self.toggle_bot()
        elif tid == "bot:join":
            self.join_bot()
        elif tid == "bot:leave":
            self.leave_bot()
        elif tid == "bot:follow":
            self.toggle_follow()

    # MyInstants -------------------------------------------------------------------------
    def open_myinstants(self) -> None:
        if self._myinstants is None:
            self._myinstants = MyInstantsDialog(lambda: self.board.folder, self.preview_bytes,
                                                self._on_myinstants_added, self)
            self._myinstants.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self._myinstants.destroyed.connect(lambda: setattr(self, "_myinstants", None))
        self._myinstants.show()
        self._myinstants.raise_()
        self._myinstants.activateWindow()

    def _on_myinstants_added(self, path: Path) -> None:
        self.board.add_keys([path.name])

    def preview_bytes(self, data: bytes) -> None:
        """Riproduce un suono scaricato solo in cuffia (non arriva a Discord)."""
        if not self.engine.status.running:
            self.statusBar().showMessage("Audio fermo: premi «Avvia audio».", 4000)
        tmp = config_dir() / "cache" / "anteprima.mp3"
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(data)
            audio = decode(tmp, self.engine.sample_rate)
        except Exception as exc:
            QMessageBox.warning(self, "Anteprima", f"Impossibile riprodurre l'anteprima:\n{exc}")
            return
        self.engine.play("__anteprima__", audio, 1.0, preview=True)

    # VST3 -----------------------------------------------------------------------------
    def vst_plugins(self) -> list[Path]:
        if self._vst_cache is None:
            self._vst_cache = scan_vst3(self.config.vst3_dirs)
        return self._vst_cache

    def rescan_vst(self) -> None:
        self._vst_cache = None
        n = len(self.vst_plugins())
        self.statusBar().showMessage(f"Trovati {n} plugin VST3.", 5000)

    # Impostazioni / salvataggio -----------------------------------------------------
    def open_settings(self, tab: int = 0) -> None:
        old_bot = dict(self.config.data["discord"])
        old_audio = dict(self.config.data["audio"])
        old_midi = self.config.data["midi"].get("input", "")
        dlg = SettingsDialog(self.config, self, midi_bridge=self.midi_bridge)
        dlg.tabs.setCurrentIndex(tab)
        self._settings_dialog = dlg
        try:
            ok = dlg.exec()
        finally:
            self._settings_dialog = None
        if ok:
            self.apply_bot_shortcuts()
            self.remote.apply()
            if self.remote.server.error:
                QMessageBox.warning(self, "Controllo remoto", self.remote.server.error)
            dc = self.config.data["discord"]
            if self.bot.running and (dc["token"] != old_bot.get("token") or dc["owner_id"] != old_bot.get("owner_id")):
                self.start_bot()
            else:
                self.bot.follow = dc.get("follow", True)
                self.bot.continuous = bool(dc.get("continuous", True))
                self._update_exclusive()
            self.config.save()
            self._vst_cache = None
            # riavvia audio e MIDI solo se sono cambiati (un riavvio interrompe per un attimo anche il bot)
            if self.config.data["audio"] != old_audio or not self.engine.status.running:
                self.start_audio()
            if self.config.data["midi"].get("input", "") != old_midi:
                self.open_midi()

    def schedule_save(self) -> None:
        self._save_timer.start()

    def save(self) -> None:
        self.config.data["mixer"] = self.engine.to_dict()
        self.config.data["player"] = self.engine.player.to_dict()
        self.config.data["window"] = {
            "geometry": bytes(self.saveGeometry().toBase64()).decode(),
            "library_splitter": bytes(self.board.splitter.saveState().toBase64()).decode(),
            "tab": self.tabs.currentIndex(),
        }
        try:
            self.config.save()
        except OSError as exc:
            self.statusBar().showMessage(f"Salvataggio impostazioni fallito: {exc}", 8000)

    def _restore_window(self) -> None:
        w = self.config.data.get("window", {})
        if w.get("geometry"):
            self.restoreGeometry(QByteArray.fromBase64(w["geometry"].encode()))
        if w.get("library_splitter"):
            self.board.splitter.restoreState(QByteArray.fromBase64(w["library_splitter"].encode()))
        self.tabs.setCurrentIndex(int(w.get("tab", 0)) if str(w.get("tab", 0)).isdigit() else 0)

    def _tick(self) -> None:
        self.mixer.update_meters()
        self.board.set_playing(self.engine.playing_keys())
        if self.engine.status.running:
            self.status_label.setText(f"{self.engine.sample_rate} Hz · buffer {self.engine.block_size}"
                                      f" · dropout {self.engine.xruns}")
        else:
            self.status_label.setText("Audio fermo")

    def closeEvent(self, event) -> None:
        self.save()
        self.bot.stop()
        self.remote.stop()
        self.engine.player.close()
        self.player_view.shutdown()
        self.engine.stop()
        self.midi_in.close()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLESHEET)
    window = MainWindow(Config())
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
