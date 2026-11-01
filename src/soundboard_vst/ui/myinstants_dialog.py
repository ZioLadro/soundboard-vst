"""Finestra di ricerca su MyInstants: anteprima in cuffia e aggiunta ai pad."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout,
)

from .. import myinstants
from ..myinstants import Instant
from . import theme

INSTANT_ROLE = Qt.ItemDataRole.UserRole + 1


class _Bridge(QObject):
    """Riporta i risultati dei thread di rete nel thread dell'interfaccia."""
    results = Signal(int, list, bool)       # id richiesta, risultati, aggiungi
    failed = Signal(str)
    preview_ready = Signal(object, bytes)
    saved = Signal(object, object)          # Instant, Path


class MyInstantsDialog(QDialog):
    def __init__(self, folder: Callable[[], Path], on_preview: Callable[[bytes], None],
                 on_added: Callable[[Path], None], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cerca su MyInstants")
        self.resize(560, 620)
        self._folder = folder
        self._on_preview = on_preview
        self._on_added = on_added
        self._pool = ThreadPoolExecutor(max_workers=3)
        self._bridge = _Bridge()
        self._bridge.results.connect(self._show_results)
        self._bridge.failed.connect(self._show_error)
        self._bridge.preview_ready.connect(lambda inst, data: self._on_preview(data))
        self._bridge.saved.connect(self._on_saved)
        self._request = 0
        self._query = ""
        self._page = 1
        self._mode = "search"
        self._added: set[str] = set()

        self.query = QLineEdit()
        self.query.setPlaceholderText("Cerca un suono (es. vine boom, bruh, applausi)…")
        self.query.returnPressed.connect(self.search)
        go = QPushButton("Cerca")
        go.setObjectName("primary")
        go.clicked.connect(self.search)
        trend = QPushButton("Tendenze")
        trend.setToolTip("Suoni più popolari in Italia")
        trend.clicked.connect(self.load_trending)
        top = QHBoxLayout()
        top.addWidget(self.query, 1)
        top.addWidget(go)
        top.addWidget(trend)

        self.results = QListWidget()
        self.results.setObjectName("library")
        self.results.itemDoubleClicked.connect(lambda it: self.preview())
        self.results.currentItemChanged.connect(lambda *_: self._update_buttons())

        self.status = QLabel("Scrivi qualcosa e premi Invio.")
        self.status.setStyleSheet(f"color: {theme.MUTED};")
        self.status.setWordWrap(True)

        self.preview_btn = QPushButton("▶  Ascolta in cuffia")
        self.preview_btn.clicked.connect(self.preview)
        self.add_btn = QPushButton("＋  Aggiungi ai pad")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self.add_selected)
        self.more_btn = QPushButton("Altri risultati")
        self.more_btn.clicked.connect(self.load_more)
        self.page_btn = QPushButton("Apri pagina")
        self.page_btn.setToolTip("Apri la pagina del suono su myinstants.com")
        self.page_btn.clicked.connect(self._open_page)
        actions = QHBoxLayout()
        actions.addWidget(self.preview_btn)
        actions.addWidget(self.add_btn)
        actions.addStretch(1)
        actions.addWidget(self.page_btn)
        actions.addWidget(self.more_btn)

        note = QLabel("I suoni vengono scaricati da myinstants.com nella tua cartella dei suoni. "
                      "Molti sono estratti da opere protette: usali per divertimento personale.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.results, 1)
        lay.addWidget(self.status)
        lay.addLayout(actions)
        lay.addWidget(note)
        self._update_buttons()

    # Ricerca -------------------------------------------------------------------------
    def search(self) -> None:
        q = self.query.text().strip()
        if not q:
            return
        self._mode, self._query, self._page = "search", q, 1
        self._fetch(append=False)

    def load_trending(self) -> None:
        self._mode, self._query, self._page = "trending", "", 1
        self._fetch(append=False)

    def load_more(self) -> None:
        self._page += 1
        self._fetch(append=True)

    def _fetch(self, append: bool) -> None:
        self._request += 1
        rid, mode, q, page = self._request, self._mode, self._query, self._page
        self.status.setText("Cerco…")
        self.more_btn.setEnabled(False)

        def job():
            try:
                res = myinstants.trending("it", page) if mode == "trending" else myinstants.search(q, page)
                self._bridge.results.emit(rid, res, append)
            except Exception as exc:
                self._bridge.failed.emit(f"Ricerca non riuscita: {exc}")

        self._pool.submit(job)

    def _show_results(self, rid: int, res: list, append: bool) -> None:
        if rid != self._request:
            return   # risposta superata da una ricerca più recente
        if not append:
            self.results.clear()
        for inst in res:
            it = QListWidgetItem(inst.name + ("   ✓" if inst.url in self._added else ""))
            it.setData(INSTANT_ROLE, inst)
            it.setToolTip(inst.url)
            self.results.addItem(it)
        total = self.results.count()
        if not res and not append:
            self.status.setText("Nessun risultato.")
        elif not res:
            self.status.setText(f"{total} risultati, non ce ne sono altri.")
        else:
            self.status.setText(f"{total} risultati · doppio clic per ascoltare")
            if not append:
                self.results.setCurrentRow(0)
        self.more_btn.setEnabled(bool(res))
        self._update_buttons()

    def _show_error(self, msg: str) -> None:
        self.status.setText(msg)
        self.more_btn.setEnabled(self.results.count() > 0)

    # Azioni ------------------------------------------------------------------------
    def _current(self) -> Instant | None:
        it = self.results.currentItem()
        return it.data(INSTANT_ROLE) if it else None

    def _update_buttons(self) -> None:
        has = self._current() is not None
        for b in (self.preview_btn, self.add_btn, self.page_btn):
            b.setEnabled(has)

    def preview(self) -> None:
        inst = self._current()
        if not inst:
            return
        self.status.setText(f"Carico «{inst.name}»…")

        def job():
            try:
                self._bridge.preview_ready.emit(inst, myinstants.download_bytes(inst))
            except Exception as exc:
                self._bridge.failed.emit(f"Anteprima non riuscita: {exc}")

        self._pool.submit(job)

    def add_selected(self) -> None:
        inst = self._current()
        if not inst:
            return
        self.status.setText(f"Scarico «{inst.name}»…")
        folder = self._folder()

        def job():
            try:
                self._bridge.saved.emit(inst, myinstants.save_to(folder, inst))
            except Exception as exc:
                self._bridge.failed.emit(f"Download non riuscito: {exc}")

        self._pool.submit(job)

    def _on_saved(self, inst: Instant, path: Path) -> None:
        self._added.add(inst.url)
        for i in range(self.results.count()):
            it = self.results.item(i)
            if it.data(INSTANT_ROLE).url == inst.url and not it.text().endswith("✓"):
                it.setText(it.text() + "   ✓")
        self.status.setText(f"Aggiunto «{path.stem}» ai pad.")
        self._on_added(path)

    def _open_page(self) -> None:
        inst = self._current()
        if inst:
            QDesktopServices.openUrl(QUrl(inst.page_url))

    def done(self, result: int) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        super().done(result)
