"""Forma d'onda con maniglie per scegliere inizio, fine e dissolvenze di un suono."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme

HANDLE_PX = 7          # distanza entro cui si «prende» una maniglia
FADE_BOX = 9           # lato dei quadratini delle dissolvenze


def envelope(data: np.ndarray, buckets: int = 1200) -> np.ndarray:
    """Picco (0..1) del suono in ``buckets`` intervalli, per disegnare la forma d'onda."""
    mono = np.abs(data).max(axis=0) if data.ndim == 2 else np.abs(data)
    n = mono.shape[0]
    if n == 0:
        return np.zeros(buckets, np.float32)
    edges = np.linspace(0, n, buckets + 1).astype(np.int64)
    edges[-1] = n
    starts = np.minimum(edges[:-1], n - 1)
    peaks = np.maximum.reduceat(mono, starts)
    return np.clip(peaks, 0.0, 1.0).astype(np.float32)


class WaveformEditor(QWidget):
    """Mostra il suono; si trascinano le linee di inizio/fine e i quadratini in alto delle dissolvenze.

    Tutti i valori sono in secondi; ``end`` è sempre il punto vero di fine (non 0).
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration = 0.0
        self.start = 0.0
        self.end = 0.0
        self.fade_in = 0.0
        self.fade_out = 0.0
        self._env = np.zeros(0, np.float32)
        self._drag: str | None = None
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setToolTip("Trascina le linee per scegliere inizio e fine, e i quadratini in alto per le dissolvenze")

    # Dati ---------------------------------------------------------------------------------
    def set_audio(self, data: np.ndarray, sample_rate: int) -> None:
        self.duration = data.shape[1] / float(sample_rate) if data.size else 0.0
        self._env = envelope(data)
        self.end = self.end or self.duration
        self.update()

    def set_values(self, start: float, end: float, fade_in: float, fade_out: float) -> None:
        d = self.duration
        self.start = min(max(0.0, start), d)
        self.end = d if end <= 0 else min(max(self.start, end), d)
        span = self.end - self.start
        self.fade_in = min(max(0.0, fade_in), span)
        self.fade_out = min(max(0.0, fade_out), span)
        self.update()

    # Coordinate ------------------------------------------------------------------------------
    def _area(self) -> QRectF:
        return QRectF(6, FADE_BOX + 6, max(1, self.width() - 12), max(1, self.height() - FADE_BOX - 12))

    def _x(self, t: float) -> float:
        a = self._area()
        return a.left() + (t / self.duration if self.duration else 0.0) * a.width()

    def _t(self, x: float) -> float:
        a = self._area()
        return min(max(0.0, (x - a.left()) / a.width()), 1.0) * self.duration

    def _hit(self, pos) -> str | None:
        if not self.duration:
            return None
        x, y = pos.x(), pos.y()
        fi_x, fo_x = self._x(self.start + self.fade_in), self._x(self.end - self.fade_out)
        if y <= FADE_BOX + 8:                       # riga in alto: quadratini delle dissolvenze
            if abs(x - fi_x) <= HANDLE_PX:
                return "fade_in"
            if abs(x - fo_x) <= HANDLE_PX:
                return "fade_out"
        ds, de = abs(x - self._x(self.start)), abs(x - self._x(self.end))
        if min(ds, de) <= HANDLE_PX:
            return "start" if ds <= de else "end"
        return None

    # Mouse --------------------------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = self._hit(event.position())
            if self._drag is None and self.duration:
                # clic altrove: sposta la maniglia più vicina tra inizio e fine
                t = self._t(event.position().x())
                self._drag = "start" if abs(t - self.start) <= abs(t - self.end) else "end"
                self._move(event.position().x())

    def mouseMoveEvent(self, event):
        if self._drag:
            self._move(event.position().x())
        else:
            hit = self._hit(event.position())
            self.setCursor(Qt.CursorShape.SizeHorCursor if hit else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self._drag = None

    def _move(self, x: float) -> None:
        t = self._t(x)
        if self._drag == "start":
            self.start = min(t, self.end - 0.01)
        elif self._drag == "end":
            self.end = max(t, self.start + 0.01)
        elif self._drag == "fade_in":
            self.fade_in = max(0.0, t - self.start)
        elif self._drag == "fade_out":
            self.fade_out = max(0.0, self.end - t)
        span = self.end - self.start
        self.fade_in, self.fade_out = min(self.fade_in, span), min(self.fade_out, span)
        self.update()
        self.changed.emit()

    # Disegno --------------------------------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        a = self._area()
        p.fillRect(self.rect(), QColor(theme.PANEL_2))
        mid = a.center().y()
        accent = QColor(theme.ACCENT)
        if not self.duration or not len(self._env):
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Forma d'onda non disponibile")
            return
        # forma d'onda
        n = len(self._env)
        w = int(a.width())
        idx = np.minimum((np.arange(w) * n / max(1, w)).astype(int), n - 1)
        peaks = self._env[idx]
        wave_col = QColor(theme.TEXT)
        wave_col.setAlpha(170)
        p.setPen(QPen(wave_col, 1))
        for i, v in enumerate(peaks):
            h = max(0.5, float(v) * a.height() / 2)
            x = a.left() + i + 0.5
            p.drawLine(QPointF(x, mid - h), QPointF(x, mid + h))
        # parti escluse
        shade = QColor(theme.PANEL_2)
        shade.setAlpha(200)
        xs, xe = self._x(self.start), self._x(self.end)
        p.fillRect(QRectF(a.left(), a.top(), xs - a.left(), a.height()), shade)
        p.fillRect(QRectF(xe, a.top(), a.right() - xe, a.height()), shade)
        # curva del volume (dissolvenze)
        path = QPainterPath()
        top, bottom = a.top() + 1, a.bottom() - 1
        xfi, xfo = self._x(self.start + self.fade_in), self._x(self.end - self.fade_out)
        path.moveTo(xs, bottom)
        steps = 24
        for k in range(steps + 1):
            f = k / steps
            g = np.sin(f * np.pi / 2) ** 2
            path.lineTo(xs + (xfi - xs) * f, bottom - (bottom - top) * g)
        path.lineTo(xfo, top)
        for k in range(steps + 1):
            f = k / steps
            g = np.cos(f * np.pi / 2) ** 2
            path.lineTo(xfo + (xe - xfo) * f, bottom - (bottom - top) * g)
        fill = QColor(accent)
        fill.setAlpha(40)
        p.fillPath(path, fill)
        p.setPen(QPen(accent, 1.5))
        p.drawPath(path)
        # maniglie di inizio e fine
        p.setPen(QPen(accent, 2))
        for x in (xs, xe):
            p.drawLine(QPointF(x, a.top() - 2), QPointF(x, a.bottom() + 2))
        # quadratini delle dissolvenze
        p.setBrush(accent)
        for x in (xfi, xfo):
            p.drawRect(QRectF(x - FADE_BOX / 2, 2, FADE_BOX, FADE_BOX))
        p.end()
