"""Finestre per modificare i parametri degli inserti."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QLabel, QLineEdit, QMessageBox,
    QScrollArea, QSlider, QVBoxLayout, QWidget,
)

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


class BuiltinParamsDialog(QDialog):
    """Slider per gli effetti integrati; le modifiche sono immediate."""

    def __init__(self, slot: InsertSlot, parent=None):
        super().__init__(parent)
        self.setWindowTitle(slot.display_name)
        self.setMinimumWidth(380)
        grid = QGridLayout()
        for row, spec in enumerate(slot.param_specs()):
            value = float(getattr(slot.plugin, spec.attr))
            label = QLabel(spec.label)
            readout = QLabel(_fmt(value, spec.unit))
            readout.setObjectName("dbLabel")
            readout.setMinimumWidth(70)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, STEPS)
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
        grid.setColumnStretch(1, 1)
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
            self._rows.append((name.lower(), [label, slider, readout]))
        grid.setColumnStretch(1, 1)
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
