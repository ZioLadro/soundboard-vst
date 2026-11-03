"""Tab Player: coda di brani locali e YouTube, ricerca, controlli di trasporto."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QSize, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QSlider, QSplitter, QToolButton, QVBoxLayout,
    QWidget,
)

from .. import eventlog
from .. import youtube
from ..audio.mixer import MAX_DB, MIN_DB
from ..audio.player import AUDIO_EXTENSIONS, Player, Track, format_time, probe_duration, read_m3u, write_m3u
from . import icons
from . import theme
from .meter import format_db

INDEX_ROLE = Qt.ItemDataRole.UserRole + 1
TRACK_ROLE = Qt.ItemDataRole.UserRole + 2


def short_error(exc: Exception) -> str:
    """Messaggio d'errore leggibile (yt-dlp scrive righe lunghissime)."""
    msg = str(exc).replace("ERROR: ", "").split("; please report", 1)[0]
    return msg if len(msg) <= 220 else msg[:217] + "…"


class _Bridge(QObject):
    player_event = Signal(str)
    tracks_found = Signal(int, list, str)      # id richiesta, brani, modalità ("add" | "search")
    failed = Signal(str)
    duration = Signal(object, float)            # Track, durata


class PlayerView(QWidget):
    started = Signal()          # un brano è partito (per far trasmettere il bot)
    changed = Signal()          # qualcosa da salvare
    level_changed = Signal()    # volume del canale Player cambiato da qui

    def __init__(self, player: Player, strip, parent=None):
        super().__init__(parent)
        self.player = player
        self.strip = strip
        self._pool = ThreadPoolExecutor(max_workers=3)
        self._bridge = _Bridge()
        self._bridge.player_event.connect(self._on_player_event)
        self._bridge.tracks_found.connect(self._on_tracks_found)
        self._bridge.failed.connect(self._on_failed)
        self._bridge.duration.connect(self._on_duration)
        player.on_change = self._bridge.player_event.emit
        player.resolvers["youtube"] = youtube.resolver
        self._request = 0
        self._request_by = ""
        self._seeking = False
        self.last_message = ""
        self.setAcceptDrops(True)

        # In riproduzione -----------------------------------------------------------------
        now = QFrame()
        now.setObjectName("panel")
        self.title = QLabel("Nessun brano")
        self.title.setStyleSheet("font-size: 16pt; font-weight: 700;")
        self.title.setWordWrap(True)
        self.subtitle = QLabel("Aggiungi file, cartelle, link o playlist di YouTube")
        self.subtitle.setStyleSheet(f"color: {theme.MUTED};")
        self.elapsed = QLabel("0:00")
        self.total = QLabel("--:--")
        for lab in (self.elapsed, self.total):
            lab.setObjectName("dbLabel")
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._do_seek)
        srow = QHBoxLayout()
        srow.addWidget(self.elapsed)
        srow.addWidget(self.seek, 1)
        srow.addWidget(self.total)

        def tbtn(name, tip, fn, big=False):
            b = QToolButton()
            b.setIcon(icons.icon(name))
            b.setIconSize(QSize(30, 30) if big else QSize(22, 22))
            b.setToolTip(tip)
            b.clicked.connect(fn)
            b.setStyleSheet("padding: 4px 14px;" if big else "padding: 4px 10px;")
            b.setMinimumSize(56 if big else 44, 40)
            return b

        self.prev_btn = tbtn("prev", "Precedente", player.prev)
        self.play_btn = tbtn("play", "Play / Pausa (spazio)", self._toggle, big=True)
        self.stop_btn = tbtn("stop", "Stop", player.stop)
        self.next_btn = tbtn("next", "Successivo", player.next)
        self.repeat_btn = tbtn("repeat", "Ripeti: no", self._cycle_repeat)
        self.shuffle_btn = tbtn("shuffle", "Casuale", self._toggle_shuffle)
        self.shuffle_btn.setCheckable(True)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(int(MIN_DB * 10), int(MAX_DB * 10))
        self.volume.setFixedWidth(160)
        self.volume.valueChanged.connect(self._on_volume)
        self.volume_label = QLabel()
        self.volume_label.setObjectName("dbLabel")
        self.volume_label.setMinimumWidth(64)
        trow = QHBoxLayout()
        for b in (self.prev_btn, self.play_btn, self.stop_btn, self.next_btn):
            trow.addWidget(b)
        trow.addSpacing(12)
        trow.addWidget(self.repeat_btn)
        trow.addWidget(self.shuffle_btn)
        trow.addStretch(1)
        trow.addWidget(QLabel("Volume"))
        trow.addWidget(self.volume)
        trow.addWidget(self.volume_label)
        self.status = QLabel()
        self.status.setWordWrap(True)
        nv = QVBoxLayout(now)
        nv.setContentsMargins(14, 12, 14, 12)
        nv.addWidget(self.title)
        nv.addWidget(self.subtitle)
        nv.addLayout(srow)
        nv.addLayout(trow)
        nv.addWidget(self.status)

        # Aggiunta ------------------------------------------------------------------------
        self.input = QLineEdit()
        self.input.setPlaceholderText("Incolla un link YouTube (video o playlist) oppure cerca su YouTube…")
        self.input.returnPressed.connect(self._submit)
        go = QPushButton("Aggiungi / Cerca")
        go.setObjectName("primary")
        go.clicked.connect(self._submit)
        add_files = QPushButton("File…")
        add_files.clicked.connect(self._add_files)
        add_dir = QPushButton("Cartella…")
        add_dir.clicked.connect(self._add_folder)
        open_pl = QPushButton("Apri playlist…")
        open_pl.clicked.connect(self._open_playlist)
        save_pl = QPushButton("Salva playlist…")
        save_pl.clicked.connect(self._save_playlist)
        clear = QPushButton("Svuota")
        clear.setObjectName("danger")
        clear.clicked.connect(self._clear)
        arow = QHBoxLayout()
        arow.addWidget(self.input, 1)
        arow.addWidget(go)
        brow = QHBoxLayout()
        for b in (add_files, add_dir, open_pl, save_pl):
            brow.addWidget(b)
        brow.addStretch(1)
        brow.addWidget(clear)

        # Coda e risultati -------------------------------------------------------------------
        queue_panel = QFrame()
        queue_panel.setObjectName("panel")
        qtitle = QLabel("CODA")
        qtitle.setObjectName("sectionTitle")
        self.queue_count = QLabel()
        self.queue_count.setStyleSheet(f"color: {theme.MUTED};")
        self.queue = QListWidget()
        self.queue.setObjectName("library")
        self.queue.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.queue.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.queue.itemDoubleClicked.connect(lambda it: player.play(it.data(INDEX_ROLE)))
        self.queue.model().rowsMoved.connect(self._on_rows_moved)
        self.queue.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue.customContextMenuRequested.connect(self._queue_menu)
        QShortcut(QKeySequence.StandardKey.Delete, self.queue, activated=self._remove_selected)
        qh = QHBoxLayout()
        qh.addWidget(qtitle)
        qh.addStretch(1)
        qh.addWidget(self.queue_count)
        qv = QVBoxLayout(queue_panel)
        qv.setContentsMargins(10, 10, 10, 10)
        qv.addLayout(qh)
        qv.addWidget(self.queue, 1)

        self.results_panel = QFrame()
        self.results_panel.setObjectName("panel")
        rtitle = QLabel("RISULTATI YOUTUBE")
        rtitle.setObjectName("sectionTitle")
        self.results = QListWidget()
        self.results.setObjectName("library")
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results.itemDoubleClicked.connect(lambda it: self._add_results([it], play=True))
        add_sel = QPushButton("Aggiungi selezionati")
        add_sel.clicked.connect(lambda: self._add_results(self.results.selectedItems()))
        play_now = QPushButton(icons.icon("play"), "Riproduci subito")
        play_now.clicked.connect(lambda: self._add_results(self.results.selectedItems()[:1], play=True))
        close_res = QToolButton(text="✕")
        close_res.clicked.connect(lambda: self.results_panel.hide())
        rh = QHBoxLayout()
        rh.addWidget(rtitle)
        rh.addStretch(1)
        rh.addWidget(close_res)
        rb = QHBoxLayout()
        rb.addWidget(play_now)
        rb.addWidget(add_sel)
        rb.addStretch(1)
        rv = QVBoxLayout(self.results_panel)
        rv.setContentsMargins(10, 10, 10, 10)
        rv.addLayout(rh)
        rv.addWidget(self.results, 1)
        rv.addLayout(rb)
        self.results_panel.hide()

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(queue_panel)
        split.addWidget(self.results_panel)
        split.setChildrenCollapsible(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.addWidget(now)
        lay.addLayout(arow)
        lay.addLayout(brow)
        lay.addWidget(split, 1)

        if not youtube.available():
            self._set_status(f"YouTube non disponibile: {youtube.unavailable_reason()}", error=True)

        self._timer = QTimer(self, interval=250)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.sync_volume()
        self.refresh()

    # Aggiornamento -------------------------------------------------------------------
    def refresh(self) -> None:
        self.queue.blockSignals(True)
        self.queue.clear()
        for i, t in enumerate(self.player.tracks):
            it = QListWidgetItem(f"{t.title}    {format_time(t.duration)}")
            if i == self.player.index:
                it.setIcon(icons.icon("now"))
            elif t.kind == "youtube":
                it.setIcon(icons.icon("youtube"))
            else:
                it.setIcon(icons.icon("blank"))     # allinea i titoli
            it.setData(INDEX_ROLE, i)
            it.setToolTip(t.source)
            if i == self.player.index:
                it.setForeground(Qt.GlobalColor.white)
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            self.queue.addItem(it)
        self.queue.blockSignals(False)
        n = len(self.player.tracks)
        total = sum(t.duration or 0 for t in self.player.tracks)
        self.queue_count.setText(f"{n} brani · {format_time(total)}" if n else "vuota")
        self._refresh_now()

    def _refresh_now(self) -> None:
        t = self.player.current
        st = self.player.state
        self.play_btn.setIcon(icons.icon("pause" if st in ("playing", "loading") else "play"))
        if t is None:
            self.title.setText("Nessun brano")
            self.subtitle.setText("Aggiungi file, cartelle, link o playlist di YouTube")
            return
        self.title.setText(t.title)
        where = "YouTube" if t.kind == "youtube" else Path(t.source).parent.name or "File"
        state = {"loading": "Scarico da YouTube…" if t.kind == "youtube" else "Caricamento…",
                 "paused": "In pausa", "stopped": "Fermo"}.get(st, "In riproduzione")
        self.subtitle.setText(f"{state} · {where}")
        self.total.setText(format_time(t.duration))

    def _tick(self) -> None:
        t = self.player.current
        if t is None:
            return
        pos = self.player.position if self.player.state != "stopped" else 0.0
        self.elapsed.setText(format_time(pos))
        if not self._seeking:
            self.seek.blockSignals(True)
            self.seek.setValue(int(pos / t.duration * 1000) if t.duration else 0)
            self.seek.blockSignals(False)
        self.seek.setEnabled(bool(t.duration))
        if self.volume.value() != int(round(self.strip.gain_db * 10)):
            self.sync_volume()

    def sync_volume(self) -> None:
        self.volume.blockSignals(True)
        self.volume.setValue(int(round(self.strip.gain_db * 10)))
        self.volume.blockSignals(False)
        self.volume_label.setText(format_db(self.strip.gain_db))

    def _set_status(self, text: str, error: bool = False) -> None:
        self.last_message = text
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {theme.DANGER if error else theme.MUTED};")

    def _on_player_event(self, event: str) -> None:
        if event == "progress":
            p = self.player.load_progress
            if p is not None and self.player.state == "loading":
                self.subtitle.setText(f"Scarico da YouTube… {p * 100:.0f}%")
            return
        if event == "error":
            self._set_status(short_error(Exception(self.player.error)), error=True)
            eventlog.log(eventlog.ERROR, f"Player: {short_error(Exception(self.player.error))}", "")
        elif event in ("track", "queue"):
            if event == "track":
                self._set_status("")
                self._prefetch_next()
                cur = self.player.current
                if cur is not None:
                    eventlog.log(eventlog.PLAYER, f"In riproduzione: {cur.title}", "")
            self.refresh()
            self.changed.emit()
        else:
            self._refresh_now()
        if self.player.state in ("playing", "loading"):
            self.started.emit()

    def _on_failed(self, msg: str) -> None:
        self._set_status(msg, error=True)
        eventlog.log(eventlog.ERROR, msg, self._request_by or None)

    def _prefetch_next(self) -> None:
        """Scarica in anticipo il prossimo brano di YouTube, così parte subito."""
        nxt = self.player.index + 1
        if 0 <= nxt < len(self.player.tracks):
            t = self.player.tracks[nxt]
            if t.kind == "youtube":
                try:
                    youtube.prefetch(t)
                except Exception:
                    pass

    # Trasporto ----------------------------------------------------------------------------
    def _toggle(self) -> None:
        if not self.player.tracks:
            return
        self.player.toggle()

    def _do_seek(self) -> None:
        self._seeking = False
        t = self.player.current
        if t and t.duration:
            self.player.seek(self.seek.value() / 1000 * t.duration)

    def _cycle_repeat(self) -> None:
        order = ["off", "all", "one"]
        self.player.repeat = order[(order.index(self.player.repeat) + 1) % 3]
        self._update_mode_buttons()
        self.changed.emit()

    def _toggle_shuffle(self) -> None:
        self.player.shuffle = self.shuffle_btn.isChecked()
        self._update_mode_buttons()
        self.changed.emit()

    def _update_mode_buttons(self) -> None:
        r = self.player.repeat
        on_color = "#10221f"                       # icona scura sul pulsante acceso (verde acqua)
        self.repeat_btn.setIcon(icons.icon("repeat_one" if r == "one" else "repeat",
                                           on_color if r != "off" else theme.TEXT))
        self.repeat_btn.setToolTip({"off": "Ripeti: no", "all": "Ripeti: tutta la coda", "one": "Ripeti: brano"}[r])
        self.repeat_btn.setStyleSheet("padding: 4px 10px;" +
                                      (f"background: {theme.ACCENT_2};" if r != "off" else ""))
        self.shuffle_btn.setChecked(self.player.shuffle)
        self.shuffle_btn.setIcon(icons.icon("shuffle", on_color if self.player.shuffle else theme.TEXT))
        self.shuffle_btn.setStyleSheet("padding: 4px 10px;" +
                                       (f"background: {theme.ACCENT_2};" if self.player.shuffle else ""))

    def showEvent(self, event):
        self._update_mode_buttons()
        super().showEvent(event)

    def _on_volume(self, value: int) -> None:
        self.strip.gain_db = value / 10.0
        self.volume_label.setText(format_db(self.strip.gain_db))
        self.level_changed.emit()

    # Aggiunta brani --------------------------------------------------------------------
    def add_tracks(self, tracks: list[Track], play: bool = False, by: str | None = None) -> None:
        if not tracks:
            return
        names = ", ".join(f"«{t.title}»" for t in tracks[:3]) + (f" e altri {len(tracks) - 3}" if len(tracks) > 3 else "")
        eventlog.log(eventlog.PLAYER, f"Aggiunge alla coda: {names}", by)
        start = len(self.player.tracks)
        self.player.add(tracks)
        for t in tracks:
            if t.kind == "file" and t.duration is None:
                self._pool.submit(self._probe, t)
        if play or self.player.state == "stopped" and start == 0:
            self.player.play(start)

    def _probe(self, track: Track) -> None:
        d = probe_duration(track.source)
        if d:
            self._bridge.duration.emit(track, d)

    def _on_duration(self, track: Track, d: float) -> None:
        track.duration = d
        self.refresh()

    def _submit(self) -> None:
        self.add_from_text(self.input.text())

    def add_from_text(self, text: str, remote: bool = False, by: str | None = None) -> None:
        """Link YouTube (video/playlist), percorso o ricerca. Dal telefono la ricerca aggiunge il primo risultato."""
        text = text.strip()
        if not text:
            return
        p = Path(text.strip('"'))
        if not remote and p.exists():
            self.input.clear()
            self._add_paths([p])
            return
        if not youtube.available():
            self._set_status(f"YouTube non disponibile: {youtube.unavailable_reason()}", error=True)
            return
        self._request += 1
        rid = self._request
        self._request_by = by or eventlog.current_actor()   # i risultati arrivano dopo: si ricorda chi ha chiesto
        if youtube.is_youtube_url(text):
            self._set_status("Leggo il link di YouTube…")
            mode, job = "add", (lambda: youtube.resolve(text))
        else:
            self._set_status(f"Cerco «{text}» su YouTube…")
            mode = "first" if remote else "search"
            job = (lambda: youtube.search(text, count=5 if remote else 15))

        def run():
            try:
                self._bridge.tracks_found.emit(rid, job(), mode)
            except Exception as exc:
                self._bridge.failed.emit(f"YouTube: {short_error(exc)}")

        self._pool.submit(run)

    def _on_tracks_found(self, rid: int, tracks: list, mode: str) -> None:
        if rid != self._request:
            return
        if not tracks:
            self._set_status("Nessun risultato.", error=True)
            return
        if mode == "first":
            t = tracks[0]
            self._set_status(f"Aggiunto «{t.title}» ({self._request_by}).")
            self.add_tracks([t], by=self._request_by)
            return
        if mode == "add":
            self.input.clear()
            self._set_status(f"Aggiunti {len(tracks)} brani da YouTube." if len(tracks) > 1
                             else f"Aggiunto «{tracks[0].title}».")
            self.add_tracks(tracks, by=self._request_by)
            return
        self._set_status(f"{len(tracks)} risultati: doppio clic per riprodurre, oppure selezionali e aggiungili.")
        self.results.clear()
        for t in tracks:
            it = QListWidgetItem(icons.icon("youtube"), f"{t.title}    {format_time(t.duration)}")
            it.setData(TRACK_ROLE, t)
            it.setToolTip(t.source)
            self.results.addItem(it)
        self.results_panel.show()

    def _add_results(self, items, play: bool = False) -> None:
        tracks = [Track(t.title, t.source, t.kind, t.duration) for t in (it.data(TRACK_ROLE) for it in items)]
        self.add_tracks(tracks, play=play)

    def _add_paths(self, paths: list[Path]) -> None:
        files: list[Path] = []
        for p in paths:
            if p.is_dir():
                files += sorted((f for f in p.rglob("*") if f.suffix.lower() in AUDIO_EXTENSIONS),
                                key=lambda f: str(f).lower())
            elif p.suffix.lower() in (".m3u", ".m3u8"):
                self.add_tracks(read_m3u(p))
            elif p.suffix.lower() in AUDIO_EXTENSIONS:
                files.append(p)
        self.add_tracks([Track.from_file(f) for f in files])

    def _add_files(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(self, "Aggiungi musica", "", f"Audio e video ({exts})")
        self._add_paths([Path(f) for f in files])

    def _add_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Aggiungi una cartella di musica")
        if d:
            self._add_paths([Path(d)])

    def _open_playlist(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Apri playlist", "", "Playlist (*.m3u *.m3u8)")
        if path:
            self.add_tracks(read_m3u(Path(path)))

    def _save_playlist(self) -> None:
        if not self.player.tracks:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salva playlist", "playlist.m3u", "Playlist (*.m3u)")
        if path:
            write_m3u(Path(path), self.player.tracks)
            self._set_status(f"Playlist salvata: {path}")

    def _clear(self) -> None:
        if self.player.tracks and QMessageBox.question(self, "Svuota", "Svuotare la coda?") \
                == QMessageBox.StandardButton.Yes:
            self.player.clear()

    # Coda ---------------------------------------------------------------------------------
    def _on_rows_moved(self, parent, start, end, dest, row) -> None:
        dst = row if row < start else row - 1
        self.player.move(start, dst)

    def _remove_selected(self) -> None:
        for i in sorted((it.data(INDEX_ROLE) for it in self.queue.selectedItems()), reverse=True):
            self.player.remove(i)

    def _queue_menu(self, pos) -> None:
        item = self.queue.itemAt(pos)
        if not item:
            return
        i = item.data(INDEX_ROLE)
        t = self.player.tracks[i]
        m = QMenu(self)
        m.addAction(icons.icon("play"), "Riproduci", lambda: self.player.play(i))
        if t.kind == "youtube":
            m.addAction("Apri su YouTube", lambda: QDesktopServices.openUrl(QUrl(t.source)))
        m.addSeparator()
        m.addAction("Rimuovi", self._remove_selected)
        m.exec(self.queue.mapToGlobal(pos))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self._add_paths([Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()])

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
