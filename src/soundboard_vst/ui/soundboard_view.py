"""Griglia dei suoni e gestione della cartella."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QFile, QFileSystemWatcher, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QInputDialog, QKeySequenceEdit, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QSlider, QStyle, QStyledItemDelegate, QVBoxLayout,
)

from ..audio.library import SUPPORTED_EXTENSIONS, SoundCache, SoundFile, list_sounds
from ..config import Config
from . import theme

KEY_ROLE = Qt.ItemDataRole.UserRole + 1
PATH_ROLE = Qt.ItemDataRole.UserRole + 2
PLAYING_ROLE = Qt.ItemDataRole.UserRole + 3
SHORTCUT_ROLE = Qt.ItemDataRole.UserRole + 4


class SoundTileDelegate(QStyledItemDelegate):
    """Disegna ogni suono come un riquadro arrotondato."""

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(5, 5, -5, -5)
        playing = bool(index.data(PLAYING_ROLE))
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        bg = QColor(theme.ACCENT) if playing else QColor(theme.PANEL_2)
        if hover and not playing:
            bg = bg.lighter(118)
        border = QColor(theme.ACCENT) if (hover or playing) else QColor(theme.BORDER)
        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(r, 10, 10)

        fg = QColor("#1b1406") if playing else QColor(theme.TEXT)
        shortcut = index.data(SHORTCUT_ROLE) or ""
        text_rect = r.adjusted(8, 6, -8, -16 if shortcut else -6)
        font = QFont(option.font)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(fg)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                         index.data(Qt.ItemDataRole.DisplayRole))
        if shortcut:
            small = QFont(option.font)
            small.setPointSizeF(max(7.0, option.font.pointSizeF() - 2))
            painter.setFont(small)
            painter.setPen(QColor("#5a4513") if playing else QColor(theme.MUTED))
            painter.drawText(r.adjusted(6, 0, -6, -5),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, shortcut)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(150, 78)


class SoundSettingsDialog(QDialog):
    def __init__(self, name: str, volume: float, shortcut: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Impostazioni — {name}")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 200)
        self.volume.setValue(int(volume * 100))
        vol_label = QLabel(f"{int(volume * 100)}%")
        self.volume.valueChanged.connect(lambda v: vol_label.setText(f"{v}%"))
        vrow = QHBoxLayout()
        vrow.addWidget(self.volume, 1)
        vrow.addWidget(vol_label)
        self.shortcut = QKeySequenceEdit(QKeySequence(shortcut))
        clear = QPushButton("Cancella")
        clear.clicked.connect(self.shortcut.clear)
        srow = QHBoxLayout()
        srow.addWidget(self.shortcut, 1)
        srow.addWidget(clear)
        form = QFormLayout()
        form.addRow("Volume", vrow)
        form.addRow("Scorciatoia", srow)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

    def values(self) -> tuple[float, str]:
        return self.volume.value() / 100.0, self.shortcut.keySequence().toString()


class SoundboardView(QFrame):
    play_requested = Signal(str, object)     # chiave, Path
    stop_requested = Signal()
    changed = Signal()

    def __init__(self, config: Config, cache: SoundCache, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.config = config
        self.cache = cache
        self._sounds: list[SoundFile] = []
        self._shortcuts: list[QShortcut] = []
        self.setAcceptDrops(True)

        title = QLabel("SOUNDBOARD")
        title.setObjectName("sectionTitle")
        self.folder_label = QLabel()
        self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.folder_label.setStyleSheet(f"color: {theme.MUTED};")

        change = QPushButton("Cambia cartella…")
        change.clicked.connect(self.choose_folder)
        open_btn = QPushButton("Apri cartella")
        open_btn.clicked.connect(self.open_folder)
        add_btn = QPushButton("Aggiungi suoni…")
        add_btn.clicked.connect(self.import_dialog)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(220)
        self.search.textChanged.connect(self._apply_filter)
        self.overlap = QCheckBox("Sovrapponi")
        self.overlap.setToolTip("Se attivo, premere di nuovo un suono lo sovrappone invece di ripartire")
        self.overlap.setChecked(bool(config.data.get("overlap_sounds", True)))
        self.overlap.toggled.connect(self._on_overlap)
        stop = QPushButton("■  Stop tutto")
        stop.setObjectName("danger")
        stop.clicked.connect(self.stop_requested)

        top = QHBoxLayout()
        top.addWidget(title)
        top.addSpacing(8)
        top.addWidget(self.folder_label, 1)
        top.addWidget(change)
        top.addWidget(open_btn)
        top.addWidget(add_btn)

        bar = QHBoxLayout()
        bar.addWidget(self.search)
        bar.addWidget(self.overlap)
        bar.addStretch(1)
        self.count_label = QLabel()
        self.count_label.setStyleSheet(f"color: {theme.MUTED};")
        bar.addWidget(self.count_label)
        bar.addWidget(stop)

        self.grid = QListWidget()
        self.grid.setObjectName("sounds")
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setWordWrap(True)
        self.grid.setGridSize(QSize(150, 78))
        self.grid.setSpacing(0)
        self.grid.setMouseTracking(True)
        self.grid.setItemDelegate(SoundTileDelegate(self.grid))
        self.grid.itemClicked.connect(self._on_click)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._context_menu)

        self.empty_hint = QLabel()
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setStyleSheet(f"color: {theme.MUTED}; padding: 30px;")
        self.empty_hint.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.addLayout(top)
        lay.addLayout(bar)
        lay.addWidget(self.grid, 1)
        lay.addWidget(self.empty_hint, 1)

        self.watcher = QFileSystemWatcher(self)
        self._reload_timer = QTimer(self, singleShot=True, interval=300)
        self._reload_timer.timeout.connect(self.reload)
        self.watcher.directoryChanged.connect(lambda _: self._reload_timer.start())

        self.set_folder(config.sounds_dir, save=False)

    # Cartella ----------------------------------------------------------------
    @property
    def folder(self) -> Path:
        return self.config.sounds_dir

    def set_folder(self, folder: Path, save: bool = True) -> None:
        folder = Path(folder)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Cartella suoni", f"Impossibile creare {folder}:\n{exc}")
        self.config.sounds_dir = folder
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        if folder.is_dir():
            self.watcher.addPath(str(folder))
        self.folder_label.setText(str(folder))
        self.reload()
        if save:
            self.changed.emit()

    def choose_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Cartella dei suoni", str(self.folder))
        if d:
            self.set_folder(Path(d))

    def open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder)))

    def reload(self) -> None:
        self._sounds = list_sounds(self.folder)
        self.grid.clear()
        for s in self._sounds:
            settings = self.config.data["sounds"].get(s.key, {})
            it = QListWidgetItem(s.name)
            it.setData(SHORTCUT_ROLE, settings.get("shortcut", ""))
            it.setData(KEY_ROLE, s.key)
            it.setData(PATH_ROLE, str(s.path))
            it.setToolTip(f"{s.path.name}\nClic: riproduci · Tasto destro: opzioni")
            self.grid.addItem(it)
        self._rebuild_shortcuts()
        self._apply_filter(self.search.text())
        has = bool(self._sounds)
        self.grid.setVisible(has)
        self.empty_hint.setVisible(not has)
        self.empty_hint.setText(
            "Nessun suono in questa cartella.\n\nTrascina qui file audio "
            f"({', '.join(sorted(e[1:] for e in SUPPORTED_EXTENSIONS))}) "
            "oppure usa «Aggiungi suoni…».")
        self.count_label.setText(f"{len(self._sounds)} suoni")

    def _apply_filter(self, text: str) -> None:
        t = text.lower().strip()
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    # Import ------------------------------------------------------------------
    def import_dialog(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(self, "Aggiungi suoni", "", f"Audio ({exts})")
        self.import_files([Path(f) for f in files])

    def import_files(self, files: list[Path]) -> None:
        copied, skipped = 0, []
        for f in files:
            if f.suffix.lower() not in SUPPORTED_EXTENSIONS:
                skipped.append(f.name)
                continue
            dest = self.folder / f.name
            if dest.resolve() == f.resolve():
                continue
            n = 1
            while dest.exists():
                dest = self.folder / f"{f.stem} ({n}){f.suffix}"
                n += 1
            try:
                shutil.copy2(f, dest)
                copied += 1
            except OSError as exc:
                skipped.append(f"{f.name} ({exc})")
        if skipped:
            QMessageBox.information(self, "Aggiungi suoni", "Non importati:\n" + "\n".join(skipped))
        if copied:
            self.reload()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        self.import_files([p for p in paths if p.is_file()])

    # Riproduzione ----------------------------------------------------------------
    def _on_click(self, item: QListWidgetItem) -> None:
        self.play_requested.emit(item.data(KEY_ROLE), Path(item.data(PATH_ROLE)))

    def play_key(self, key: str) -> None:
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            if it.data(KEY_ROLE) == key:
                self._on_click(it)
                return

    def _on_overlap(self, on: bool) -> None:
        self.config.data["overlap_sounds"] = on
        self.changed.emit()

    def set_playing(self, keys: set[str]) -> None:
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            on = it.data(KEY_ROLE) in keys
            if bool(it.data(PLAYING_ROLE)) != on:
                it.setData(PLAYING_ROLE, on)

    def _rebuild_shortcuts(self) -> None:
        for sc in self._shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts = []
        for s in self._sounds:
            seq = self.config.data["sounds"].get(s.key, {}).get("shortcut", "")
            if seq:
                sc = QShortcut(QKeySequence(seq), self)
                sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
                sc.activated.connect(lambda key=s.key: self.play_key(key))
                self._shortcuts.append(sc)

    # Menu contestuale -------------------------------------------------------------
    def _context_menu(self, pos) -> None:
        item = self.grid.itemAt(pos)
        if not item:
            m = QMenu(self)
            m.addAction("Aggiungi suoni…", self.import_dialog)
            m.addAction("Ricarica", self.reload)
            m.exec(self.grid.mapToGlobal(pos))
            return
        key, path = item.data(KEY_ROLE), Path(item.data(PATH_ROLE))
        m = QMenu(self)
        m.addAction("▶  Riproduci", lambda: self._on_click(item))
        m.addAction("Volume e scorciatoia…", lambda: self._edit_settings(key))
        m.addAction("Rinomina…", lambda: self._rename(path))
        m.addAction("Mostra nella cartella", self.open_folder)
        m.addSeparator()
        m.addAction("Sposta nel cestino", lambda: self._trash(path))
        m.exec(self.grid.mapToGlobal(pos))

    def _edit_settings(self, key: str) -> None:
        s = self.config.sound_settings(key)
        dlg = SoundSettingsDialog(Path(key).stem, s.get("volume", 1.0), s.get("shortcut", ""), self)
        if dlg.exec():
            s["volume"], s["shortcut"] = dlg.values()
            self.reload()
            self.changed.emit()

    def _rename(self, path: Path) -> None:
        new, ok = QInputDialog.getText(self, "Rinomina", "Nuovo nome:", text=path.stem)
        new = new.strip()
        if not ok or not new or new == path.stem:
            return
        if any(c in new for c in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Rinomina", "Il nome contiene caratteri non validi.")
            return
        dest = path.with_name(new + path.suffix)
        if dest.exists():
            QMessageBox.warning(self, "Rinomina", "Esiste già un file con questo nome.")
            return
        try:
            path.rename(dest)
        except OSError as exc:
            QMessageBox.warning(self, "Rinomina", str(exc))
            return
        sounds = self.config.data["sounds"]
        if path.name in sounds:
            sounds[dest.name] = sounds.pop(path.name)
        self.cache.forget(path)
        self.reload()
        self.changed.emit()

    def _trash(self, path: Path) -> None:
        if QMessageBox.question(self, "Sposta nel cestino",
                                f"Spostare «{path.name}» nel cestino?") != QMessageBox.StandardButton.Yes:
            return
        if not QFile.moveToTrash(str(path)):
            QMessageBox.warning(self, "Sposta nel cestino", "Impossibile spostare il file nel cestino.")
            return
        self.config.data["sounds"].pop(path.name, None)
        self.cache.forget(path)
        self.reload()
        self.changed.emit()
