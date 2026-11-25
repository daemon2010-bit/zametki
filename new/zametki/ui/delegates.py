# -*- coding: utf-8 -*-
"""Отрисовка строк списков: заметка (цвет-метка, заголовок, сниппет, дата, pin),
папка (имя + счётчик). Подсветка найденного в поиске."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from .icons import is_dark_theme, png_icon

NOTE_ROLE = Qt.UserRole + 1      # dict заметки
FOLDER_ROLE = Qt.UserRole + 2    # dict папки

_DELETE_PM = {}   # (dark, size) -> QPixmap, чтобы не пересобирать на каждом paint


def star_path(rect: 'QRectF'):
    """Пятиконечная звезда, вписанная в rect."""
    import math
    cx, cy = rect.center().x(), rect.center().y()
    r_out = min(rect.width(), rect.height()) / 2
    r_in = r_out * 0.45
    path = QPainterPath()
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r_out if i % 2 == 0 else r_in
        pt = QPointF(cx + rad * math.cos(ang), cy + rad * math.sin(ang))
        if i == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    path.closeSubpath()
    return path


def short_date(ts: float) -> str:
    """Компактная дата: 05.11.26 14:32."""
    import time
    if not ts:
        return ''
    try:
        return time.strftime('%d.%m.%y %H:%M', time.localtime(float(ts)))
    except (OSError, ValueError, OverflowError, TypeError):
        return ''


def date_only(ts: float) -> str:
    """Только дата: 05.11.26."""
    import time
    if not ts:
        return ''
    try:
        return time.strftime('%d.%m.%y', time.localtime(float(ts)))
    except (OSError, ValueError, OverflowError, TypeError):
        return ''


def human_date(ts: float) -> str:
    import time
    if not ts:
        return ''
    try:
        lt = time.localtime(float(ts))
        loc_t = time.strftime('%H:%M', lt)
    except (OSError, ValueError, OverflowError, TypeError):
        return ''
    now = time.localtime()
    if now[:3] == lt[:3]:
        return 'Сегодня ' + loc_t
    import datetime
    yest = datetime.date.today() - datetime.timedelta(days=1)
    if yest.timetuple()[:3] == lt[:3]:
        return 'Вчера ' + loc_t
    months = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
              'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря')
    d = f'{lt[2]} {months[lt[1] - 1]}'
    if lt[0] != now[0]:
        d += f' {lt[0]} г.'
    return d + ', ' + loc_t


class NoteDelegate(QStyledItemDelegate):
    """Отрисовка заметки в четырёх видах: card / list / table / gallery."""

    def __init__(self, colors_provider, parent=None):
        super().__init__(parent)
        self._colors = colors_provider
        self.search = ''
        self.mode = 'card'

    # ---------- геометрия видов ----------
    def sizeHint(self, option, index):
        if self.mode == 'card':
            return QSize(option.rect.width(), 70)
        return QSize(option.rect.width(), 32)

    def _draw_pill(self, p, rect, selected, hovered):
        c = self._colors()
        card_r = rect.adjusted(5, 2, -5, -2)
        if selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c['sel']))
            p.drawRoundedRect(card_r, 9, 9)
        elif hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c['hover']))
            p.drawRoundedRect(card_r, 9, 9)

    def _draw_colorbar(self, p, rect, note):
        if note.get('color'):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(note['color']))
            # цветная полоска строго ВНУТРИ рамки карточки (левый край рамки = left + 5)
            p.drawRoundedRect(QRectF(rect.left() + 8, rect.top() + 9, 3.5, rect.height() - 18), 2, 2)

    def _draw_star(self, p, x, y, size, pinned):
        """Звезда избранного: залита — закреплено, контур — нет."""
        c = self._colors()
        path = star_path(QRectF(x, y, size, size))
        if pinned:
            p.setPen(QPen(QColor(c['accent']), 1))
            p.setBrush(QColor(c['accent']))
        else:
            p.setPen(QPen(QColor(c['text2']), 1))
            p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def _draw_delete(self, p, cx, cy, size=9):
        """Крестик удаления: рисуется линиями (чёткий в любом масштабе),
        центр в точке (cx, cy)."""
        c = self._colors()
        pen = QPen(QColor(c['text2']), 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        r = size / 2
        p.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
        p.drawLine(QPointF(cx + r, cy - r), QPointF(cx - r, cy + r))

    def _draw_restore(self, p, cx, cy, size=10):
        """Изогнутая стрелка возврата из корзины (↩), центр в точке (cx, cy)."""
        c = self._colors()
        pen = QPen(QColor(c['text2']), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        r = size / 2
        # дуга возврата: сверху влево -> наконечник стрелки, снизу полукруг справа
        path = QPainterPath()
        path.moveTo(cx - r * 0.85, cy - r * 0.25)
        path.lineTo(cx + r * 0.25, cy - r * 0.25)
        path.cubicTo(cx + r * 1.05, cy - r * 0.25,
                     cx + r * 1.05, cy + r * 0.85,
                     cx + r * 0.20, cy + r * 0.85)
        path.lineTo(cx - r * 0.45, cy + r * 0.85)
        p.drawPath(path)
        # наконечник стрелки влево
        ax, ay = cx - r * 0.85, cy - r * 0.25
        p.drawLine(QPointF(ax, ay), QPointF(ax + r * 0.55, ay - r * 0.55))
        p.drawLine(QPointF(ax, ay), QPointF(ax + r * 0.55, ay + r * 0.55))

    def _draw_bell(self, p, cx, cy, size=9):
        """Маленький векторный колокольчик активного напоминания."""
        c = self._colors()
        pen = QPen(QColor(c['accent']), 1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        r = size / 2
        path = QPainterPath()
        path.moveTo(cx - r * 0.85, cy + r * 0.45)
        path.lineTo(cx + r * 0.85, cy + r * 0.45)
        path.lineTo(cx + r * 0.60, cy + r * 0.10)
        path.lineTo(cx + r * 0.60, cy - r * 0.25)
        path.cubicTo(cx + r * 0.60, cy - r * 0.90,
                     cx - r * 0.60, cy - r * 0.90,
                     cx - r * 0.60, cy - r * 0.25)
        path.lineTo(cx - r * 0.60, cy + r * 0.10)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(cx - r * 0.22, cy + r * 0.82), QPointF(cx + r * 0.22, cy + r * 0.82))

    def _font(self, base, size, bold=False):
        f = QFont(base)
        f.setFamily('Segoe UI')
        f.setPointSizeF(size)
        f.setBold(bold)
        return f

    # ---------- отрисовка ----------
    def paint(self, painter: QPainter, option, index):
        note = index.data(NOTE_ROLE)
        if note is None:
            return
        p = painter
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        getattr(self, '_paint_' + self.mode)(p, option, note)
        p.restore()

    def _paint_card(self, p, option, note):
        c = self._colors()
        rect = option.rect
        is_deleted = bool(note.get('deleted'))
        self._draw_pill(p, rect, bool(option.state & QStyle.State_Selected),
                        bool(option.state & QStyle.State_MouseOver))
        # аккуратная тонкая рамка карточки с ровными отступами
        p.setPen(QPen(QColor(c['line']), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(rect.adjusted(5, 2, -5, -2)), 9, 9)
        self._draw_colorbar(p, rect, note)
        row1_cy = rect.top() + 17.5
        if is_deleted:
            x = rect.left() + 16
            w = max(20, rect.width() - 16 - 56)
        else:
            # звезда избранного строго на одной горизонтали с заголовком и крестиком
            self._draw_star(p, rect.left() + 14, row1_cy - 5.5, 11,
                            bool(note.get('pinned')))
            x = rect.left() + 31
            w = max(20, rect.width() - 31 - 34)
        p.setFont(self._font(option.font, 10.5, True))
        fm = QFontMetrics(p.font())
        title_baseline = row1_cy + (fm.ascent() - fm.descent()) / 2
        self._draw_highlight(p, x, title_baseline, w, fm,
                             note.get('title') or 'Новая заметка', QColor(c['text']))
        p.setFont(self._font(option.font, 9))
        fm2 = QFontMetrics(p.font())
        snippet = (note.get('snippet') or '').replace('\n', ' ')
        p.setPen(QColor(c['text2']))
        p.drawText(QRectF(x, rect.top() + 29, w, 17), Qt.AlignLeft | Qt.AlignVCenter,
                   fm2.elidedText(snippet, Qt.ElideRight, w))
        p.setFont(self._font(option.font, 8))
        fm3 = QFontMetrics(p.font())
        date = short_date(note.get('modified') or note.get('created') or 0)
        p.drawText(QRectF(x, rect.top() + 47, w, 15), Qt.AlignLeft | Qt.AlignVCenter, date)
        if not is_deleted and (note.get('reminder_at') or 0) > 0:
            bell_x = x + fm3.horizontalAdvance(date) + 10
            if bell_x < rect.right() - 16:
                self._draw_bell(p, bell_x, rect.top() + 54.5)
        # в корзине - стрелка восстановления рядом с крестиком удаления
        if is_deleted:
            self._draw_restore(p, rect.right() - 40, row1_cy)
        # крестик удаления СПРАВА, на одной горизонтали с заголовком
        self._draw_delete(p, rect.right() - 18, row1_cy)

    def _paint_list(self, p, option, note):
        c = self._colors()
        rect = option.rect
        is_deleted = bool(note.get('deleted'))
        self._draw_pill(p, rect, bool(option.state & QStyle.State_Selected),
                        bool(option.state & QStyle.State_MouseOver))
        self._draw_colorbar(p, rect, note)
        if is_deleted:
            x = rect.left() + 16
            right_pad = 36
        else:
            # звезда избранного СЛЕВА, по вертикали - на уровне текста строки
            self._draw_star(p, rect.left() + 14, rect.center().y() - 5, 10,
                            bool(note.get('pinned')))
            x = rect.left() + 30
            right_pad = 16
        w = max(20, rect.width() - (x - rect.left()) - right_pad)
        p.setFont(self._font(option.font, 9.5, bool(note.get('pinned'))))
        fm = QFontMetrics(p.font())
        title = note.get('title') or 'Новая заметка'
        date = short_date(note.get('modified') or note.get('created') or 0)
        dw = fm.horizontalAdvance(date) + 14
        has_rem = (not is_deleted) and ((note.get('reminder_at') or 0) > 0)
        rem_pad = 16 if has_rem else 0
        self._draw_highlight(p, x, rect.center().y() + (fm.ascent() - fm.descent()) / 2, max(10, w - dw - rem_pad), fm,
                             title, QColor(c['text']))
        if has_rem:
            self._draw_bell(p, rect.right() - right_pad - dw - 6, rect.center().y())
        p.setPen(QColor(c['text2']))
        p.drawText(QRectF(rect.right() - right_pad - dw, rect.top(), dw, rect.height()),
                   Qt.AlignRight | Qt.AlignVCenter, date)
        if is_deleted:
            self._draw_restore(p, rect.right() - 18, rect.center().y())

    def _paint_table(self, p, option, note):
        c = self._colors()
        rect = option.rect
        if bool(option.state & QStyle.State_Selected):
            p.fillRect(rect, QColor(c['sel']))
        elif bool(option.state & QStyle.State_MouseOver):
            p.fillRect(rect, QColor(c['hover']))
        if note.get('color'):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(note['color']))
            p.drawEllipse(QRectF(rect.left() + 6, rect.center().y() - 3, 6, 6))
        w = rect.width()
        col1 = w * 0.46      # заголовок
        col2 = w * 0.27      # изменено
        y = rect.center().y()
        p.setFont(self._font(option.font, 9.5, bool(note.get('pinned'))))
        fm = QFontMetrics(p.font())
        title = note.get('title') or 'Новая заметка'
        self._draw_highlight(p, rect.left() + 18, y + fm.ascent() / 2 - 1, col1 - 26, fm,
                             title, QColor(c['text']))
        # даты: мельче и серым, с обрезкой — колонки не наезжают друг на друга
        p.setFont(self._font(option.font, 8))
        fm2 = QFontMetrics(p.font())
        p.setPen(QColor(c['text2']))
        p.drawText(QRectF(rect.left() + col1, rect.top(), col2 - 12, rect.height()),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   fm2.elidedText(short_date(note.get('modified') or 0), Qt.ElideRight, col2 - 12))
        p.drawText(QRectF(rect.left() + col1 + col2, rect.top(), w * 0.27 - 10, rect.height()),
                   Qt.AlignLeft | Qt.AlignVCenter, date_only(note.get('created') or 0))
        p.setPen(QColor(c['line']))
        p.drawLine(QPointF(rect.left() + col1 - 8, rect.top() + 5),
                   QPointF(rect.left() + col1 - 8, rect.bottom() - 5))
        p.drawLine(QPointF(rect.left() + col1 + col2 - 8, rect.top() + 5),
                   QPointF(rect.left() + col1 + col2 - 8, rect.bottom() - 5))

    def _draw_highlight(self, p, x, y, w, fm, text, color):
        """Рисует текст с подсветкой подстроки поиска (акцентным цветом)."""
        from PySide6.QtCore import QPointF
        p.setPen(color)
        q = self.search.strip().lower()
        if not q:
            p.drawText(QPointF(x, y), fm.elidedText(text, Qt.ElideRight, w))
            return
        low = text.lower()
        pos = low.find(q)
        if pos < 0:
            p.drawText(QPointF(x, y), fm.elidedText(text, Qt.ElideRight, w))
            return
        colors = self._colors()
        cx = x
        pre, match, post = text[:pos], text[pos:pos + len(q)], text[pos + len(q):]
        if fm.horizontalAdvance(pre) + fm.horizontalAdvance(match) + fm.horizontalAdvance(post) > w:
            text_el = fm.elidedText(text, Qt.ElideRight, w)
            if text_el != text:
                p.drawText(QPointF(x, y), text_el)
                return
        p.setPen(QColor(colors['text']))
        p.drawText(QPointF(cx, y), pre)
        cx += fm.horizontalAdvance(pre)
        p.setPen(QColor(colors['accent']))
        f = p.font()
        f.setUnderline(True)
        p.setFont(f)
        p.drawText(QPointF(cx, y), match)
        cx += fm.horizontalAdvance(match)
        f.setUnderline(False)
        p.setFont(f)
        p.setPen(QColor(colors['text']))
        p.drawText(QPointF(cx, y), post)


class FolderDelegate(QStyledItemDelegate):
    def __init__(self, colors_provider, count_fn, parent=None):
        super().__init__(parent)
        self._colors = colors_provider
        self._count_fn = count_fn   # folder_id -> int

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 30)

    def paint(self, p: QPainter, option, index):
        c = self._colors()
        folder = index.data(FOLDER_ROLE)
        if folder is None:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c['sel']))
            p.drawRoundedRect(rect.adjusted(4, 1, -4, -1), 8, 8)
        elif hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c['hover']))
            p.drawRoundedRect(rect.adjusted(4, 1, -4, -1), 8, 8)
        f = QFont(option.font)
        f.setPointSize(10.5)
        f.setBold(selected)
        p.setFont(f)
        fm = QFontMetrics(f)
        count = self._count_fn(folder['id'])
        cnt_text = str(count)
        cw = fm.horizontalAdvance(cnt_text) + 10
        p.setPen(QColor(c['text'] if selected else c['text2']))
        p.drawText(QRectF(rect.left() + 12, rect.top(), rect.width() - 24 - cw, rect.height()),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(folder['name'], Qt.ElideRight, rect.width() - 34 - cw))
        p.setPen(QColor(c['text2']))
        p.drawText(QRectF(rect.right() - 12 - cw, rect.top(), cw, rect.height()),
                   Qt.AlignRight | Qt.AlignVCenter, cnt_text)
        p.restore()
