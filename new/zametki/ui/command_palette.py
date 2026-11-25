# -*- coding: utf-8 -*-
"""Командная палитра (Ctrl+K): быстрый переход к заметке или действию."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QLineEdit, QListWidget, QListWidgetItem,
                               QVBoxLayout)


class CommandPalette(QDialog):
    """Всплывающий быстрый поиск по заметкам и командам."""

    def __init__(self, entries: list, parent=None):
        """entries: список кортежей (label, subtitle, callback)."""
        super().__init__(parent)
        self.setWindowTitle('Быстрый переход')
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setFixedWidth(480)
        self._entries = entries
        self._chosen_cb = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        self.input = QLineEdit()
        self.input.setPlaceholderText('Найти заметку или команду… (Enter - открыть, Esc - закрыть)')
        lay.addWidget(self.input)

        self.list = QListWidget()
        self.list.setMinimumHeight(260)
        self.list.setMaximumHeight(340)
        lay.addWidget(self.list)

        self.input.textChanged.connect(self._filter)
        self.input.returnPressed.connect(self._activate)
        self.list.itemActivated.connect(lambda *_: self._activate())
        self.list.itemClicked.connect(lambda *_: self._activate())
        self.input.installEventFilter(self)

        self._filter('')
        self.input.setFocus()

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Down:
                row = self.list.currentRow()
                if row + 1 < self.list.count():
                    self.list.setCurrentRow(row + 1)
                return True
            if key == Qt.Key.Key_Up:
                row = self.list.currentRow()
                if row > 0:
                    self.list.setCurrentRow(row - 1)
                return True
            if key == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)

    def _filter(self, text: str):
        q = text.strip().lower()
        self.list.clear()
        for label, sub, cb in self._entries:
            hay = (label + ' ' + sub).lower()
            if q and q not in hay:
                continue
            disp = f'{label}   -   {sub}' if sub else label
            it = QListWidgetItem(disp)
            it.setData(Qt.ItemDataRole.UserRole, cb)
            self.list.addItem(it)
            if self.list.count() >= 40:
                break
        if self.list.count() > 0:
            self.list.setCurrentRow(0)

    def _activate(self):
        it = self.list.currentItem()
        if it is None:
            return
        self._chosen_cb = it.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def run_chosen(self):
        if callable(self._chosen_cb):
            self._chosen_cb()
