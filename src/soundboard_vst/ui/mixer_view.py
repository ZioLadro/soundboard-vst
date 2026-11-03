"""Sezione mixer: gli ingressi (Microfono e quelli aggiunti), Soundboard, Sintesi vocale, Player,
Master e Monitor. Ogni canale ha inserti, pan, fader, MUTE e (ingressi e sorgenti) SOLO."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QSizePolicy, QSlider, QToolButton, QVBoxLayout, QWidget,
)

from ..audio.engine import AudioEngine
from ..audio.mixer import ChannelStrip, InputStrip, format_pan
from ..audio.plugins import BUILTIN_EFFECTS, InsertSlot, create_builtin, load_vst3, vst3_names_in_file
from .meter import DbFader, LevelMeter, format_db
from .plugin_dialogs import edit_slot, open_native_editor

SLOT_ROLE = Qt.ItemDataRole.UserRole + 1


class PanSlider(QSlider):
    """Pan orizzontale da -100 (sinistra) a +100 (destra); doppio clic = centro."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(-100, 100)
        self.setPageStep(10)
        self.setSingleStep(2)
        self.setToolTip("Pan: sposta il canale a sinistra o a destra (doppio clic = centro)")

    def mouseDoubleClickEvent(self, event):
        self.setValue(0)


class StripTitle(QLabel):
    """Titolo del canale; doppio clic per rinominare (solo ingressi)."""
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()


class StripWidget(QFrame):
    changed = Signal()                       # qualcosa da salvare
    rename_requested = Signal()
    remove_requested = Signal()

    def __init__(self, strip: ChannelStrip, vst_list: Callable[[], list[Path]],
                 rescan: Callable[[], None], parent=None, soloable: bool = True):
        super().__init__(parent)
        self.strip = strip
        self._vst_list = vst_list
        self._rescan = rescan
        self.setObjectName("panel")
        self.setMinimumWidth(190)

        self.title = title = StripTitle(strip.name)
        title.setObjectName("stripTitle")
        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        title_row.addWidget(title, 1)
        if isinstance(strip, InputStrip):
            title.setToolTip("Doppio clic per rinominare")
            title.double_clicked.connect(self.rename_requested)
            menu_btn = QToolButton(text="⋯")
            menu_btn.setObjectName("small")
            menu_btn.setToolTip("Rinomina o togli l'ingresso")
            menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(menu_btn)
            menu.addAction("Rinomina…", self.rename_requested.emit)
            rm = menu.addAction("Togli ingresso", self.remove_requested.emit)
            rm.setEnabled(strip.id != "mic")
            menu_btn.setMenu(menu)
            title_row.addWidget(menu_btn)

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
        self.solo: QPushButton | None = None
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        buttons.addWidget(self.mute, 1)
        if soloable:
            self.solo = QPushButton("SOLO")
            self.solo.setObjectName("solo")
            self.solo.setCheckable(True)
            self.solo.setChecked(strip.solo)
            self.solo.setToolTip("Ascolta solo i canali in SOLO: gli altri ingressi e sorgenti tacciono\n"
                                 "(anche verso Discord). Si possono mettere in solo più canali.")
            self.solo.toggled.connect(self._on_solo)
            buttons.addWidget(self.solo, 1)

        # Pan -------------------------------------------------------------------------
        pan_label = QLabel("PAN")
        pan_label.setObjectName("sectionTitle")
        self.pan = PanSlider()
        self.pan.setValue(int(round(strip.pan * 100)))
        self.pan_value = QLabel(format_pan(strip.pan))
        self.pan_value.setMinimumWidth(42)
        self.pan_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.pan.valueChanged.connect(self._on_pan)
        pan_row = QHBoxLayout()
        pan_row.setSpacing(6)
        pan_row.addWidget(pan_label)
        pan_row.addWidget(self.pan, 1)
        pan_row.addWidget(self.pan_value)

        self.extra = QVBoxLayout()   # spazio per opzioni specifiche (ingresso, monitor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addLayout(title_row)
        lay.addWidget(ins_label)
        lay.addWidget(self.inserts)
        lay.addLayout(ins_bar)
        lay.addLayout(self.extra)
        lay.addLayout(pan_row)
        lay.addLayout(fm, 1)
        lay.addWidget(self.db_label)
        lay.addLayout(buttons)
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
        self._sync_pan_solo()
        self.title.setText(self.strip.name)
        self.refresh_inserts()

    def _sync_pan_solo(self) -> None:
        value = int(round(self.strip.pan * 100))
        if self.pan.value() != value:
            self.pan.blockSignals(True)
            self.pan.setValue(value)
            self.pan.blockSignals(False)
            self.pan_value.setText(format_pan(self.strip.pan))
        if self.solo is not None and self.solo.isChecked() != self.strip.solo:
            self.solo.blockSignals(True)
            self.solo.setChecked(self.strip.solo)
            self.solo.blockSignals(False)

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
        self._sync_pan_solo()
        if self.title.text() != self.strip.name:
            self.title.setText(self.strip.name)

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

    def _on_solo(self, on: bool) -> None:
        self.strip.solo = on
        self.changed.emit()

    def _on_pan(self, value: int) -> None:
        self.strip.pan = value / 100.0
        self.pan_value.setText(format_pan(self.strip.pan))
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


def channel_options(max_in: int) -> list[tuple[str, tuple[int, bool]]]:
    """Scelte dei canali di un ingresso: stereo a coppie, poi mono uno per uno."""
    n = max(1, int(max_in))
    out = [(f"Stereo {c + 1}-{c + 2}", (c, False)) for c in range(0, n - 1, 2)]
    out += [(f"Mono {c + 1}", (c, True)) for c in range(n)]
    return out


class MixerView(QWidget):
    changed = Signal()

    def __init__(self, engine: AudioEngine, vst_list: Callable[[], list[Path]],
                 rescan: Callable[[], None], parent=None, inputs: Callable[[], list] = list,
                 current_input: Callable[[], str] | None = None, set_input: Callable[..., None] | None = None,
                 on_mic_to_bot: Callable[..., None] | None = None,
                 on_inputs_changed: Callable[[], None] | None = None):
        """``inputs()``: dispositivi d'ingresso, come nomi o come (nome, canali);
        ``set_input(nome, id_ingresso, channel=…, mono=…)``: cambia dispositivo o canali di un ingresso;
        ``on_mic_to_bot(attivo, nome)``: un ingresso viene mandato (o non più) al bot;
        ``on_inputs_changed()``: ingressi aggiunti o tolti (da salvare, dispositivi da riaprire)."""
        super().__init__(parent)
        self.engine = engine
        self._vst_list, self._rescan = vst_list, rescan
        self._inputs = inputs
        self._set_input, self._on_mic_to_bot = set_input, on_mic_to_bot
        self._on_inputs_changed = on_inputs_changed
        self.strips: list[StripWidget] = []
        self._input_ui: dict[str, dict] = {}
        self._hear_inputs: dict[str, QCheckBox] = {}
        self._device_cache: list[tuple[str, int]] | None = None
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(8)
        self.rebuild()

    # Costruzione -------------------------------------------------------------------------
    def _signature(self) -> tuple:
        return tuple((s.id, s.name) for s in self.engine.strips)

    def rebuild(self) -> None:
        """Ricrea i canali (dopo aver aggiunto, tolto o rinominato un ingresso)."""
        while self._row.count():
            item = self._row.takeAt(0)
            old = item.widget()
            if old is not None:
                old.hide()
                old.setParent(None)
                old.deleteLater()
        self.strips = []
        self._input_ui = {}
        self._hear_inputs = {}
        self._built = self._signature()
        eng = self.engine
        soloable = {s.id for s in eng.source_strips}
        for strip in eng.strips:
            w = StripWidget(strip, self._vst_list, self._rescan, soloable=strip.id in soloable)
            w.changed.connect(self.changed)
            self.strips.append(w)
            self._row.addWidget(w)
            if isinstance(strip, InputStrip):
                w.rename_requested.connect(lambda s=strip: self.rename_input(s.id))
                w.remove_requested.connect(lambda s=strip: self.remove_input(s.id))
                self._add_input_options(w, strip)
                if strip is eng.inputs[-1]:
                    self._row.addWidget(self._add_input_button())
            if strip is eng.monitor:
                self._add_monitor_options(w)
        self.refresh_inputs()

    def _add_input_button(self) -> QPushButton:
        b = QPushButton("＋\nIngresso")
        b.setObjectName("addInput")
        b.setToolTip("Aggiungi un canale d'ingresso (un altro microfono, uno strumento, una linea…)")
        b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        b.setFixedWidth(64)
        b.clicked.connect(self.add_input)
        return b

    def _add_input_options(self, w: StripWidget, strip: InputStrip) -> None:
        label = QLabel("INGRESSO")
        label.setObjectName("sectionTitle")
        combo = QComboBox()
        combo.setToolTip("Dispositivo di questo canale (l'audio si riavvia per un attimo)")
        combo.setMinimumContentsLength(10)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.activated.connect(lambda i, sid=strip.id: self._input_chosen(sid, i))
        refresh = QToolButton(text="↻")
        refresh.setObjectName("small")
        refresh.setToolTip("Aggiorna l'elenco dei dispositivi")
        refresh.clicked.connect(lambda: self.refresh_inputs(reload=True))
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(combo, 1)
        row.addWidget(refresh)
        channels = QComboBox()
        channels.setToolTip("Canali del dispositivo: stereo (due canali) o mono (uno solo, al centro:\n"
                            "spostalo con il pan). Utile per le schede con più ingressi (es. ASIO).")
        channels.activated.connect(lambda i, sid=strip.id: self._channels_chosen(sid, i))
        to_bot = QCheckBox("Anche al bot Discord")
        to_bot.setToolTip(
            "Questo ingresso (con i suoi inserti) arriva anche dal bot.\n"
            "Utile per far parlare il bot (es. con il pitch shifter); se parli anche dal tuo Discord,\n"
            "chi ascolta ti sente due volte: in quel caso muta uno dei due.")
        to_bot.setChecked(strip.to_bot)
        to_bot.toggled.connect(lambda on, sid=strip.id: self._to_bot_toggled(sid, on))
        w.extra.addWidget(label)
        w.extra.addLayout(row)
        w.extra.addWidget(channels)
        w.extra.addWidget(to_bot)
        self._input_ui[strip.id] = {"device": combo, "channels": channels, "to_bot": to_bot}
        if strip is self.engine.mic:
            self.input_combo, self.mic_to_bot, self.mic_channels = combo, to_bot, channels

    def _add_monitor_options(self, w: StripWidget) -> None:
        label = QLabel("ASCOLTA")
        label.setObjectName("sectionTitle")
        self.hear_sounds = QCheckBox("Suoni")
        self.hear_sounds.setChecked(self.engine.monitor_hear_sounds)
        self.hear_player = QCheckBox("Player")
        self.hear_player.setChecked(self.engine.monitor_hear_player)
        self.hear_tts = QCheckBox("Voce")
        self.hear_tts.setToolTip("Sintesi vocale")
        self.hear_tts.setChecked(self.engine.monitor_hear_tts)
        self.hear_tts.toggled.connect(lambda v: self._set_monitor("monitor_hear_tts", v))
        self.hear_player.toggled.connect(lambda v: self._set_monitor("monitor_hear_player", v))
        self.hear_sounds.toggled.connect(lambda v: self._set_monitor("monitor_hear_sounds", v))
        w.extra.addWidget(label)
        w.extra.addWidget(self.hear_sounds)
        w.extra.addWidget(self.hear_tts)
        w.extra.addWidget(self.hear_player)
        for strip in self.engine.inputs:
            cb = QCheckBox(strip.name)
            cb.setChecked(strip.hear)
            cb.setToolTip("Sentire questo ingresso in cuffia (con i suoi inserti). Attenzione al feedback con le casse.")
            cb.toggled.connect(lambda v, s=strip: self._set_hear(s, v))
            w.extra.addWidget(cb)
            self._hear_inputs[strip.id] = cb
        self.hear_mic = self._hear_inputs["mic"]

    # Ingressi -------------------------------------------------------------------------------
    def _devices(self, reload: bool = False) -> list[tuple[str, int]]:
        if self._device_cache is None or reload:
            try:
                items = list(self._inputs())
            except Exception:
                items = []
            self._device_cache = [(i, 2) if isinstance(i, str) else (str(i[0]), int(i[1])) for i in items]
        return self._device_cache

    def refresh_inputs(self, reload: bool = True) -> None:
        devs = self._devices(reload)
        names = [n for n, _ in devs]
        counts = dict(devs)
        for sid, ui in self._input_ui.items():
            strip = self.engine.input_strip(sid)
            if strip is None:
                continue
            combo: QComboBox = ui["device"]
            current = strip.device or ""
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("— nessuno —", "")
            for n in names:
                combo.addItem(n, n)
            if current and current not in names:
                combo.addItem(f"{current} (non trovato)", current)
            combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.setToolTip(current or "Nessun ingresso")
            combo.blockSignals(False)

            ch: QComboBox = ui["channels"]
            ch.blockSignals(True)
            ch.clear()
            n_ch = counts.get(current, max(2, strip.channel + 2))
            for text, data in channel_options(n_ch):
                ch.addItem(text, data)
            want = (strip.channel, strip.mono or n_ch == 1)
            idx = next((i for i in range(ch.count()) if tuple(ch.itemData(i)) == want), -1)
            if idx < 0:
                ch.addItem(f"{'Mono' if strip.mono else 'Stereo'} {strip.channel_label} (non disponibile)", want)
                idx = ch.count() - 1
            ch.setCurrentIndex(idx)
            ch.setEnabled(bool(current))
            ch.blockSignals(False)
            ui["to_bot"].blockSignals(True)
            ui["to_bot"].setChecked(strip.to_bot)
            ui["to_bot"].blockSignals(False)

    def _call_set_input(self, strip: InputStrip, name: str, **kw) -> None:
        if self._set_input is None:
            strip.device = name
            for k, v in kw.items():
                setattr(strip, k, v)
            self.changed.emit()
            return
        if strip.id == "mic" and not kw:
            self._set_input(name)
        else:
            self._set_input(name, strip.id, **kw)

    def _input_chosen(self, strip_id: str, index: int) -> None:
        strip = self.engine.input_strip(strip_id)
        combo = self._input_ui[strip_id]["device"]
        name = combo.itemData(index) or ""
        if strip is not None and name != (strip.device or ""):
            self._call_set_input(strip, name)
        combo.setToolTip(name or "Nessun ingresso")

    def _channels_chosen(self, strip_id: str, index: int) -> None:
        strip = self.engine.input_strip(strip_id)
        data = self._input_ui[strip_id]["channels"].itemData(index)
        if strip is None or data is None:
            return
        channel, mono = int(data[0]), bool(data[1])
        if (channel, mono) != (strip.channel, strip.mono):
            self._call_set_input(strip, strip.device, channel=channel, mono=mono)

    def _to_bot_toggled(self, strip_id: str, on: bool) -> None:
        strip = self.engine.input_strip(strip_id)
        if strip is None:
            return
        strip.to_bot = on
        if self._on_mic_to_bot is not None:
            if strip.id == "mic":
                self._on_mic_to_bot(on)
            else:
                self._on_mic_to_bot(on, strip.name)
        self.changed.emit()

    def _set_hear(self, strip: InputStrip, on: bool) -> None:
        strip.hear = on
        self.changed.emit()

    def add_input(self) -> InputStrip | None:
        try:
            strip = self.engine.add_input()
        except ValueError as exc:
            QMessageBox.information(self, "Ingressi", str(exc))
            return None
        self.rebuild()
        self.changed.emit()
        if self._on_inputs_changed is not None:
            self._on_inputs_changed()
        return strip

    def rename_input(self, strip_id: str, name: str | None = None) -> None:
        strip = self.engine.input_strip(strip_id)
        if strip is None:
            return
        if name is None:
            name, ok = QInputDialog.getText(self, "Rinomina ingresso", "Nome del canale:", text=strip.name)
            if not ok:
                return
        name = " ".join(str(name).split())[:40]
        if not name or name == strip.name:
            return
        strip.name = name
        self.rebuild()
        self.changed.emit()

    def remove_input(self, strip_id: str, confirm: bool = True) -> None:
        strip = self.engine.input_strip(strip_id)
        if strip is None or strip_id == "mic":
            return
        if confirm and QMessageBox.question(self, "Togli ingresso", f"Togliere il canale «{strip.name}» "
                                            "con i suoi inserti?") != QMessageBox.StandardButton.Yes:
            return
        self.engine.remove_input(strip_id)
        self.rebuild()
        self.changed.emit()
        if self._on_inputs_changed is not None:
            self._on_inputs_changed()

    # Monitor ----------------------------------------------------------------------------------
    def _set_monitor(self, attr: str, value: bool) -> None:
        setattr(self.engine, attr, value)
        self.changed.emit()

    # Sincronizzazione -------------------------------------------------------------------------
    def sync_from_model(self) -> None:
        if self._signature() != self._built:
            self.rebuild()
        for w in self.strips:
            w.sync_from_model()
        for cb, value in ((self.hear_tts, self.engine.monitor_hear_tts),
                          (self.hear_sounds, self.engine.monitor_hear_sounds),
                          (self.hear_player, self.engine.monitor_hear_player)):
            cb.blockSignals(True)
            cb.setChecked(value)
            cb.blockSignals(False)
        for strip in self.engine.inputs:
            cb = self._hear_inputs.get(strip.id)
            if cb is not None:
                cb.blockSignals(True)
                cb.setChecked(strip.hear)
                cb.blockSignals(False)
        self.refresh_inputs(reload=False)

    def sync_levels(self) -> None:
        """Aggiorna fader, pan, mute e solo (dopo un cambio da MIDI, dal Player o dalla pagina web)."""
        if self._signature() != self._built:
            self.rebuild()
        for w in self.strips:
            w.sync_levels()

    def levels(self) -> dict:
        """Livelli mostrati dai meter (dB, con caduta e picco): gli stessi per la pagina web."""
        return {w.strip.id: [round(v, 1) for v in (*w.meter._level, *w.meter._hold)] for w in self.strips}

    def update_meters(self) -> None:
        for w in self.strips:
            w.update_meter()
