# -*- coding: utf-8 -*-
"""Иконки приложения.

Кнопки инструментов — ВЕКТОРНЫЕ SVG пользователя (копия в icons_svg/,
готовится scripts/make_icons.py), рисуются в рантайме через QtSvg:
чётко в любом размере, перекраска под тёмную тему подстановкой цветов.
Жёлтый значок приложения и цветные кружки рисуются кодом.
"""
import math
import os
import re

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QIcon, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtSvg import QSvgRenderer

# kind -> имя файла SVG (без расширения)
ICON_FILES = {
    'scope_notes': '1. Все заметки',
    'compose': '2. Новая заметка',
    'scope_trash': '3. Недавно удаленные',
    'view_card': 'Вид Крупный перечень',
    'view_list': 'Вид Список',
    'bold': 'Полужирный',
    'italic': 'Курсив',
    'under': 'Подчеркнутый',
    'strike': 'Зачеркнутый',
    'bullet': 'Маркированный список',
    'numbered': 'Нумерованный список',
    'check': 'Чек лист',
    'align_l': 'Выравнивание по левому краю',
    'align_c': 'Выравнивание по центру',
    'align_r': 'Выравнивание по правому краю',
    'image': 'Вставить изображение',
    'marker': 'Выделение маркером',
    'textcolor': 'Цвет текста',
    'export': 'Экспорт',
    'delete': 'Удалить',
}

_SVG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icons_svg')

# тёмная тема: подстановка цветов (штрихи -> светлый текст, подложки -> фон панели)
_DARK_MAP = {
    '#231f20': '#F5F5F7',
    '#010101': '#F5F5F7',
    '#000000': '#F5F5F7',
    '#000': '#F5F5F7',
    '#fff': '#232326',
    '#ffffff': '#232326',
}

_svg_cache = {}      # (kind, dark) -> QByteArray готового SVG
_icon_cache = {}     # (kind, dark) -> QIcon с набором pixmap разных размеров
ICON_SIZES = (16, 20, 24, 32, 48, 64)

_BARE_SHAPE_RE = re.compile(
    r'<(rect|path|polygon|circle|ellipse)(\s+[^>]*?)(/?)>',
    re.IGNORECASE,
)


def _recolor_dark(svg_text: str) -> str:
    def sub(m):
        return _DARK_MAP.get(m.group(0).lower(), m.group(0))
    return re.sub(r'#[0-9a-fA-F]{3,8}\b', sub, svg_text)


def _apply_default_fill(svg_text: str, fill: str) -> str:
    """QtSvg (Tiny 1.2) игнорирует CSS-селектор '*', поэтому для фигур без
    class и без fill задаём fill-атрибут напрямую (и на корневом <svg>)."""
    svg_text = re.sub(
        r'(<svg\b)(?![^>]*\bfill=)',
        rf'\1 fill="{fill}"',
        svg_text,
        count=1,
    )

    def patch_shape(m):
        tag, attrs, self_close = m.group(1), m.group(2), m.group(3)
        low = attrs.lower()
        if 'class=' in low or 'fill=' in low or 'style=' in low:
            return m.group(0)
        return f'<{tag} fill="{fill}"{attrs}{self_close}>'

    return _BARE_SHAPE_RE.sub(patch_shape, svg_text)


def _svg_bytes(kind: str, dark: bool) -> QByteArray:
    key = (kind, dark)
    data = _svg_cache.get(key)
    if data is None:
        with open(os.path.join(_SVG_DIR, ICON_FILES[kind] + '.svg'),
                  'r', encoding='utf-8-sig') as f:
            text = f.read()
        if dark:
            text = _recolor_dark(text)
        fill = '#F5F5F7' if dark else '#231F20'
        text = _apply_default_fill(text, fill)
        data = QByteArray(text.encode('utf-8'))
        _svg_cache[key] = data
    return data


def png_icon(kind: str, dark: bool) -> QIcon:
    """Векторная иконка кнопки: QSvgRenderer -> pixmap набора размеров.
    Имя оставлено прежним (png_icon) для совместимости вызовов."""
    key = (kind, dark)
    icon = _icon_cache.get(key)
    if icon is None:
        renderer = QSvgRenderer(_svg_bytes(kind, dark))
        icon = QIcon()
        for s in ICON_SIZES:
            img = QImage(s, s, QImage.Format.Format_ARGB32)
            img.fill(0)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(p, QRectF(0, 0, s, s))
            p.end()
            icon.addPixmap(QPixmap.fromImage(img))
        _icon_cache[key] = icon
    return icon


def is_dark_theme(colors: dict) -> bool:
    """Тема тёмная, если цвет текста светлый (универсально для будущих тем)."""
    try:
        return QColor(colors['text']).lightnessF() > 0.5
    except Exception:
        return False


def theme_icon(mode: str, dark: bool, dpr: float = 1.0) -> QIcon:
    """Иконка темы: солнце — день, луна — ночь, полукруг — как в Windows.
    Рендер в разрешении экрана (dpr), чтобы иконка была чёткой на масштабе
    125/150%."""
    s = 16
    px = max(1, round(s * dpr))
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    ink = QColor('#F5F5F7') if dark else QColor('#3A3A3C')
    pen = QPen(ink, 1.3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    c = QPointF(s / 2, s / 2)
    r = s * 0.30
    if mode == 'dark':
        # луна: круг минус смещённый круг
        path = QPainterPath()
        path.addEllipse(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r))
        cut = QPainterPath()
        cut.addEllipse(QRectF(c.x() - r * 0.35, c.y() - r * 1.15, 2 * r, 2 * r))
        p.setBrush(ink)
        p.setPen(Qt.NoPen)
        p.drawPath(path.subtracted(cut))
    elif mode == 'system':
        # полукруг: левая половина залита («авто»), ровный контур вокруг
        rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        p.setBrush(ink)
        p.setPen(Qt.NoPen)
        p.drawPie(rect, 90 * 16, 180 * 16)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(ink, 1.3))
        p.drawEllipse(rect)
    else:
        # солнце: круг + лучи
        p.setBrush(ink)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(c.x() - r * 0.62, c.y() - r * 0.62, r * 1.24, r * 1.24))
        p.setPen(pen)
        for i in range(8):
            ang = i * math.pi / 4
            x1 = c.x() + math.cos(ang) * (r * 0.86)
            y1 = c.y() + math.sin(ang) * (r * 0.86)
            x2 = c.x() + math.cos(ang) * (r * 1.18)
            y2 = c.y() + math.sin(ang) * (r * 1.18)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    p.end()
    return QIcon(pm)


def folder_icon(dark: bool, dpr: float = 1.0) -> QIcon:
    """Векторная иконка папки (открыть папку заметок): сплошной силуэт
    со швом-разделителем в цвет фона. Рендер в разрешении экрана."""
    s = 16
    px = max(1, round(s * dpr))
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    ink = QColor('#F5F5F7') if dark else QColor('#3A3A3C')
    paper = QColor('#2A2A2E') if dark else QColor('#FFFFFF')
    path = QPainterPath()
    path.moveTo(1.2, 3.4)
    path.quadTo(1.2, 2.2, 2.4, 2.2)
    path.lineTo(5.4, 2.2)
    path.quadTo(6.4, 2.2, 7.0, 3.1)
    path.lineTo(7.8, 4.2)
    path.lineTo(13.6, 4.2)
    path.quadTo(14.8, 4.2, 14.8, 5.4)
    path.lineTo(14.8, 12.8)
    path.quadTo(14.8, 13.8, 13.6, 13.8)
    path.lineTo(2.4, 13.8)
    path.quadTo(1.2, 13.8, 1.2, 12.8)
    path.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(ink)
    p.drawPath(path)
    # шов между «крышкой» и карманом — цветом фона
    p.setPen(QPen(paper, 1.1))
    p.drawLine(QPointF(1.2, 6.3), QPointF(14.8, 6.3))
    p.end()
    return QIcon(pm)


def paint_app_icon(size: int = 64) -> QPixmap:
    """Жёлтый скруглённый квадрат с белыми строками — как у Apple Notes."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(size * 0.08, size * 0.08, size * 0.84, size * 0.84)
    grad = QLinearGradient(r.topLeft(), r.bottomLeft())
    grad.setColorAt(0.0, QColor('#FFDE33'))
    grad.setColorAt(1.0, QColor('#FFC400'))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(r, size * 0.2, size * 0.2)
    pen = QPen(QColor('#FFFFFF'), max(2.0, size * 0.06), Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    x0, x1 = size * 0.27, size * 0.73
    for i, frac in enumerate((0.38, 0.52, 0.66)):
        y = size * frac
        p.drawLine(QPointF(x0 if i != 0 else size * 0.33, y),
                   QPointF(x1 if i != 2 else size * 0.6, y))
    p.end()
    return pm


def glyph(size: int = 18, color: str = '#3A3A3C', kind: str = 'note') -> QPixmap:
    """Линейный глиф: note (страница с карандашом), plus, trash, folder, pin, search."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), max(1.1, size * 0.055), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = size
    m = s * 0.18
    if kind == 'note':
        path = QPainterPath()
        path.moveTo(m, m + s * 0.1)
        path.lineTo(s * 0.62, m + s * 0.1)
        path.lineTo(s - m, s * 0.38)
        path.lineTo(s - m, s - m)
        path.lineTo(m, s - m)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(s * 0.30, s * 0.52), QPointF(s * 0.70, s * 0.52))
        p.drawLine(QPointF(s * 0.30, s * 0.68), QPointF(s * 0.60, s * 0.68))
        p.drawLine(QPointF(s * 0.62, m + s * 0.1), QPointF(s * 0.62, s * 0.38))
        p.drawLine(QPointF(s * 0.62, s * 0.38), QPointF(s - m, s * 0.38))
    elif kind == 'plus':
        p.drawLine(QPointF(s / 2, m + s * 0.08), QPointF(s / 2, s - m - s * 0.08))
        p.drawLine(QPointF(m + s * 0.08, s / 2), QPointF(s - m - s * 0.08, s / 2))
    elif kind == 'trash':
        p.drawRoundedRect(QRectF(s * 0.26, s * 0.34, s * 0.48, s * 0.46), s * 0.06, s * 0.06)
        p.drawLine(QPointF(s * 0.18, s * 0.30), QPointF(s * 0.82, s * 0.30))
        p.drawLine(QPointF(s * 0.40, s * 0.30), QPointF(s * 0.40, s * 0.20))
        p.drawLine(QPointF(s * 0.60, s * 0.30), QPointF(s * 0.60, s * 0.20))
        p.drawLine(QPointF(s * 0.40, s * 0.30), QPointF(s * 0.40, s * 0.24))
        p.drawLine(QPointF(s * 0.44, s * 0.46), QPointF(s * 0.44, s * 0.68))
        p.drawLine(QPointF(s * 0.56, s * 0.46), QPointF(s * 0.56, s * 0.68))
    elif kind == 'folder':
        path = QPainterPath()
        path.moveTo(m, s * 0.30)
        path.lineTo(m, s * 0.74)
        path.lineTo(s - m, s * 0.74)
        path.lineTo(s - m, s * 0.40)
        path.lineTo(s * 0.5, s * 0.40)
        path.lineTo(s * 0.38, s * 0.30)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == 'pin':
        path = QPainterPath()
        path.addEllipse(QRectF(s * 0.36, s * 0.16, s * 0.28, s * 0.28))
        p.drawPath(path)
        p.drawLine(QPointF(s / 2, s * 0.44), QPointF(s / 2, s * 0.86))
        p.drawLine(QPointF(s * 0.34, s * 0.86), QPointF(s * 0.66, s * 0.86))
    elif kind == 'pane':
        p.drawRoundedRect(QRectF(m, m, s * 0.34, s - 2 * m), 2, 2)
        p.drawRoundedRect(QRectF(m + s * 0.40, m, s - 2 * m - s * 0.40, s - 2 * m), 2, 2)
    elif kind == 'image':
        p.drawRoundedRect(QRectF(m, m + s * 0.08, s - 2 * m, s * 0.68), s * 0.08, s * 0.08)
        p.drawEllipse(QRectF(s * 0.32, s * 0.26, s * 0.14, s * 0.14))
        path = QPainterPath()
        path.moveTo(m + 2, s * 0.62)
        path.lineTo(s * 0.42, s * 0.40)
        path.lineTo(s * 0.60, s * 0.56)
        path.lineTo(s * 0.72, s * 0.48)
        path.lineTo(s - m - 2, s * 0.66)
        p.drawPath(path)
    elif kind == 'link':
        p.drawRoundedRect(QRectF(s * 0.14, s * 0.40, s * 0.44, s * 0.20), s * 0.1, s * 0.1)
        p.drawRoundedRect(QRectF(s * 0.42, s * 0.40, s * 0.44, s * 0.20), s * 0.1, s * 0.1)
    elif kind == 'heading':
        p.drawLine(QPointF(s * 0.28, m), QPointF(s * 0.28, s - m))
        p.drawLine(QPointF(s * 0.72, m), QPointF(s * 0.72, s - m))
        p.drawLine(QPointF(s * 0.28, s / 2), QPointF(s * 0.72, s / 2))
    elif kind == 'marker':
        path = QPainterPath()
        path.moveTo(s * 0.66, m)
        path.lineTo(s * 0.82, s * 0.18)
        path.lineTo(s * 0.44, s * 0.56)
        path.lineTo(s * 0.30, s * 0.42)
        path.closeSubpath()
        p.drawPath(path)
        pen2 = QPen(QColor(color), max(1.4, s * 0.08), Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen2)
        p.drawLine(QPointF(s * 0.24, s * 0.80), QPointF(s * 0.66, s * 0.80))
    elif kind == 'align_l':
        for y in (0.30, 0.46, 0.62, 0.78):
            p.drawLine(QPointF(m, s * y), QPointF(s * (0.86 if y != 0.46 else 0.62), s * y))
    elif kind == 'align_c':
        for y in (0.30, 0.46, 0.62, 0.78):
            x0 = s * (0.30 if y != 0.46 else 0.38)
            x1 = s * (0.86 if y != 0.46 else 0.62)
            p.drawLine(QPointF(x0, s * y), QPointF(x1, s * y))
    elif kind == 'align_r':
        for y in (0.30, 0.46, 0.62, 0.78):
            p.drawLine(QPointF(s * (0.30 if y != 0.46 else 0.38), s * y), QPointF(s - m, s * y))
    elif kind == 'check':
        p.drawRoundedRect(QRectF(s * 0.16, s * 0.16, s * 0.68, s * 0.68), s * 0.14, s * 0.14)
        p.drawLine(QPointF(s * 0.32, s * 0.52), QPointF(s * 0.45, s * 0.66))
        p.drawLine(QPointF(s * 0.45, s * 0.66), QPointF(s * 0.70, s * 0.34))
    elif kind == 'bullet':
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        for y in (0.30, 0.52, 0.74):
            p.drawEllipse(QRectF(s * 0.16, s * y - s * 0.045, s * 0.11, s * 0.11))
        p.setPen(pen)
        p.drawLine(QPointF(s * 0.38, s * 0.30), QPointF(s * 0.84, s * 0.30))
        p.drawLine(QPointF(s * 0.38, s * 0.52), QPointF(s * 0.84, s * 0.52))
        p.drawLine(QPointF(s * 0.38, s * 0.74), QPointF(s * 0.84, s * 0.74))
    elif kind == 'compose':
        # страница с карандашом — как кнопка новой заметки в Apple Notes
        path = QPainterPath()
        path.moveTo(m, m + s * 0.06)
        path.lineTo(s * 0.56, m + s * 0.06)
        path.lineTo(s * 0.56, s * 0.34)
        path.lineTo(s * 0.80, s * 0.34)
        path.lineTo(s * 0.80, s * 0.52)
        path.lineTo(s - m, s * 0.60)
        path.lineTo(s - m, s - m)
        path.lineTo(m, s - m)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(s * 0.56, m + s * 0.06), QPointF(s * 0.56, s * 0.34))
        p.drawLine(QPointF(s * 0.56, s * 0.34), QPointF(s * 0.80, s * 0.34))
        pen2 = QPen(QColor(color), max(1.3, s * 0.07), Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen2)
        p.drawLine(QPointF(s * 0.48, s * 0.72), QPointF(s * 0.88, s * 0.26))
        p.drawLine(QPointF(s * 0.48, s * 0.72), QPointF(s * 0.42, s * 0.84))
    elif kind == 'sidebar':
        p.drawRoundedRect(QRectF(m, m + s * 0.06, s - 2 * m, s * 0.76), s * 0.07, s * 0.07)
        p.drawLine(QPointF(m + s * 0.34, m + s * 0.06), QPointF(m + s * 0.34, m + s * 0.82))
    elif kind == 'view_list':
        for y in (0.26, 0.5, 0.74):
            p.drawLine(QPointF(m, s * y), QPointF(s - m, s * y))
    elif kind == 'view_card':
        for y in (0.30, 0.54):
            p.drawLine(QPointF(m, s * y), QPointF(s - m, s * y))
        p.drawLine(QPointF(m, s * 0.78), QPointF(s * 0.55, s * 0.78))
    elif kind == 'view_table':
        p.drawLine(QPointF(m, s * 0.30), QPointF(s - m, s * 0.30))
        p.drawLine(QPointF(m, s * 0.62), QPointF(s - m, s * 0.62))
        p.drawLine(QPointF(s * 0.52, s * 0.14), QPointF(s * 0.52, s * 0.86))
    elif kind == 'view_gallery':
        p.drawRoundedRect(QRectF(m, m, s * 0.36, s * 0.36), s * 0.06, s * 0.06)
        p.drawRoundedRect(QRectF(s * 0.54, m, s * 0.36, s * 0.36), s * 0.06, s * 0.06)
        p.drawRoundedRect(QRectF(m, s * 0.54, s * 0.36, s * 0.36), s * 0.06, s * 0.06)
        p.drawRoundedRect(QRectF(s * 0.54, s * 0.54, s * 0.36, s * 0.36), s * 0.06, s * 0.06)
    p.end()
    return pm


def chip_icon(size: int = 14, hex_color: str = '#FFD60A') -> QIcon:
    """Цветной кружок для меню меток и маркеров."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor('#00000030'), 1))
    p.setBrush(QColor(hex_color if hex_color else '#FFFFFF'))
    p.drawEllipse(2, 2, size - 4, size - 4)
    p.end()
    return QIcon(pm)


def letter_icon(text: str, style: str = '', size: int = 20, color: str = '#3A3A3C') -> QIcon:
    """Кнопка-буква (B, I, U, S, A) с нужным начертанием — лёгкая, без жирноты."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    f = QFont('Segoe UI', int(size * 0.5))
    f.setBold('b' in style)
    f.setItalic('i' in style)
    f.setUnderline('u' in style)
    f.setStrikeOut('s' in style)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(pm.rect(), Qt.AlignCenter, text)
    p.end()
    return QIcon(pm)


def numbered_list_icon(dark: bool, dpr: float = 1.0) -> QIcon:
    """Векторная SVG-иконка нумерованного списка в едином стиле с остальными."""
    return png_icon('numbered', dark)


def sidebar_toggle_icon(dark: bool, dpr: float = 1.0) -> QIcon:
    """Векторная иконка скрытия/показа списка заметок (режим фокуса)."""
    s = 16
    px = max(1, round(s * dpr))
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    ink = QColor('#F5F5F7') if dark else QColor('#3A3A3C')
    pen = QPen(ink, 1.3)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(1.5, 2.2, 13.0, 11.6), 2.0, 2.0)
    p.drawLine(QPointF(5.8, 2.2), QPointF(5.8, 13.8))
    p.end()
    return QIcon(pm)


def glyph_icon(size: int, color: str, kind: str) -> QIcon:
    return QIcon(glyph(size, color, kind))
