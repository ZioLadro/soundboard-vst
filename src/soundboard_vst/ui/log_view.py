"""Scheda «Registro»: console con tutto quello che succede (chi suona cosa, playlist, Discord…)."""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import eventlog
from . import theme

MAX_ROWS = eventlog.MAX_EVENTS


class _Bridge(QObject):
    event = Signal(object)


class LogView(QWidget):
    def __init__(self, log: eventlog.EventLog | None = None, parent=None):
        super().__init__(parent)
        self.log = log or eventlog.LOG
        self.kind = QComboBox()
        self.kind.addItem("Tutto", "")
        for key, label in eventlog.CATEGORIES.items():
            self.kind.addItem(f"{eventlog.ICONS.get(key, '')}  {label}", key)
        self.kind.currentIndexChanged.connect(self._rebuild)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca (nome, suono, comando…)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._rebuild)
        self.follow = QCheckBox("Scorri in automatico")
        self.follow.setChecked(True)
        clear = QPushButton("Pulisci")
        clear.setToolTip("Svuota la console (i file del registro restano)")
        clear.clicked.connect(self._clear)
        folder = QPushButton("Apri cartella dei registri")
        folder.setToolTip("Un file al giorno, tenuto per 14 giorni")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log.folder()))))
        self.count = QLabel()
        self.count.setStyleSheet(f"color: {theme.MUTED};")
        bar = QHBoxLayout()
        bar.addWidget(self.kind)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.follow)
        bar.addWidget(self.count)
        bar.addWidget(clear)
        bar.addWidget(folder)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Ora", "Tipo", "Chi", "Cosa"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        hdr = self.table.horizontalHeader()
        for col in (0, 1, 2):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.addLayout(bar)
        lay.addWidget(self.table, 1)

        self._bridge = _Bridge()
        self._bridge.event.connect(self._on_event)
        self.log.add_listener(self._bridge.event.emit)
        self._rebuild()

    def shutdown(self) -> None:
        self.log.remove_listener(self._bridge.event.emit)

    # Filtri ----------------------------------------------------------------------------
    def _matches(self, ev: eventlog.Event) -> bool:
        kind = self.kind.currentData()
        if kind and ev.category != kind:
            return False
        t = self.search.text().strip().lower()
        return not t or t in ev.text.lower() or t in ev.who.lower()

    def _rebuild(self) -> None:
        self.table.setRowCount(0)
        for ev in self.log.events():
            if self._matches(ev):
                self._append(ev)
        self._update_count()
        if self.follow.isChecked():
            self.table.scrollToBottom()

    def _on_event(self, ev: eventlog.Event) -> None:
        if not self._matches(ev):
            return
        if self.table.rowCount() >= MAX_ROWS:
            self.table.removeRow(0)
        self._append(ev)
        self._update_count()
        if self.follow.isChecked():
            self.table.scrollToBottom()

    def _append(self, ev: eventlog.Event) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        cells = [time.strftime("%H:%M:%S", time.localtime(ev.time)),
                 f"{eventlog.ICONS.get(ev.category, '')} {eventlog.CATEGORIES.get(ev.category, ev.category)}",
                 ev.who, ev.text]
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if col == 0:
                item.setToolTip(time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(ev.time)))
            if col == 3:
                item.setToolTip(ev.text)
            if ev.category in (eventlog.ERROR, eventlog.PERMISSION):
                item.setForeground(QColor(theme.DANGER))
            elif col in (0, 1):
                item.setForeground(QColor(theme.MUTED))
            self.table.setItem(row, col, item)

    def _update_count(self) -> None:
        self.count.setText(f"{self.table.rowCount()} eventi")

    def _clear(self) -> None:
        self.log.clear()
        self._rebuild()

    def rows(self) -> list[tuple[str, str, str]]:
        """(tipo, chi, cosa) delle righe mostrate (per i test)."""
        return [tuple(self.table.item(r, c).text() for c in (1, 2, 3)) for r in range(self.table.rowCount())]
