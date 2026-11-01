"""Finestra principale."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from . import APP_NAME, __version__, midi
from .audio import devices
from .audio.engine import AudioEngine
from .audio.library import SoundCache, decode
from .audio.plugins import scan_vst3
from .config import Config, config_dir
from .ui import theme
from .ui.mixer_view import MixerView
from .ui.myinstants_dialog import MyInstantsDialog
from .ui.settings_dialog import SettingsDialog
from .ui.sound_dialog import MidiBridge
from .ui.soundboard_view import SoundboardView


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
        header.addWidget(settings_btn)
        header.addWidget(self.audio_btn)

        # Tab: Soundboard e Mixer ----------------------------------------------------
        self.board = SoundboardView(config, self.cache)
        self.board.play_requested.connect(self.play_sound)
        self.board.stop_requested.connect(self.engine.stop_sounds)
        self.board.myinstants_requested.connect(self.open_myinstants)
        self.board.changed.connect(self.schedule_save)

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
        self.tabs.addTab(self.board, "Soundboard")
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
        self.midi_bridge = MidiBridge()
        self.midi_bridge.event.connect(self._on_midi)
        self.midi_in = midi.MidiInput()
        self.board.midi_bridge = self.midi_bridge
        if autostart:
            QTimer.singleShot(0, self.first_start)
            QTimer.singleShot(0, self.open_midi)

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
        if self.board.is_learning:
            return
        key = self.board.key_for_midi(ev)
        if key is None:
            return
        path = self.board.path_for(key)
        if not path.exists():
            return
        scale = ev.value / 127.0 if self.config.data["midi"].get("velocity") else 1.0
        self.play_sound(key, path, scale)

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
    def open_settings(self) -> None:
        dlg = SettingsDialog(self.config, self)
        if dlg.exec():
            self.config.save()
            self._vst_cache = None
            self.start_audio()
            self.open_midi()

    def schedule_save(self) -> None:
        self._save_timer.start()

    def save(self) -> None:
        self.config.data["mixer"] = self.engine.to_dict()
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
