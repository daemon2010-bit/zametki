# -*- coding: utf-8 -*-
"""Главное окно: папки, список заметок, редактор; трей, поиск, сортировка."""
import os
import re
import time

from PySide6.QtCore import (QDateTime, QEvent, QItemSelectionModel, QMimeData,
                            QRect, QSize, QTime, QTimer, Qt, Signal)
from PySide6.QtGui import (QAction, QColor, QDrag, QFont, QIcon, QKeySequence,
                           QPalette, QShortcut, QTextBlockFormat, QTextListFormat)
from PySide6.QtWidgets import (QApplication, QComboBox, QDateTimeEdit, QDialog,
                               QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QSizePolicy, QSplitter, QSystemTrayIcon, QToolButton,
                               QToolTip, QVBoxLayout, QWidget)

from ..core import backup, i18n, share, versions, webdav_sync
from ..core import store as st
from .command_palette import CommandPalette
from .delegates import NOTE_ROLE, NoteDelegate, human_date
from .editor import NoteEditor
from .export import export_note, import_notes
from .icons import (chip_icon, folder_icon, is_dark_theme, numbered_list_icon,
                    paint_app_icon, png_icon, sidebar_toggle_icon, theme_icon)
from .reminders import ReminderEngine
from .settings_dialog import SettingsDialog
from .theme import apply_window_titlebar_theme
from .versions_dialog import VersionsDialog

TAG_RE = re.compile(r'(?<!\w)#([A-Za-zА-Яа-яЁё0-9_-]{2,32})')

COLORS = [('', 'Без цвета'), ('#FFD60A', 'Жёлтый'), ('#FF9F0A', 'Оранжевый'),
          ('#FF453A', 'Красный'), ('#32D74B', 'Зелёный'), ('#0A84FF', 'Синий'),
          ('#BF5AF2', 'Фиолетовый')]

NOTE_MIME = 'application/x-zametki-note'


def _vline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setObjectName('vsep')
    return line


class ResponsiveToolbar(QWidget):
    """Адаптивная панель инструментов: при нехватке ширины сворачивает
    непомещающиеся кнопки в стандартное выпадающее меню «» без наслоения."""

    def __init__(self, menu_builder, parent=None):
        super().__init__(parent)
        self._menu_builder = menu_builder
        self._entries = []       # list[(widget, is_sep)]
        self._hidden = []        # list[widget] — скрытые не-разделители
        self._spacing = 3
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(36)
        self.setFixedHeight(30)
        self.overflow_btn = QToolButton(self)
        self.overflow_btn.setText('»')
        self.overflow_btn.setToolTip('Остальные инструменты форматирования')
        self.overflow_btn.setFixedSize(24, 26)
        self.overflow_btn.clicked.connect(self._open_overflow)
        self.overflow_btn.hide()

    def add_item(self, widget: QWidget, is_sep: bool = False):
        widget.setParent(self)
        if not is_sep and not isinstance(widget, QComboBox):
            widget.setFixedSize(26, 26)
        elif is_sep:
            widget.setFixedSize(5, 18)
        self._entries.append((widget, is_sep))
        widget.show()
        self._relayout()

    def _item_width(self, widget: QWidget, is_sep: bool) -> int:
        if is_sep:
            return 5
        if isinstance(widget, QComboBox):
            return widget.width() if widget.width() > 0 else 64
        return 26

    def _relayout(self):
        avail = self.width()
        if avail <= 0:
            return
        h = self.height()
        widths = [self._item_width(w, sep) for w, sep in self._entries]
        total = sum(widths) + self._spacing * max(0, len(widths) - 1)
        self._hidden = []
        if total <= avail:
            self.overflow_btn.hide()
            x = 0
            for (w, sep), iw in zip(self._entries, widths):
                ih = 18 if sep else min(26, h)
                w.setGeometry(x, (h - ih) // 2, iw, ih)
                w.show()
                x += iw + self._spacing
            return
        ov_w = self.overflow_btn.width()
        limit = max(0, avail - ov_w - self._spacing)
        vis = []
        x = 0
        overflowed = False
        for (w, sep), iw in zip(self._entries, widths):
            need = iw + (self._spacing if vis else 0)
            if not overflowed and x + need <= limit:
                vis.append((w, sep, iw))
                x += need
            else:
                overflowed = True
                w.hide()
                if not sep:
                    self._hidden.append(w)
        # не оставляем висячий разделитель прямо перед «»
        while vis and vis[-1][1]:
            sep_w, _, _ = vis.pop()
            sep_w.hide()
        x = 0
        for w, sep, iw in vis:
            ih = 18 if sep else min(26, h)
            w.setGeometry(x, (h - ih) // 2, iw, ih)
            w.show()
            x += iw + self._spacing
        if self._hidden:
            ov_h = self.overflow_btn.height()
            self.overflow_btn.setGeometry(x, (h - ov_h) // 2, ov_w, ov_h)
            self.overflow_btn.show()
        else:
            self.overflow_btn.hide()

    def _open_overflow(self):
        if not self._hidden:
            return
        menu = self._menu_builder(self._hidden)
        if menu is not None:
            menu.exec(self.overflow_btn.mapToGlobal(self.overflow_btn.rect().bottomLeft()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def showEvent(self, event):
        super().showEvent(event)
        self._relayout()


class NotesList(QListWidget):
    """Список заметок; на карточках — звезда избранного, восстановление (в корзине)
    и крестик удаления."""

    note_delete_requested = Signal(str)    # note_id
    note_restore_requested = Signal(str)   # note_id — вернуть из корзины
    note_star_requested = Signal(str)      # note_id — переключить «избранное»
    notes_reordered = Signal(list)         # list[str] — новый порядок note_id после перетаскивания

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('notes_list')
        self.setMouseTracking(True)
        self._swallow_mouse = False
        # перетаскивание заметок друг относительно друга (не выделяет всё при движении мыши)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def select_single_row(self, row: int):
        """Чётко выделяет ровно одну строку (или снимает выделение при row < 0),
        без накопления лишних выделений от ExtendedSelection."""
        self.clearSelection()
        if 0 <= row < self.count():
            self.setCurrentRow(
                row,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Current,
            )
        else:
            self.setCurrentRow(-1)

    def mousePressEvent(self, event):
        it = self.itemAt(event.position().toPoint())
        if it is not None:
            pos = event.position().toPoint()
            note = it.data(NOTE_ROLE)
            if note and self._in_star_zone(it, pos):
                self._swallow_mouse = True
                self.note_star_requested.emit(note['id'])
                return
            if note and self._in_restore_zone(it, pos):
                self._swallow_mouse = True
                self.note_restore_requested.emit(note['id'])
                return
            if note and self._in_delete_zone(it, pos):
                self._swallow_mouse = True
                self.note_delete_requested.emit(note['id'])
                return
        self._swallow_mouse = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._swallow_mouse:
            return
        pos = event.position().toPoint()
        it = self.itemAt(pos)
        on_action = False
        if it is not None:
            note = it.data(NOTE_ROLE)
            if note and (self._in_star_zone(it, pos)
                         or self._in_restore_zone(it, pos)
                         or self._in_delete_zone(it, pos)):
                on_action = True
        if on_action:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._swallow_mouse:
            self._swallow_mouse = False
            return
        super().mouseReleaseEvent(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ToolTip:
            pos = event.pos()
            it = self.itemAt(pos)
            if it is not None:
                note = it.data(NOTE_ROLE)
                if note:
                    tip = ''
                    if self._in_restore_zone(it, pos):
                        tip = 'Восстановить из корзины'
                    elif self._in_delete_zone(it, pos):
                        tip = 'Удалить навсегда' if note.get('deleted') else 'Переместить в корзину'
                    elif self._in_star_zone(it, pos):
                        tip = 'Открепить' if note.get('pinned') else 'Закрепить сверху'
                    if tip:
                        QToolTip.showText(event.globalPos(), tip, self)
                        return True
            QToolTip.hideText()
        return super().viewportEvent(event)

    def _in_star_zone(self, item, pos) -> bool:
        note = item.data(NOTE_ROLE)
        if note and note.get('deleted'):
            return False
        delegate = self.itemDelegate()
        if not isinstance(delegate, NoteDelegate):
            return False
        r = self.visualItemRect(item)
        if delegate.mode == 'card':
            # звезда СЛЕВА, на уровне строки заголовка
            zone = QRect(r.left() + 8, r.top() + 5, 22, 24)
            return zone.contains(pos)
        # список: звезда у левого края, вся высота строки
        zone = QRect(r.left() + 8, r.top(), 20, r.height())
        return zone.contains(pos)

    def _in_restore_zone(self, item, pos) -> bool:
        note = item.data(NOTE_ROLE)
        if not note or not note.get('deleted'):
            return False
        delegate = self.itemDelegate()
        if not isinstance(delegate, NoteDelegate):
            return False
        r = self.visualItemRect(item)
        if delegate.mode == 'card':
            zone = QRect(r.right() - 52, r.top() + 5, 23, 24)
            return zone.contains(pos)
        if delegate.mode == 'list':
            zone = QRect(r.right() - 30, r.top(), 24, r.height())
            return zone.contains(pos)
        return False

    def _in_delete_zone(self, item, pos) -> bool:
        delegate = self.itemDelegate()
        if not isinstance(delegate, NoteDelegate):
            return False
        r = self.visualItemRect(item)
        if delegate.mode == 'card':
            # крестик СПРАВА, на уровне строки заголовка
            zone = QRect(r.right() - 30, r.top() + 5, 24, 24)
            return zone.contains(pos)
        return False

    def dropEvent(self, event):
        super().dropEvent(event)
        ids = []
        for i in range(self.count()):
            note = self.item(i).data(NOTE_ROLE)
            if note and note.get('id'):
                ids.append(note['id'])
        if ids:
            self.notes_reordered.emit(ids)


class FindBar(QWidget):
    """Компактная полоска поиска внутри открытой заметки (Ctrl+Shift+F)."""

    def __init__(self, editor: NoteEditor, parent=None):
        super().__init__(parent)
        self._editor = editor
        self._matches = []
        self._idx = -1
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 3, 10, 3)
        lay.setSpacing(4)
        self.input = QLineEdit()
        self.input.setPlaceholderText('Найти в заметке… (Enter - далее, Esc - закрыть)')
        self.input.setClearButtonEnabled(True)
        self.lbl_count = QLabel('')
        self.lbl_count.setMinimumWidth(68)
        self.lbl_count.setAlignment(Qt.AlignCenter)
        self.btn_prev = QToolButton()
        self.btn_prev.setText('▲')
        self.btn_prev.setToolTip('Предыдущее совпадение (Shift+Enter)')
        self.btn_prev.setFixedSize(24, 24)
        self.btn_next = QToolButton()
        self.btn_next.setText('▼')
        self.btn_next.setToolTip('Следующее совпадение (Enter)')
        self.btn_next.setFixedSize(24, 24)
        self.btn_close = QToolButton()
        self.btn_close.setText('×')
        self.btn_close.setToolTip('Закрыть поиск (Esc)')
        self.btn_close.setFixedSize(24, 24)
        lay.addWidget(self.input, 1)
        lay.addWidget(self.lbl_count)
        lay.addWidget(self.btn_prev)
        lay.addWidget(self.btn_next)
        lay.addWidget(self.btn_close)

        self.input.textChanged.connect(self._on_query)
        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_next.clicked.connect(lambda: self.step(+1))
        self.btn_close.clicked.connect(self.close_bar)
        self.input.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.close_bar()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.step(-1)
                else:
                    self.step(+1)
                return True
        return super().eventFilter(obj, event)

    def open_bar(self, initial: str = ''):
        self.show()
        if initial:
            self.input.setText(initial)
        self.input.setFocus()
        self.input.selectAll()
        self._on_query(self.input.text())

    def close_bar(self):
        self.hide()
        self._matches = []
        self._idx = -1
        self._editor.clear_search_highlights()
        self._editor.setFocus()

    def _on_query(self, text: str):
        self._matches = self._editor.highlight_search(text, 0 if text.strip() else -1)
        if not text.strip():
            self._idx = -1
            self.lbl_count.setText('')
        elif not self._matches:
            self._idx = -1
            self.lbl_count.setText('0 из 0')
        else:
            self._idx = 0
            self.lbl_count.setText(f'1 из {len(self._matches)}')

    def step(self, delta: int):
        q = self.input.text().strip()
        if not q:
            return
        if not self._matches:
            self._matches = self._editor.highlight_search(q, 0)
        if not self._matches:
            self.lbl_count.setText('0 из 0')
            return
        self._idx = (self._idx + delta) % len(self._matches)
        self._editor.highlight_search(q, self._idx)
        self.lbl_count.setText(f'{self._idx + 1} из {len(self._matches)}')


class MainWindow(QMainWindow):
    request_new_note = Signal()   # от глобального хоткея
    webdav_sync_done = Signal(object, str)  # (result_dict_or_None, error_str)

    def __init__(self, store, theme_mgr, hotkey, parent=None):
        super().__init__(parent)
        self.store = store
        self.theme = theme_mgr
        self.hotkey = hotkey
        self.current = None          # открытая заметка
        self._colorful_btns = []
        self._last_theme_text = None   # нормализация цвета — только при смене темы
        self._filter_color = ''        # активный фильтр по цветной метке
        self._filter_tag = ''          # активный фильтр по #тегу
        self._focus_mode = False
        self._saved_splitter_sizes = None
        self.setWindowTitle('Заметки')
        self.setWindowIcon(QIcon(paint_app_icon()))
        self._build_ui()
        self._build_tray()
        self._wire()
        self.theme.changed.connect(self._on_theme)
        self._on_theme(self.theme.colors)
        self.editor.set_store(self.store)
        self.editor.files_dropped.connect(self._import_paths)
        self._show_trash = False
        self.rebuild_notes()
        self._apply_view(self.store.setting('view', 'card'))
        self._apply_lang()
        self.phone = None
        self._phone_apply(self.store.setting('phone', False))
        self.reminders = ReminderEngine(self.store, self._notify_reminder, self)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self.rebuild_notes)
        self._stats_timer = QTimer(self)
        self._stats_timer.setSingleShot(True)
        self._stats_timer.setInterval(400)
        self._stats_timer.timeout.connect(self._update_footer)
        self.request_new_note.connect(lambda: (self.restore_and_activate(), self.new_note()))
        self.webdav_sync_done.connect(self._on_webdav_sync_done)
        QTimer.singleShot(1500, self._run_auto_purge_trash)
        QTimer.singleShot(3000, lambda: backup.run_daily_async(self.store.root))

    def _run_auto_purge_trash(self):
        if self.store.setting('auto_purge_trash', False):
            purged = self.store.purge_expired_trash(30)
            if purged:
                self.rebuild_notes()

    def _notify_reminder(self, title: str, text: str):
        if self._tray_ok and self.tray.isVisible():
            self.tray.showMessage(title, text, QIcon(paint_app_icon()), 10000)
        else:
            QMessageBox.information(self, 'Напоминание: ' + title, text)

    # ================= UI =================
    def _build_ui(self):
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # --- панель списка ---
        self.list_pane = QWidget()
        lv = QVBoxLayout(self.list_pane)
        lv.setContentsMargins(0, 6, 0, 0)
        lv.setSpacing(5)
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 0, 8, 0)
        bar.setSpacing(4)
        # две пиктограммы вместо бокового меню папок: Заметки и Удалённые
        # (первые три кнопки крупнее остальных — основные действия)
        self.btn_notes_scope = QToolButton()
        self.btn_notes_scope.setCheckable(True)
        self.btn_notes_scope.setToolTip('Все заметки')
        self.btn_notes_scope.setIconSize(QSize(20, 20))
        self.btn_trash_scope = QToolButton()
        self.btn_trash_scope.setCheckable(True)
        self.btn_trash_scope.setToolTip('Недавно удалённые')
        self.btn_trash_scope.setIconSize(QSize(20, 20))
        self.btn_compose = QToolButton()
        self.btn_compose.setToolTip('Новая заметка (Ctrl+N)')
        self.btn_compose.setIconSize(QSize(20, 20))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Поиск')
        self.search.setClearButtonEnabled(True)
        self.btn_view = QToolButton()
        self.btn_view.setToolTip('Вид списка — переключение по кругу')
        self.btn_view.setIconSize(QSize(16, 16))
        bar.addWidget(self.btn_notes_scope)
        bar.addWidget(self.btn_trash_scope)
        bar.addSpacing(8)
        bar.addWidget(self.btn_compose)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.btn_view)
        lv.addLayout(bar)
        # компактная полоска фильтров по цвету и #тегам
        flt_bar = QHBoxLayout()
        flt_bar.setContentsMargins(10, 0, 10, 0)
        flt_bar.setSpacing(3)
        self._color_filter_btns = {}
        btn_all = QToolButton()
        btn_all.setText('Все')
        btn_all.setCheckable(True)
        btn_all.setChecked(True)
        btn_all.setToolTip('Показать все заметки (сбросить фильтр)')
        btn_all.setFixedHeight(20)
        btn_all.clicked.connect(self._clear_filters)
        self._color_filter_btns[''] = btn_all
        flt_bar.addWidget(btn_all)
        for hex_, name in COLORS[1:]:
            cb = QToolButton()
            cb.setCheckable(True)
            cb.setIcon(chip_icon(11, hex_))
            cb.setIconSize(QSize(11, 11))
            cb.setFixedSize(20, 20)
            cb.setToolTip(f'Фильтр по метке: {name}')
            cb.clicked.connect(lambda _=False, h=hex_: self._toggle_color_filter(h))
            self._color_filter_btns[hex_] = cb
            flt_bar.addWidget(cb)
        flt_bar.addStretch(1)
        self.btn_tag_filter = QToolButton()
        self.btn_tag_filter.setText('# Теги')
        self.btn_tag_filter.setToolTip('Фильтр по #тегам из текста заметок')
        self.btn_tag_filter.setFixedHeight(20)
        self.btn_tag_filter.clicked.connect(self._open_tag_menu)
        flt_bar.addWidget(self.btn_tag_filter)
        lv.addLayout(flt_bar)
        self.notes_list = NotesList()
        self.notes_list.setItemDelegate(NoteDelegate(lambda: self.theme.colors))
        self.notes_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        # ExtendedSelection: Shift — диапазон, Ctrl — по одной, Ctrl+A — все
        self.notes_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.notes_list.notes_reordered.connect(self._on_notes_reordered)
        lv.addWidget(self.notes_list, 1)
        # строка статуса: количество заметок под стикерами
        self.status_label = QLabel()
        self.status_label.setFont(QFont('Segoe UI', 8))
        self.status_label.setContentsMargins(14, 2, 8, 4)
        lv.addWidget(self.status_label)

        # --- редактор ---
        self.editor_pane = QWidget()
        ev = QVBoxLayout(self.editor_pane)
        ev.setContentsMargins(0, 6, 0, 0)
        ev.setSpacing(4)
        fmt_bar = QHBoxLayout()
        fmt_bar.setContentsMargins(10, 2, 10, 2)
        fmt_bar.setSpacing(3)
        # кнопка режима фокуса (скрыть/показать список заметок)
        self.btn_focus = QToolButton()
        self.btn_focus.setCheckable(True)
        self.btn_focus.setToolTip('Режим фокуса - скрыть/показать список заметок (Ctrl+\\)')
        self.btn_focus.setIconSize(QSize(16, 16))
        self.btn_focus.setFixedSize(26, 26)
        self.btn_focus.clicked.connect(self.toggle_focus_mode)
        fmt_bar.addWidget(self.btn_focus)
        self.fmt_toolbar = ResponsiveToolbar(self._build_overflow_menu)
        self.fmt_buttons = {}
        # буквы с начертанием — «залипающие», состояние следует за курсором
        for key, tip in (('bold', 'Полужирный (Ctrl+B)'),
                         ('italic', 'Курсив (Ctrl+I)'),
                         ('under', 'Подчёркнутый (Ctrl+U)'),
                         ('strike', 'Зачёркнутый')):
            b = QToolButton()
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setIconSize(QSize(16, 16))
            self.fmt_buttons[key] = b
            self.fmt_toolbar.add_item(b)
        self.fmt_toolbar.add_item(_vline(), is_sep=True)
        # списки — мгновенные действия, не залипают
        for key, tip in (('bullet', 'Маркированный список'),
                         ('numbered', 'Нумерованный список'),
                         ('check', 'Чек-лист (Ctrl+Shift+C)')):
            b = QToolButton()
            b.setToolTip(tip)
            b.setCheckable(False)
            b.setIconSize(QSize(16, 16))
            self.fmt_buttons[key] = b
            self.fmt_toolbar.add_item(b)
        self.fmt_toolbar.add_item(_vline(), is_sep=True)
        # выравнивание — мгновенные действия
        for key, tip in (('alignL', 'По левому краю'),
                         ('alignC', 'По центру'),
                         ('alignR', 'По правому краю')):
            b = QToolButton()
            b.setToolTip(tip)
            b.setCheckable(False)
            b.setIconSize(QSize(16, 16))
            self.fmt_buttons[key] = b
            self.fmt_toolbar.add_item(b)
        self.fmt_toolbar.add_item(_vline(), is_sep=True)
        # картинки, маркер, цвет — прямо на панели (функция «Заголовок» убрана:
        # первая строка заметки и так всегда оформляется как заголовок)
        self.btn_image = QToolButton()
        self.btn_image.setToolTip('Вставить изображение (или Ctrl+V / перетащите файл). Ссылки в тексте распознаются сами')
        self.btn_marker = QToolButton()
        self.btn_marker.setToolTip('Выделение маркером')
        self.btn_marker.setPopupMode(QToolButton.InstantPopup)
        self.btn_marker.setMenu(self._marker_menu())
        self.btn_textcolor = QToolButton()
        self.btn_textcolor.setToolTip('Цвет текста')
        self.btn_textcolor.setPopupMode(QToolButton.InstantPopup)
        self.btn_textcolor.setMenu(self._textcolor_menu())
        for b in (self.btn_image, self.btn_marker, self.btn_textcolor):
            b.setIconSize(QSize(16, 16))
            self.fmt_toolbar.add_item(b)
        # размер текста — как в Word: окошко с выпадающими цифрами
        from PySide6.QtGui import QIntValidator
        self.size_combo = QComboBox()
        self.size_combo.setEditable(True)
        self.size_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.size_combo.setToolTip('Размер текста (у выделенного или у следующего ввода)')
        for idx, s in enumerate((8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36)):
            self.size_combo.addItem(str(s))
            self.size_combo.setItemData(idx, QSize(0, 22), Qt.ItemDataRole.SizeHintRole)
        self.size_combo.setMaxVisibleItems(12)
        # симметричная форма: значение по центру, стрелка видна, все цифры влезают
        self.size_combo.setFixedWidth(64)
        self._apply_size_combo_style(False)
        self.size_combo.lineEdit().setAlignment(Qt.AlignCenter)
        self.size_combo.lineEdit().setValidator(QIntValidator(6, 40, self))
        self.size_combo.activated.connect(self._size_combo_applied)
        self.size_combo.lineEdit().returnPressed.connect(self._size_combo_applied)
        self.fmt_toolbar.add_item(self.size_combo)
        fmt_bar.addWidget(self.fmt_toolbar, 1)
        # тема, папка, экспорт и «···» закреплены справа и никогда не сжимаются
        self.btn_theme = QToolButton()
        self.btn_theme.setToolTip('Тема: светлая (клик переключает светлая - тёмная - как в Windows)')
        self.btn_theme.setIconSize(QSize(16, 16))
        self.btn_theme.setFixedSize(26, 26)
        self.btn_theme.clicked.connect(self._cycle_theme)
        fmt_bar.addWidget(self.btn_theme)
        self.btn_folder = QToolButton()
        self.btn_folder.setToolTip('Открыть папку заметок')
        self.btn_folder.setIconSize(QSize(16, 16))
        self.btn_folder.setFixedSize(26, 26)
        self.btn_folder.clicked.connect(self._open_data_folder)
        fmt_bar.addWidget(self.btn_folder)
        # отдельная кнопка «Экспорт» в верхнем меню (PDF/HTML/TXT/Markdown)
        self.btn_export = QToolButton()
        self.btn_export.setToolTip('Экспорт заметки — PDF, HTML, TXT, Markdown')
        self.btn_export.setIconSize(QSize(16, 16))
        self.btn_export.setFixedSize(26, 26)
        fmt_bar.addWidget(self.btn_export)
        self.btn_more = QToolButton()
        self.btn_more.setText('···')
        self.btn_more.setFixedSize(26, 26)
        self.btn_more.setToolTip('Ещё: убрать форматирование, импорт, экспорт, история версий, настройки')
        fmt_bar.addWidget(self.btn_more)
        self.editor = NoteEditor(lambda: self.theme.colors)
        self.find_bar = FindBar(self.editor)
        # плашка происхождения заметки (от кого / с какого ПК / когда) с кнопкой очистки
        self.origin_bar = QWidget()
        ob = QHBoxLayout(self.origin_bar)
        ob.setContentsMargins(14, 3, 10, 3)
        ob.setSpacing(6)
        self.lbl_origin = QLabel('')
        self.lbl_origin.setFont(QFont('Segoe UI', 8.5))
        self.btn_clear_origin = QToolButton()
        self.btn_clear_origin.setText('×')
        self.btn_clear_origin.setToolTip('Очистить информацию об источнике заметки')
        self.btn_clear_origin.setFixedSize(20, 20)
        self.btn_clear_origin.clicked.connect(self._clear_note_origin)
        ob.addWidget(self.lbl_origin, 1)
        ob.addWidget(self.btn_clear_origin)
        self.origin_bar.hide()

        self.editor_footer = QLabel('')
        self.editor_footer.setFont(QFont('Segoe UI', 8))
        self.editor_footer.setContentsMargins(14, 2, 14, 4)
        ev.addLayout(fmt_bar)
        ev.addWidget(self.find_bar)
        ev.addWidget(self.origin_bar)
        ev.addWidget(self.editor, 1)
        ev.addWidget(self.editor_footer)

        self.splitter = splitter
        splitter.addWidget(self.list_pane)
        splitter.addWidget(self.editor_pane)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 720])
        # колонки не должны сжиматься в ноль и не восстанавливаться при растяжении окна
        self.list_pane.setMinimumWidth(270)
        self.editor_pane.setMinimumWidth(340)
        root.addWidget(splitter)
        self.setCentralWidget(central)
        self.resize(1050, 640)
        self._restore_geometry()

        # горячие клавиши окна
        for seq, slot in (('Ctrl+N', self.new_note), ('Ctrl+F', self.search.setFocus),
                          ('Ctrl+Shift+F', self.open_find_in_note),
                          ('Ctrl+K', self.open_command_palette),
                          ('Ctrl+\\', self.toggle_focus_mode),
                          ('Ctrl+Shift+V', self.editor.paste_plain),
                          ('Ctrl+Shift+M', self.editor.toggle_code_block),
                          ('Ctrl+B', lambda: self._fmt('bold')), ('Ctrl+I', lambda: self._fmt('italic')),
                          ('Ctrl+U', lambda: self._fmt('under')), ('Ctrl+Shift+C', self.editor.toggle_checklist),
                          ('Ctrl+]', lambda: self._change_font_size(+1)),
                          ('Ctrl+[', lambda: self._change_font_size(-1)),
                          ('Ctrl+Q', self._quit)):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(slot)
        sc_del = QShortcut(QKeySequence(Qt.Key_Delete), self.notes_list)
        sc_del.setContext(Qt.WidgetWithChildrenShortcut)
        sc_del.activated.connect(self._delete_via_key)

    def restore_and_activate(self):
        """Показывает и активирует главное окно из трея, свёрнутого или фонового состояния."""
        if not self.isVisible():
            self.show()
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
            if self.isMaximized():
                self.showMaximized()
            else:
                self.showNormal()
        self.raise_()
        self.activateWindow()

    def _build_tray(self):
        self.tray = QSystemTrayIcon(QIcon(paint_app_icon()), self)
        menu = QMenu()
        act_show = menu.addAction('Открыть Заметки')
        act_show.triggered.connect(self.restore_and_activate)
        act_new = menu.addAction('Новая заметка')
        act_new.triggered.connect(lambda: (self.restore_and_activate(), self.new_note()))
        menu.addSeparator()
        act_quit = menu.addAction('Выход')
        act_quit.triggered.connect(self._quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip('Заметки')
        self.tray.activated.connect(
            lambda reason: self.restore_and_activate() if reason == QSystemTrayIcon.Trigger else None)
        self._tray_ok = QSystemTrayIcon.isSystemTrayAvailable()
        if self._tray_ok:
            self.tray.show()

    # ================= сборка меню =================
    def _editor_menu(self, pos):
        menu = self._build_editor_menu(pos)
        menu.exec(self.editor.viewport().mapToGlobal(pos))

    def _build_editor_menu(self, pos=None) -> QMenu:
        """Контекстное меню редактора в стиле Word: форматирование под рукой."""
        from PySide6.QtGui import QFont as _QFont
        menu = QMenu(self)
        if pos is not None and self.editor.image_scale_actions(menu, pos):
            menu.addSeparator()   # правый клик по картинке: сначала её размер
        act_undo = menu.addAction('Отменить\tCtrl+Z', self.editor.undo)
        act_undo.setEnabled(self.editor.document().isUndoAvailable())
        act_redo = menu.addAction('Вернуть\tCtrl+Shift+Z', self.editor.redo)
        act_redo.setEnabled(self.editor.document().isRedoAvailable())
        menu.addSeparator()
        cursor = self.editor.textCursor()
        act_copy = menu.addAction('Копировать', self.editor.copy)
        act_copy.setEnabled(cursor.hasSelection())
        menu.addAction('Вставить', self.editor.paste)
        menu.addAction('Вставить без форматирования\tCtrl+Shift+V', self.editor.paste_plain)
        menu.addSeparator()

        cf = cursor.charFormat()
        bold_now = cf.fontWeight() >= _QFont.Weight.Bold

        def add(text, slot, shortcut='', checked=False):
            act = menu.addAction(text + ('\t' + shortcut if shortcut else ''))
            act.triggered.connect(slot)
            if checked is not None:
                act.setCheckable(True)
                act.setChecked(checked)
            return act

        add('Полужирный', self.toggle_bold, 'Ctrl+B', bold_now)
        add('Курсив', self.toggle_italic, 'Ctrl+I', cf.fontItalic())
        add('Подчёркнутый', self.toggle_under, 'Ctrl+U', cf.fontUnderline())
        add('Зачёркнутый', self.toggle_strike, '', cf.fontStrikeOut())
        add('Код / моноширинный', self.editor.toggle_code_block, 'Ctrl+Shift+M', None)
        menu.addSeparator()
        in_list = cursor.currentList() is not None
        add('Маркированный список', self.toggle_bullets, '', in_list)
        add('Нумерованный список', self.toggle_numbered, '', None)
        add('Чек-лист', self.editor.toggle_checklist, 'Ctrl+Shift+C', False)
        menu.addSeparator()
        add('По левому краю', self.align_left, '', None)
        add('По центру', self.align_center, '', None)
        add('По правому краю', self.align_right, '', None)
        menu.addSeparator()
        menu.addMenu(self._textcolor_menu())
        menu.addMenu(self._marker_menu())
        menu.addSeparator()
        add('Вставить изображение…', self.editor.insert_from_file, '', None)
        add('Убрать форматирование', self.editor.clear_extra_format, '', None)
        menu.addSeparator()
        add('Выделить всё', self.editor.selectAll, 'Ctrl+A', None)
        return menu

    def _apply_view(self, mode):
        """Вид списка заметок: card (крупный перечень) / list (список).
        Виды «Таблица» и «Галерея» убраны."""
        from PySide6.QtWidgets import QListView
        mode = mode if mode in ('card', 'list') else 'card'
        self._view_mode = mode
        self.store.set_setting('view', mode)
        delegate = self.notes_list.itemDelegate()
        if isinstance(delegate, NoteDelegate):
            delegate.mode = mode
        # после удалённых «галереи/таблицы» ОБЯЗАТЕЛЬНО сбрасываем сетку:
        # оставшийся gridSize давал огромные промежутки и горизонтальный бегунок
        self.notes_list.setFlow(QListView.Flow.TopToBottom)
        self.notes_list.setWrapping(False)
        self.notes_list.setGridSize(QSize())
        self.notes_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.notes_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._on_theme(self.theme.colors)
        self.notes_list.viewport().update()

    def _cycle_view(self):
        order = ('card', 'list')
        idx = order.index(getattr(self, '_view_mode', 'card'))
        self._apply_view(order[(idx + 1) % len(order)])

    def _apply_size_combo_style(self, dark: bool):
        arrow_name = 'down_arrow_dark.svg' if dark else 'down_arrow.svg'
        arrow = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'icons_svg', arrow_name).replace('\\', '/')
        self.size_combo.setStyleSheet(
            'QComboBox { padding: 2px 2px 2px 6px; }'
            'QComboBox::drop-down { border: none; width: 18px; }'
            f'QComboBox::down-arrow {{ image: url({arrow}); width: 10px; height: 6px; }}'
            'QComboBox QAbstractItemView::item { min-height: 22px; }')

    def _build_overflow_menu(self, hidden_widgets) -> QMenu:
        """Меню скрытых инструментов панели при узком редакторе."""
        menu = QMenu(self)
        labels = {
            self.fmt_buttons['bold']: 'Полужирный (Ctrl+B)',
            self.fmt_buttons['italic']: 'Курсив (Ctrl+I)',
            self.fmt_buttons['under']: 'Подчёркнутый (Ctrl+U)',
            self.fmt_buttons['strike']: 'Зачёркнутый',
            self.fmt_buttons['bullet']: 'Маркированный список',
            self.fmt_buttons['numbered']: 'Нумерованный список',
            self.fmt_buttons['check']: 'Чек-лист (Ctrl+Shift+C)',
            self.fmt_buttons['alignL']: 'По левому краю',
            self.fmt_buttons['alignC']: 'По центру',
            self.fmt_buttons['alignR']: 'По правому краю',
            self.btn_image: 'Вставить изображение…',
        }
        for w in hidden_widgets:
            if w is self.btn_marker:
                sub = self._marker_menu()
                sub.setIcon(w.icon())
                menu.addMenu(sub)
            elif w is self.btn_textcolor:
                sub = self._textcolor_menu()
                sub.setIcon(w.icon())
                menu.addMenu(sub)
            elif w is self.size_combo:
                cur_sz = int(round(self.editor.current_font_size()))
                sub = menu.addMenu(f'Размер текста ({cur_sz} pt)')
                for s in (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36):
                    act = sub.addAction(str(s), lambda sz=s: self.editor.set_font_size(sz))
                    act.setCheckable(True)
                    act.setChecked(s == cur_sz)
            elif isinstance(w, QToolButton):
                act = menu.addAction(w.icon(), labels.get(w, w.toolTip() or w.text()))
                if w.isCheckable():
                    act.setCheckable(True)
                    act.setChecked(w.isChecked())
                act.triggered.connect(w.click)
        return menu

    def _marker_menu(self) -> QMenu:
        dark = is_dark_theme(self.theme.colors)
        palette = (('Жёлтый', '#6B5900'), ('Зелёный', '#1F5432'), ('Розовый', '#6B2848')) if dark else (
            ('Жёлтый', '#FFE680'), ('Зелёный', '#C6F6D5'), ('Розовый', '#FFD6E8'))
        m = QMenu(self)
        m.setTitle('Маркер')
        m.setToolTip('Выделение маркером')
        for name, hex_ in (*palette, ('Убрать выделение', 'transparent')):
            act = m.addAction(name)
            act.triggered.connect(lambda _=False, h=hex_: self.editor.set_highlight(QColor(h)))
            if hex_ != 'transparent':
                act.setIcon(chip_icon(12, hex_))
        return m

    def _textcolor_menu(self) -> QMenu:
        m = QMenu(self)
        m.setTitle('Цвет текста')
        for name, hex_ in (('Обычный', None), ('Красный', '#E5484D'), ('Оранжевый', '#FF9F0A'),
                           ('Синий', '#3B82F6'), ('Зелёный', '#30A46C'), ('Серый', '#8A8F98')):
            if hex_ is None:
                act = m.addAction(name, lambda: self.editor.reset_text_color())
            else:
                act = m.addAction(name, lambda h=hex_: self.editor.set_text_color(QColor(h)))
                act.setIcon(chip_icon(12, hex_))
        return m

    def _size_combo_applied(self):
        try:
            size = float(self.size_combo.lineEdit().text().replace(',', '.'))
        except ValueError:
            return
        self.editor.set_font_size(min(40, max(6, size)))

    def _change_font_size(self, step: int):
        size = self.editor.current_font_size()
        self.editor.set_font_size(min(40, max(6, round((size + step) * 2) / 2)))

    def _lang(self) -> str:
        return i18n.normalize_lang(self.store.setting('lang', 'ru'))

    def _tr(self, key: str, **kwargs) -> str:
        return i18n.tr(key, self._lang(), **kwargs)

    def _apply_lang(self):
        self.setWindowTitle(self._tr('app_title'))
        self.btn_notes_scope.setToolTip(self._tr('all_notes'))
        self.btn_trash_scope.setToolTip(self._tr('trash'))
        self.btn_compose.setToolTip(self._tr('new_note_tip'))
        self.search.setPlaceholderText(self._tr('search_ph'))
        self._color_filter_btns[''].setText(self._tr('filter_all'))
        self._color_filter_btns[''].setToolTip(self._tr('filter_all_tip'))
        if not self._filter_tag:
            self.btn_tag_filter.setText(self._tr('tags_btn'))
        self.btn_tag_filter.setToolTip(self._tr('tags_tip'))
        self.btn_focus.setToolTip(self._tr('focus_tip'))
        self.find_bar.input.setPlaceholderText(self._tr('find_ph'))
        self._update_pages()
        self._update_footer()

    def _more_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction(self._tr('clear_format'), self.editor.clear_extra_format)
        menu.addSeparator()
        menu.addAction(self._tr('import_file'), self._import)
        menu.addAction(self._tr('export_share'), self._export_current)
        menu.addAction('Показать QR-код заметки…' if self._lang() == 'ru' else 'Show note QR code…',
                       lambda: self.current and self._show_note_qr(self.current))
        menu.addAction(self._tr('versions'), self._show_versions)
        if self.store.setting('webdav_url', ''):
            menu.addAction(self._tr('sync_webdav'), self._sync_webdav_now)
        menu.addSeparator()
        menu.addAction(self._tr('settings'), self._open_settings)
        menu.addSeparator()
        menu.addAction(self._tr('quit'), self._quit)
        return menu

    def _cycle_theme(self):
        """День → ночь → как в Windows → день."""
        order = ('light', 'dark', 'system')
        current = getattr(self.theme, 'mode', 'light')
        if current not in order:
            current = 'light'
        self._apply_theme_mode(order[(order.index(current) + 1) % len(order)])

    def _apply_theme_mode(self, mode: str):
        """Смена темы: светлая (день) / тёмная (ночь) / как в Windows."""
        mode = mode if mode in ('light', 'dark', 'system') else 'system'
        self.store.set_setting('theme', mode)
        self.theme.set_mode(mode)

    def _open_data_folder(self):
        """Папка, где сейчас хранятся заметки, в Проводнике."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.store.root + os.sep))

    def _note_menu(self, note) -> QMenu:
        menu = QMenu(self)
        if note['deleted']:
            menu.addAction('Восстановить', lambda: self.restore_note(note))
            menu.addAction('Удалить навсегда', lambda: self.purge_note(note))
            return menu
        pin_name = 'Открепить' if note.get('pinned') else 'Закрепить'
        menu.addAction(pin_name, lambda: self.toggle_pin(note))
        menu.addAction('Дублировать', lambda: self.duplicate_note(note))
        sub = menu.addMenu('Цветная метка')
        for hex_, name in COLORS:
            act = sub.addAction(('● ' if note.get('color') == hex_ else '    ') + name)
            act.triggered.connect(lambda _=False, h=hex_: self.set_color(note, h))
        sub_r = menu.addMenu('Напоминание')
        sub_r.addAction('Через час', lambda: self.set_reminder(note, hours=1))
        sub_r.addAction('Завтра в 9:00', lambda: self.set_reminder(note, tomorrow9=True))
        sub_r.addAction('Выбрать дату и время…', lambda: self._remind_dialog(note))
        if note.get('reminder_at'):
            sub_r.addAction('Отменить напоминание', lambda: self.set_reminder(note, clear=True))
        menu.addSeparator()
        menu.addAction('Экспорт…', lambda: (self.editor.flush(), export_note(self, self.store.notes.get(note['id'], note))))
        menu.addAction('Показать QR-код заметки…', lambda: self._show_note_qr(note))
        menu.addAction('История версий…', self._show_versions)
        menu.addAction('Переместить в корзину', lambda: self.trash_note(note))
        if self._show_trash:
            menu.addSeparator()
            menu.addAction('Очистить корзину', self._empty_trash)
        return menu

    # ================= обработчики =================
    def _wire(self):
        self.btn_notes_scope.clicked.connect(lambda: self._set_scope(False))
        self.btn_trash_scope.clicked.connect(lambda: self._set_scope(True))
        self.btn_compose.clicked.connect(self.new_note)
        self.btn_view.clicked.connect(self._cycle_view)
        self.search.textChanged.connect(self._on_search)
        self.btn_more.clicked.connect(
            lambda: (self._more_menu().exec(self.btn_more.mapToGlobal(self.btn_more.rect().bottomLeft()))))
        fmt_slots = {
            'bold': self.toggle_bold, 'italic': self.toggle_italic,
            'under': self.toggle_under, 'strike': self.toggle_strike,
            'bullet': self.toggle_bullets, 'numbered': self.toggle_numbered,
            'check': self.editor.toggle_checklist,
            'alignL': self.align_left, 'alignC': self.align_center, 'alignR': self.align_right,
        }
        for key, slot in fmt_slots.items():
            self.fmt_buttons[key].clicked.connect(slot)
        self.btn_image.clicked.connect(self.editor.insert_from_file)
        self.btn_export.clicked.connect(self._export_current)
        self.notes_list.currentRowChanged.connect(self._on_note_row)
        self.notes_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.notes_list.customContextMenuRequested.connect(self._note_menu_at)
        self.editor.save_requested.connect(self._on_note_saved)
        self.editor.textChanged.connect(self._sync_fmt_buttons)
        self.editor.textChanged.connect(lambda: self._stats_timer.start())
        self.editor.cursorPositionChanged.connect(self._sync_fmt_buttons)
        self.editor.currentCharFormatChanged.connect(lambda *_: self._sync_fmt_buttons())
        self.notes_list.note_delete_requested.connect(self._on_cross_delete)
        self.notes_list.note_restore_requested.connect(self._on_restore_click)
        self.notes_list.note_star_requested.connect(self._on_star_click)
        self.editor.setContextMenuPolicy(Qt.CustomContextMenu)
        self.editor.customContextMenuRequested.connect(self._editor_menu)

    # --- форматирование ---
    def _fmt(self, key):
        """Кнопки Ж/К/Ч/З. С выделением — логика Word по ВСЕМ символам выделения:
        свойство у всех включено → снять, иначе → включить. Повторный клик
        всегда снимает только что применённое. Без выделения — «липкий»
        формат ввода. Раньше состояние читалось по одному СОСЕДНЕМУ символу
        (charFormat() при выделении), из-за чего кнопка могла применить
        формат дважды и никогда его не снять."""
        from PySide6.QtGui import QFont, QTextCharFormat
        getters = {
            'bold': lambda f: f.fontWeight() >= QFont.Weight.Bold,
            'italic': lambda f: f.fontItalic(),
            'under': lambda f: f.fontUnderline(),
            'strike': lambda f: f.fontStrikeOut(),
        }
        setters = {
            'bold': (lambda fmt, v: fmt.setFontWeight(
                QFont.Weight.Bold if v else QFont.Weight.Normal)),
            'italic': (lambda fmt, v: fmt.setFontItalic(v)),
            'under': (lambda fmt, v: fmt.setFontUnderline(v)),
            'strike': (lambda fmt, v: fmt.setFontStrikeOut(v)),
        }
        tc = self.editor.textCursor()
        if tc.hasSelection():
            fmts = self.editor.selection_char_formats(tc)
            all_on = bool(fmts) and all(getters[key](f) for f in fmts)
            fmt = QTextCharFormat()
            setters[key](fmt, not all_on)
            tc.mergeCharFormat(fmt)
        else:
            # «липкий» формат ввода; жирный у заголовка — уже 600 (DemiBold),
            # поэтому порог для каретки — DemiBold, как у состояния кнопки
            cf = self.editor.currentCharFormat()
            cur = (cf.fontWeight() >= QFont.Weight.DemiBold if key == 'bold'
                   else getters[key](cf))
            fmt = QTextCharFormat()
            setters[key](fmt, not cur)
            self.editor.mergeCurrentCharFormat(fmt)
        self.editor.textChanged.emit()

    def toggle_bold(self): self._fmt('bold')
    def toggle_italic(self): self._fmt('italic')
    def toggle_under(self): self._fmt('under')
    def toggle_strike(self): self._fmt('strike')

    def _toggle_list_style(self, list_style):
        """Список для ВСЕХ выделенных строк (или строки с курсором):
        если строки уже в списке того же стиля - снимаем, иначе создаём единый список."""
        from PySide6.QtGui import QTextCursor
        cursor = self.editor.textCursor()
        blocks = self.editor._selected_blocks(cursor)
        if not blocks:
            return
        same_list = any(
            block.textList() is not None and block.textList().format().style() == list_style
            for block in blocks
        )
        self.editor._restyling = True
        cursor.beginEditBlock()
        try:
            tl_new = None
            for block in blocks:
                tl = block.textList()
                if tl is not None:
                    tl.remove(block)
                    bf = block.blockFormat()
                    bf.setIndent(0)
                    bc = QTextCursor(block)
                    bc.mergeBlockFormat(bf)
                if not same_list:
                    bc = QTextCursor(block)
                    bf = block.blockFormat()
                    if (bf.indent() or 0) > 0:
                        bf.setIndent(0)
                        bc.mergeBlockFormat(bf)
                    self.editor.sync_block_bullet_format(block)
                    if tl_new is None:
                        lf = QTextListFormat()
                        lf.setStyle(list_style)
                        lf.setIndent(1)
                        tl_new = bc.createList(lf)
                    else:
                        tl_new.add(block)
        finally:
            cursor.endEditBlock()
            self.editor._restyling = False
        self.editor._dirty = True
        self.editor.textChanged.emit()

    def _toggle_bullets(self):
        self._toggle_list_style(QTextListFormat.Style.ListDisc)

    def toggle_numbered(self):
        self._toggle_list_style(QTextListFormat.Style.ListDecimal)

    toggle_bullets = _toggle_bullets

    def _align(self, which):
        """Выравнивание меняет ТОЛЬКО выравнивание: берём чистый
        QTextBlockFormat с одним свойством, чтобы не переносить на соседние
        строки отступы/списки текущего блока (раньше блок-формат целиком
        «стягивал» строку к отступу нижестоящей)."""
        from PySide6.QtGui import QTextBlockFormat
        cursor = self.editor.textCursor()
        bf = QTextBlockFormat()
        bf.setAlignment({'left': Qt.AlignLeft, 'center': Qt.AlignCenter,
                         'right': Qt.AlignRight}[which])
        cursor.mergeBlockFormat(bf)
        self.editor.textChanged.emit()

    def align_left(self): self._align('left')
    def align_center(self): self._align('center')
    def align_right(self): self._align('right')

    def _sync_fmt_buttons(self, *_):
        """B/I/U/S: без выделения отражают формат ввода у курсора (как в Word),
        с выделением — состояние всего выделения. В первой строке (заголовок)
        ввод продолжается полужирным крупным; при выходе из заголовка формат
        ввода возвращается к обычному."""
        from PySide6.QtGui import QFont, QTextCharFormat
        if getattr(self.editor, '_restyling', False):
            return
        cursor = self.editor.textCursor()
        doc = self.editor.document()
        in_title = cursor.block() == doc.firstBlock()
        # ВАЖНО: Qt применяет setCurrentCharFormat К АКТИВНОМУ ВЫДЕЛЕНИЮ и тем
        # самым меняет сам документ (текст под выделением терял/получал стиль).
        # Поэтому при выделении формат ввода не трогаем вовсе — ввод поверх
        # выделения и так наследует формат соседнего символа.
        if cursor.hasSelection():
            pass
        else:
            cf = self.editor.currentCharFormat()
            if in_title:
                # формат ввода первой строки = её текущий уровень заголовка
                # (авто 17pt / выбранный пользователем уровень)
                tf = self.editor._title_font(doc.firstBlock().text() != '')
                if (abs(cf.fontPointSize() - tf.pointSizeF()) > 0.01
                        or cf.fontWeight() < tf.weight()):
                    nf = QTextCharFormat(cf)
                    nf.setFont(tf)
                    self.editor._restyling = True
                    try:
                        self.editor.setCurrentCharFormat(nf)
                    finally:
                        self.editor._restyling = False
            elif cf.fontWeight() >= QFont.Weight.DemiBold and cf.fontPointSize() >= 14:
                # вышли из заголовка — вернуться к обычному формату ввода
                nf = QTextCharFormat(cf)
                f = nf.font()
                f.setPointSize(11)
                f.setWeight(QFont.Weight.Normal)
                nf.setFont(f)
                self.editor._restyling = True
                try:
                    self.editor.setCurrentCharFormat(nf)
                    blk = cursor.block()
                    if blk.text() == '' and blk.charFormat().fontPointSize() >= 14:
                        from PySide6.QtGui import QTextCursor
                        bc = QTextCursor(blk)
                        bc.setBlockCharFormat(nf)
                finally:
                    self.editor._restyling = False
        cf = self.editor.currentCharFormat()
        if cursor.hasSelection():
            # при выделении кнопки отражают состояние ВСЕГО выделения:
            # свойство включено у всех символов → галка, иначе — нет
            fmts = self.editor.selection_char_formats(cursor)
            bold = bool(fmts) and all(f.fontWeight() >= QFont.Weight.Bold for f in fmts)
            italic = bool(fmts) and all(f.fontItalic() for f in fmts)
            under = bool(fmts) and all(f.fontUnderline() for f in fmts)
            strike = bool(fmts) and all(f.fontStrikeOut() for f in fmts)
        else:
            bold = cf.fontWeight() >= QFont.Weight.DemiBold
            italic = cf.fontItalic()
            under = cf.fontUnderline()
            strike = cf.fontStrikeOut()
        self.fmt_buttons['bold'].setChecked(bold)
        self.fmt_buttons['italic'].setChecked(italic)
        self.fmt_buttons['under'].setChecked(under)
        self.fmt_buttons['strike'].setChecked(strike)
        # окошко размера показывает текущий размер (не мешая вводу своего)
        if not self.size_combo.hasFocus():
            self.size_combo.setEditText(str(int(round(self.editor.current_font_size()))))

    # --- переключение «Заметки» / «Удалённые» ---
    def _set_scope(self, trash: bool):
        if self._show_trash == trash:
            self.btn_notes_scope.setChecked(not trash)
            self.btn_trash_scope.setChecked(trash)
            return
        self.editor.flush()
        self._show_trash = trash
        self.btn_notes_scope.setChecked(not trash)
        self.btn_trash_scope.setChecked(trash)
        # создавать заметки в корзине нельзя — кнопка неактивна
        self.btn_compose.setEnabled(not trash)
        self.rebuild_notes()

    def _on_cross_delete(self, note_id: str):
        """Крестик на карточке: в «Заметках» — в корзину, в «Удалённых» — навсегда (с подтверждением)."""
        note = self.store.notes.get(note_id)
        if note is None:
            return
        if note['deleted']:
            self.purge_note(note)   # purge_note спрашивает подтверждение
        else:
            self.trash_note(note)

    def _on_restore_click(self, note_id: str):
        """Значок возврата на заметке в корзине: восстанавливает заметку."""
        note = self.store.notes.get(note_id)
        if note is None or not note['deleted']:
            return
        self.restore_note(note)

    def _on_star_click(self, note_id: str):
        """Звезда на карточке/строке: закрепить заметку сверху или открепить."""
        note = self.store.notes.get(note_id)
        if note is None:
            return
        if note['deleted']:
            return   # в корзине закрепление не имеет смысла
        self.toggle_pin(note)

    def _sort_key(self, note):
        sort = self.store.setting('sort', 'modified')
        if sort == 'created':
            return st.num_or_zero(note.get('created', 0))
        if sort == 'title':
            return str(note.get('title') or '').lower()
        return st.num_or_zero(note.get('modified', 0))

    def rebuild_notes(self):
        self.editor.flush()
        search = self.search.text().strip().lower()
        notes = list(self.store.notes.values())
        if self._show_trash:
            notes = [n for n in notes if n['deleted']]
        else:
            notes = [n for n in notes if not n['deleted']]   # все папки в одном списке
        if self._filter_color:
            notes = [n for n in notes if (n.get('color') or '') == self._filter_color]
        if self._filter_tag:
            tag_needle = '#' + self._filter_tag.lower()
            notes = [n for n in notes if tag_needle in (n.get('plain') or '').lower()]
        if search:
            notes = [n for n in notes if search in (n.get('title') or '').lower()
                     or search in (n.get('plain') or '').lower()]
        pinned = [n for n in notes if n.get('pinned')]
        rest = [n for n in notes if not n.get('pinned')]
        sort_mode = self.store.setting('sort', 'modified')
        if sort_mode == 'title':
            pinned.sort(key=lambda n: n['title'].lower())
            rest.sort(key=lambda n: n['title'].lower())
        elif sort_mode == 'manual':
            order = self.store.setting('manual_order', [])
            order_idx = {nid: i for i, nid in enumerate(order)} if isinstance(order, list) else {}
            pinned.sort(key=lambda n: (order_idx.get(n['id'], -1), -self._sort_key(n)))
            rest.sort(key=lambda n: (order_idx.get(n['id'], -1), -self._sort_key(n)))
        else:
            pinned.sort(key=self._sort_key, reverse=True)
            rest.sort(key=self._sort_key, reverse=True)
        ordered = pinned + rest
        self.notes_list.blockSignals(True)
        self.notes_list.clearSelection()
        self.notes_list.clear()
        self.notes_list.setCurrentRow(-1)
        delegate = self.notes_list.itemDelegate()
        if isinstance(delegate, NoteDelegate):
            delegate.search = search
        for note in ordered:
            it = QListWidgetItem()
            it.setData(NOTE_ROLE, note)
            self.notes_list.addItem(it)
        self.notes_list.blockSignals(False)
        # строка статуса: сколько заметок сейчас в списке
        if self._show_trash:
            self.status_label.setText(self._tr('status_trash', n=len(ordered)))
        else:
            extra = self.store.trash_count()
            if extra:
                self.status_label.setText(self._tr('status_notes_trash', n=len(ordered), t=extra))
            else:
                self.status_label.setText(self._tr('status_notes', n=len(ordered)))
        if self.current is not None:
            row = next((i for i, n in enumerate(ordered) if n['id'] == self.current['id']), -1)
            if row >= 0:
                self.notes_list.blockSignals(True)
                self.notes_list.select_single_row(row)
                self.notes_list.blockSignals(False)
            else:
                self.notes_list.clearSelection()
                self._update_pages()
        else:
            self.notes_list.clearSelection()

    def _on_notes_reordered(self, ids: list):
        """Сохраняет ручной порядок заметок после перетаскивания мышью."""
        if self._show_trash or not ids:
            self.rebuild_notes()
            return
        # если включён фильтр/поиск, сохраняем порядок видимых и дописываем остальные
        prev = self.store.setting('manual_order', [])
        prev_list = list(prev) if isinstance(prev, list) else []
        seen = set(ids)
        merged = list(ids) + [nid for nid in prev_list if nid not in seen and nid in self.store.notes]
        self.store.set_settings({'sort': 'manual', 'manual_order': merged})
        self.rebuild_notes()

    def _detach_editor(self):
        """Безопасно отвязывает редактор от текущей заметки (после удаления/восстановления)."""
        if self.editor._save_timer.isActive():
            self.editor._save_timer.stop()
        self.current = None
        self.editor.note = None
        self.editor._dirty = False
        self.editor.blockSignals(True)
        self.editor.clear()
        self.editor.blockSignals(False)
        self._update_pages()

    def _on_note_row(self, row):
        it = self.notes_list.item(row)
        note = it.data(NOTE_ROLE) if it else None
        if note is None:
            self._detach_editor()
            return
        if self.current is not None and self.current['id'] == note['id']:
            return
        self.editor.flush()
        self.current = note
        self.editor.load_note(note)
        self._update_pages()
        self._sync_fmt_buttons()   # окошко размера сразу показывает размер заголовка
        self._update_origin_bar()
        self._update_footer()
        if self.find_bar.isVisible():
            self.find_bar._on_query(self.find_bar.input.text())

    def _update_origin_bar(self):
        note = self.current
        origin = note.get('origin') if note else None
        if not isinstance(origin, dict) or not origin:
            self.origin_bar.hide()
            return
        src = origin.get('source_type') or 'pc'
        sender = (origin.get('sender_name') or '').strip()
        device = (origin.get('device_name') or '').strip()
        ts = origin.get('received_at') or origin.get('sent_at') or 0
        dt = human_date(ts) if ts else ''
        if src == 'friend' and sender:
            who = f'От: {sender}' + (f' ({device})' if device else '')
        elif src == 'phone':
            who = f'С телефона: {device or "Android"}' + (f' ({sender})' if sender else '')
        else:
            who = f'С ПК: {device or "другой ПК"}' + (f' ({sender})' if sender else '')
        self.lbl_origin.setText(who + (f'  ·  {dt}' if dt else ''))
        self.origin_bar.show()

    def _clear_note_origin(self):
        if self.current is None:
            return
        self.current['origin'] = None
        self.store.save_note(self.current)
        self.origin_bar.hide()

    def open_zametka_file(self, path: str):
        """Открывает .zametka (из проводника, MAX или перетаскивания):
        импортирует заметку с меткой origin и сразу открывает её."""
        if not path or not share.is_zametka_file(path):
            return None
        try:
            note = share.import_zametka(self.store, path)
        except Exception as e:
            QMessageBox.warning(self, 'Импорт .zametka', f'Не удалось открыть файл: {e}')
            return None
        self.rebuild_notes()
        self.restore_and_activate()
        self._jump_to_note(note['id'])
        return note

    def _sync_webdav_now(self):
        url = self.store.setting('webdav_url', '')
        user = self.store.setting('webdav_user', '')
        pwd = st.unprotect_secret(str(self.store.setting('webdav_pass', '') or ''))
        if not url:
            QMessageBox.information(self, 'WebDAV', 'Сначала укажите адрес WebDAV в Настройках.')
            return
        if getattr(self, '_webdav_busy', False):
            return
        self._webdav_busy = True
        self.editor.flush()
        import threading

        def worker():
            try:
                res = webdav_sync.sync_webdav(self.store, url, user, pwd)
                self.webdav_sync_done.emit(res, '')
            except Exception as e:
                self.webdav_sync_done.emit(None, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_webdav_sync_done(self, res, err: str):
        self._webdav_busy = False
        if err:
            QMessageBox.warning(self, 'WebDAV', f'Ошибка синхронизации: {err}')
            return
        self.rebuild_notes()
        if self.current is not None and self.current['id'] in self.store.notes:
            self.current = self.store.notes[self.current['id']]
            self.editor.load_note(self.current)
            self._update_origin_bar()
        msg = f"Синхронизация завершена: отправлено {res['pushed']}, получено {res['pulled']}."
        if res['errors']:
            msg += '\nОшибок: ' + str(len(res['errors']))
        QMessageBox.information(self, 'WebDAV', msg)

    def _update_pages(self):
        """Пустой редактор без заметки — показать подсказку или состояние."""
        has = self.current is not None
        self.editor.setEnabled(has)
        self.btn_export.setEnabled(has)   # экспортировать нечего без заметки
        if not has:
            self.editor.setPlaceholderText(self._tr('placeholder'))
            self.editor_footer.setText('')
            self.origin_bar.hide()

    def _update_footer(self):
        if self.current is None:
            self.editor_footer.setText('')
            return
        plain = self.editor.toPlainText()
        words = len(plain.split())
        chars = len(plain)
        dt_str = human_date(self.current.get('modified') or self.current.get('created') or 0)
        parts = []
        if dt_str:
            parts.append(self._tr('footer_mod', dt=dt_str))
        parts.append(self._tr('footer_words', w=words))
        parts.append(self._tr('footer_chars', c=chars))
        self.editor_footer.setText('  ·  '.join(parts))

    # --- фильтры по цвету и #тегам, поиск в заметке, фокус, палитра команд ---
    def _clear_filters(self):
        self._filter_color = ''
        self._filter_tag = ''
        self._sync_filter_ui()
        self.rebuild_notes()

    def _toggle_color_filter(self, hex_color: str):
        self._filter_color = '' if self._filter_color == hex_color else hex_color
        self._sync_filter_ui()
        self.rebuild_notes()

    def _collect_tags(self) -> list:
        counts = {}
        for n in self.store.notes.values():
            if n.get('deleted') != self._show_trash:
                continue
            seen = set(m.lower() for m in TAG_RE.findall(n.get('plain') or ''))
            for t in seen:
                counts[t] = counts.get(t, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def _open_tag_menu(self):
        tags = self._collect_tags()
        menu = QMenu(self)
        if self._filter_tag:
            menu.addAction('Сбросить тег', lambda: self._set_tag_filter(''))
            menu.addSeparator()
        if not tags:
            act = menu.addAction('Нет тегов (добавьте #тег в текст заметки)')
            act.setEnabled(False)
        else:
            for tag, cnt in tags:
                act = menu.addAction(f'#{tag} ({cnt})', lambda t=tag: self._set_tag_filter(t))
                act.setCheckable(True)
                act.setChecked(tag == self._filter_tag)
        menu.exec(self.btn_tag_filter.mapToGlobal(self.btn_tag_filter.rect().bottomLeft()))

    def _set_tag_filter(self, tag: str):
        self._filter_tag = '' if self._filter_tag == tag else tag
        self._sync_filter_ui()
        self.rebuild_notes()

    def _sync_filter_ui(self):
        has_filter = bool(self._filter_color or self._filter_tag)
        for h, btn in self._color_filter_btns.items():
            btn.setChecked((not has_filter) if h == '' else (h == self._filter_color))
        self.btn_tag_filter.setText(f'#{self._filter_tag}' if self._filter_tag else self._tr('tags_btn'))

    def open_find_in_note(self):
        if self.current is None:
            return
        sel = self.editor.textCursor().selectedText().replace('\u2029', ' ').strip()
        self.find_bar.open_bar(sel if len(sel) <= 60 else '')

    def toggle_focus_mode(self):
        self._focus_mode = not self._focus_mode
        self.btn_focus.setChecked(self._focus_mode)
        if self._focus_mode:
            self._saved_splitter_sizes = self.splitter.sizes()
            self.list_pane.hide()
        else:
            self.list_pane.show()
            if self._saved_splitter_sizes:
                self.splitter.setSizes(self._saved_splitter_sizes)

    def open_command_palette(self):
        entries = []
        # команды
        entries.append(('Новая заметка', 'Ctrl+N', self.new_note))
        entries.append(('Переключить тему', 'день / ночь / как в Windows', self._cycle_theme))
        entries.append(('Режим фокуса', 'скрыть/показать список (Ctrl+\\)', self.toggle_focus_mode))
        if self.current is not None:
            entries.append(('Найти в заметке', 'Ctrl+Shift+F', self.open_find_in_note))
            entries.append(('Экспорт заметки…', 'PDF / HTML / TXT / MD', self._export_current))
            entries.append(('История версий…', 'откат изменений', self._show_versions))
        entries.append(('Корзина / Все заметки', 'переключить список', lambda: self._set_scope(not self._show_trash)))
        entries.append(('Настройки…', 'папка данных, тема, телефон', self._open_settings))
        # активные заметки
        active = sorted(
            (n for n in self.store.notes.values() if not n.get('deleted')),
            key=lambda n: n.get('modified', 0), reverse=True,
        )
        for n in active:
            nid = n['id']
            entries.append((n.get('title') or 'Новая заметка', n.get('snippet') or 'Заметка',
                            lambda i=nid: self._jump_to_note(i)))
        dlg = CommandPalette(entries, self)
        g = self.geometry()
        dlg.move(g.center().x() - dlg.width() // 2, g.top() + 80)
        if dlg.exec():
            dlg.run_chosen()

    def _jump_to_note(self, note_id: str):
        if self._show_trash:
            self._set_scope(False)
        if self._filter_color or self._filter_tag or self.search.text():
            self._filter_color = ''
            self._filter_tag = ''
            self._sync_filter_ui()
            self.search.clear()
            self.rebuild_notes()
        for i in range(self.notes_list.count()):
            if self.notes_list.item(i).data(NOTE_ROLE)['id'] == note_id:
                self.notes_list.select_single_row(i)
                self.editor.setFocus()
                break

    def _show_note_qr(self, note):
        """Показывает офлайн QR-код для передачи заметки на Android без сети."""
        self.editor.flush()
        fresh = self.store.notes.get(note['id'], note)
        payload, err = share.encode_note_qr(self.store, fresh)
        if err:
            QMessageBox.information(self, 'QR-код заметки', err)
            return
        from .settings_dialog import _qr_pixmap
        pm = _qr_pixmap(payload, 280)
        if pm.isNull():
            QMessageBox.warning(self, 'QR-код заметки', 'Не удалось построить QR-код')
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f'QR-код - {fresh.get("title") or "Заметка"}')
        v = QVBoxLayout(dlg)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setPixmap(pm)
        v.addWidget(lbl)
        hint = QLabel('Откройте «Заметки» на телефоне и нажмите иконку QR-сканера сверху.\nПередача работает полностью офлайн (без Wi-Fi и интернета).')
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        v.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        dlg.exec()

    def _export_current(self):
        if self.current is None:
            return
        self.editor.flush()   # экспортируем самое свежее содержимое
        export_note(self, self.current)

    def _on_search(self, text):
        if len(self.store.notes) > 30:
            self._search_timer.start()
        else:
            self.rebuild_notes()

    # --- действия с заметками ---
    def new_note(self):
        if self._show_trash:            # Ctrl+N из корзины — переключаемся на «Заметки»
            self._set_scope(False)
        note = self.store.create_note(st.DEFAULT_FOLDER)
        self.rebuild_notes()
        # выбрать новую
        for i in range(self.notes_list.count()):
            if self.notes_list.item(i).data(NOTE_ROLE)['id'] == note['id']:
                self.notes_list.select_single_row(i)
                break
        self.editor.setFocus()

    def _on_note_saved(self, note_id, html):
        note = self.store.notes.get(note_id)
        if note is None:
            return
        doc_plain = self.editor.toPlainText()
        title, snippet = st.note_plain_parts(doc_plain)
        note['html'] = html
        note['plain'] = doc_plain
        note['title'] = title
        note['snippet'] = snippet
        note['modified'] = time.time()
        note['title_size'] = self.editor._title_size
        versions.snapshot(self.store.root, note_id, html, min_interval=30.0)
        self.store.save_note(note)
        self._refresh_item(note)
        self._update_footer()

    def _refresh_item(self, note):
        for i in range(self.notes_list.count()):
            it = self.notes_list.item(i)
            if it.data(NOTE_ROLE)['id'] == note['id']:
                it.setData(NOTE_ROLE, dict(note))
                self.notes_list.viewport().update()
                break
        # пересортировка по дате изменения — с задержкой, чтобы не мешать набору
        if self.store.setting('sort', 'modified') == 'modified':
            if not hasattr(self, '_reorder_timer'):
                self._reorder_timer = QTimer(self)
                self._reorder_timer.setSingleShot(True)
                self._reorder_timer.setInterval(1500)
                self._reorder_timer.timeout.connect(self._deferred_reorder)
            self._reorder_timer.start()

    def _deferred_reorder(self):
        sel_id = self.current['id'] if self.current else None
        self.rebuild_notes()
        if sel_id:
            for i in range(self.notes_list.count()):
                if self.notes_list.item(i).data(NOTE_ROLE)['id'] == sel_id:
                    self.notes_list.blockSignals(True)
                    self.notes_list.select_single_row(i)
                    self.notes_list.blockSignals(False)
                    break

    def trash_note(self, note):
        if self.current is not None and self.current['id'] == note['id']:
            self.editor.flush()
            self._detach_editor()
        self.store.trash_note(note)
        self.rebuild_notes()

    def restore_note(self, note):
        if self._show_trash and self.current is not None and self.current['id'] == note['id']:
            self.editor.flush()
            self._detach_editor()
        self.store.restore_note(note)
        self.rebuild_notes()

    def purge_note(self, note):
        btn = QMessageBox.question(
            self, self._tr('purge_title'),
            self._tr('purge_msg', title=note.get('title') or self._tr('new_note')),
        )
        if btn == QMessageBox.Yes:
            if self.current is not None and self.current['id'] == note['id']:
                self._detach_editor()
            self.store.purge_note(note)
            self.rebuild_notes()

    def _empty_trash(self):
        btn = QMessageBox.question(
            self, self._tr('empty_trash_title'), self._tr('empty_trash_msg'),
        )
        if btn != QMessageBox.Yes:
            return
        for note in [n for n in self.store.notes.values() if n['deleted']]:
            self.store.purge_note(note)
        self._detach_editor()
        self.rebuild_notes()

    def duplicate_note(self, note):
        new = self.store.duplicate_note(note)
        self.rebuild_notes()
        for i in range(self.notes_list.count()):
            if self.notes_list.item(i).data(NOTE_ROLE)['id'] == new['id']:
                self.notes_list.select_single_row(i)
                break

    def toggle_pin(self, note):
        note['pinned'] = not note.get('pinned')
        note['modified'] = time.time()
        self.store.save_note(note)
        self.rebuild_notes()

    def set_color(self, note, hex_color):
        note['color'] = hex_color
        note['modified'] = time.time()
        self.store.save_note(note)
        self._refresh_item(note)
        self._update_footer()

    def set_reminder(self, note, hours=None, tomorrow9=False, clear=False, ts=0.0):
        if clear:
            note['reminder_at'] = 0.0
        elif hours:
            note['reminder_at'] = time.time() + hours * 3600
        elif tomorrow9:
            dt = QDateTime.currentDateTime().addDays(1)
            dt.setTime(QTime(9, 0, 0))
            note['reminder_at'] = dt.toSecsSinceEpoch()
        elif ts:
            note['reminder_at'] = ts
        self.store.save_note(note)

    def _remind_dialog(self, note):
        dlg = QDialog(self)
        dlg.setWindowTitle('Напоминание')
        v = QVBoxLayout(dlg)
        dt = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        dt.setCalendarPopup(True)
        v.addWidget(dt)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec():
            self.set_reminder(note, ts=dt.dateTime().toSecsSinceEpoch())

    def _delete_via_key(self):
        notes = self._selected_notes()
        if not notes:
            return
        if len(notes) > 1:
            if all(note['deleted'] for note in notes):
                self._bulk_purge(notes)
            else:
                self._bulk_trash(notes)
            return
        note = notes[0]
        if note['deleted']:
            self.purge_note(note)
        else:
            self.trash_note(note)

    # --- контекстные меню ---
    def _note_menu_at(self, pos):
        it = self.notes_list.itemAt(pos)
        if it is None:
            return
        selected = self.notes_list.selectedItems()
        if it not in selected:
            # правый клик вне выделения: выделяем только эту заметку
            for other in selected:
                other.setSelected(False)
            it.setSelected(True)
            selected = [it]
        if len(selected) > 1:
            notes = [i.data(NOTE_ROLE) for i in selected if i.data(NOTE_ROLE)]
            self._bulk_menu(notes).exec(self.notes_list.mapToGlobal(pos))
            return
        self.notes_list.setCurrentItem(it)
        self._note_menu(it.data(NOTE_ROLE)).exec(self.notes_list.mapToGlobal(pos))

    def _selected_notes(self) -> list:
        return [i.data(NOTE_ROLE) for i in self.notes_list.selectedItems()
                if i.data(NOTE_ROLE)]

    def _bulk_menu(self, notes) -> QMenu:
        menu = QMenu(self)
        n = len(notes)
        if all(not note['deleted'] for note in notes):
            menu.addAction(f'Убрать в корзину ({n})',
                           lambda: self._bulk_trash(notes))
        else:
            menu.addAction(f'Восстановить ({n})',
                           lambda: self._bulk_restore(notes))
            menu.addAction(f'Удалить навсегда ({n})',
                           lambda: self._bulk_purge(notes))
        return menu

    def _bulk_trash(self, notes):
        cur_id = self.current['id'] if self.current else None
        if cur_id and any(note['id'] == cur_id for note in notes):
            self.editor.flush()
            self._detach_editor()
        for note in notes:
            self.store.trash_note(note)
        self.rebuild_notes()

    def _bulk_restore(self, notes):
        cur_id = self.current['id'] if self.current else None
        if self._show_trash and cur_id and any(note['id'] == cur_id for note in notes):
            self.editor.flush()
            self._detach_editor()
        for note in notes:
            self.store.restore_note(note)
        self.rebuild_notes()

    def _bulk_purge(self, notes):
        btn = QMessageBox.question(
            self, self._tr('purge_title'),
            self._tr('purge_bulk_msg', n=len(notes)),
        )
        if btn != QMessageBox.Yes:
            return
        cur_id = self.current['id'] if self.current else None
        if cur_id and any(note['id'] == cur_id for note in notes):
            self._detach_editor()
        for note in notes:
            self.store.purge_note(note)
        self.rebuild_notes()

    # --- импорт/экспорт/версии ---
    def _import(self):
        n = import_notes(self, self.store)
        if n:
            self.rebuild_notes()
            QMessageBox.information(self, 'Импорт', f'Импортировано заметок: {n}')

    def _show_versions(self):
        if self.current is None:
            return
        self.editor.flush()

        def restore(html):
            note = self.current
            if note is None:
                return
            versions.snapshot(self.store.root, note['id'], note.get('html') or '')
            note['html'] = html
            self.editor.load_note(note)
            self._on_note_saved(note['id'], html)

        VersionsDialog(self.store.root, self.current, restore, self).exec()

    # --- настройки/тема/данные ---
    def _phone_apply(self, enabled: bool):
        """Включить/выключить режим «Телефон» по настройке."""
        if enabled and self.phone is None:
            from ..core.phoneserver import PhoneServer
            try:
                self.phone = PhoneServer(self.store, self.store.setting('phone_port', 8787))
                self.phone.changed.connect(self._on_phone_changed)
                self.phone.start()
            except OSError as e:
                self.phone = None
                QMessageBox.warning(self, 'Телефон', f'Не удалось запустить веб-сервер: {e}')
        elif not enabled and self.phone is not None:
            self.phone.stop()
            self.phone = None

    def _on_phone_changed(self):
        # заметки изменились с телефона: обновляем списки и подтягиваем открытую заметку
        sel_id = self.current['id'] if self.current else None
        if sel_id:
            fresh = self.store.notes.get(sel_id)
            if fresh is None or (fresh.get('deleted') and not self._show_trash):
                self._detach_editor()
                sel_id = None
            elif not self.editor._dirty and fresh.get('modified', 0) > self.current.get('modified', 0):
                self.current = fresh
                self.editor.load_note(fresh)
                self._update_origin_bar()
                self._update_footer()
        self.rebuild_notes()
        if sel_id:
            for i in range(self.notes_list.count()):
                if self.notes_list.item(i).data(NOTE_ROLE)['id'] == sel_id:
                    self.notes_list.blockSignals(True)
                    self.notes_list.select_single_row(i)
                    self.notes_list.blockSignals(False)
                    break

    def phone_url(self) -> str:
        return self.phone.url() if self.phone else ''

    def _import_paths(self, paths: list):
        """Файлы, перетащенные в окно (.zametka/txt/html/md), становятся заметками."""
        count = 0
        last_id = None
        for path in paths:
            if not os.path.isfile(path):
                continue
            if share.is_zametka_file(path):
                try:
                    n = share.import_zametka(self.store, path)
                    last_id = n['id']
                    count += 1
                except Exception:
                    pass
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except OSError:
                continue
            note = self.store.create_note()
            ext = os.path.splitext(path)[1].lower()
            if ext in ('.html', '.htm'):
                from PySide6.QtGui import QTextDocument
                doc = QTextDocument()
                doc.setHtml(content)
                html, plain = doc.toHtml(), doc.toPlainText()
            else:
                from ..core.phoneserver import plain_to_html
                html = plain_to_html(content)
                plain = content
            title, snippet = st.note_plain_parts(plain)
            note['html'] = html
            note['plain'] = plain
            note['title'] = title or os.path.splitext(os.path.basename(path))[0]
            note['snippet'] = snippet[:200]
            self.store.save_note(note)
            count += 1
        if count:
            self.rebuild_notes()
            if last_id:
                self._jump_to_note(last_id)

    def _open_settings(self):
        dlg = SettingsDialog(self.store, self)
        dlg.settings_changed.connect(self._apply_settings)
        dlg.exec()

    def _apply_settings(self, vals):
        self.store.set_settings(vals)
        self.theme.set_mode(vals.get('theme', 'system'))
        self._apply_lang()
        self._register_hotkey()
        self._phone_apply(bool(vals.get('phone', self.store.setting('phone', False))))
        self.rebuild_notes()

    def _on_theme(self, colors):
        # кнопки — PNG-набор пользователя (icons_png/light|dark, см. scripts/make_icons.py)
        ic = lambda kind: png_icon(kind, is_dark_theme(colors))
        mode = getattr(self, '_view_mode', 'card')
        self.btn_compose.setIcon(ic('compose'))
        self.btn_notes_scope.setIcon(ic('scope_notes'))
        self.btn_trash_scope.setIcon(ic('scope_trash'))
        self.btn_view.setIcon(ic('view_' + mode))
        self.btn_view.setToolTip('Вид: ' + {'card': 'Крупный перечень', 'list': 'Список'}[
            mode] + ' (переключение по кругу)')
        fmt_icons = {'bold': 'bold', 'italic': 'italic', 'under': 'under',
                     'strike': 'strike', 'bullet': 'bullet', 'check': 'check',
                     'alignL': 'align_l', 'alignC': 'align_c', 'alignR': 'align_r'}
        for key, kind in fmt_icons.items():
            self.fmt_buttons[key].setIcon(ic(kind))
        self.btn_image.setIcon(ic('image'))
        self.btn_marker.setIcon(ic('marker'))
        self.btn_textcolor.setIcon(ic('textcolor'))
        self.status_label.setStyleSheet(f"color: {colors['text2']}; background: transparent;")
        self.editor_footer.setStyleSheet(f"color: {colors['text2']}; background: transparent;")
        self.origin_bar.setStyleSheet(f"background: {colors['hover']}; border-bottom: 1px solid {colors['line']};")
        self.lbl_origin.setStyleSheet(f"color: {colors['text2']}; background: transparent;")
        self.btn_export.setIcon(ic('export'))
        # тема и папка заметок — кнопки рядом с экспортом
        # режим берём У МЕНЕДЖЕРА темы (истина в последней инстанции):
        # в настройках могла остаться legacy-'system', словарь дня/ночи её не знает
        mode_setting = getattr(self.theme, 'mode', 'light')
        if mode_setting not in ('light', 'dark', 'system'):
            mode_setting = 'light'
        dark_now = is_dark_theme(colors)
        _dpr = self.devicePixelRatioF() or 1.0   # чёткие иконки на масштабе 125/150%
        self.fmt_buttons['numbered'].setIcon(numbered_list_icon(dark_now, _dpr))
        self.btn_focus.setIcon(sidebar_toggle_icon(dark_now, _dpr))
        self.btn_theme.setIcon(theme_icon(mode_setting, dark_now, _dpr))
        self.btn_theme.setToolTip('Тема: ' + {'light': 'день', 'dark': 'ночь',
                                              'system': 'как в Windows'}[mode_setting]
                                  + ' (клик переключает)')
        self.btn_folder.setIcon(folder_icon(dark_now, _dpr))
        self._apply_size_combo_style(dark_now)
        old_m = self.btn_marker.menu()
        self.btn_marker.setMenu(self._marker_menu())
        if old_m is not None:
            old_m.deleteLater()
        old_t = self.btn_textcolor.menu()
        self.btn_textcolor.setMenu(self._textcolor_menu())
        if old_t is not None:
            old_t.deleteLater()
        apply_window_titlebar_theme(self, dark_now)
        self.notes_list.viewport().update()
        # редактор СЛЕДУЕТ теме (QSS красит QTextBrowser), а «обычный» текст
        # без принудительного цвета перекрашивается под фон: убираем
        # запечённые цвета по умолчанию (#1D1D1F/#F5F5F7/#000000) из документа.
        # Нормализация — только при РЕАЛЬНОЙ смене темы, не при каждом виде
        if self._last_theme_text != colors['text']:
            self._last_theme_text = colors['text']
            self.editor.normalize_theme_colors()
        self.editor._restyle_first_line()

    def _register_hotkey(self):
        seq = self.store.setting('hotkey', 'Ctrl+Alt+N')
        ok = self.hotkey.register(self.winId(), seq) if seq else True
        if not ok and seq:
            QMessageBox.warning(self, 'Горячая клавиша',
                                f'Не удалось занять «{seq}» — возможно, её использует другая программа.\n'
                                'Быстрая заметка недоступна, остальное работает как обычно.')

    # --- геометрия/закрытие ---
    def _restore_geometry(self):
        import base64
        from PySide6.QtGui import QGuiApplication
        b64 = self.store.setting('geometry_b64', '')
        if b64:
            try:
                self.restoreGeometry(base64.b64decode(b64))
                # окно должно попасть хотя бы на один экран, иначе сбрасываем
                screens = QGuiApplication.screens()
                geo = self.frameGeometry()
                on_screen = any(geo.intersects(s.availableGeometry()) for s in screens)
                if on_screen and self.width() > 300 and self.height() > 200:
                    return
            except Exception:
                pass
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.setGeometry(
            max(screen.left() + 40, screen.center().x() - 525),
            max(screen.top() + 40, screen.center().y() - 320),
            min(1050, screen.width() - 80), min(640, screen.height() - 80))

    def _save_geometry(self):
        import base64
        self.store.set_setting('geometry_b64', base64.b64encode(self.saveGeometry()).decode('ascii'))

    def closeEvent(self, event):
        if self.store.setting('tray', False) and self._tray_ok and not getattr(self, '_quitting', False):
            # Фоновый режим включён в настройках: прячем окно в трей (повторный
            # запуск exe или клик по значку в трее вернёт окно; полный выход - Ctrl+Q).
            self.editor.flush()
            event.ignore()
            self.hide()
            return
        self.editor.flush()
        self._save_geometry()
        self.hotkey.unregister()
        if self.phone is not None:
            self.phone.stop()
            self.phone = None
        if hasattr(self, 'single') and self.single:
            self.single.close()
        event.accept()

    def _quit(self):
        self._quitting = True
        self.close()
        QApplication.quit()
