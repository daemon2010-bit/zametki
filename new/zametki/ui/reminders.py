# -*- coding: utf-8 -*-
"""Напоминания: проверка раз в 30 секунд, системное уведомление через трей.
Работает, пока приложение запущено (при закрытии в трей — тоже)."""
import time

from PySide6.QtCore import QObject, QTimer


class ReminderEngine(QObject):
    def __init__(self, store, notify_cb, parent=None):
        QObject.__init__(self, parent)
        self.store = store
        self.notify = notify_cb          # функция(title, text)
        self.timer = QTimer(self)
        self.timer.setInterval(30_000)
        self.timer.timeout.connect(self.check)
        self.timer.start()

    def check(self):
        now = time.time()
        for note in list(self.store.notes.values()):
            rem = note.get('reminder_at') or 0
            if rem and rem <= now and not note.get('deleted'):
                title = note.get('title') or 'Напоминание'
                text = (note.get('snippet') or '')[:120] or 'Пора взглянуть на заметку'
                try:
                    self.notify(title, text)
                except Exception:
                    continue
                note['reminder_at'] = 0.0
                self.store.save_note(note)
