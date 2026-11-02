"""Frasi da far dire alla sintesi vocale: finestra per crearle o modificarle e scelta della voce."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)

from .. import tts
from . import theme


class VoiceLoader(QObject):
    """Carica gli elenchi delle voci in un thread (le voci neurali arrivano da Internet)."""

    loaded = Signal(str, object)          # motore, list[tts.Voice]

    def load(self, engine: str, refresh: bool = False) -> None:
        cached = None if refresh else tts.cached_voices(engine)
        if cached is not None:
            self.loaded.emit(engine, cached)
            return

        def run():
            try:
                voices = tts.list_voices(engine, refresh=refresh)
            except Exception:
                voices = []
            try:
                self.loaded.emit(engine, voices)
            except RuntimeError:
                pass                       # finestra già chiusa

        threading.Thread(target=run, name=f"tts-voices-{engine}", daemon=True).start()


class VoiceCombo(QComboBox):
    """Scelta della voce. ``engines`` = motori da elencare; con ``default_item`` la prima voce
    è «Predefinita» (dati vuoti). I dati di ogni voce sono (motore, id)."""

    def __init__(self, engines: list[str], selected: tuple[str, str] = ("", ""), default_item: str = "",
                 parent=None):
        super().__init__(parent)
        self.engines = engines
        self.default_item = default_item
        self._selected = selected
        self._voices: dict[str, list[tts.Voice]] = {}
        self.setMinimumContentsLength(28)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.loader = VoiceLoader(self)
        self.loader.loaded.connect(self._on_loaded)
        self._rebuild()
        for e in engines:
            self.loader.load(e)

    def set_engines(self, engines: list[str]) -> None:
        self._selected = self.selected()
        self.engines = engines
        self._rebuild()
        for e in engines:
            if e not in self._voices:
                self.loader.load(e)

    def refresh(self) -> None:
        self._selected = self.selected()
        for e in self.engines:
            self.loader.load(e, refresh=True)

    def selected(self) -> tuple[str, str]:
        data = self.currentData()
        return tuple(data) if data else ("", "")

    def _on_loaded(self, engine: str, voices) -> None:
        self._voices[engine] = list(voices)
        self._selected = self.selected() if self.count() else self._selected
        self._rebuild()

    def _rebuild(self) -> None:
        keep = self._selected
        self.blockSignals(True)
        self.clear()
        if self.default_item:
            self.addItem(self.default_item, None)
        for e in self.engines:
            voices = self._voices.get(e)
            prefix = "🌐 " if e == tts.ENGINE_EDGE and len(self.engines) > 1 else \
                "💻 " if len(self.engines) > 1 else ""
            if voices is None:
                self.addItem(f"{prefix}Carico le voci…", None)
                self.model().item(self.count() - 1).setEnabled(False)
                continue
            for v in voices:
                self.addItem(prefix + v.label, (e, v.id))
        if keep and keep[1]:
            idx = self.findData(keep)
            if idx < 0:                            # voce salvata ma non (ancora) nell'elenco
                self.addItem(f"{keep[1]}", tuple(keep))
                idx = self.count() - 1
            self.setCurrentIndex(idx)
        else:
            self.setCurrentIndex(0)
        self.blockSignals(False)


class PhraseDialog(QDialog):
    """Testo e voce di una frase sul pad."""

    def __init__(self, phrase: dict | None, preview: Callable[[str, str, str], None] | None = None,
                 parent=None):
        super().__init__(parent)
        phrase = phrase or {}
        self.setWindowTitle("Modifica frase" if phrase.get("text") else "Nuova frase")
        self.setMinimumWidth(480)
        self._preview = preview
        self.text = QPlainTextEdit(phrase.get("text", ""))
        self.text.setPlaceholderText("Cosa deve dire, es. «Buonanotte a tutti!»")
        self.text.setMinimumHeight(90)
        self.text.setTabChangesFocus(True)
        engines = [tts.ENGINE_EDGE, tts.ENGINE_SYSTEM]
        self.voice = VoiceCombo(engines, (phrase.get("engine", ""), phrase.get("voice", "")),
                                default_item="Voce predefinita")
        self.voice.setToolTip("«Voce predefinita» segue Impostazioni → Sintesi vocale")
        listen = QPushButton("▶  Ascolta in cuffia")
        listen.setToolTip("Anteprima solo per te: non arriva a Discord")
        listen.clicked.connect(self._listen)
        listen.setEnabled(preview is not None)
        vrow = QHBoxLayout()
        vrow.addWidget(self.voice, 1)
        vrow.addWidget(listen)
        form = QFormLayout()
        form.addRow("Frase", self.text)
        form.addRow("Voce", vrow)
        hint = QLabel("🌐 voci neurali Microsoft (servono Internet) · 💻 voci del sistema (offline). "
                      "Nome, colore, emoji, scorciatoia e nota MIDI si cambiano con «Personalizza…».")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self.error = QLabel()
        self.error.setStyleSheet(f"color: {theme.DANGER};")
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(self.error)
        lay.addWidget(buttons)

    def values(self) -> dict:
        engine, voice = self.voice.selected()
        return {"text": tts.clean_text(self.text.toPlainText()), "engine": engine, "voice": voice}

    def _listen(self) -> None:
        v = self.values()
        if v["text"] and self._preview is not None:
            self._preview(v["text"], v["voice"], v["engine"])

    def _accept(self) -> None:
        if not self.values()["text"]:
            self.error.setText("Scrivi la frase.")
            return
        self.accept()
