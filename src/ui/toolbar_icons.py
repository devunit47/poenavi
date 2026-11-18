"""Small theme-aware vector icons used by compact toolbar buttons."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


def _canvas():
    pixmap = QPixmap(48, 48)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    return pixmap, painter


def _finish(pixmap, painter) -> QIcon:
    painter.end()
    return QIcon(pixmap)


def line_icon_canvas(color):
    pixmap, painter = _canvas()
    painter.setPen(QPen(QColor(color), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    return pixmap, painter


def finish_line_icon(pixmap, painter) -> QIcon:
    icon = _finish(pixmap, painter)
    disabled = QPixmap(pixmap.size())
    disabled.setDevicePixelRatio(pixmap.devicePixelRatio())
    disabled.fill(Qt.transparent)
    with QPainter(disabled) as dim:
        dim.setOpacity(0.45)
        dim.drawPixmap(0, 0, pixmap)
    icon.addPixmap(disabled, QIcon.Disabled)
    return icon


def list_add_icon(color) -> QIcon:
    """Draw a list with a plus for managing the entries it contains."""
    pixmap, painter = line_icon_canvas(color)
    painter.drawLine(QPointF(4, 6), QPointF(19, 6))
    painter.drawLine(QPointF(4, 12), QPointF(11, 12))
    painter.drawLine(QPointF(4, 18), QPointF(11, 18))
    painter.drawLine(QPointF(14, 15), QPointF(21, 15))
    painter.drawLine(QPointF(17.5, 11.5), QPointF(17.5, 18.5))
    return finish_line_icon(pixmap, painter)


def trash_icon(color) -> QIcon:
    pixmap, painter = line_icon_canvas(color)
    painter.drawLine(QPointF(4, 6.5), QPointF(20, 6.5))
    handle = QPainterPath(QPointF(9, 6.5))
    handle.lineTo(10, 3.5)
    handle.lineTo(14, 3.5)
    handle.lineTo(15, 6.5)
    painter.drawPath(handle)
    bin_body = QPainterPath(QPointF(6, 6.5))
    bin_body.lineTo(7, 20.5)
    bin_body.lineTo(17, 20.5)
    bin_body.lineTo(18, 6.5)
    painter.drawPath(bin_body)
    painter.drawLine(QPointF(12, 10.5), QPointF(12, 16.5))
    return finish_line_icon(pixmap, painter)


def reload_icon(color) -> QIcon:
    pixmap, painter = line_icon_canvas(color)
    painter.drawArc(QRectF(4.5, 4.5, 15, 15), 30 * 16, 300 * 16)
    painter.drawPolyline(QPolygonF([
        QPointF(18.5, 4), QPointF(18.5, 8.25), QPointF(14.25, 8.25),
    ]))
    return finish_line_icon(pixmap, painter)


def update_check_icon(color) -> QIcon:
    """A magnifier with a check mark for checking the app version."""
    pixmap, painter = line_icon_canvas(color)
    painter.drawEllipse(QPointF(10, 10), 6.5, 6.5)
    painter.drawLine(QPointF(14.6, 14.6), QPointF(20, 20))
    painter.drawPolyline(QPolygonF([
        QPointF(7.2, 10), QPointF(9.1, 11.9), QPointF(12.8, 8.2),
    ]))
    return finish_line_icon(pixmap, painter)


def download_icon(color) -> QIcon:
    pixmap, painter = line_icon_canvas(color)
    painter.drawLine(QPointF(12, 3.5), QPointF(12, 14.5))
    painter.drawPolyline(QPolygonF([
        QPointF(7.5, 10), QPointF(12, 14.5), QPointF(16.5, 10),
    ]))
    painter.drawPolyline(QPolygonF([
        QPointF(4.5, 15), QPointF(4.5, 19.5), QPointF(19.5, 19.5), QPointF(19.5, 15),
    ]))
    return finish_line_icon(pixmap, painter)


def checking_icon(color) -> QIcon:
    pixmap, painter = line_icon_canvas(color)
    painter.drawEllipse(QPointF(12, 12), 8, 8)
    painter.drawPolyline(QPolygonF([
        QPointF(12, 7), QPointF(12, 12), QPointF(15.5, 14),
    ]))
    return finish_line_icon(pixmap, painter)


def hideout_notification_icon(color, active) -> QIcon:
    """A house with a bell that is struck through when muted."""
    pixmap, painter = line_icon_canvas(color)
    painter.drawPolyline(QPolygonF([
        QPointF(2.5, 10), QPointF(10.5, 3), QPointF(17, 8.7),
    ]))
    painter.drawPolyline(QPolygonF([
        QPointF(4.5, 8.4), QPointF(4.5, 20.5), QPointF(10, 20.5),
    ]))
    bell = QPainterPath(QPointF(11.5, 17.5))
    bell.quadTo(13, 16.2, 13, 13.5)
    bell.cubicTo(13, 9.4, 19, 9.4, 19, 13.5)
    bell.quadTo(19, 16.2, 20.5, 17.5)
    bell.closeSubpath()
    painter.drawPath(bell)
    painter.drawLine(QPointF(15.3, 20), QPointF(16.7, 20))
    if not active:
        painter.drawLine(QPointF(11.5, 10), QPointF(21, 19.5))
    return finish_line_icon(pixmap, painter)


def memo_icon(accent_color, panel_color, dark_color) -> QIcon:
    pixmap, painter = _canvas()
    accent, panel, dark = map(QColor, (accent_color, panel_color, dark_color))
    page = QPainterPath(QPointF(5.0, 2.8))
    page.lineTo(15.8, 2.8)
    page.lineTo(20.0, 7.0)
    page.lineTo(20.0, 21.0)
    page.lineTo(5.0, 21.0)
    page.closeSubpath()
    painter.setPen(QPen(accent, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(panel)
    painter.drawPath(page)
    painter.drawLine(QPointF(15.8, 3.1), QPointF(15.8, 7.0))
    painter.drawLine(QPointF(15.8, 7.0), QPointF(19.7, 7.0))
    painter.setPen(QPen(dark, 1.5, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(QPointF(8.0, 10.0), QPointF(16.8, 10.0))
    painter.drawLine(QPointF(8.0, 14.0), QPointF(16.8, 14.0))
    painter.drawLine(QPointF(8.0, 18.0), QPointF(14.0, 18.0))
    return _finish(pixmap, painter)


def image_manager_icon(accent_color, panel_color, dark_color) -> QIcon:
    pixmap, painter = _canvas()
    accent, panel, dark = map(QColor, (accent_color, panel_color, dark_color))
    painter.setPen(QPen(accent.darker(150), 1.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(dark)
    painter.drawRoundedRect(2.8, 3.2, 15.5, 14.5, 2.0, 2.0)
    painter.setPen(QPen(accent, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(panel)
    painter.drawRoundedRect(5.5, 6.0, 15.5, 14.5, 2.0, 2.0)
    painter.setBrush(accent)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPointF(16.4, 10.4), 1.7, 1.7)
    mountain = QPainterPath(QPointF(7.4, 18.4))
    mountain.lineTo(11.5, 13.2)
    mountain.lineTo(14.2, 16.1)
    mountain.lineTo(16.1, 14.3)
    mountain.lineTo(19.2, 18.4)
    mountain.closeSubpath()
    painter.setBrush(accent.darker(115))
    painter.drawPath(mountain)
    return _finish(pixmap, painter)


def _draw_gear(painter, accent, panel, dark):
    center, radius, tooth = QPointF(12.0, 12.0), 5.5, 2.4
    cx, cy = center.x(), center.y()
    painter.setPen(QPen(accent, 2.6, Qt.SolidLine, Qt.RoundCap))
    diagonal = tooth * 0.72
    for start, end in (
        ((cx, cy - radius - tooth), (cx, cy - radius)),
        ((cx, cy + radius), (cx, cy + radius + tooth)),
        ((cx - radius - tooth, cy), (cx - radius, cy)),
        ((cx + radius, cy), (cx + radius + tooth, cy)),
        ((cx - radius - diagonal, cy - radius - diagonal), (cx - radius * .72, cy - radius * .72)),
        ((cx + radius * .72, cy + radius * .72), (cx + radius + diagonal, cy + radius + diagonal)),
        ((cx - radius - diagonal, cy + radius + diagonal), (cx - radius * .72, cy + radius * .72)),
        ((cx + radius * .72, cy - radius * .72), (cx + radius + diagonal, cy - radius - diagonal)),
    ):
        painter.drawLine(QPointF(*start), QPointF(*end))
    painter.setPen(QPen(accent, 1.2))
    painter.setBrush(panel)
    painter.drawEllipse(center, radius, radius)
    painter.setBrush(dark)
    painter.drawEllipse(center, radius * .36, radius * .36)


def settings_icon(accent_color, panel_color, dark_color) -> QIcon:
    pixmap, painter = _canvas()
    _draw_gear(painter, QColor(accent_color), QColor(panel_color), QColor(dark_color))
    return _finish(pixmap, painter)


def vendor_presets_icon(accent_color, panel_color, dark_color) -> QIcon:
    pixmap, painter = _canvas()
    accent, panel, dark = map(QColor, (accent_color, panel_color, dark_color))
    painter.setPen(QPen(accent, 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(panel)
    painter.drawRoundedRect(3.0, 8.0, 16.0, 12.5, 1.8, 1.8)
    painter.setBrush(accent)
    painter.drawRect(2.5, 5.0, 17.0, 4.0)
    painter.setPen(QPen(dark, 1.2))
    for x in (6.8, 11.0, 15.2):
        painter.drawLine(QPointF(x, 5.3), QPointF(x, 8.7))
    painter.setPen(QPen(accent, 1.2))
    painter.setBrush(dark)
    painter.drawRoundedRect(5.0, 11.2, 5.0, 9.3, 1.0, 1.0)
    painter.setPen(QPen(dark, 1.5, Qt.SolidLine, Qt.RoundCap))
    painter.setBrush(accent)
    painter.drawRoundedRect(12.0, 11.0, 10.0, 10.0, 1.7, 1.7)
    painter.setPen(QPen(dark, 1.3, Qt.SolidLine, Qt.RoundCap))
    for y in (14.0, 17.0):
        painter.drawLine(QPointF(14.4, y), QPointF(19.6, y))
    return _finish(pixmap, painter)
