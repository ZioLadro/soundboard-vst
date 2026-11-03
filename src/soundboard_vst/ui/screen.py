"""Adattamento allo schermo: dimensioni iniziali, finestre che stanno nello schermo, testi accorciati.

Le misure sono in pixel «logici»: con il ridimensionamento di Windows al 125% uno schermo 1920×1080
offre 1536×864, al 150% 1280×720; un 2560×1440 (2K) al 125% offre 2048×1152.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QScrollArea, QSizePolicy, QStackedWidget, QWidget,
)

MIN_WINDOW = QSize(1000, 640)


def available(widget: QWidget | None = None) -> QSize:
    screen = (widget.screen() if widget is not None else None) or QGuiApplication.primaryScreen()
    return screen.availableGeometry().size() if screen is not None else QSize(1920, 1040)


def initial_window_size(widget: QWidget | None = None) -> QSize:
    """Finestra principale alla prima apertura: grande ma non a tutto schermo, con limiti sensati."""
    avail = available(widget)
    w = int(min(max(avail.width() * 0.82, MIN_WINDOW.width()), 1820, avail.width()))
    h = int(min(max(avail.height() * 0.86, MIN_WINDOW.height()), 1150, avail.height()))
    return QSize(w, h)


def fit_to_screen(widget: QWidget, width: int, height: int, margin: float = 0.92) -> None:
    """Ridimensiona una finestra senza superare lo schermo (e la centra sul genitore, se c'è)."""
    avail = available(widget.parentWidget() or widget)
    widget.resize(min(width, int(avail.width() * margin)), min(height, int(avail.height() * margin)))


def keep_on_screen(widget: QWidget) -> None:
    """Dopo aver ripristinato la posizione salvata: se la finestra non sta più nello schermo, la riduce."""
    screen = widget.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        return
    geo = screen.availableGeometry()
    w, h = min(widget.width(), geo.width()), min(widget.height(), geo.height())
    if (w, h) != (widget.width(), widget.height()):
        widget.resize(w, h)
    frame = widget.frameGeometry()
    if not geo.intersects(frame) or frame.top() < geo.top():
        widget.move(geo.left() + (geo.width() - w) // 2, geo.top() + (geo.height() - h) // 2)


class ElidedLabel(QLabel):
    """Etichetta che si accorcia con «…» invece di allargare la finestra; il testo intero è nel tooltip."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)

    def setText(self, text: str) -> None:            # noqa: N802 (API di Qt)
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self) -> QSize:              # noqa: N802
        return QSize(40, super().minimumSizeHint().height())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        r = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideMiddle, r.width())
        p.drawText(r, int(self.alignment() | Qt.AlignmentFlag.AlignVCenter), text)


def scrollable(widget: QWidget, horizontal: bool = True, vertical: bool = True) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if horizontal
                                      else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if vertical
                                    else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area


class SideTabs(QWidget):
    """Elenco a sinistra + pagine: come una QTabWidget, ma con tante schede non serve scorrere."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.list = QListWidget()
        self.list.setObjectName("sideTabs")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stack = QStackedWidget()
        self.list.currentRowChanged.connect(self.stack.setCurrentIndex)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.list)
        lay.addWidget(self.stack, 1)

    def addTab(self, widget: QWidget, title: str) -> int:   # noqa: N802
        self.list.addItem(title)
        self.stack.addWidget(widget)
        self._fit_list()
        if self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        return self.list.count() - 1

    def _fit_list(self) -> None:
        # larghezza dal testo più lungo, con il carattere effettivo del foglio di stile (anche scalato)
        self.list.ensurePolished()
        fm = self.list.fontMetrics()
        widest = max(fm.horizontalAdvance(self.list.item(i).text()) for i in range(self.list.count()))
        self.list.setFixedWidth(widest + 56)

    def showEvent(self, event):
        self._fit_list()
        super().showEvent(event)

    def count(self) -> int:
        return self.list.count()

    def tabText(self, index: int) -> str:                    # noqa: N802
        return self.list.item(index).text()

    def setCurrentIndex(self, index: int) -> None:           # noqa: N802
        if 0 <= index < self.count():
            self.list.setCurrentRow(index)

    def currentIndex(self) -> int:                           # noqa: N802
        return self.list.currentRow()

    def widget(self, index: int) -> QWidget:
        return self.stack.widget(index)
