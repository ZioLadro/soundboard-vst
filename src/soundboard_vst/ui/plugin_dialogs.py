"""Finestre per modificare i parametri degli inserti."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from .. import midi_map
from ..audio.plugins import InsertSlot

STEPS = 1000


def _fmt(value: float, unit: str) -> str:
    if abs(value) >= 100:
        txt = f"{value:.0f}"
    elif abs(value) >= 10:
        txt = f"{value:.1f}"
    else:
        txt = f"{value:.2f}"
    return f"{txt} {unit}".strip()


# Collegamento con la mappa MIDI: lo imposta la finestra principale (midi_label, midi_learn,
# midi_learn_cancel, midi_clear). Senza, i pulsanti MIDI non compaiono.
MIDI = None


class MidiParamButton(QWidget):
    """«MIDI» accanto a un parametro: impara il controllo da usare, ✕ lo toglie."""

    def __init__(self, target_id: str, parent=None):
        super().__init__(parent)
        self.target_id = target_id
        self.learn = QPushButton()
        self.learn.setObjectName("small")
        self.learn.setToolTip("Premi e muovi un potenziometro/fader (CC) o suona una nota del controller")
        self.learn.clicked.connect(self._toggle)
        self.clear = QPushButton("✕")
        self.clear.setObjectName("small")
        self.clear.setFixedWidth(26)
        self.clear.setToolTip("Togli il controllo MIDI")
        self.clear.clicked.connect(self._clear)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.learn)
        lay.addWidget(self.clear)
        self._learning = False
        self._show(MIDI.midi_label(target_id) if MIDI else "")

    def _show(self, label: str) -> None:
        self.learn.setText(label or "MIDI")
        self.learn.setStyleSheet("" if not label else "color: #3ec7b2; font-weight: 600;")
        self.clear.setVisible(bool(label))

    def _toggle(self) -> None:
        if MIDI is None:
            return
        if self._learning:
            MIDI.midi_learn_cancel()
            self._learning = False
            self._show(MIDI.midi_label(self.target_id))
            return
        self._learning = True
        self.learn.setText("Muovi…")
        MIDI.midi_learn(self.target_id, self._done)

    def _done(self, label: str) -> None:
        self._learning = False
        try:
            self._show(label or MIDI.midi_label(self.target_id))
        except RuntimeError:
            pass                                   # finestra già chiusa

    def _clear(self) -> None:
        MIDI.midi_clear(self.target_id)
        self._show("")


def _follow(dialog: QDialog, rows) -> None:
    """Gli slider seguono i valori cambiati da fuori (controller MIDI, pagina web)."""
    def tick():
        for slider, get in rows:
            v = get()
            if v is None or slider.isSliderDown():
                continue
            pos = int(round(max(0.0, min(1.0, v)) * STEPS))
            if pos != slider.value():
                slider.blockSignals(True)
                slider.setValue(pos)
                slider.blockSignals(False)
    timer = QTimer(dialog, interval=150)
    timer.timeout.connect(tick)
    timer.start()


class BuiltinParamsDialog(QDialog):
    """Slider per gli effetti integrati; le modifiche sono immediate."""

    def __init__(self, slot: InsertSlot, parent=None):
        super().__init__(parent)
        self.setWindowTitle(slot.display_name)
        self.setMinimumWidth(560)
        grid = QGridLayout()
        follow = []
        for row, spec in enumerate(slot.param_specs()):
            value = float(getattr(slot.plugin, spec.attr))
            label = QLabel(spec.label)
            readout = QLabel(_fmt(value, spec.unit))
            readout.setObjectName("dbLabel")
            readout.setMinimumWidth(70)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, STEPS)
            slider.setMinimumWidth(220)
            span = spec.maximum - spec.minimum
            slider.setValue(int(round((value - spec.minimum) / span * STEPS)))

            def on_change(v, spec=spec, readout=readout, span=span):
                val = spec.minimum + span * v / STEPS
                setattr(slot.plugin, spec.attr, val)
                readout.setText(_fmt(val, spec.unit))

            slider.valueChanged.connect(on_change)
            grid.addWidget(label, row, 0)
            grid.addWidget(slider, row, 1)
            grid.addWidget(readout, row, 2)
            if MIDI is not None:
                grid.addWidget(MidiParamButton(midi_map.param_target(slot.uid, spec.attr)), row, 3)

            def get(spec=spec, readout=readout):
                v = slot.get_normalized(spec.attr)
                if v is not None:
                    readout.setText(_fmt(spec.minimum + v * (spec.maximum - spec.minimum), spec.unit))
                return v
            follow.append((slider, get))
        grid.setColumnStretch(1, 1)
        _follow(self, follow)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.addLayout(grid)
        lay.addWidget(buttons)


class VstParamsDialog(QDialog):
    """Editor generico (non bloccante) per i parametri di un VST3."""

    def __init__(self, slot: InsertSlot, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Parametri — {slot.display_name}")
        self.resize(480, 560)
        self._rows: list[tuple[str, list[QWidget]]] = []
        follow = []

        search = QLineEdit()
        search.setPlaceholderText("Filtra parametri…")
        search.textChanged.connect(self._filter)

        container = QWidget()
        grid = QGridLayout(container)
        try:
            params = list(slot.plugin.parameters.items())
        except Exception:
            params = []
        for row, (name, param) in enumerate(params):
            label = QLabel(getattr(param, "name", name))
            label.setToolTip(name)
            readout = QLabel(self._text(param))
            readout.setObjectName("dbLabel")
            readout.setMinimumWidth(90)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, STEPS)
            try:
                slider.setValue(int(round(float(param.raw_value) * STEPS)))
            except Exception:
                slider.setEnabled(False)

            def on_change(v, param=param, readout=readout):
                try:
                    param.raw_value = v / STEPS
                    readout.setText(self._text(param))
                except Exception:
                    pass

            slider.valueChanged.connect(on_change)
            grid.addWidget(label, row, 0)
            grid.addWidget(slider, row, 1)
            grid.addWidget(readout, row, 2)
            widgets = [label, slider, readout]
            if MIDI is not None:
                learn = MidiParamButton(midi_map.param_target(slot.uid, name))
                grid.addWidget(learn, row, 3)
                widgets.append(learn)
            self._rows.append((name.lower(), widgets))

            def get(param=param, readout=readout):
                try:
                    v = float(param.raw_value)
                except Exception:
                    return None
                readout.setText(self._text(param))
                return v
            follow.append((slider, get))
        grid.setColumnStretch(1, 1)
        _follow(self, follow)
        if not params:
            grid.addWidget(QLabel("Questo plugin non espone parametri."), 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.addWidget(search)
        lay.addWidget(scroll, 1)
        lay.addWidget(buttons)

    @staticmethod
    def _text(param) -> str:
        try:
            return str(param.string_value)
        except Exception:
            try:
                return f"{float(param.raw_value):.2f}"
            except Exception:
                return ""

    def _filter(self, text: str) -> None:
        t = text.lower().strip()
        for name, widgets in self._rows:
            for w in widgets:
                w.setVisible(not t or t in name)


def open_native_editor(slot: InsertSlot, parent=None) -> None:
    """Apre la finestra grafica del plugin.

    pedalboard richiede il thread principale e lo blocca finché la finestra
    resta aperta: l'audio continua, ma l'interfaccia si ferma fino alla chiusura.
    """
    try:
        slot.plugin.show_editor()
    except Exception as exc:
        QMessageBox.warning(parent, "Editor plugin",
                            f"Impossibile aprire l'editor di {slot.display_name}:\n{exc}\n\n"
                            "Puoi usare «Parametri» per modificarlo.")


def edit_slot(slot: InsertSlot, parent=None) -> None:
    if slot.kind == "builtin":
        BuiltinParamsDialog(slot, parent).exec()
    else:
        VstParamsDialog(slot, parent).exec()
