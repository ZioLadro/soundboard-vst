"""Meter di livello stereo e fader in dB."""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QSlider, QWidget

from ..audio.mixer import MAX_DB, MIN_DB
from . import theme

METER_MIN_DB = -60.0
METER_MAX_DB = 6.0


def _norm(db: float) -> float:
    return max(0.0, min(1.0, (db - METER_MIN_DB) / (METER_MAX_DB - METER_MIN_DB)))


class LevelMeter(QWidget):
    """Barre verticali L/R con picco trattenuto."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(22)
        self.setMinimumHeight(120)
        self._level = [METER_MIN_DB, METER_MIN_DB]
        self._hold = [METER_MIN_DB, METER_MIN_DB]
        self._hold_ticks = [0, 0]

    def set_peaks(self, left: float, right: float) -> None:
        for i, p in enumerate((left, right)):
            db = 20 * math.log10(p) if p > 1e-6 else METER_MIN_DB
            # salita istantanea, discesa ~20 dB/s a 30 fps
            self._level[i] = db if db > self._level[i] else max(db, self._level[i] - 0.7)
            if db >= self._hold[i]:
                self._hold[i] = db
                self._hold_ticks[i] = 45
            elif self._hold_ticks[i] > 0:
                self._hold_ticks[i] -= 1
            else:
                self._hold[i] = max(METER_MIN_DB, self._hold[i] - 0.5)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        bar_w = (self.width() - 3) / 2
        grad = QLinearGradient(0, h, 0, 0)
        grad.setColorAt(0.0, QColor(theme.ACCENT_2))
        grad.setColorAt(_norm(-12), QColor(theme.ACCENT_2))
        grad.setColorAt(_norm(-6), QColor("#d9c94a"))
        grad.setColorAt(_norm(0), QColor(theme.DANGER))
        grad.setColorAt(1.0, QColor(theme.DANGER))
        for i in range(2):
            x = i * (bar_w + 3)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.BG))
            p.drawRoundedRect(QRectF(x, 0, bar_w, h), 2, 2)
            lh = _norm(self._level[i]) * h
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(x, h - lh, bar_w, lh), 2, 2)
            if self._hold[i] > METER_MIN_DB + 1:
                y = h - _norm(self._hold[i]) * h
                p.setBrush(QColor(theme.TEXT if self._hold[i] < 0 else theme.DANGER))
                p.drawRect(QRectF(x, y, bar_w, 2))
        # tacca 0 dB
        p.setBrush(QColor(theme.MUTED))
        p.drawRect(QRectF(0, h - _norm(0) * h, self.width(), 1))


class DbFader(QSlider):
    """Fader verticale in decimi di dB; doppio clic = 0 dB."""

    db_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Vertical, parent)
        self.setRange(int(MIN_DB * 10), int(MAX_DB * 10))
        self.setPageStep(30)
        self.setSingleStep(5)
        self.setMinimumHeight(120)
        self.valueChanged.connect(lambda v: self.db_changed.emit(v / 10.0))

    def db(self) -> float:
        return self.value() / 10.0

    def set_db(self, db: float) -> None:
        self.setValue(int(round(db * 10)))

    def mouseDoubleClickEvent(self, event):
        self.set_db(0.0)


def format_db(db: float) -> str:
    return "-∞ dB" if db <= MIN_DB else f"{db:+.1f} dB"
