# -*- coding: utf-8 -*-
"""Запуск приложения «Заметки» (новая версия)."""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

from zametki import APP_TITLE
from zametki.core import store as st
from zametki.core.single import SingleInstance
from zametki.core.hotkey import GlobalHotkey
from zametki.ui.main_window import MainWindow
from zametki.ui.theme import ThemeManager


def install_crash_hook(root_provider):
    def hook(tp, val, tb):
        try:
            path = os.path.join(root_provider(), 'crash.log')
            with open(path, 'a', encoding='utf-8') as f:
                import time
                f.write('\n[%s]\n' % time.strftime('%Y-%m-%d %H:%M:%S'))
                traceback.print_exception(tp, val, tb, file=f)
        except Exception:
            pass
        sys.__excepthook__(tp, val, tb)
    sys.excepthook = hook


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationDisplayName(APP_TITLE)
    from PySide6.QtGui import QFont
    app.setFont(QFont('Segoe UI', 9))

    open_arg = ''
    for arg in sys.argv[1:]:
        if os.path.isfile(arg) and arg.lower().endswith('.zametka'):
            open_arg = os.path.abspath(arg)
            break

    single = SingleInstance()
    if not single.first:
        # второй экземпляр: попросить открытое окно показать себя и открыть .zametka
        single.notify_existing(open_arg)
        single.close()
        return 0

    root_provider = st.data_dir
    install_crash_hook(root_provider)

    store = st.Store()
    theme = ThemeManager()
    theme.set_mode(store.setting('theme', 'system'))

    hotkey = GlobalHotkey()
    app.installNativeEventFilter(hotkey)
    app.installNativeEventFilter(single)

    win = MainWindow(store, theme, hotkey)
    win.single = single
    hotkey.triggered.connect(win.request_new_note.emit)

    def raise_window():
        """Повторный запуск/сообщение второго экземпляра: разворачивает окно
        из трея или с панели задач, сохраняя состояние Maximized."""
        win.restore_and_activate()

    single.raised.connect(raise_window)
    single.file_opened.connect(win.open_zametka_file)
    win.show()
    single.register_main_window(int(win.winId()))
    win._register_hotkey()
    if open_arg:
        from PySide6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(200, lambda: win.open_zametka_file(open_arg))

    app.exec()
    app.removeNativeEventFilter(hotkey)
    app.removeNativeEventFilter(single)
    single.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
