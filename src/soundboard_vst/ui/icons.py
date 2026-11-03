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


# Icona del programma -------------------------------------------------------------------------
APP_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def paint_app_icon(p: QPainter, size: int) -> None:
    """Icona originale: fumetto della chat vocale con una doppia croma (♫) e onde sonore.

    Disegnata su una griglia 256×256 e scalata; sotto i 32 px le onde spariscono per restare leggibile.
    """
    from PySide6.QtGui import QLinearGradient

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 256.0, size / 256.0)
    small = size < 32

    # Fondo: quadrato arrotondato scuro con un leggero gradiente
    bg = QLinearGradient(0, 0, 256, 256)
    bg.setColorAt(0.0, QColor("#2d3240"))
    bg.setColorAt(1.0, QColor("#14161b"))
    p.setPen(QPen(QColor("#3a4050"), 4) if not small else Qt.PenStyle.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 56, 56)

    # Fumetto (voce) con la coda in basso a sinistra
    bubble = QPainterPath()
    bubble.addRoundedRect(QRectF(30, 44, 168, 132), 48, 48)
    tail = QPainterPath()
    tail.moveTo(58, 150)
    tail.lineTo(40, 214)
    tail.lineTo(112, 168)
    tail.closeSubpath()
    bubble = bubble.united(tail)
    grad = QLinearGradient(30, 44, 198, 214)
    grad.setColorAt(0.0, QColor("#57dcc6"))
    grad.setColorAt(1.0, QColor("#239c8a"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawPath(bubble)

    # Doppia croma (♫) dentro il fumetto
    note = QColor(theme.BG)
    p.setBrush(note)
    p.save()
    for cx, cy in ((84, 142), (146, 130)):
        p.save()
        p.translate(cx, cy)
        p.rotate(-22)
        p.drawEllipse(QRectF(-21, -14, 42, 28))
        p.restore()
    p.restore()
    p.drawRect(QRectF(95, 76, 11, 64))              # gambi
    p.drawRect(QRectF(157, 64, 11, 64))
    beam = QPolygonF([QPointF(95, 76), QPointF(168, 58), QPointF(168, 80), QPointF(95, 98)])
    p.drawPolygon(beam)

    # Onde sonore a destra (arancio, colore dei suoni in riproduzione)
    if not small:
        pen = QPen(QColor(theme.ACCENT), 15, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(176, 82, 40, 76), -60 * 16, 120 * 16)
        p.drawArc(QRectF(170, 58, 68, 124), -55 * 16, 110 * 16)
    else:
        p.setBrush(QColor(theme.ACCENT))
        p.drawEllipse(QRectF(196, 34, 40, 40))         # puntino «attivo» al posto delle onde
    p.restore()


def app_icon_image(size: int):
    from PySide6.QtGui import QImage

    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    paint_app_icon(p, size)
    p.end()
    return img


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    """Icona della finestra, della barra delle applicazioni e del programma ridotto a icona."""
    ic = QIcon()
    for s in APP_ICON_SIZES:
        ic.addPixmap(QPixmap.fromImage(app_icon_image(s)))
    return ic


def ico_bytes(sizes=(16, 20, 24, 32, 40, 48, 64, 128, 256)) -> bytes:
    """File .ico di Windows con più dimensioni (immagini PNG), per l'eseguibile."""
    import struct

    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    pngs = []
    for s in sizes:
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        app_icon_image(s).save(buf, "PNG")
        buf.close()
        pngs.append((s, bytes(data)))
    out = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    for s, png in pngs:
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    return out + b"".join(png for _, png in pngs)
