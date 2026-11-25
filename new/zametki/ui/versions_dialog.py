# -*- coding: utf-8 -*-
"""Диалог истории версий заметки: список снапшотов, предпросмотр, откат."""
import os
import time

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QListWidget,
                               QTextBrowser, QVBoxLayout, QLabel)

from ..core import versions

_DEFAULT_INKS = {'#1d1d1f', '#f5f5f7', '#000000', '#000'}


class VersionsDialog(QDialog):
    def __init__(self, root: str, note, restore_cb, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'История версий - {note.get("title") or "Новая заметка"}')
        self.setMinimumSize(640, 460)
        self.note = note
        self.restore_cb = restore_cb
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Снапшоты сохраняются при изменениях. Откат заменяет текущий текст (текущая версия тоже сохранится в истории).'))
        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumWidth(190)
        self.preview = QTextBrowser()
        self.preview.document().setBaseUrl(QUrl.fromLocalFile(root + os.sep))
        body.addWidget(self.list)
        body.addWidget(self.preview, 1)
        layout.addLayout(body)
        self._items = versions.list_versions(root, note['id'])
        for ts, path in self._items:
            self.list.addItem(time.strftime('%d.%m.%Y %H:%M:%S', time.localtime(ts / 1000)))
        self.list.currentRowChanged.connect(self._show)
        if self._items:
            self.list.setCurrentRow(0)
        buttons = QDialogButtonBox(QDialogButtonBox.RestoreDefaults | QDialogButtonBox.Close)
        btn_restore = buttons.button(QDialogButtonBox.RestoreDefaults)
        btn_restore.setText('Восстановить выбранную')
        btn_restore.setEnabled(bool(self._items))
        # RestoreDefaults не эмитит accepted() — подключаем напрямую к clicked
        btn_restore.clicked.connect(self._restore)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _normalize_preview(self):
        doc = self.preview.document()
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
                        if fg.style() != Qt.BrushStyle.NoBrush and fg.color().name().lower() in _DEFAULT_INKS:
                            fixes.append((fr.position(), fr.length(), fmt))
                it += 1
            b = b.next()
        for pos, length, fmt in fixes:
            clean = QTextCharFormat(fmt)
            clean.clearForeground()
            c = QTextCursor(doc)
            c.setPosition(pos)
            c.setPosition(pos + length, QTextCursor.MoveMode.KeepAnchor)
            c.setCharFormat(clean)

    def _show(self, row):
        if 0 <= row < len(self._items):
            self.preview.setHtml(versions.read_html(self._items[row][1]))
            self._normalize_preview()

    def _restore(self):
        row = self.list.currentRow()
        if 0 <= row < len(self._items):
            html = versions.read_html(self._items[row][1])
            if html:
                self.restore_cb(html)
                self.accept()
