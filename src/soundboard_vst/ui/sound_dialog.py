"""Impostazioni di un suono: volume, inizio/fine e dissolvenze, colore, icona, scorciatoia e nota MIDI."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QDoubleSpinBox, QColorDialog, QDialog, QDialogButtonBox, QFileDialog, QMessageBox, QFormLayout, QGridLayout, QHBoxLayout, QKeySequenceEdit,
    QLabel, QLineEdit, QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget,
)

import hashlib
from pathlib import Path

from .. import midi
from ..audio.library import shape, shape_params
from ..config import config_dir
from . import theme
from .waveform import WaveformEditor
from .screen import fit_to_screen, scrollable

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


def store_image(src: Path) -> Path:
    """Copia l'immagine nella cartella dati del programma, ridotta a 512 px, e ne restituisce il percorso."""
    img = QImage(str(src))
    if img.isNull():
        raise ValueError("formato non supportato")
    if max(img.width(), img.height()) > 512:
        img = img.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    folder = config_dir() / "images"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{hashlib.sha1(src.read_bytes()).hexdigest()[:16]}.png"
    if not img.save(str(dest), "PNG"):
        raise OSError("salvataggio non riuscito")
    return dest


class MidiBridge(QObject):
    """Porta gli eventi MIDI dal thread di rtmidi all'interfaccia."""
    event = Signal(object)          # midi.MidiEvent


def text_color_for(bg: QColor) -> QColor:
    lum = 0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()
    return QColor("#15171c") if lum > 0.55 else QColor("#f4f5f8")


class SoundSettingsDialog(QDialog):
    """``audio``/``sample_rate``: il suono decodificato, per la forma d'onda (None se non disponibile).
    ``preview(dati, guadagno)``: anteprima in cuffia (con ``dati`` None la ferma)."""

    def __init__(self, name: str, settings: dict, bridge: MidiBridge | None = None,
                 midi_port: str = "", parent=None, audio=None, sample_rate: int = 48000, preview=None):
        super().__init__(parent)
        self._audio = audio
        self._sr = int(sample_rate)
        self._preview = preview
        self.setWindowTitle(f"Impostazioni — {name}")
        self.setMinimumWidth(460)
        self._bridge = bridge
        self._midi_port = midi_port
        self._learning = False
        self.color: str = settings.get("color", "") or ""
        self.image: str = settings.get("image", "") or ""

        # Nome sul pad -------------------------------------------------------------
        self.label = QLineEdit(settings.get("label", ""))
        self.label.setPlaceholderText(name)
        self.label.setToolTip("Nome mostrato sul pad (il file non viene rinominato). Vuoto = nome del file.")

        # Immagine ------------------------------------------------------------------
        self.image_preview = QLabel()
        self.image_preview.setFixedSize(72, 72)
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setStyleSheet(f"background: {theme.PANEL_2}; border: 1px solid {theme.BORDER};"
                                         "border-radius: 8px;")
        img_choose = QPushButton("Scegli…")
        img_choose.clicked.connect(self._choose_image)
        img_clear = QPushButton("Togli")
        img_clear.clicked.connect(lambda: self._set_image(""))
        ibtns = QVBoxLayout()
        ibtns.addWidget(img_choose)
        ibtns.addWidget(img_clear)
        ibtns.addStretch(1)
        irow = QHBoxLayout()
        irow.addWidget(self.image_preview)
        irow.addLayout(ibtns)
        irow.addStretch(1)
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

        # Inizio, fine e dissolvenze ---------------------------------------------------
        start, end, fade_in, fade_out = shape_params(settings)
        self.wave = WaveformEditor()
        duration = 0.0
        if audio is not None and getattr(audio, "size", 0):
            self.wave.set_audio(audio, self._sr)
            duration = self.wave.duration
        self.wave.set_values(start, end, fade_in, fade_out)
        limit = duration or 3600.0
        self.t_start, self.t_end, self.t_in, self.t_out = (self._time_box(limit) for _ in range(4))
        self.t_end.setSpecialValueText("fine")          # 0 = fino alla fine del suono
        self.t_end.setToolTip("Dove finisce il suono (0 = fino alla fine)")
        self.t_in.setToolTip("Dissolvenza in entrata: il volume sale da 0 in questo tempo")
        self.t_out.setToolTip("Dissolvenza in uscita: il volume scende a 0 in questo tempo")
        self.t_start.setValue(start)
        self.t_end.setValue(0.0 if not end or (duration and end >= duration - 0.0005) else end)
        self.t_in.setValue(fade_in)
        self.t_out.setValue(fade_out)
        for box in (self.t_start, self.t_end, self.t_in, self.t_out):
            box.valueChanged.connect(self._from_boxes)
        self.wave.changed.connect(self._from_wave)
        trow = QGridLayout()                       # due righe: sta anche nelle finestre strette
        for i, (label, box) in enumerate((("Inizio", self.t_start), ("Fine", self.t_end),
                                          ("Dissolvenza in entrata", self.t_in), ("in uscita", self.t_out))):
            trow.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            trow.addWidget(box, i // 2, (i % 2) * 2 + 1)
        trow.setColumnStretch(4, 1)
        listen = QPushButton("▶  Ascolta")
        listen.setToolTip("Anteprima solo in cuffia, con taglio, dissolvenze e volume scelti")
        listen.clicked.connect(self._listen)
        stop = QPushButton("■")
        stop.setToolTip("Ferma l'anteprima")
        stop.clicked.connect(lambda: self._preview(None, 0.0) if self._preview else None)
        reset = QPushButton("Ripristina")
        reset.setToolTip("Suono intero, senza dissolvenze")
        reset.clicked.connect(self._reset_shape)
        for b in (listen, stop):
            b.setEnabled(preview is not None and duration > 0)
        brow = QHBoxLayout()
        brow.addWidget(listen)
        brow.addWidget(stop)
        brow.addStretch(1)
        brow.addWidget(reset)
        shape_box = QVBoxLayout()
        shape_box.addWidget(self.wave)
        shape_box.addLayout(trow)
        shape_box.addLayout(brow)
        if not duration:
            note = QLabel("Forma d'onda non disponibile (la frase non è ancora stata creata o il file non si legge): "
                          "puoi comunque scrivere i tempi in secondi.")
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
            shape_box.addWidget(note)

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
        form.addRow("Nome sul pad", self.label)
        form.addRow("Immagine", irow)
        form.addRow("Volume", vrow)
        form.addRow("Taglio e\ndissolvenze", shape_box)
        form.addRow("Colore", color_box)
        form.addRow("Icona", ebox)
        form.addRow("Scorciatoia", srow)
        form.addRow("MIDI", mbox)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        body = QWidget()
        body.setLayout(form)
        lay = QVBoxLayout(self)
        lay.addWidget(scrollable(body, horizontal=False), 1)   # su schermi bassi si scorre
        lay.addWidget(buttons)
        # larga quanto serve al contenuto (più la barra di scorrimento), alta al massimo quanto lo schermo
        fit_to_screen(self, max(640, body.minimumSizeHint().width() + 48), body.sizeHint().height() + 70)

        self._set_color(self.color)
        self._set_midi(self.midi_binding)
        self._set_image(self.image)

    # Inizio, fine e dissolvenze -------------------------------------------------------------
    def _time_box(self, limit: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(0.0, limit)
        box.setDecimals(2)
        box.setSingleStep(0.05)
        box.setSuffix(" s")
        box.setKeyboardTracking(False)
        return box

    def _from_wave(self) -> None:
        w = self.wave
        full = w.end >= w.duration - 0.0005
        for box, value in ((self.t_start, w.start), (self.t_end, 0.0 if full else w.end),
                           (self.t_in, w.fade_in), (self.t_out, w.fade_out)):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)

    def _from_boxes(self) -> None:
        self.wave.set_values(self.t_start.value(), self.t_end.value(), self.t_in.value(), self.t_out.value())
        if self.wave.duration:
            self._from_wave()        # riporta nei campi eventuali valori fuori limite (es. fine prima dell'inizio)

    def shape_values(self) -> dict:
        end = self.t_end.value()
        if self.wave.duration and end and end <= self.t_start.value():
            end = 0.0
        return {"start": round(self.t_start.value(), 3), "end": round(end, 3),
                "fade_in": round(self.t_in.value(), 3), "fade_out": round(self.t_out.value(), 3)}

    def _reset_shape(self) -> None:
        for box in (self.t_start, self.t_end, self.t_in, self.t_out):
            box.blockSignals(True)
            box.setValue(0.0)
            box.blockSignals(False)
        self._from_boxes()

    def _listen(self) -> None:
        if self._preview is None or self._audio is None:
            return
        data = shape(self._audio, self._sr, *shape_params(self.shape_values()))
        self._preview(data, self.volume.value() / 100.0)

    # Immagine ---------------------------------------------------------------------------
    def _set_image(self, path: str) -> None:
        self.image = path
        pix = QPixmap(path) if path else QPixmap()
        if pix.isNull():
            self.image_preview.setPixmap(QPixmap())
            self.image_preview.setText("nessuna")
        else:
            self.image_preview.setPixmap(pix.scaled(70, 70, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                    Qt.TransformationMode.SmoothTransformation))

    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Immagine del pad", "",
                                              "Immagini (*.png *.jpg *.jpeg *.gif *.webp *.bmp)")
        if not path:
            return
        try:
            self._set_image(str(store_image(Path(path))))
        except Exception as exc:
            QMessageBox.warning(self, "Immagine", f"Impossibile usare l'immagine:\n{exc}")

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
        if self._preview is not None:
            self._preview(None, 0.0)          # chiudendo si ferma l'anteprima
        super().done(result)

    def values(self) -> dict:
        return {
            "label": self.label.text().strip(),
            "image": self.image,
            "volume": self.volume.value() / 100.0,
            "shortcut": self.shortcut.keySequence().toString(),
            "color": self.color,
            "emoji": self.emoji.text().strip(),
            "midi": self.midi_binding,
            **self.shape_values(),
        }
