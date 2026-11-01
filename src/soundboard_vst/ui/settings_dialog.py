"""Impostazioni: dispositivi audio e cartelle dei plugin VST3."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QPushButton, QVBoxLayout,
)

from ..audio import devices
from ..config import Config, default_vst3_dirs
from . import theme

NONE_LABEL = "— nessuno —"


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Impostazioni")
        self.setMinimumWidth(560)
        self.config = config
        a = config.data["audio"]

        # Audio -------------------------------------------------------------------
        self.host_api = QComboBox()
        self.input = QComboBox()
        self.virtual = QComboBox()
        self.monitor = QComboBox()
        self.sample_rate = QComboBox()
        for sr in (44100, 48000, 96000):
            self.sample_rate.addItem(f"{sr} Hz", sr)
        self.sample_rate.setCurrentIndex(max(0, self.sample_rate.findData(a.get("sample_rate", 48000))))
        self.block = QComboBox()
        for b in (128, 256, 512, 1024, 2048):
            ms = b / 48000 * 1000
            self.block.addItem(f"{b} campioni (~{ms:.0f} ms)", b)
        self.block.setCurrentIndex(max(0, self.block.findData(a.get("block_size", 512))))

        refresh = QPushButton("Aggiorna elenco")
        refresh.clicked.connect(self._fill_devices)
        self.host_api.currentIndexChanged.connect(self._fill_devices)

        hint = QLabel(
            "Per mandare l'audio a Discord installa un cavo virtuale (es. <b>VB-Audio Virtual Cable</b>), "
            "scegli <b>CABLE Input</b> come «Uscita verso Discord» e in Discord imposta "
            "<b>CABLE Output</b> come dispositivo di input. Su Windows è consigliato WASAPI."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setStyleSheet(f"color: {theme.MUTED};")

        audio_box = QGroupBox("Audio")
        form = QFormLayout(audio_box)
        api_row = QHBoxLayout()
        api_row.addWidget(self.host_api, 1)
        api_row.addWidget(refresh)
        form.addRow("Driver (host API)", api_row)
        form.addRow("Ingresso (microfono / scheda)", self.input)
        form.addRow("Uscita verso Discord", self.virtual)
        form.addRow("Monitor (cuffie)", self.monitor)
        form.addRow("Frequenza", self.sample_rate)
        form.addRow("Buffer", self.block)
        form.addRow(hint)

        if not devices.audio_available():
            warn = QLabel("PortAudio non disponibile: impossibile elencare i dispositivi.")
            warn.setStyleSheet(f"color: {theme.DANGER};")
            form.addRow(warn)

        # VST3 ---------------------------------------------------------------------
        vst_box = QGroupBox("Cartelle plugin VST3")
        self.vst_dirs = QListWidget()
        self.vst_dirs.setObjectName("inserts")
        self.vst_dirs.addItems(config.vst3_dirs)
        self.vst_dirs.setMaximumHeight(110)
        add = QPushButton("Aggiungi…")
        add.clicked.connect(self._add_dir)
        rm = QPushButton("Rimuovi")
        rm.clicked.connect(lambda: self.vst_dirs.takeItem(self.vst_dirs.currentRow()))
        reset = QPushButton("Predefinite")
        reset.clicked.connect(self._reset_dirs)
        btns = QVBoxLayout()
        for b in (add, rm, reset):
            btns.addWidget(b)
        btns.addStretch(1)
        row = QHBoxLayout(vst_box)
        row.addWidget(self.vst_dirs, 1)
        row.addLayout(btns)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(audio_box)
        lay.addWidget(vst_box)
        lay.addWidget(buttons)

        self._fill_host_apis()

    # Dispositivi ----------------------------------------------------------------
    def _fill_host_apis(self) -> None:
        apis = devices.host_apis()
        self.host_api.blockSignals(True)
        self.host_api.clear()
        self.host_api.addItems(apis)
        current = self.config.data["audio"].get("host_api") or devices.default_host_api()
        if current in apis:
            self.host_api.setCurrentText(current)
        self.host_api.blockSignals(False)
        self._fill_devices()

    def _fill_devices(self) -> None:
        api = self.host_api.currentText()
        a = self.config.data["audio"]
        ins = devices.inputs(api)
        outs = devices.outputs(api)

        def fill(combo: QComboBox, items, selected: str, mark_virtual=False):
            prev = combo.currentData() if combo.count() else None
            combo.clear()
            combo.addItem(NONE_LABEL, "")
            for d in items:
                label = d.name + ("   ★ cavo virtuale" if mark_virtual and d.looks_virtual else "")
                combo.addItem(label, d.name)
            target = prev if prev else selected
            idx = combo.findData(target)
            combo.setCurrentIndex(idx if idx >= 0 else 0)

        fill(self.input, ins, a.get("input_device", ""))
        fill(self.virtual, outs, a.get("virtual_output", ""), mark_virtual=True)
        fill(self.monitor, outs, a.get("monitor_output", ""))
        if not self.virtual.currentData():
            guess = devices.guess_virtual_output(api)
            if guess:
                self.virtual.setCurrentIndex(self.virtual.findData(guess.name))

    # VST3 --------------------------------------------------------------------------
    def _add_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Cartella plugin VST3")
        if d:
            self.vst_dirs.addItem(d)

    def _reset_dirs(self) -> None:
        self.vst_dirs.clear()
        self.vst_dirs.addItems(default_vst3_dirs())

    def _save(self) -> None:
        a = self.config.data["audio"]
        a["host_api"] = self.host_api.currentText()
        a["input_device"] = self.input.currentData() or ""
        a["virtual_output"] = self.virtual.currentData() or ""
        a["monitor_output"] = self.monitor.currentData() or ""
        a["sample_rate"] = int(self.sample_rate.currentData())
        a["block_size"] = int(self.block.currentData())
        dirs = [self.vst_dirs.item(i).text() for i in range(self.vst_dirs.count())]
        self.config.data["vst3_dirs"] = [] if dirs == default_vst3_dirs() else dirs
        self.accept()
