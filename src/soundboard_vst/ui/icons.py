"""Icone vettoriali disegnate con QPainter (niente emoji: sono uguali su ogni sistema e a ogni zoom)."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from . import theme

NAMES = ("play", "pause", "stop", "prev", "next", "repeat", "repeat_one", "shuffle", "youtube", "now")


def _tri(p: QPainter, pts) -> None:
    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))


def _arrow_head(p: QPainter, tip: tuple[float, float], direction: str, s: float) -> None:
    x, y = tip
    if direction == "right":
        _tri(p, [(x, y), (x - s, y - s * 0.8), (x - s, y + s * 0.8)])
    else:
        _tri(p, [(x, y), (x + s, y - s * 0.8), (x + s, y + s * 0.8)])


def paint(p: QPainter, name: str, r: QRectF, color: QColor) -> None:
    """Disegna l'icona ``name`` nel rettangolo ``r`` (coordinate su una griglia 24×24)."""
    p.save()
    p.translate(r.left(), r.top())
    p.scale(r.width() / 24.0, r.height() / 24.0)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    if name == "play":
        _tri(p, [(7, 4.5), (19.5, 12), (7, 19.5)])
    elif name == "pause":
        p.drawRoundedRect(QRectF(6, 5, 4.2, 14), 1, 1)
        p.drawRoundedRect(QRectF(13.8, 5, 4.2, 14), 1, 1)
    elif name == "stop":
        p.drawRoundedRect(QRectF(6, 6, 12, 12), 1.5, 1.5)
    elif name == "prev":
        p.drawRoundedRect(QRectF(5, 5.5, 2.6, 13), 1, 1)
        _tri(p, [(19, 5.5), (8.5, 12), (19, 18.5)])
    elif name == "next":
        p.drawRoundedRect(QRectF(16.4, 5.5, 2.6, 13), 1, 1)
        _tri(p, [(5, 5.5), (15.5, 12), (5, 18.5)])
    elif name in ("repeat", "repeat_one"):
        pen = QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        top = QPainterPath(QPointF(4.5, 12))
        top.lineTo(4.5, 10)
        top.quadTo(4.5, 7, 7.5, 7)
        top.lineTo(17, 7)
        p.drawPath(top)
        bottom = QPainterPath(QPointF(19.5, 12))
        bottom.lineTo(19.5, 14)
        bottom.quadTo(19.5, 17, 16.5, 17)
        bottom.lineTo(7, 17)
        p.drawPath(bottom)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        _arrow_head(p, (20, 7), "right", 3.2)
        _arrow_head(p, (4, 17), "left", 3.2)
        if name == "repeat_one":
            f = QFont()
            f.setPixelSize(8)
            f.setBold(True)
            p.setFont(f)
            p.setPen(color)
            p.drawText(QRectF(8, 8, 8, 8), Qt.AlignmentFlag.AlignCenter, "1")
    elif name == "shuffle":
        pen = QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        a = QPainterPath(QPointF(3.5, 7))
        a.lineTo(7, 7)
        a.cubicTo(12, 7, 12, 17, 17, 17)
        p.drawPath(a)
        b = QPainterPath(QPointF(3.5, 17))
        b.lineTo(7, 17)
        b.cubicTo(12, 17, 12, 7, 17, 7)
        p.drawPath(b)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        _arrow_head(p, (21, 7), "right", 3.4)
        _arrow_head(p, (21, 17), "right", 3.4)
    elif name == "youtube":
        p.setBrush(QColor("#e5534b"))
        p.drawRoundedRect(QRectF(2, 5, 20, 14), 4, 4)
        p.setBrush(QColor("#ffffff"))
        _tri(p, [(10, 8.5), (15.5, 12), (10, 15.5)])
    elif name == "blank":
        pass
    elif name == "now":
        p.setBrush(QColor(theme.ACCENT))
        for i, h in enumerate((8, 14, 10)):           # tre barrette «in riproduzione»
            p.drawRoundedRect(QRectF(5 + i * 5.3, 19 - h, 3.4, h), 1, 1)
    p.restore()


@lru_cache(maxsize=128)
def icon(name: str, color: str = theme.TEXT, size: int = 24) -> QIcon:
    """QIcon nitida anche con il ridimensionamento di Windows (disegnata a 1×, 2× e 3×)."""
    ic = QIcon()
    for scale in (1, 2, 3):
        pix = QPixmap(size * scale, size * scale)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        paint(p, name, QRectF(0, 0, size * scale, size * scale), QColor(color))
        p.end()
        pix.setDevicePixelRatio(scale)
        ic.addPixmap(pix)
    return ic


# Le stesse icone in SVG, per la pagina web (stessa griglia 24×24) ------------------------------
SVG = {
    "play": '<path d="M7 4.5 19.5 12 7 19.5z"/>',
    "pause": '<rect x="6" y="5" width="4.2" height="14" rx="1"/><rect x="13.8" y="5" width="4.2" height="14" rx="1"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    "prev": '<rect x="5" y="5.5" width="2.6" height="13" rx="1"/><path d="M19 5.5 8.5 12 19 18.5z"/>',
    "next": '<rect x="16.4" y="5.5" width="2.6" height="13" rx="1"/><path d="M5 5.5 15.5 12 5 18.5z"/>',
    "youtube": '<rect x="2" y="5" width="20" height="14" rx="4" fill="#e5534b"/><path d="M10 8.5 15.5 12 10 15.5z" fill="#fff"/>',
    "now": '<g fill="#f2a93b"><rect x="5" y="11" width="3.4" height="8" rx="1"/><rect x="10.3" y="5" width="3.4" height="14" rx="1"/><rect x="15.6" y="9" width="3.4" height="10" rx="1"/></g>',
}


def svg(name: str, size: int = 22) -> str:
    return (f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="currentColor" '
            f'aria-hidden="true">{SVG[name]}</svg>')
