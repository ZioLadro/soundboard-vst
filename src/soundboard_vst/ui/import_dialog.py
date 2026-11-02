"""Finestra «Nuovo suono da YouTube o da un link»."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
)

from .. import importer
from . import theme


class ImportDialog(QDialog):
    def __init__(self, parent=None, text: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Nuovo suono da YouTube o da un link")
        self.setMinimumWidth(520)
        self.source = QLineEdit(text)
        self.source.setPlaceholderText("Link di YouTube, di MyInstants o di un file audio, oppure cosa cercare su YouTube")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Facoltativo: altrimenti il titolo del video")
        self.start = QLineEdit()
        self.start.setPlaceholderText("es. 0:12")
        self.end = QLineEdit()
        self.end.setPlaceholderText("es. 0:18 (vuoto = fino alla fine)")
        trow = QHBoxLayout()
        trow.addWidget(QLabel("Da"))
        trow.addWidget(self.start)
        trow.addWidget(QLabel("a"))
        trow.addWidget(self.end)
        form = QFormLayout()
        form.addRow("Da dove", self.source)
        form.addRow("Nome", self.name)
        form.addRow("Pezzo", trow)
        hint = QLabel(f"Il suono viene scaricato, convertito in mp3 nella cartella dei suoni e messo nel primo pad "
                      f"libero. Massimo {importer.MAX_SECONDS // 60} minuti. Inizio e fine si possono ritoccare poi "
                      "con «Personalizza…». Scaricare da YouTube è contrario ai suoi termini: usalo per uso personale.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
        self.error = QLabel()
        self.error.setStyleSheet(f"color: {theme.DANGER};")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Importa")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(self.error)
        lay.addWidget(buttons)

    def values(self) -> dict:
        return {"source": self.source.text().strip(), "name": self.name.text().strip(),
                "start": self.start.text().strip(), "end": self.end.text().strip()}

    def _accept(self) -> None:
        v = self.values()
        if not v["source"]:
            self.error.setText("Scrivi un link o cosa cercare.")
            return
        try:
            start, end = importer.parse_time(v["start"]), importer.parse_time(v["end"])
        except importer.ImportError_ as exc:
            self.error.setText(str(exc).capitalize() + ".")
            return
        if end and end <= start:
            self.error.setText("La fine deve venire dopo l'inizio.")
            return
        self.accept()
