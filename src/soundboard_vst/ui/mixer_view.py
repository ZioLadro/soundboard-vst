"""Sezione mixer: un canale per Microfono, Soundboard, Master e Monitor."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from ..audio.engine import AudioEngine
from ..audio.mixer import ChannelStrip
from ..audio.plugins import BUILTIN_EFFECTS, InsertSlot, create_builtin, load_vst3, vst3_names_in_file
from .meter import DbFader, LevelMeter, format_db
from .plugin_dialogs import edit_slot, open_native_editor

SLOT_ROLE = Qt.ItemDataRole.UserRole + 1


class StripWidget(QFrame):
    changed = Signal()                       # qualcosa da salvare

    def __init__(self, strip: ChannelStrip, vst_list: Callable[[], list[Path]],
                 rescan: Callable[[], None], parent=None):
        super().__init__(parent)
        self.strip = strip
        self._vst_list = vst_list
        self._rescan = rescan
        self.setObjectName("panel")
        self.setMinimumWidth(190)

        title = QLabel(strip.name)
        title.setObjectName("stripTitle")

        # Inserti -------------------------------------------------------------
        ins_label = QLabel("INSERTI")
        ins_label.setObjectName("sectionTitle")
        self.inserts = QListWidget()
        self.inserts.setObjectName("inserts")
        self.inserts.setMinimumHeight(90)
        self.inserts.setToolTip("Spunta = attivo, togli la spunta per il bypass.\n"
                                "Doppio clic per aprire il plugin.")
        self.inserts.itemChanged.connect(self._on_item_changed)
        self.inserts.itemDoubleClicked.connect(lambda it: self._open(it, native=True))
        self.inserts.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.inserts.customContextMenuRequested.connect(self._context_menu)

        add_btn = QToolButton(text="+")
        add_btn.setObjectName("small")
        add_btn.setToolTip("Aggiungi inserto")
        add_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._add_menu = QMenu(self)
        self._add_menu.aboutToShow.connect(self._build_add_menu)
        add_btn.setMenu(self._add_menu)
        rm_btn = self._small("−", "Rimuovi inserto selezionato", self._remove)
        up_btn = self._small("▲", "Sposta su", lambda: self._move(-1))
        down_btn = self._small("▼", "Sposta giù", lambda: self._move(1))
        edit_btn = self._small("✎", "Apri plugin / parametri", lambda: self._open(self.inserts.currentItem(), True))
        ins_bar = QHBoxLayout()
        ins_bar.setSpacing(4)
        for b in (add_btn, rm_btn, up_btn, down_btn, edit_btn):
            ins_bar.addWidget(b)
        ins_bar.addStretch(1)

        # Fader + meter ---------------------------------------------------------
        self.fader = DbFader()
        self.fader.set_db(strip.gain_db)
        self.fader.db_changed.connect(self._on_fader)
        self.meter = LevelMeter()
        self.db_label = QLabel(format_db(strip.gain_db))
        self.db_label.setObjectName("dbLabel")
        self.db_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fm = QHBoxLayout()
        fm.addStretch(1)
        fm.addWidget(self.fader)
        fm.addSpacing(10)
        fm.addWidget(self.meter)
        fm.addStretch(1)

        self.mute = QPushButton("MUTE")
        self.mute.setObjectName("mute")
        self.mute.setCheckable(True)
        self.mute.setChecked(strip.mute)
        self.mute.toggled.connect(self._on_mute)

        self.extra = QVBoxLayout()   # spazio per opzioni specifiche (monitor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(title)
        lay.addWidget(ins_label)
        lay.addWidget(self.inserts)
        lay.addLayout(ins_bar)
        lay.addLayout(self.extra)
        lay.addLayout(fm, 1)
        lay.addWidget(self.db_label)
        lay.addWidget(self.mute)
        self.refresh_inserts()

    def _small(self, text, tip, fn):
        b = QToolButton(text=text)
        b.setObjectName("small")
        b.setToolTip(tip)
        b.clicked.connect(fn)
        return b

    # Sincronizzazione con il modello ------------------------------------------
    def sync_from_model(self) -> None:
        self.fader.blockSignals(True)
        self.fader.set_db(self.strip.gain_db)
        self.fader.blockSignals(False)
        self.db_label.setText(format_db(self.strip.gain_db))
        self.mute.blockSignals(True)
        self.mute.setChecked(self.strip.mute)
        self.mute.blockSignals(False)
        self.refresh_inserts()

    def sync_levels(self) -> None:
        if self.fader.value() != int(round(self.strip.gain_db * 10)):
            self.fader.blockSignals(True)
            self.fader.set_db(self.strip.gain_db)
            self.fader.blockSignals(False)
            self.db_label.setText(format_db(self.strip.gain_db))
        if self.mute.isChecked() != self.strip.mute:
            self.mute.blockSignals(True)
            self.mute.setChecked(self.strip.mute)
            self.mute.blockSignals(False)

    def refresh_inserts(self, select: InsertSlot | None = None) -> None:
        self.inserts.blockSignals(True)
        self.inserts.clear()
        for slot in self.strip.inserts:
            text = slot.display_name + ("  (errore)" if slot.failed else "")
            it = QListWidgetItem(text)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked if slot.bypass else Qt.CheckState.Checked)
            it.setData(SLOT_ROLE, slot)
            it.setToolTip(slot.path or "Effetto integrato")
            self.inserts.addItem(it)
            if slot is select:
                self.inserts.setCurrentItem(it)
        self.inserts.blockSignals(False)

    def update_meter(self) -> None:
        self.meter.set_peaks(*self.strip.take_peak())

    # Azioni ------------------------------------------------------------------
    def _on_fader(self, db: float) -> None:
        self.strip.gain_db = db
        self.db_label.setText(format_db(db))
        self.changed.emit()

    def _on_mute(self, on: bool) -> None:
        self.strip.mute = on
        self.changed.emit()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        slot: InsertSlot = item.data(SLOT_ROLE)
        slot.bypass = item.checkState() != Qt.CheckState.Checked
        if not slot.bypass:
            slot.failed = False  # riprova dopo un errore
        self.changed.emit()

    def _current_slot(self) -> InsertSlot | None:
        it = self.inserts.currentItem()
        return it.data(SLOT_ROLE) if it else None

    def _build_add_menu(self) -> None:
        m = self._add_menu
        m.clear()
        builtin = m.addMenu("Effetti integrati")
        for type_name, (label, _) in BUILTIN_EFFECTS.items():
            act = builtin.addAction(label)
            act.triggered.connect(lambda _=False, t=type_name: self._add_builtin(t))
        vst = m.addMenu("Plugin VST3")
        plugins = self._vst_list()
        if not plugins:
            a = vst.addAction("Nessun plugin trovato nelle cartelle VST3")
            a.setEnabled(False)
        for p in plugins:
            a = vst.addAction(p.stem)
            a.setToolTip(str(p))
            a.triggered.connect(lambda _=False, path=p: self._add_vst(str(path)))
        vst.addSeparator()
        vst.addAction("Riscansiona cartelle", self._rescan)
        m.addAction("Sfoglia file VST3…", self._browse_vst)

    def _add_builtin(self, type_name: str) -> None:
        slot = create_builtin(type_name)
        self.strip.add_insert(slot)
        self.refresh_inserts(select=slot)
        self.changed.emit()

    def _browse_vst(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Scegli un plugin VST3", "", "Plugin VST3 (*.vst3)")
        if path:
            self._add_vst(path)

    def _add_vst(self, path: str) -> None:
        name = None
        names = vst3_names_in_file(path)
        if len(names) > 1:
            name, ok = QInputDialog.getItem(self, "Plugin multiplo",
                                            "Questo file contiene più plugin. Quale vuoi caricare?",
                                            names, 0, False)
            if not ok:
                return
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            slot = load_vst3(path, name)
        except Exception as exc:
            QMessageBox.warning(self, "Plugin VST3", f"Impossibile caricare il plugin:\n{path}\n\n{exc}")
            return
        finally:
            self.unsetCursor()
        self.strip.add_insert(slot)
        self.refresh_inserts(select=slot)
        self.changed.emit()

    def _remove(self) -> None:
        slot = self._current_slot()
        if slot:
            self.strip.remove_insert(slot)
            self.refresh_inserts()
            self.changed.emit()

    def _move(self, delta: int) -> None:
        slot = self._current_slot()
        if slot:
            self.strip.move_insert(slot, delta)
            self.refresh_inserts(select=slot)
            self.changed.emit()

    def _open(self, item: QListWidgetItem | None, native: bool) -> None:
        if item is None:
            return
        slot: InsertSlot = item.data(SLOT_ROLE)
        if native and slot.has_editor:
            window = self.window()
            if hasattr(window, "statusBar"):
                window.statusBar().showMessage(
                    f"Editor di {slot.display_name} aperto: chiudilo per tornare alla soundboard.")
            # lascia ridisegnare la status bar prima che l'editor blocchi il thread
            QTimer.singleShot(50, lambda: (open_native_editor(slot, self), self.changed.emit()))
        else:
            edit_slot(slot, self)
            self.changed.emit()

    def _context_menu(self, pos) -> None:
        item = self.inserts.itemAt(pos)
        if not item:
            return
        slot: InsertSlot = item.data(SLOT_ROLE)
        m = QMenu(self)
        if slot.has_editor:
            m.addAction("Apri interfaccia plugin", lambda: self._open(item, True))
        m.addAction("Parametri…", lambda: self._open(item, False))
        m.addSeparator()
        m.addAction("Rimuovi", self._remove)
        m.exec(self.inserts.mapToGlobal(pos))


class MixerView(QWidget):
    changed = Signal()

    def __init__(self, engine: AudioEngine, vst_list: Callable[[], list[Path]],
                 rescan: Callable[[], None], parent=None):
        super().__init__(parent)
        self.engine = engine
        self.strips: list[StripWidget] = []
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for strip in engine.strips:
            w = StripWidget(strip, vst_list, rescan)
            w.changed.connect(self.changed)
            self.strips.append(w)
            row.addWidget(w)
            if strip is engine.monitor:
                self._add_monitor_options(w)

    def _add_monitor_options(self, w: StripWidget) -> None:
        label = QLabel("ASCOLTA")
        label.setObjectName("sectionTitle")
        self.hear_sounds = QCheckBox("Suoni")
        self.hear_mic = QCheckBox("Microfono")
        self.hear_sounds.setChecked(self.engine.monitor_hear_sounds)
        self.hear_mic.setChecked(self.engine.monitor_hear_mic)
        self.hear_mic.setToolTip("Sentirti in cuffia (con i tuoi inserti). Attenzione al feedback con le casse.")
        self.hear_player = QCheckBox("Player")
        self.hear_player.setChecked(self.engine.monitor_hear_player)
        self.hear_player.toggled.connect(lambda v: self._set_monitor("monitor_hear_player", v))
        self.hear_sounds.toggled.connect(lambda v: self._set_monitor("monitor_hear_sounds", v))
        self.hear_mic.toggled.connect(lambda v: self._set_monitor("monitor_hear_mic", v))
        w.extra.addWidget(label)
        w.extra.addWidget(self.hear_sounds)
        w.extra.addWidget(self.hear_player)
        w.extra.addWidget(self.hear_mic)

    def _set_monitor(self, attr: str, value: bool) -> None:
        setattr(self.engine, attr, value)
        self.changed.emit()

    def sync_from_model(self) -> None:
        for w in self.strips:
            w.sync_from_model()
        self.hear_sounds.setChecked(self.engine.monitor_hear_sounds)
        self.hear_mic.setChecked(self.engine.monitor_hear_mic)
        self.hear_player.setChecked(self.engine.monitor_hear_player)

    def sync_levels(self) -> None:
        """Aggiorna solo fader e mute (dopo un cambio da MIDI o dal Player)."""
        for w in self.strips:
            w.sync_levels()

    def update_meters(self) -> None:
        for w in self.strips:
            w.update_meter()
