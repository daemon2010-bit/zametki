# -*- coding: utf-8 -*-
"""Редактор заметки: форматирование, чек-листы, картинки, автоссылки, автосохранение."""
import os
import re
import uuid

from PySide6.QtCore import QTimer, QUrl, Signal, Qt
from PySide6.QtGui import (QColor, QFont, QImage, QTextBlockFormat, QTextCharFormat,
                           QTextCursor, QTextDocument, QTextFormat, QTextImageFormat,
                           QTextListFormat)
from PySide6.QtWidgets import QApplication, QFileDialog, QTextBrowser, QTextEdit

from ..core import store as st

URL_RE = re.compile(r'(https?://[^\s<>"\']+|www\.[^\s<>"\']+)', re.IGNORECASE)


class NoteEditor(QTextBrowser):
    save_requested = Signal(str, str)      # (note_id, html)
    title_hint = Signal(str)               # заголовок для шапки
    files_dropped = Signal(list)           # перетащили не-картинки (txt/html) — импорт

    def __init__(self, colors_provider, parent=None):
        super().__init__(parent)
        self._colors = colors_provider     # функция -> dict цветов темы
        self.note = None
        self._restyling = False
        self._dirty = False
        self._img_resize = None            # состояние перетаскивания размера картинки
        self._title_size = 0.0             # размер заголовка первой строки (0 — авто 17pt)
        self.setReadOnly(False)
        # QTextBrowser при создании отключает undo/redo документа; без этой
        # строки Ctrl+Z не работает вообще
        self.document().setUndoRedoEnabled(True)
        self.setAcceptRichText(True)
        self.setOpenExternalLinks(True)
        self.setAcceptDrops(True)
        # каретка, выделение, кликабельные ссылки и перетаскивание текста/картинок:
        # у QTextBrowser набор флагов по умолчанию «только чтение» — без правки
        # каретка не рисуется и dnd не работает
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setTabChangesFocus(False)
        self.setCursorWidth(2)             # курсор видно на любом фоне
        self.document().setDefaultFont(QFont('Segoe UI', 11))
        self._apply_page_margins()
        self.textChanged.connect(self._on_changed)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._emit_save)
        self._link_timer = QTimer(self)
        self._link_timer.setSingleShot(True)
        self._link_timer.setInterval(600)
        self._link_timer.timeout.connect(self._autolink)

    # ---------- поля страницы ----------
    def _apply_page_margins(self):
        """Поля текста 5 мм слева и справа (мм пересчитываются в логические
        пиксели по DPI экрана, чтобы на любом масштабе было ровно 5 мм)."""
        try:
            dpi = self.logicalDpiY() or 96
        except Exception:
            dpi = 96
        px = max(12, round(5 / 25.4 * dpi))
        self.document().setDocumentMargin(0)          # отступ задаём только здесь
        self.setViewportMargins(px, 10, px, 10)       # сверху/снизу — небольшая подушка

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_page_margins()   # DPI мог смениться вместе с экраном

    # ---------- загрузка/сохранение ----------
    def set_store(self, store: st.Store):
        self.store = store
        self.document().setBaseUrl(QUrl.fromLocalFile(store.root + os.sep))

    def load_note(self, note):
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._emit_save()
        self.note = note
        try:
            self._title_size = float(note.get('title_size', 0.0) or 0.0)
        except (TypeError, ValueError):
            self._title_size = 0.0
        self.blockSignals(True)
        self.clear()
        self.document().setDefaultFont(QFont('Segoe UI', 11))
        self.setHtml(note.get('html') or '')
        self.normalize_theme_colors()
        self._restyle_first_line()
        self._normalize_list_bullets()
        self._dirty = False
        self.blockSignals(False)

    def flush(self):
        was_active = self._save_timer.isActive()
        if was_active:
            self._save_timer.stop()
        if self._dirty or was_active:
            self._emit_save()

    def _on_changed(self):
        if self.note is None or self._restyling:
            return
        self._dirty = True
        self._restyle_first_line()
        self._save_timer.start()
        self._link_timer.start()

    # ---------- автоссылки: URL в тексте становится кликабельной ссылкой ----------
    def _autolink(self):
        if self.note is None:
            return
        doc = self.document()
        changed = False
        self._restyling = True
        self.blockSignals(True)
        try:
            block = doc.firstBlock()
            while block.isValid():
                text = block.text()
                for m in URL_RE.finditer(text):
                    cursor = QTextCursor(doc)
                    cursor.setPosition(block.position() + m.start())
                    cursor.setPosition(block.position() + m.end(), QTextCursor.KeepAnchor)
                    if cursor.charFormat().anchorHref():
                        continue    # уже ссылка
                    url = m.group(0)
                    if url.lower().startswith('www.'):
                        url = 'https://' + url
                    fmt = QTextCharFormat()
                    fmt.setAnchor(True)
                    fmt.setAnchorHref(url)
                    fmt.setForeground(QColor('#3B82F6'))
                    fmt.setFontUnderline(True)
                    cursor.mergeCharFormat(fmt)
                    changed = True
                block = block.next()
        finally:
            self.blockSignals(False)
            self._restyling = False
        if changed:
            self._dirty = True
            self._save_timer.stop()
            self._emit_save()

    def _emit_save(self):
        if self.note is None:
            return
        self._dirty = False
        self.save_requested.emit(self.note['id'], self.toHtml())

    def plain_parts(self):
        plain = self.toPlainText()
        return st.note_plain_parts(plain)

    def selection_char_formats(self, cursor=None):
        """Форматы всех фрагментов, пересекающихся с выделением (у каретки —
        формат ввода). Нужно для надёжного переключения кнопок форматирования:
        charFormat() при выделении читает лишь один СОСЕДНИЙ символ — при
        мышином выделении он может оказаться перед выделением или даже в
        соседней строке (заголовке), и кнопка работала «через раз»."""
        if cursor is None:
            cursor = self.textCursor()
        if not cursor.hasSelection():
            return [self.currentCharFormat()]
        doc = self.document()
        start, end = sorted((cursor.selectionStart(), cursor.selectionEnd()))
        formats = []
        block = doc.findBlock(start)
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fr = it.fragment()
                if fr.isValid():
                    fpos = fr.position()
                    if fpos + fr.length() > start and fpos < end:
                        formats.append(fr.charFormat())
                it += 1
            if block.position() + block.length() >= end:
                break
            block = block.next()
        return formats

    # ---------- первая строка как заголовок ----------
    def _title_font(self, want_bold: bool) -> QFont:
        f = QFont('Segoe UI')
        f.setPointSize(17)
        f.setWeight(QFont.Weight.DemiBold if want_bold else QFont.Weight.Normal)
        if self._title_size > 0:
            # пользователь сменил размер заголовка кнопкой «размер текста»
            f.setPointSizeF(self._title_size)
        return f

    def _first_line_is_title(self, want_bold: bool) -> bool:
        """True, если КАЖДЫЙ фрагмент первой строки уже оформлен как заголовок.
        Проверять только первый символ нельзя: двойной щелчок и перетаскивание
        слов могут испортить часть строки, и она оставалась «рваной» навсегда."""
        block = self.document().firstBlock()
        expected_pt = self._title_font(want_bold).pointSizeF()
        it = block.begin()
        seen = False
        while not it.atEnd():
            fr = it.fragment()
            if fr.isValid() and fr.text():
                f = fr.charFormat().font()
                if (abs(f.pointSizeF() - expected_pt) > 0.1 or f.bold() != want_bold
                        or f.family() != 'Segoe UI'):
                    return False
                seen = True
            it += 1
        return seen

    def sync_block_bullet_format(self, block):
        """Синхронизирует blockCharFormat блока с реальным размером текста в нём,
        чтобы маркеры (кружочки) маркированного списка не наследовали 17pt от
        заголовка на обычной строке и не сжимались в заголовке."""
        if not block.isValid():
            return
        pt = 0.0
        it = block.begin()
        while not it.atEnd():
            fr = it.fragment()
            if fr.isValid() and fr.text() and not fr.charFormat().isImageFormat():
                ps = fr.charFormat().font().pointSizeF()
                if ps > 0:
                    pt = ps
                    break
            it += 1
        if pt <= 0:
            if block == self.document().firstBlock():
                pt = self._title_font(block.text() != '').pointSizeF()
            else:
                pt = 11.0
        cur_bcf = block.charFormat()
        cur_f = cur_bcf.font()
        fg = cur_bcf.foreground()
        has_fg = fg.style() != Qt.BrushStyle.NoBrush
        if (abs(cur_f.pointSizeF() - pt) < 0.1
                and cur_f.weight() == QFont.Weight.Normal
                and cur_f.family() == 'Segoe UI'
                and not has_fg):
            return
        bcf = QTextCharFormat()
        f = QFont('Segoe UI')
        f.setPointSizeF(pt)
        f.setWeight(QFont.Weight.Normal)
        bcf.setFont(f)
        bc = QTextCursor(block)
        bc.setBlockCharFormat(bcf)

    def _normalize_list_bullets(self):
        """Выравнивает blockCharFormat у всех строк списков в документе."""
        b = self.document().firstBlock()
        while b.isValid():
            if b.textList() is not None:
                self.sync_block_bullet_format(b)
            b = b.next()

    def _restyle_first_line(self, force: bool = False):
        if self._restyling:
            return
        self._restyling = True
        try:
            doc = self.document()
            block = doc.firstBlock()
            want_bold = block.text() != ''
            # если первая строка уже оформлена как заголовок — НЕ трогаем документ:
            # каждая лишняя правка добавляет шаг в стек Ctrl+Z и «ломает» отмену
            if not force and block.length() > 1 and self._first_line_is_title(want_bold):
                if block.textList() is not None:
                    self.sync_block_bullet_format(block)
                return
            # важно: форматируем СИМВОЛЫ строки (mergeCharFormat), а не базу блока
            # (mergeBlockCharFormat не перезаписывает уже существующие фрагменты —
            # из-за этого заголовок становился «рваным»: часть 11pt, часть 17pt)
            cursor = QTextCursor(block)
            cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            fmt = QTextCharFormat()
            fmt.setFont(self._title_font(want_bold))
            cursor.mergeCharFormat(fmt)
            if block.textList() is not None:
                self.sync_block_bullet_format(block)
        finally:
            self._restyling = False

    def _indent_list(self, delta: int) -> bool:
        """Tab / Shift+Tab внутри списка или чек-листа меняет уровень вложенности."""
        cursor = self.textCursor()
        blocks = self._selected_blocks(cursor)
        if not blocks or not any(b.textList() is not None for b in blocks):
            return False
        unordered_styles = (
            QTextListFormat.Style.ListDisc,
            QTextListFormat.Style.ListCircle,
            QTextListFormat.Style.ListSquare,
        )
        self._restyling = True
        cursor.beginEditBlock()
        try:
            for block in blocks:
                tl = block.textList()
                if tl is None:
                    continue
                lf = QTextListFormat(tl.format())
                cur_ind = max(1, lf.indent())
                new_ind = cur_ind + delta
                if new_ind < 1:
                    tl.remove(block)
                    bf = block.blockFormat()
                    bf.setIndent(0)
                    bf.setMarker(QTextBlockFormat.MarkerType.NoMarker)
                    QTextCursor(block).mergeBlockFormat(bf)
                else:
                    new_ind = min(6, new_ind)
                    lf.setIndent(new_ind)
                    if lf.style() in unordered_styles:
                        lf.setStyle(unordered_styles[(new_ind - 1) % len(unordered_styles)])
                    bc = QTextCursor(block)
                    bc.createList(lf)
                    self.sync_block_bullet_format(block)
        finally:
            cursor.endEditBlock()
            self._restyling = False
        self._dirty = True
        self.textChanged.emit()
        return True

    def _try_markdown_space(self) -> bool:
        """Автоформатирование при пробеле: '- '/'* ' -> список, '[] ' -> чек-лист, '1. ' -> нумерованный."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False
        blk = cursor.block()
        if blk == self.document().firstBlock() or blk.textList() is not None:
            return False
        prefix = blk.text()[:cursor.positionInBlock()]
        if prefix not in ('-', '*', '[]', '[ ]', '1.'):
            return False
        self._restyling = True
        cursor.beginEditBlock()
        try:
            del_c = QTextCursor(blk)
            del_c.setPosition(blk.position())
            del_c.setPosition(blk.position() + len(prefix), QTextCursor.MoveMode.KeepAnchor)
            del_c.removeSelectedText()
            self.sync_block_bullet_format(blk)
            lf = QTextListFormat()
            lf.setIndent(1)
            if prefix == '1.':
                lf.setStyle(QTextListFormat.Style.ListDecimal)
            else:
                lf.setStyle(QTextListFormat.Style.ListDisc)
            QTextCursor(blk).createList(lf)
            if prefix in ('[]', '[ ]') and self._block_markers_supported():
                bf = blk.blockFormat()
                bf.setMarker(QTextBlockFormat.MarkerType.Unchecked)
                QTextCursor(blk).mergeBlockFormat(bf)
        finally:
            cursor.endEditBlock()
            self._restyling = False
        self._dirty = True
        self.textChanged.emit()
        return True

    def _try_markdown_hr(self) -> bool:
        """'---' + Enter превращается в горизонтальный разделитель."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False
        blk = cursor.block()
        if blk == self.document().firstBlock() or blk.text().strip() != '---':
            return False
        cursor.beginEditBlock()
        try:
            del_c = QTextCursor(blk)
            del_c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            del_c.removeSelectedText()
            del_c.insertHtml('<hr/>')
            del_c.insertBlock()
            self.setTextCursor(del_c)
        finally:
            cursor.endEditBlock()
        self._dirty = True
        self.textChanged.emit()
        return True

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Tab:
            if self._indent_list(+1):
                return
            self.textCursor().insertText('    ')
            return
        if key == Qt.Key.Key_Backtab:
            if self._indent_list(-1):
                return
            return
        if key == Qt.Key.Key_Space and not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            if self._try_markdown_space():
                return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._try_markdown_hr():
                return
        was_first = (
            key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self.textCursor().block() == self.document().firstBlock()
        )
        super().keyPressEvent(event)
        if was_first:
            cur = self.textCursor()
            blk = cur.block()
            if blk != self.document().firstBlock():
                # при переходе с заголовка по Enter сбрасываем blockCharFormat новой
                # строки на 11pt Normal, чтобы кружочки списков не были гигантскими
                self._restyling = True
                try:
                    bcf = QTextCharFormat()
                    f = QFont('Segoe UI', 11)
                    f.setWeight(QFont.Weight.Normal)
                    bcf.setFont(f)
                    bc = QTextCursor(blk)
                    bc.setBlockCharFormat(bcf)
                    self.setCurrentCharFormat(bcf)
                finally:
                    self._restyling = False

    def mouseDoubleClickEvent(self, event):
        # Быстрое нажатие по квадратику чек-листа: переключение уже произошло
        # в mousePressEvent (второе нажатие двойного щелчка приходит как
        # MouseButtonDblClick) — не выделяем соседние слова.
        if self._marker_block_at(event.position().toPoint()) is not None:
            return
        super().mouseDoubleClickEvent(event)
        # Двойное выделение не должно влиять на стиль заголовка: после
        # выделения слова принудительно возвращаем строке заголовочный вид
        # и выставляем формат ввода как у заголовка — замена слова при вводе
        # не «теряет» 17pt и полужирное начертание.
        cursor = self.textCursor()
        if cursor.block() == self.document().firstBlock():
            self._restyle_first_line(force=True)
            if cursor.hasSelection():
                probe = QTextCursor(self.document())
                probe.setPosition(max(1, cursor.selectionStart()))
                self.setCurrentCharFormat(probe.charFormat())

    # ---------- чек-листы ----------
    def _block_markers_supported(self) -> bool:
        return hasattr(QTextBlockFormat.MarkerType, 'Unchecked')

    def toggle_checklist(self):
        """Цикл для выделенных строк: без отметки -> ☐ -> ☑ -> без отметки."""
        cursor = self.textCursor()
        blocks = self._selected_blocks(cursor)
        if not blocks:
            return
        first_fmt = blocks[0].blockFormat()
        try:
            cur = first_fmt.marker()
        except Exception:
            cur = None
        if cur == QTextBlockFormat.MarkerType.Unchecked:
            new = QTextBlockFormat.MarkerType.Checked
        elif cur == QTextBlockFormat.MarkerType.Checked:
            new = QTextBlockFormat.MarkerType.NoMarker
        else:
            new = QTextBlockFormat.MarkerType.Unchecked
        self._restyling = True
        cursor.beginEditBlock()
        try:
            tl_new = None
            for block in blocks:
                bf = block.blockFormat()
                bf.setMarker(new)
                bc = QTextCursor(block)
                bc.mergeBlockFormat(bf)
                if new == QTextBlockFormat.MarkerType.NoMarker:
                    tl = block.textList()
                    if tl is not None:
                        tl.remove(block)
                        bf2 = block.blockFormat()
                        bf2.setIndent(0)
                        QTextCursor(block).mergeBlockFormat(bf2)
                elif block.textList() is None:
                    self.sync_block_bullet_format(block)
                    bc2 = QTextCursor(block)
                    if tl_new is None:
                        lf = QTextListFormat()
                        lf.setStyle(QTextListFormat.Style.ListDisc)
                        lf.setIndent(1)
                        tl_new = bc2.createList(lf)
                    else:
                        tl_new.add(block)
        finally:
            cursor.endEditBlock()
            self._restyling = False
        self._dirty = True
        self.textChanged.emit()

    def _selected_blocks(self, cursor):
        """Все блоки диапазона, включая ПУСТЫЕ строки: маркированный список
        и чек-лист должны добавлять/снимать маркер и на пустой строке."""
        doc = self.document()
        start = doc.firstBlock()
        end = doc.lastBlock()
        if cursor.hasSelection():
            start = doc.findBlock(cursor.selectionStart())
            # selectionEnd может указывать на НАЧАЛО следующей строки (выделение
            # захватывает перевод строки) — тогда последняя затронутая строка
            # предыдущая, иначе менялся «следующий» блок вместо выделенного
            end = doc.findBlock(max(cursor.selectionEnd() - 1, cursor.selectionStart()))
        else:
            start = end = cursor.block()
        blocks, b = [], start
        while True:
            blocks.append(b)
            if b == end:
                break
            b = b.next()
            if not b.isValid():
                break
        return blocks

    # ---------- клик по чекбоксу ----------
    def _marker_block_at(self, pos):
        """Блок, чей КВАДРАТИК чек-листа содержит точку, или None.

        Зона — ровно сам квадратик: привязана к КУРСОРУ НАЧАЛА СТРОКИ
        (он рисуется в начале квадратика, текст — на ~15px правее).
        Привязка к курсору в точке клика недопустима: его rect.left()
        совпадает с координатой клика, и переключалось нажатие на ЛЮБОЕ
        слово строки.
        """
        if not self._block_markers_supported():
            return None
        cursor = self.cursorForPosition(pos)
        block = cursor.block()
        try:
            marker = block.blockFormat().marker()
        except Exception:
            return None
        if marker == QTextBlockFormat.MarkerType.NoMarker:
            return None
        anchor = QTextCursor(self.document())
        anchor.setPosition(block.position())   # начало строки = левый край квадратика
        rect = self.cursorRect(anchor)
        if (rect.left() - 2 <= pos.x() < rect.left() + 15
                and rect.top() - 2 <= pos.y() <= rect.bottom() + 2):
            return block
        return None

    def _toggle_marker(self, block):
        bc = QTextCursor(block)
        bf = block.blockFormat()
        bf.setMarker(QTextBlockFormat.MarkerType.Checked
                     if bf.marker() == QTextBlockFormat.MarkerType.Unchecked
                     else QTextBlockFormat.MarkerType.Unchecked)
        bc.mergeBlockFormat(bf)
        self.textChanged.emit()

    def _handle_marker_click(self, event) -> bool:
        block = self._marker_block_at(event.position().toPoint())
        if block is None:
            return False
        self._toggle_marker(block)
        return True
    def _image_at(self, pos):
        """(курсор-выделение картинки, формат, индекс символа) под точкой или None."""
        if hasattr(pos, 'toPoint'):        # QPointF → QPoint (cursorForPosition требует QPoint)
            pos = pos.toPoint()
        doc = self.document()
        c = self.cursorForPosition(pos)
        # формат символа i = charFormat курсора, стоящего на позиции i+1
        for i in (c.position() - 1, c.position()):
            if not (0 <= i < doc.characterCount() - 1):
                continue
            probe = QTextCursor(doc)
            probe.setPosition(i + 1)
            fmt = probe.charFormat()
            if fmt.isImageFormat():
                blk = doc.findBlock(i)
                try:
                    has_marker = (blk.blockFormat().marker()
                                  != QTextBlockFormat.MarkerType.NoMarker)
                except Exception:
                    has_marker = False
                if has_marker and i == blk.position():
                    continue    # квадратик чек-листа — не картинка
                sel = QTextCursor(doc)
                sel.setPosition(i)
                sel.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
                return sel, QTextImageFormat(fmt), i
        return None

    def _image_rect(self, idx: int, img_fmt):
        """Область картинки на экране. Курсор-каретка ставится ПЕРЕД символом
        картинки (на idx): курсор-выделение стоит после картинки и дал бы
        прямоугольник, сдвинутый на её ширину."""
        from PySide6.QtCore import QRect
        caret = QTextCursor(self.document())
        caret.setPosition(idx)
        r = self.cursorRect(caret)
        w, h = img_fmt.width(), img_fmt.height()
        if (w <= 0 or h <= 0) and hasattr(self, 'store'):
            # старые вставки без размера — берём естественный из файла
            try:
                path = os.path.join(self.store.root, img_fmt.name().replace('/', os.sep))
                img = QImage(path)
                if not img.isNull():
                    w, h = img.width(), img.height()
            except OSError:
                pass
        if w <= 0:
            w, h = 320, 240
        return QRect(int(r.left()), int(r.top()), int(w), int(h))

    def _image_press(self, event) -> bool:
        pos = event.position().toPoint()
        found = self._image_at(pos)
        if not found:
            return False
        sel, fmt, idx = found
        rect = self._image_rect(idx, fmt)
        corner = rect.adjusted(rect.width() - 16, rect.height() - 16, 0, 0)
        if corner.contains(pos):
            # правый нижний угол: начинаем изменение размера
            self._img_resize = {'index': idx, 'rect': rect,
                                'w0': max(1, rect.width()), 'h0': max(1, rect.height())}
            self.viewport().setCursor(Qt.CursorShape.SizeFDiagCursor)
            return True
        # клик по картинке: выделяем её символ — теперь её можно перетащить мышью
        self.setTextCursor(sel)
        return False   # пусть Qt обработает press и начнёт drag при движении

    def _apply_img_size(self, idx: int, w: int, h: int):
        doc = self.document()
        c = QTextCursor(doc)
        c.setPosition(idx)
        c.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
        old = QTextImageFormat(c.charFormat())
        fmt = QTextImageFormat()
        fmt.setName(old.name())
        fmt.setToolTip(old.toolTip())
        fmt.setWidth(w)
        fmt.setHeight(h)
        self._restyling = True
        c.setCharFormat(fmt)   # полная замена формата: merge не надёжна для image-форматов
        self._restyling = False
        self._dirty = True
        self._save_timer.start()

    def _natural_size(self, img_fmt):
        """Естественный размер картинки — из файла вложения (он не меняется)."""
        if hasattr(self, 'store') and self.note is not None:
            try:
                path = os.path.join(self.store.root, img_fmt.name().replace('/', os.sep))
                img = QImage(path)
                if not img.isNull():
                    return img.width(), img.height()
            except OSError:
                pass
        w, h = img_fmt.width(), img_fmt.height()
        return (w if w > 0 else 320, h if h > 0 else 240)

    def image_scale_actions(self, menu, pos) -> bool:
        """В меню добавляются пункты размера картинки под курсором.
        Гарантированный способ изменить размер без перетаскивания."""
        found = self._image_at(pos)
        if not found:
            return False
        _sel, fmt, idx = found
        nw, nh = self._natural_size(fmt)
        sub = menu.addMenu('Размер картинки')
        for frac, name in ((0.25, '25%'), (0.5, '50%'), (0.75, '75%'),
                           (1.0, '100% (оригинал)')):
            sub.addAction(name, lambda f=frac: self._apply_img_size(
                idx, max(40, int(nw * f)), max(30, int(nh * f))))
        return True

    def mousePressEvent(self, event):
        # чекбокс — ПЕРВЫМ: в Qt 6.12 квадратик чек-листа это inline-объект
        # с image-форматом, и обработчик картинок ниже «поймал» бы его раньше
        if self._handle_marker_click(event):
            return
        if self._image_press(event):
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._img_resize:
            st = self._img_resize
            new_w = int(min(max(pos.x() - st['rect'].left(), 40), 1600))
            new_h = int(new_w * st['h0'] / st['w0'])
            self._apply_img_size(st['index'], new_w, max(24, new_h))
            return
        # подсказка курсором: над квадратиком чек-листа появляется «ручка»
        if self._marker_block_at(pos) is not None:
            if self.viewport().cursor().shape() != Qt.CursorShape.PointingHandCursor:
                self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            super().mouseMoveEvent(event)
            return
        # подсказка курсором: угол картинки = ресайз
        found = self._image_at(pos)
        if found:
            rect = self._image_rect(found[2], found[1])
            if rect.adjusted(rect.width() - 16, rect.height() - 16, 0, 0).contains(pos):
                self.viewport().setCursor(Qt.CursorShape.SizeFDiagCursor)
                super().mouseMoveEvent(event)
                return
        if self.viewport().cursor().shape() in (Qt.CursorShape.SizeFDiagCursor,
                                                Qt.CursorShape.PointingHandCursor):
            self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # Отпускание кнопки над квадратиком чек-листа поглощаем: уход в
        # QTextControl вызывает выделение соседних слов при быстром
        # (двойном) нажатии на галочку.
        if self._marker_block_at(event.position().toPoint()) is not None:
            return
        if self._img_resize:
            self._img_resize = None
            self.viewport().unsetCursor()
            self._save_timer.stop()
            self._emit_save()
            return
        super().mouseReleaseEvent(event)

    # ---------- картинки ----------
    def insert_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Вставить изображение', '',
            'Изображения (*.png *.jpg *.jpeg *.gif *.bmp *.webp)')
        if path:
            self._insert_image_path(path)

    def _insert_image_path(self, path: str) -> str:
        """Сохраняет картинку в attachments и вставляет относительной ссылкой."""
        if self.note is None or not hasattr(self, 'store'):
            return ''
        img = QImage(path)
        if img.isNull():
            return ''
        note_dir = os.path.join(self.store.attach_dir, self.note['id'])
        os.makedirs(note_dir, exist_ok=True)
        ext = os.path.splitext(path)[1].lower() or '.png'
        if ext not in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'):
            ext = '.png'
        name = uuid.uuid4().hex[:12] + ext
        dst = os.path.join(note_dir, name)
        img.save(dst)
        rel = f'attachments/{self.note["id"]}/{name}'
        self._insert_image_fmt(rel, img.width(), img.height())
        return rel

    def _insert_image_fmt(self, rel: str, natural_w: int, natural_h: int):
        """Вставка картинки с явным размером (нужен для последующего ресайза)."""
        fmt = QTextImageFormat()
        fmt.setName(rel)
        w = natural_w or 320
        h = natural_h or 240
        if w > 460:                       # крупные картинки ужимаем к ширине редактора
            h = int(h * 460 / w)
            w = 460
        fmt.setWidth(w)
        fmt.setHeight(h)
        self.textCursor().insertImage(fmt)
        self.textChanged.emit()

    def insertFromMimeData(self, source):
        if source.hasImage():
            img = QImage(source.imageData())
            if not img.isNull():
                if self.note is None or not hasattr(self, 'store'):
                    return
                note_dir = os.path.join(self.store.attach_dir, self.note['id'])
                os.makedirs(note_dir, exist_ok=True)
                name = uuid.uuid4().hex[:12] + '.png'
                img.save(os.path.join(note_dir, name))
                self._insert_image_fmt(f'attachments/{self.note["id"]}/{name}',
                                       img.width(), img.height())
                return
        if source.hasUrls():
            locals_ = [u.toLocalFile() for u in source.urls() if u.isLocalFile()]
            imgs = [p for p in locals_ if os.path.splitext(p)[1].lower() in
                    ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')]
            others = [p for p in locals_ if p not in imgs]
            if imgs:
                for p in imgs:
                    self._insert_image_path(p)
            if others:
                self.files_dropped.emit(others)
            if imgs or others:
                return
        super().insertFromMimeData(source)

    # ---------- цвет текста ----------
    def set_text_color(self, color: QColor):
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        self.textCursor().mergeCharFormat(fmt)
        self.mergeCurrentCharFormat(fmt)
        self.textChanged.emit()

    def reset_text_color(self):
        """Сбрасывает явный цвет текста, чтобы текст следовал активной теме."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            doc = self.document()
            start, end = sorted((cursor.selectionStart(), cursor.selectionEnd()))
            fixes = []
            b = doc.findBlock(start)
            while b.isValid():
                it = b.begin()
                while not it.atEnd():
                    fr = it.fragment()
                    if fr.isValid():
                        fpos = fr.position()
                        fend = fpos + fr.length()
                        a, z = max(fpos, start), min(fend, end)
                        if z > a and not fr.charFormat().isImageFormat():
                            fixes.append((a, z, fr.charFormat()))
                    it += 1
                if b.position() + b.length() >= end:
                    break
                b = b.next()
            cursor.beginEditBlock()
            try:
                for a, z, fmt in fixes:
                    clean = QTextCharFormat(fmt)
                    clean.clearForeground()
                    c = QTextCursor(doc)
                    c.setPosition(a)
                    c.setPosition(z, QTextCursor.MoveMode.KeepAnchor)
                    c.setCharFormat(clean)
            finally:
                cursor.endEditBlock()
        else:
            cf = QTextCharFormat(self.currentCharFormat())
            cf.clearForeground()
            self.setCurrentCharFormat(cf)
        self.textChanged.emit()

    def set_highlight(self, color: QColor):
        if color == QColor('transparent') or color.alpha() == 0:
            cursor = self.textCursor()
            if cursor.hasSelection():
                doc = self.document()
                start, end = sorted((cursor.selectionStart(), cursor.selectionEnd()))
                fixes = []
                b = doc.findBlock(start)
                while b.isValid():
                    it = b.begin()
                    while not it.atEnd():
                        fr = it.fragment()
                        if fr.isValid():
                            fpos = fr.position()
                            fend = fpos + fr.length()
                            a, z = max(fpos, start), min(fend, end)
                            if z > a and not fr.charFormat().isImageFormat():
                                fixes.append((a, z, fr.charFormat()))
                        it += 1
                    if b.position() + b.length() >= end:
                        break
                    b = b.next()
                cursor.beginEditBlock()
                try:
                    for a, z, fmt in fixes:
                        clean = QTextCharFormat(fmt)
                        clean.clearBackground()
                        c = QTextCursor(doc)
                        c.setPosition(a)
                        c.setPosition(z, QTextCursor.MoveMode.KeepAnchor)
                        c.setCharFormat(clean)
                finally:
                    cursor.endEditBlock()
            else:
                cf = QTextCharFormat(self.currentCharFormat())
                cf.clearBackground()
                self.setCurrentCharFormat(cf)
            self.textChanged.emit()
            return
        fmt = QTextCharFormat()
        fmt.setBackground(color)
        self.textCursor().mergeCharFormat(fmt)
        self.mergeCurrentCharFormat(fmt)
        self.textChanged.emit()

    def clear_extra_format(self):
        """Убирает форматирование выделения (или всей заметки): цвет, маркер,
        начертание и размер, оставляя текст адаптивным к светлой/тёмной теме."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.Document)
        doc = self.document()
        start, end = sorted((cursor.selectionStart(), cursor.selectionEnd()))
        fixes = []
        b = doc.findBlock(start)
        while b.isValid():
            it = b.begin()
            while not it.atEnd():
                fr = it.fragment()
                if fr.isValid():
                    fpos = fr.position()
                    fend = fpos + fr.length()
                    a, z = max(fpos, start), min(fend, end)
                    if z > a and not fr.charFormat().isImageFormat():
                        fixes.append((a, z, fr.charFormat()))
                it += 1
            if b.position() + b.length() >= end:
                break
            b = b.next()
        self._restyling = True
        cursor.beginEditBlock()
        try:
            for a, z, old in fixes:
                clean = QTextCharFormat()
                f = QFont('Segoe UI', 11)
                f.setWeight(QFont.Weight.Normal)
                clean.setFont(f)
                if old.anchorHref():
                    clean.setAnchor(True)
                    clean.setAnchorHref(old.anchorHref())
                    clean.setForeground(QColor('#3B82F6'))
                    clean.setFontUnderline(True)
                c = QTextCursor(doc)
                c.setPosition(a)
                c.setPosition(z, QTextCursor.MoveMode.KeepAnchor)
                c.setCharFormat(clean)
            if doc.findBlock(start).blockNumber() == 0:
                self._title_size = 0.0
        finally:
            cursor.endEditBlock()
            self._restyling = False
        self._restyle_first_line(force=True)
        self._normalize_list_bullets()
        self.textChanged.emit()

    # ---------- цвет текста, следующий за темой ----------
    DEFAULT_THEME_COLORS = {'#1d1d1f', '#f5f5f7', '#000000', '#000'}
    LIGHT_MARKERS = ('#ffe680', '#c6f6d5', '#ffd6e8', '#eae9e4')
    DARK_MARKERS = ('#6b5900', '#1f5432', '#6b2848', '#34343a')

    # ---------- вставка чистым текстом, блок кода и поиск в заметке ----------
    def paste_plain(self):
        """Вставка из буфера обмена чистым текстом (без чужих шрифтов и фонов)."""
        text = QApplication.clipboard().text()
        if not text:
            return
        self.textCursor().insertText(text)
        self._dirty = True
        self.textChanged.emit()

    def toggle_code_block(self):
        """Переключает моноширинный стиль кода для выделения или текущей строки."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        fmts = self.selection_char_formats(cursor)
        is_code = bool(fmts) and all(f.font().family().lower() == 'consolas' for f in fmts)
        colors = self._colors()
        try:
            dark = QColor(colors['text']).lightnessF() > 0.5
        except Exception:
            dark = False
        cursor.beginEditBlock()
        try:
            if is_code:
                fmt = QTextCharFormat()
                f = QFont('Segoe UI', 11)
                f.setWeight(QFont.Weight.Normal)
                fmt.setFont(f)
                cursor.mergeCharFormat(fmt)
                # очищаем фон кода
                doc = self.document()
                start, end = sorted((cursor.selectionStart(), cursor.selectionEnd()))
                b = doc.findBlock(start)
                fixes = []
                while b.isValid():
                    it = b.begin()
                    while not it.atEnd():
                        fr = it.fragment()
                        if fr.isValid():
                            a = max(fr.position(), start)
                            z = min(fr.position() + fr.length(), end)
                            if z > a and not fr.charFormat().isImageFormat():
                                fixes.append((a, z, fr.charFormat()))
                        it += 1
                    if b.position() + b.length() >= end:
                        break
                    b = b.next()
                for a, z, old in fixes:
                    clean = QTextCharFormat(old)
                    clean.clearBackground()
                    c = QTextCursor(doc)
                    c.setPosition(a)
                    c.setPosition(z, QTextCursor.MoveMode.KeepAnchor)
                    c.setCharFormat(clean)
            else:
                fmt = QTextCharFormat()
                f = QFont('Consolas', 10)
                fmt.setFont(f)
                fmt.setBackground(QColor('#34343A' if dark else '#EAE9E4'))
                cursor.mergeCharFormat(fmt)
        finally:
            cursor.endEditBlock()
        self._dirty = True
        self.textChanged.emit()

    def highlight_search(self, query: str, current_idx: int = -1) -> list:
        """Недеструктивная подсветка всех совпадений в документе через ExtraSelections."""
        q = (query or '').strip()
        if not q:
            self.setExtraSelections([])
            return []
        doc = self.document()
        matches = []
        c = QTextCursor(doc)
        while True:
            c = doc.find(q, c)
            if c.isNull():
                break
            matches.append((c.selectionStart(), c.selectionEnd()))
        colors = self._colors()
        try:
            dark = QColor(colors['text']).lightnessF() > 0.5
        except Exception:
            dark = False
        bg_all = QColor('#5A4A12' if dark else '#FFF3B0')
        bg_cur = QColor('#B8860B' if dark else '#FFCA28')
        fg_cur = QColor('#FFFFFF' if dark else '#1D1D1F')
        sels = []
        for idx, (a, z) in enumerate(matches):
            es = QTextEdit.ExtraSelection()
            tc = QTextCursor(doc)
            tc.setPosition(a)
            tc.setPosition(z, QTextCursor.MoveMode.KeepAnchor)
            es.cursor = tc
            if idx == current_idx:
                es.format.setBackground(bg_cur)
                es.format.setForeground(fg_cur)
            else:
                es.format.setBackground(bg_all)
            sels.append(es)
        self.setExtraSelections(sels)
        if 0 <= current_idx < len(matches):
            a, z = matches[current_idx]
            tc = QTextCursor(doc)
            tc.setPosition(a)
            tc.setPosition(z, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(tc)
            self.ensureCursorVisible()
        return matches

    def clear_search_highlights(self):
        self.setExtraSelections([])

    def normalize_theme_colors(self):
        """Убирает явные цвета текста, совпадающие с цветом «по умолчанию»
        (#1D1D1F, #F5F5F7, #000000), и адаптирует стандартные маркеры под тему,
        чтобы текст оставался читаемым и в светлой, и в тёмной теме.

        ДВА ПРОХОДА: сначала собираем диапазоны, потом применяем — правка
        документа во время итерации по фрагментам делает итераторы
        недействительными."""
        doc = self.document()
        colors = self._colors()
        try:
            dark = QColor(colors['text']).lightnessF() > 0.5
        except Exception:
            dark = False
        bg_map = (dict(zip(self.LIGHT_MARKERS, self.DARK_MARKERS))
                  if dark else dict(zip(self.DARK_MARKERS, self.LIGHT_MARKERS)))
        fixes = []
        b = doc.firstBlock()
        while b.isValid():
            it = b.begin()
            while not it.atEnd():
                fr = it.fragment()
                if fr.isValid():
                    fmt = fr.charFormat()
                    if not fmt.isImageFormat():
                        fg = fmt.foreground()
                        clear_fg = (fg.style() != Qt.BrushStyle.NoBrush and
                                    fg.color().name().lower() in self.DEFAULT_THEME_COLORS)
                        bg = fmt.background()
                        new_bg = None
                        if bg.style() != Qt.BrushStyle.NoBrush:
                            bname = bg.color().name().lower()
                            if bname in bg_map:
                                new_bg = bg_map[bname]
                        if clear_fg or new_bg:
                            fixes.append((fr.position(), fr.length(), fmt, clear_fg, new_bg))
                it += 1
            b = b.next()
        for pos, length, fmt, clear_fg, new_bg in fixes:
            clean = QTextCharFormat(fmt)
            if clear_fg:
                clean.clearForeground()
            if new_bg:
                clean.setBackground(QColor(new_bg))
            c = QTextCursor(doc)
            c.setPosition(pos)
            c.setPosition(pos + length, QTextCursor.MoveMode.KeepAnchor)
            c.setCharFormat(clean)

    # ---------- размер текста ----------
    def set_font_size(self, size: float):
        size = float(size)
        fmt = QTextCharFormat()
        f = QFont('Segoe UI')
        f.setPointSizeF(size)
        fmt.setFont(f)
        cursor = self.textCursor()
        if cursor.hasSelection():
            # выделение касается первой строки — меняем и размер заголовка,
            # иначе авто-стиль вернёт 17pt и «ничего не произойдёт»
            if self.document().findBlock(cursor.selectionStart()).blockNumber() == 0:
                self._title_size = size
            cursor.mergeCharFormat(fmt)
            for blk in self._selected_blocks(cursor):
                if blk.textList() is not None:
                    self.sync_block_bullet_format(blk)
        else:
            if cursor.block().blockNumber() == 0:
                self._title_size = size
            self.mergeCurrentCharFormat(fmt)
            if cursor.block().textList() is not None:
                self.sync_block_bullet_format(cursor.block())
        self.textChanged.emit()

    def current_font_size(self) -> float:
        cursor = self.textCursor()
        if cursor.hasSelection():
            fmts = self.selection_char_formats(cursor)
            if fmts:
                ps = fmts[0].font().pointSizeF()
                return float(ps) if ps > 0 else 11.0
            return 11.0
        ps = self.currentCharFormat().font().pointSizeF()
        return float(ps) if ps > 0 else 11.0
