"""Impostazioni di un suono: volume, colore, icona, scorciatoia e nota MIDI."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QColorDialog, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout, QKeySequenceEdit,
    QLabel, QLineEdit, QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget,
)

from .. import midi
from . import theme

PALETTE = [
    ("Rosso", "#e5534b"), ("Arancio", "#f0883e"), ("Giallo", "#d4a72c"), ("Verde", "#57ab5a"),
    ("Acqua", "#3ec7b2"), ("Azzurro", "#39a0ed"), ("Blu", "#6e7ff3"), ("Viola", "#a371f7"),
    ("Rosa", "#db61a2"), ("Marrone", "#b08968"), ("Grigio", "#8b949e"), ("Notte", "#3b4a63"),
]

QUICK_EMOJI = [
    "😂", "🤣", "😱", "😭", "💀", "🤡", "😎", "🙏",
    "🔥", "💥", "⚡", "🎉", "👏", "👍", "👎", "❤️",
    "🥁", "🎺", "📯", "🎵", "🔔", "🚨", "🐐", "🦆",
]


class MidiBridge(QObject):
    """Porta gli eventi MIDI dal thread di rtmidi all'interfaccia."""
    event = Signal(object)          # midi.MidiEvent


def text_color_for(bg: QColor) -> QColor:
    lum = 0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()
    return QColor("#15171c") if lum > 0.55 else QColor("#f4f5f8")


class SoundSettingsDialog(QDialog):
    def __init__(self, name: str, settings: dict, bridge: MidiBridge | None = None,
                 midi_port: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Impostazioni — {name}")
        self.setMinimumWidth(460)
        self._bridge = bridge
        self._midi_port = midi_port
        self._learning = False
        self.color: str = settings.get("color", "") or ""
        self.midi_binding: dict | None = settings.get("midi") or None

        # Volume -------------------------------------------------------------------
        volume = float(settings.get("volume", 1.0))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 200)
        self.volume.setValue(int(volume * 100))
        vol_label = QLabel(f"{int(volume * 100)}%")
        vol_label.setMinimumWidth(40)
        self.volume.valueChanged.connect(lambda v: vol_label.setText(f"{v}%"))
        vrow = QHBoxLayout()
        vrow.addWidget(self.volume, 1)
        vrow.addWidget(vol_label)

        # Colore -------------------------------------------------------------------
        color_box = QWidget()
        cg = QGridLayout(color_box)
        cg.setContentsMargins(0, 0, 0, 0)
        cg.setSpacing(4)
        self._swatches: list[tuple[QToolButton, str]] = []
        none_btn = QToolButton(text="✕")
        none_btn.setToolTip("Nessun colore")
        none_btn.setFixedSize(26, 26)
        none_btn.clicked.connect(lambda: self._set_color(""))
        cg.addWidget(none_btn, 0, 0)
        self._swatches.append((none_btn, ""))
        for i, (label, hexcol) in enumerate(PALETTE, start=1):
            b = QToolButton()
            b.setToolTip(label)
            b.setFixedSize(26, 26)
            b.clicked.connect(lambda _=False, c=hexcol: self._set_color(c))
            cg.addWidget(b, i // 7, i % 7)
            self._swatches.append((b, hexcol))
        more = QPushButton("Altro…")
        more.clicked.connect(self._pick_color)
        cg.addWidget(more, 1, 7)
        self._custom_btn = more

        # Icona ----------------------------------------------------------------------
        self.emoji = QLineEdit(settings.get("emoji", ""))
        self.emoji.setPlaceholderText("Emoji (Win + . per tutte)")
        self.emoji.setMaxLength(8)
        self.emoji.setMaximumWidth(170)
        self.emoji.setStyleSheet("font-size: 14pt;")
        emoji_clear = QPushButton("Togli")
        emoji_clear.clicked.connect(self.emoji.clear)
        erow = QHBoxLayout()
        erow.addWidget(self.emoji)
        erow.addWidget(emoji_clear)
        erow.addStretch(1)
        quick = QWidget()
        qg = QGridLayout(quick)
        qg.setContentsMargins(0, 0, 0, 0)
        qg.setSpacing(2)
        for i, e in enumerate(QUICK_EMOJI):
            b = QToolButton(text=e)
            b.setFixedSize(30, 30)
            b.setStyleSheet("font-size: 13pt; padding: 0;")
            b.clicked.connect(lambda _=False, e=e: self.emoji.setText(e))
            qg.addWidget(b, i // 8, i % 8)
        ebox = QVBoxLayout()
        ebox.addLayout(erow)
        ebox.addWidget(quick)

        # Scorciatoia ----------------------------------------------------------------
        self.shortcut = QKeySequenceEdit(QKeySequence(settings.get("shortcut", "")))
        clear = QPushButton("Cancella")
        clear.clicked.connect(self.shortcut.clear)
        srow = QHBoxLayout()
        srow.addWidget(self.shortcut, 1)
        srow.addWidget(clear)

        # MIDI -------------------------------------------------------------------------
        self.midi_label = QLabel()
        self.learn_btn = QPushButton("Impara")
        self.learn_btn.setToolTip("Premi e poi suona la nota o il pad del controller")
        self.learn_btn.clicked.connect(self._toggle_learn)
        midi_clear = QPushButton("Cancella")
        midi_clear.clicked.connect(lambda: self._set_midi(None))
        mrow = QHBoxLayout()
        mrow.addWidget(self.midi_label, 1)
        mrow.addWidget(self.learn_btn)
        mrow.addWidget(midi_clear)
        self.midi_hint = QLabel()
        self.midi_hint.setWordWrap(True)
        self.midi_hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
        mbox = QVBoxLayout()
        mbox.addLayout(mrow)
        mbox.addWidget(self.midi_hint)
        if not midi.available():
            self.learn_btn.setEnabled(False)
            self.midi_hint.setText("MIDI non disponibile: manca la libreria python-rtmidi.")
        elif not midi_port:
            self.learn_btn.setEnabled(False)
            self.midi_hint.setText("Scegli prima un controller in Impostazioni → MIDI.")
        else:
            self.midi_hint.setText(f"Controller: {midi_port}")

        form = QFormLayout()
        form.addRow("Volume", vrow)
        form.addRow("Colore", color_box)
        form.addRow("Icona", ebox)
        form.addRow("Scorciatoia", srow)
        form.addRow("MIDI", mbox)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

        self._set_color(self.color)
        self._set_midi(self.midi_binding)

    # Colore ---------------------------------------------------------------------------
    def _set_color(self, color: str) -> None:
        self.color = color
        for b, c in self._swatches:
            selected = c == color
            border = theme.TEXT if selected else theme.BORDER
            width = 2 if selected else 1
            bg = c or theme.PANEL_2
            b.setStyleSheet(f"background: {bg}; border: {width}px solid {border}; border-radius: 6px;")
        custom = color and color not in [c for _, c in PALETTE]
        self._custom_btn.setStyleSheet(
            f"background: {color}; color: {text_color_for(QColor(color)).name()};" if custom else "")

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self.color or theme.ACCENT), self, "Colore del pad")
        if c.isValid():
            self._set_color(c.name())

    # MIDI ----------------------------------------------------------------------------
    def _set_midi(self, binding: dict | None) -> None:
        self.midi_binding = binding
        self.midi_label.setText(midi.binding_label(binding) or "Nessuna nota assegnata")

    def _toggle_learn(self) -> None:
        if self._bridge is None:
            return
        if self._learning:
            self._stop_learn()
            return
        self._learning = True
        self.learn_btn.setText("Annulla")
        self.midi_label.setText("Suona una nota sul controller…")
        self._bridge.event.connect(self._on_midi)

    def _stop_learn(self) -> None:
        if self._learning and self._bridge is not None:
            try:
                self._bridge.event.disconnect(self._on_midi)
            except (RuntimeError, TypeError):
                pass
        self._learning = False
        self.learn_btn.setText("Impara")
        self._set_midi(self.midi_binding)

    def _on_midi(self, ev) -> None:
        self.midi_binding = ev.binding()
        self._stop_learn()

    @property
    def learning(self) -> bool:
        return self._learning

    def done(self, result: int) -> None:
        self._stop_learn()
        super().done(result)

    def values(self) -> dict:
        return {
            "volume": self.volume.value() / 100.0,
            "shortcut": self.shortcut.keySequence().toString(),
            "color": self.color,
            "emoji": self.emoji.text().strip(),
            "midi": self.midi_binding,
        }
