"""Soundboard: libreria dei file e griglia di pad a pagine."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import (
    QFile, QFileSystemWatcher, QMimeData, QPoint, QRectF, Qt, QTimer, QUrl, Signal,
)
from PySide6.QtGui import (
    QColor, QDesktopServices, QDrag, QFont, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen,
    QFontMetrics, QPixmap, QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSizePolicy,
    QSplitter, QTabBar, QToolButton, QVBoxLayout, QWidget,
)

from ..audio.library import SUPPORTED_EXTENSIONS, SoundCache, list_sounds
from ..config import Config
from ..pads import MAX_SIZE, MIN_SIZE, PadLayout
from .. import midi
from . import theme
from .sound_dialog import MidiBridge, SoundSettingsDialog, text_color_for

MIME_KEY = "application/x-soundboard-key"
MIME_PAD = "application/x-soundboard-pad"
KEY_ROLE = Qt.ItemDataRole.UserRole + 1


# Pad ------------------------------------------------------------------------------
_PIXMAPS: dict[str, tuple[float, QPixmap | None]] = {}


def _load_pixmap(path: str) -> QPixmap | None:
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        return None
    hit = _PIXMAPS.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    pix = QPixmap(path)
    if pix.isNull():
        pix = None
    elif max(pix.width(), pix.height()) > 512:   # le immagini grandi si ridimensionano una volta sola
        pix = pix.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    _PIXMAPS[path] = (mtime, pix)
    return pix


class PadButton(QWidget):
    clicked = Signal(int)
    menu_requested = Signal(int, QPoint)
    dropped_key = Signal(int, str)
    dropped_pad = Signal(int, int)          # sorgente, destinazione
    dropped_files = Signal(int, list)

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.key: str | None = None
        self.label = ""
        self.shortcut = ""
        self.missing = False
        self.playing = False
        self.color = ""
        self.emoji = ""
        self.midi_label = ""
        self.image = ""
        self._hover = False
        self._press_pos: QPoint | None = None
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setMinimumSize(64, 44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_sound(self, key: str | None, label: str, shortcut: str, missing: bool,
                  color: str = "", emoji: str = "", midi_label: str = "", image: str = "") -> None:
        self.key, self.label, self.shortcut, self.missing = key, label, shortcut, missing
        self.color, self.emoji, self.midi_label = color, emoji, midi_label
        self.image = image
        tip = "Slot vuoto: clic o trascina qui un suono" if key is None else \
            f"{key}\nClic: riproduci · Trascina: sposta · Tasto destro: opzioni"
        if midi_label:
            tip += f"\nMIDI: {midi_label}"
        if missing:
            tip = f"{key}\nFile non trovato nella cartella"
        self.setToolTip(tip)
        self.update()

    def set_playing(self, on: bool) -> None:
        if on != self.playing:
            self.playing = on
            self.update()

    # Disegno ---------------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        empty = self.key is None
        if empty:
            pen = QPen(QColor(theme.ACCENT if self._hover else theme.BORDER), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(QColor(theme.PANEL))
            p.drawRoundedRect(r, 9, 9)
            p.setPen(QColor(theme.MUTED if self._hover else theme.BORDER))
            f = QFont(self.font())
            f.setPointSizeF(f.pointSizeF() + 6)
            p.setFont(f)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "+")
            return
        if self.color:
            base = QColor(self.color)
            if self.playing:
                bg = base.lighter(135)
            elif self._hover:
                bg = base
            else:
                bg = base.darker(125)
            fg = text_color_for(bg)
            muted = QColor(fg)
            muted.setAlphaF(0.65)
            border = QColor(theme.TEXT) if self.playing else (base.lighter(130) if self._hover else base)
            p.setPen(QPen(border, 2.5 if self.playing else 1))
        else:
            bg = QColor(theme.ACCENT) if self.playing else QColor(theme.PANEL_2)
            if self._hover and not self.playing:
                bg = bg.lighter(118)
            fg = QColor("#1b1406") if self.playing else QColor(theme.TEXT)
            muted = QColor("#5a4513") if self.playing else QColor(theme.MUTED)
            border = QColor(theme.ACCENT) if (self._hover or self.playing) else QColor(theme.BORDER)
            p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 9, 9)

        pix = _load_pixmap(self.image) if self.image else None
        if pix is not None:
            # immagine a riempimento, ritagliata con gli angoli arrotondati e velata in basso
            path = QPainterPath()
            path.addRoundedRect(r.adjusted(1, 1, -1, -1), 8, 8)
            p.save()
            p.setClipPath(path)
            scaled = pix.scaled(int(r.width()), int(r.height()), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(r.left() + (r.width() - scaled.width()) / 2),
                         int(r.top() + (r.height() - scaled.height()) / 2), scaled)
            veil = QLinearGradient(0, r.top(), 0, r.bottom())
            veil.setColorAt(0.0, QColor(0, 0, 0, 40))
            veil.setColorAt(0.5, QColor(0, 0, 0, 30))
            veil.setColorAt(1.0, QColor(0, 0, 0, 200))
            p.fillRect(r, veil)
            if self.playing:
                p.fillRect(r, QColor(255, 255, 255, 50))
            p.restore()
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(theme.ACCENT if not self.color else self.color), 3) if self.playing
                     else QPen(QColor(theme.ACCENT) if self._hover else QColor(0, 0, 0, 0), 1.5))
            p.drawRoundedRect(r, 9, 9)
            fg = QColor("#ffffff")
            muted = QColor(255, 255, 255, 190)

        small = QFont(self.font())
        small.setPointSizeF(max(7.0, self.font().pointSizeF() - 2))
        p.setFont(small)
        p.setPen(muted)
        p.drawText(r.adjusted(7, 4, -7, -4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   str(self.index + 1))
        footer = " · ".join(x for x in (self.shortcut, self.midi_label) if x)
        if footer:
            fm = p.fontMetrics()
            p.drawText(r.adjusted(6, 0, -6, -4), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                       fm.elidedText(footer, Qt.TextElideMode.ElideRight, int(r.width()) - 12))

        content = r.adjusted(8, 12, -8, -14 if footer else -8)
        if pix is not None:
            # con l'immagine il nome va in basso, sopra la velatura
            lh = QFontMetrics(QFont(self.font())).height()
            content = QRectF(content.left(), content.bottom() - lh * 1.4 - (3 if footer else 0),
                             content.width(), lh * 1.4)
        elif self.emoji:
            esize = max(10.0, min(content.height() * 0.45, content.width() * 0.4))
            ef = QFont(self.font())
            ef.setPixelSize(int(esize))
            p.setFont(ef)
            emoji_rect = QRectF(content.left(), content.top(), content.width(), esize * 1.25)
            p.drawText(emoji_rect, Qt.AlignmentFlag.AlignCenter, self.emoji)
            content = content.adjusted(0, esize * 1.2, 0, 0)

        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold)
        f.setStrikeOut(self.missing)
        p.setFont(f)
        p.setPen(QColor(theme.DANGER) if self.missing else fg)
        flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
        if pix is not None:
            text = p.fontMetrics().elidedText(self.label, Qt.TextElideMode.ElideRight, int(content.width()))
            p.drawText(content, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, text)
        elif self.emoji and content.height() < p.fontMetrics().height() * 2:
            text = p.fontMetrics().elidedText(self.label, Qt.TextElideMode.ElideRight, int(content.width()))
            p.drawText(content, Qt.AlignmentFlag.AlignCenter, text)
        else:
            p.drawText(content, flags, self.label)

    # Mouse ------------------------------------------------------------------------
    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        elif event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(self.index, event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if self._press_pos is None or self.key is None:
            return
        if (event.position().toPoint() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return
        self._press_pos = None
        mime = QMimeData()
        mime.setData(MIME_PAD, str(self.index).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab().scaled(self.width() // 2 or 1, self.height() // 2 or 1))
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            self._press_pos = None
            self.clicked.emit(self.index)

    # Drop ------------------------------------------------------------------------
    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasFormat(MIME_KEY) or md.hasFormat(MIME_PAD) or md.hasUrls():
            event.acceptProposedAction()
            self._hover = True
            self.update()

    def dragLeaveEvent(self, event):
        self._hover = False
        self.update()

    def dropEvent(self, event):
        self._hover = False
        md = event.mimeData()
        if md.hasFormat(MIME_PAD):
            src = int(bytes(md.data(MIME_PAD)).decode())
            if src != self.index:
                self.dropped_pad.emit(src, self.index)
        elif md.hasFormat(MIME_KEY):
            self.dropped_key.emit(self.index, bytes(md.data(MIME_KEY)).decode())
        elif md.hasUrls():
            paths = [Path(u.toLocalFile()) for u in md.urls() if u.isLocalFile()]
            self.dropped_files.emit(self.index, [p for p in paths if p.is_file()])
        event.acceptProposedAction()
        self.update()


class LibraryList(QListWidget):
    """Elenco dei file: trascinabili sui pad."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("library")
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def mimeData(self, items):
        md = QMimeData()
        if items:
            md.setData(MIME_KEY, items[0].data(KEY_ROLE).encode())
        return md

    def mimeTypes(self):
        return [MIME_KEY]


# Vista principale -------------------------------------------------------------------
class SoundboardView(QWidget):
    play_requested = Signal(str, object)     # chiave, Path
    stop_requested = Signal()
    myinstants_requested = Signal()
    sounds_reloaded = Signal()
    changed = Signal()

    def __init__(self, config: Config, cache: SoundCache, parent=None):
        super().__init__(parent)
        self.config = config
        self.cache = cache
        self.layout_model = PadLayout.from_dict(config.data.get("pads"))
        self._first_layout = not config.data.get("pads")
        self._keys: list[str] = []
        self._known: set[str] | None = None
        self._pads: list[PadButton] = []
        self._shortcuts: list[QShortcut] = []
        self.midi_bridge: MidiBridge | None = None
        self.midi_port = ""
        self._learn_dialog: SoundSettingsDialog | None = None
        self.setAcceptDrops(True)

        # Barra cartella ---------------------------------------------------------------
        self.folder_label = QLabel()
        self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.folder_label.setStyleSheet(f"color: {theme.MUTED};")
        change = QPushButton("Cambia cartella…")
        change.clicked.connect(self.choose_folder)
        open_btn = QPushButton("Apri cartella")
        open_btn.clicked.connect(self.open_folder)
        add_btn = QPushButton("Aggiungi file…")
        add_btn.clicked.connect(self.import_dialog)
        mi_btn = QPushButton("Cerca su MyInstants")
        mi_btn.setObjectName("primary")
        mi_btn.clicked.connect(self.myinstants_requested)
        folder_title = QLabel("CARTELLA")
        folder_title.setObjectName("sectionTitle")
        top = QHBoxLayout()
        top.addWidget(folder_title)
        top.addWidget(self.folder_label, 1)
        for b in (change, open_btn, add_btn, mi_btn):
            top.addWidget(b)

        # Libreria -----------------------------------------------------------------------
        lib_panel = QFrame()
        lib_panel.setObjectName("panel")
        lib_title = QLabel("LIBRERIA")
        lib_title.setObjectName("sectionTitle")
        self.count_label = QLabel()
        self.count_label.setStyleSheet(f"color: {theme.MUTED};")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca nella libreria…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.library = LibraryList()
        self.library.itemDoubleClicked.connect(lambda it: self.play_key(it.data(KEY_ROLE)))
        self.library.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.library.customContextMenuRequested.connect(self._library_menu)
        lib_hint = QLabel("Trascina un suono su un pad · doppio clic per ascoltarlo")
        lib_hint.setWordWrap(True)
        lib_hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
        lh = QHBoxLayout()
        lh.addWidget(lib_title)
        lh.addStretch(1)
        lh.addWidget(self.count_label)
        lv = QVBoxLayout(lib_panel)
        lv.setContentsMargins(10, 10, 10, 10)
        lv.addLayout(lh)
        lv.addWidget(self.search)
        lv.addWidget(self.library, 1)
        lv.addWidget(lib_hint)

        # Pad ---------------------------------------------------------------------------
        pad_panel = QFrame()
        pad_panel.setObjectName("panel")
        self.pages = QTabBar()
        self.pages.setObjectName("pages")
        self.pages.setExpanding(False)
        self.pages.setMovable(True)
        self.pages.setDrawBase(False)
        self.pages.currentChanged.connect(self._on_page_changed)
        self.pages.tabMoved.connect(self._on_page_moved)
        self.pages.tabBarDoubleClicked.connect(self._rename_page)
        self.pages.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.pages.customContextMenuRequested.connect(self._page_menu)
        add_page = QToolButton(text="+")
        add_page.setToolTip("Nuova pagina")
        add_page.clicked.connect(self._add_page)

        self.rows_spin = QComboBox()
        self.cols_spin = QComboBox()
        self.rows_spin.setToolTip("Righe")
        self.cols_spin.setToolTip("Colonne")
        for sp, v in ((self.rows_spin, self.layout_model.rows), (self.cols_spin, self.layout_model.cols)):
            for n in range(MIN_SIZE, MAX_SIZE + 1):
                sp.addItem(str(n), n)
            sp.setCurrentIndex(v - MIN_SIZE)
            sp.currentIndexChanged.connect(self._on_grid_size)
        self.slots_label = QLabel()
        self.slots_label.setStyleSheet(f"color: {theme.MUTED};")
        self.overlap = QCheckBox("Sovrapponi")
        self.overlap.setToolTip("Se attivo, premere di nuovo un suono lo sovrappone invece di ripartire")
        self.overlap.setChecked(bool(config.data.get("overlap_sounds", True)))
        self.overlap.toggled.connect(self._on_overlap)
        stop = QPushButton("■  Stop tutto")
        stop.setObjectName("danger")
        stop.clicked.connect(self.stop_requested)

        bar = QHBoxLayout()
        bar.addWidget(self.pages)
        bar.addWidget(add_page)
        bar.addStretch(1)
        bar.addWidget(QLabel("Griglia"))
        bar.addWidget(self.rows_spin)
        bar.addWidget(QLabel("×"))
        bar.addWidget(self.cols_spin)
        bar.addWidget(self.slots_label)
        bar.addSpacing(10)
        bar.addWidget(self.overlap)
        bar.addWidget(stop)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(2)
        pv = QVBoxLayout(pad_panel)
        pv.setContentsMargins(10, 8, 10, 10)
        pv.addLayout(bar)
        pv.addWidget(self.grid_host, 1)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(lib_panel)
        split.addWidget(pad_panel)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([250, 900])
        split.setChildrenCollapsible(False)
        self.splitter = split

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top)
        lay.addWidget(split, 1)

        self.watcher = QFileSystemWatcher(self)
        self._reload_timer = QTimer(self, singleShot=True, interval=300)
        self._reload_timer.timeout.connect(self.reload)
        self.watcher.directoryChanged.connect(lambda _: self._reload_timer.start())

        self._build_grid()
        self._rebuild_page_tabs()
        self.set_folder(config.sounds_dir, save=False)

    # Cartella ---------------------------------------------------------------------
    @property
    def folder(self) -> Path:
        return self.config.sounds_dir

    def set_folder(self, folder: Path, save: bool = True) -> None:
        folder = Path(folder)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Cartella suoni", f"Impossibile creare {folder}:\n{exc}")
        changed_folder = self.config.sounds_dir != folder or self._known is None
        self.config.sounds_dir = folder
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        if folder.is_dir():
            self.watcher.addPath(str(folder))
        self.folder_label.setText(str(folder))
        if changed_folder:
            self._known = None
        self.reload()
        if save:
            self.changed.emit()

    def choose_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Cartella dei suoni", str(self.folder))
        if d:
            self.set_folder(Path(d))

    def open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder)))

    def path_for(self, key: str) -> Path:
        return self.folder / key

    def reload(self) -> None:
        sounds = list_sounds(self.folder)
        self._keys = [s.key for s in sounds]
        current = set(self._keys)
        layout_changed = False
        if self._known is None:
            # primo caricamento: con una disposizione nuova riempiamo i pad con tutti i file
            if self._first_layout:
                for k in self._keys:
                    self.layout_model.place(k)
                self._first_layout = False
                layout_changed = bool(self._keys)
        else:
            for k in self._keys:   # file comparsi nella cartella: vanno nel primo pad libero
                if k not in self._known and not self.layout_model.contains(k):
                    self.layout_model.place(k)
                    layout_changed = True
        self._known = current
        self._refresh_library()
        self._rebuild_page_tabs()
        self._refresh_pads()
        self._rebuild_shortcuts()
        if layout_changed:
            self._save_layout()
        self.sounds_reloaded.emit()

    def _refresh_library(self) -> None:
        self.library.clear()
        for k in self._keys:
            cfg = self.config.data["sounds"].get(k, {})
            emoji, name = cfg.get("emoji", ""), cfg.get("label") or Path(k).stem
            it = QListWidgetItem(f"{emoji}  {name}" if emoji else name)
            it.setData(KEY_ROLE, k)
            on_pad = self.layout_model.contains(k)
            if not on_pad:
                it.setForeground(QColor(theme.MUTED))
            it.setToolTip(k + ("" if on_pad else "\nNon è su nessun pad"))
            self.library.addItem(it)
        self._apply_filter(self.search.text())
        self.count_label.setText(f"{len(self._keys)}")

    def _apply_filter(self, text: str) -> None:
        t = text.lower().strip()
        for i in range(self.library.count()):
            it = self.library.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    # Griglia ------------------------------------------------------------------------
    def _build_grid(self) -> None:
        for pad in self._pads:
            pad.deleteLater()
        self._pads = []
        rows, cols = self.layout_model.rows, self.layout_model.cols
        for i in range(rows * cols):
            pad = PadButton(i)
            pad.clicked.connect(self._on_pad_clicked)
            pad.menu_requested.connect(self._pad_menu)
            pad.dropped_key.connect(self._on_drop_key)
            pad.dropped_pad.connect(self._on_drop_pad)
            pad.dropped_files.connect(self._on_drop_files)
            r, c = divmod(i, cols)
            self.grid.addWidget(pad, r, c)
            self._pads.append(pad)
        for r in range(MAX_SIZE):
            self.grid.setRowStretch(r, 1 if r < rows else 0)
        for c in range(MAX_SIZE):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)
        self.slots_label.setText(f"= {rows * cols} slot")

    def _refresh_pads(self) -> None:
        slots = self.layout_model.page.slots
        existing = set(self._keys)
        sounds_cfg = self.config.data["sounds"]
        for pad in self._pads:
            key = slots.get(pad.index)
            if key is None:
                pad.set_sound(None, "", "", False)
            else:
                cfg = sounds_cfg.get(key, {})
                pad.set_sound(key, cfg.get("label") or Path(key).stem, cfg.get("shortcut", ""),
                              key not in existing, cfg.get("color", ""), cfg.get("emoji", ""),
                              midi.binding_label(cfg.get("midi")), cfg.get("image", ""))

    def _on_grid_size(self) -> None:
        self.layout_model.resize(self.rows_spin.currentData(), self.cols_spin.currentData())
        self._build_grid()
        self._rebuild_page_tabs()
        self._refresh_pads()
        self._save_layout()

    # Pagine -------------------------------------------------------------------------
    def _rebuild_page_tabs(self) -> None:
        self.pages.blockSignals(True)
        while self.pages.count():
            self.pages.removeTab(0)
        for pg in self.layout_model.pages:
            self.pages.addTab(pg.name)
        self.pages.setCurrentIndex(self.layout_model.current)
        self.pages.blockSignals(False)

    def _on_page_changed(self, index: int) -> None:
        if 0 <= index < len(self.layout_model.pages):
            self.layout_model.current = index
            self._refresh_pads()
            self._save_layout()

    def _on_page_moved(self, src: int, dst: int) -> None:
        pages = self.layout_model.pages
        pages.insert(dst, pages.pop(src))
        self.layout_model.current = self.pages.currentIndex()
        self._save_layout()

    def _add_page(self) -> None:
        self.layout_model.current = self.layout_model.add_page()
        self._rebuild_page_tabs()
        self._refresh_pads()
        self._save_layout()

    def _rename_page(self, index: int) -> None:
        if index < 0:
            return
        pg = self.layout_model.pages[index]
        name, ok = QInputDialog.getText(self, "Rinomina pagina", "Nome:", text=pg.name)
        if ok and name.strip():
            pg.name = name.strip()
            self.pages.setTabText(index, pg.name)
            self._save_layout()

    def _delete_page(self, index: int) -> None:
        pg = self.layout_model.pages[index]
        if pg.slots and QMessageBox.question(
                self, "Elimina pagina",
                f"Eliminare «{pg.name}»? I file restano nella cartella.") != QMessageBox.StandardButton.Yes:
            return
        self.layout_model.remove_page(index)
        self._rebuild_page_tabs()
        self._refresh_pads()
        self._refresh_library()
        self._save_layout()

    def _page_menu(self, pos) -> None:
        index = self.pages.tabAt(pos)
        if index < 0:
            return
        m = QMenu(self)
        m.addAction("Rinomina…", lambda: self._rename_page(index))
        m.addAction("Svuota pagina", lambda: self._clear_page(index))
        m.addSeparator()
        m.addAction("Elimina pagina", lambda: self._delete_page(index))
        m.exec(self.pages.mapToGlobal(pos))

    def _clear_page(self, index: int) -> None:
        self.layout_model.pages[index].slots.clear()
        self._refresh_pads()
        self._refresh_library()
        self._save_layout()

    def _save_layout(self) -> None:
        self.config.data["pads"] = self.layout_model.to_dict()
        self.changed.emit()

    # Interazione con i pad ------------------------------------------------------------
    def _on_pad_clicked(self, index: int) -> None:
        key = self.layout_model.page.slots.get(index)
        if key is None:
            self._choose_for_pad(index)
        else:
            self.play_key(key)

    def _choose_for_pad(self, index: int) -> None:
        if not self._keys:
            self.import_dialog(target=index)
            return
        names = [Path(k).stem for k in self._keys]
        name, ok = QInputDialog.getItem(self, f"Slot {index + 1}", "Suono da assegnare:", names, 0, False)
        if ok:
            self._assign(index, self._keys[names.index(name)])

    def _assign(self, index: int, key: str) -> None:
        self.layout_model.assign(self.layout_model.current, index, key)
        self._refresh_pads()
        self._refresh_library()
        self._save_layout()

    def _on_drop_key(self, index: int, key: str) -> None:
        self._assign(index, key)

    def _on_drop_pad(self, src: int, dst: int) -> None:
        self.layout_model.move(self.layout_model.current, src, dst)
        self._refresh_pads()
        self._save_layout()

    def _on_drop_files(self, index: int, paths: list) -> None:
        self.import_files(paths, target=index)

    def _pad_menu(self, index: int, global_pos: QPoint) -> None:
        key = self.layout_model.page.slots.get(index)
        m = QMenu(self)
        if key is None:
            m.addAction("Assegna suono…", lambda: self._choose_for_pad(index))
            m.addAction("Aggiungi file…", lambda: self.import_dialog(target=index))
        else:
            m.addAction("▶  Riproduci", lambda: self.play_key(key))
            m.addAction("Cambia suono…", lambda: self._choose_for_pad(index))
            m.addAction("Personalizza (nome, immagine, colore, MIDI)…", lambda: self._edit_settings(key))
            m.addAction("Togli dal pad", lambda: self._clear_pad(index))
            m.addSeparator()
            if key in self._keys:
                m.addAction("Rinomina file…", lambda: self._rename(self.path_for(key)))
                m.addAction("Sposta file nel cestino", lambda: self._trash(self.path_for(key)))
        m.exec(global_pos)

    def _clear_pad(self, index: int) -> None:
        self.layout_model.clear(self.layout_model.current, index)
        self._refresh_pads()
        self._refresh_library()
        self._save_layout()

    def _library_menu(self, pos) -> None:
        item = self.library.itemAt(pos)
        m = QMenu(self)
        if item:
            key = item.data(KEY_ROLE)
            path = self.path_for(key)
            m.addAction("▶  Riproduci", lambda: self.play_key(key))
            m.addAction("Metti nel primo pad libero", lambda: self.place_on_pad(key))
            m.addAction("Personalizza (nome, immagine, colore, MIDI)…", lambda: self._edit_settings(key))
            m.addAction("Rinomina…", lambda: self._rename(path))
            m.addSeparator()
            m.addAction("Sposta nel cestino", lambda: self._trash(path))
        else:
            m.addAction("Aggiungi file…", self.import_dialog)
            m.addAction("Ricarica", self.reload)
        m.exec(self.library.mapToGlobal(pos))

    def place_on_pad(self, key: str) -> None:
        page, _ = self.layout_model.place(key)
        if page != self.layout_model.current:
            self.layout_model.current = page
        self._rebuild_page_tabs()
        self._refresh_pads()
        self._refresh_library()
        self._save_layout()

    # Import -------------------------------------------------------------------------
    def import_dialog(self, target: int | None = None) -> None:
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(self, "Aggiungi file audio", "", f"Audio ({exts})")
        self.import_files([Path(f) for f in files], target=target)

    def import_files(self, files: list[Path], target: int | None = None) -> list[str]:
        """Copia i file nella cartella e li mette sui pad (dal pad ``target`` in poi)."""
        added: list[str] = []
        skipped: list[str] = []
        for f in files:
            if f.suffix.lower() not in SUPPORTED_EXTENSIONS:
                skipped.append(f.name)
                continue
            dest = self.folder / f.name
            if dest.exists() and dest.resolve() == f.resolve():
                added.append(dest.name)
                continue
            n = 1
            while dest.exists():
                dest = self.folder / f"{f.stem} ({n}){f.suffix}"
                n += 1
            try:
                shutil.copy2(f, dest)
                added.append(dest.name)
            except OSError as exc:
                skipped.append(f"{f.name} ({exc})")
        if skipped:
            QMessageBox.information(self, "Aggiungi file", "Non importati:\n" + "\n".join(skipped))
        self.add_keys(added, target)
        return added

    def add_keys(self, keys: list[str], target: int | None = None) -> None:
        """Registra file appena arrivati nella cartella e li assegna ai pad."""
        if not keys:
            return
        page = self.layout_model.current
        for i, key in enumerate(keys):
            if i == 0 and target is not None:
                self.layout_model.assign(page, target, key)
            elif not self.layout_model.contains(key):
                self.layout_model.place(key)
        if self._known is not None:
            self._known |= set(keys)
        self.reload()
        self._save_layout()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        self.import_files([p for p in paths if p.is_file()])

    # Riproduzione -----------------------------------------------------------------
    def play_key(self, key: str, quiet: bool = False) -> None:
        path = self.path_for(key)
        if not path.exists():
            if not quiet:
                QMessageBox.warning(self, "Suono", f"«{key}» non è più nella cartella.")
            return
        self.play_requested.emit(key, path)

    def _on_overlap(self, on: bool) -> None:
        self.config.data["overlap_sounds"] = on
        self.changed.emit()

    def set_playing(self, keys: set[str]) -> None:
        for pad in self._pads:
            pad.set_playing(pad.key in keys if pad.key else False)

    def _rebuild_shortcuts(self) -> None:
        for sc in self._shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts = []
        for key in self._keys:
            seq = self.config.data["sounds"].get(key, {}).get("shortcut", "")
            if seq:
                sc = QShortcut(QKeySequence(seq), self)
                sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
                sc.activated.connect(lambda key=key: self.play_key(key))
                self._shortcuts.append(sc)

    # Gestione file -------------------------------------------------------------------
    def _edit_settings(self, key: str) -> None:
        s = self.config.sound_settings(key)
        dlg = SoundSettingsDialog(Path(key).stem, s, self.midi_bridge, self.midi_port, self)
        self._learn_dialog = dlg
        try:
            ok = dlg.exec()
        finally:
            self._learn_dialog = None
        if ok:
            vals = dlg.values()
            if vals["midi"]:   # una nota MIDI suona un solo suono
                for other, cfg in self.config.data["sounds"].items():
                    if other != key and midi.matches(cfg.get("midi"), midi.MidiEvent(
                            vals["midi"]["type"], vals["midi"]["channel"], vals["midi"]["number"], 1)):
                        cfg["midi"] = None
            s.update(vals)
            self._refresh_pads()
            self._refresh_library()
            self._rebuild_shortcuts()
            self.changed.emit()

    def play_page_slot(self, page: int, index: int) -> None:
        """Suona lo slot ``index`` (da 0) della pagina ``page`` (usato dal controllo remoto)."""
        if 0 <= page < len(self.layout_model.pages):
            key = self.layout_model.pages[page].slots.get(index)
            if key is not None:
                self.play_key(key, quiet=True)

    def play_slot(self, number: int) -> None:
        """Suona lo slot ``number`` (da 1) della pagina corrente."""
        key = self.layout_model.page.slots.get(number - 1)
        if key is not None:
            self.play_key(key)

    def change_page(self, delta: int) -> None:
        n = len(self.layout_model.pages)
        if n > 1:
            self.pages.setCurrentIndex((self.layout_model.current + delta) % n)

    @property
    def is_learning(self) -> bool:
        return self._learn_dialog is not None and self._learn_dialog.learning

    def key_for_midi(self, event) -> str | None:
        for key, cfg in self.config.data["sounds"].items():
            if midi.matches(cfg.get("midi"), event):
                return key
        return None

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
        self.layout_model.rename_key(path.name, dest.name)
        if self._known is not None:
            self._known.discard(path.name)
            self._known.add(dest.name)
        self.cache.forget(path)
        self.reload()
        self._save_layout()

    def _trash(self, path: Path) -> None:
        if QMessageBox.question(self, "Sposta nel cestino",
                                f"Spostare «{path.name}» nel cestino?") != QMessageBox.StandardButton.Yes:
            return
        if not QFile.moveToTrash(str(path)):
            QMessageBox.warning(self, "Sposta nel cestino", "Impossibile spostare il file nel cestino.")
            return
        self.config.data["sounds"].pop(path.name, None)
        self.layout_model.remove_key(path.name)
        self.cache.forget(path)
        self.reload()
        self._save_layout()
