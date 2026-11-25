# -*- coding: utf-8 -*-
"""Один экземпляр приложения (Win32 named mutex + адресное сообщение главному окну).

Без QtNetwork — чтобы не тащить сетевые библиотеки в компактную сборку.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import tempfile

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

ERROR_ALREADY_EXISTS = 183
HWND_BROADCAST = 0xFFFF
MUTEX_NAME = 'zametki-single-instance'
MSG_NAME = 'zametki-raise-window'

# use_last_error=True обязателен: ctypes.get_last_error() возвращает ошибку
# именно нашего вызова, тогда как обычный kernel32.GetLastError() между
# вызовом и чтением перезаписывается внутренними вызовами ctypes/Python.
_k32 = ctypes.WinDLL('kernel32', use_last_error=True)
_u32 = ctypes.WinDLL('user32', use_last_error=True)

_k32.CreateMutexW.argtypes = [wt.LPVOID, wt.BOOL, wt.LPCWSTR]
_k32.CreateMutexW.restype = wt.HANDLE
_k32.CloseHandle.argtypes = [wt.HANDLE]
_k32.CloseHandle.restype = wt.BOOL

_u32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
_u32.RegisterWindowMessageW.restype = wt.UINT
_u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_u32.PostMessageW.restype = wt.BOOL
_u32.IsWindow.argtypes = [wt.HWND]
_u32.IsWindow.restype = wt.BOOL
_u32.AllowSetForegroundWindow.argtypes = [wt.DWORD]
_u32.AllowSetForegroundWindow.restype = wt.BOOL


class SingleInstance(QAbstractNativeEventFilter, QObject):
    raised = Signal()
    file_opened = Signal(str)

    def __init__(self, name_suffix: str = ''):
        QAbstractNativeEventFilter.__init__(self)
        QObject.__init__(self)
        self._suffix = name_suffix
        self._marker = os.path.join(tempfile.gettempdir(), f'zametki-hwnd{name_suffix}.json')
        self._open_file = os.path.join(tempfile.gettempdir(), f'zametki-open{name_suffix}.json')
        self._mutex = _k32.CreateMutexW(None, False, MUTEX_NAME + name_suffix)
        self.first = ctypes.get_last_error() != ERROR_ALREADY_EXISTS
        self._msg_id = _u32.RegisterWindowMessageW(MSG_NAME + name_suffix)

    def register_main_window(self, hwnd: int):
        """Записывает точный HWND и PID главного окна, чтобы второй экземпляр
        будил именно MainWindow, а не скрытые popup-окна Qt (QComboBox/QMenu)."""
        if not self.first or not hwnd:
            return
        try:
            tmp = self._marker + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({'hwnd': int(hwnd), 'pid': os.getpid()}, f)
            os.replace(tmp, self._marker)
        except OSError:
            pass

    def notify_existing(self, open_path: str = ''):
        """Из второго экземпляра: попросить главное окно первого экземпляра показаться
        и (опционально) открыть переданный файл .zametka."""
        if open_path:
            try:
                tmp = self._open_file + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump({'path': os.path.abspath(open_path)}, f, ensure_ascii=False)
                os.replace(tmp, self._open_file)
            except OSError:
                pass
        sent = False
        try:
            with open(self._marker, 'r', encoding='utf-8') as f:
                info = json.load(f)
            hwnd = int(info.get('hwnd') or 0)
            pid = int(info.get('pid') or 0)
            if hwnd and _u32.IsWindow(wt.HWND(hwnd)):
                if pid > 0:
                    _u32.AllowSetForegroundWindow(pid)
                _u32.PostMessageW(wt.HWND(hwnd), self._msg_id, 0, 0)
                sent = True
        except (OSError, ValueError, TypeError):
            pass
        if not sent:
            # резерв: широковещательное сообщение (обрабатывает только nativeEventFilter)
            _u32.PostMessageW(wt.HWND(HWND_BROADCAST), self._msg_id, 0, 0)

    def _consume_open_file(self):
        if not os.path.exists(self._open_file):
            return
        try:
            with open(self._open_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            os.remove(self._open_file)
            p = str(data.get('path') or '').strip()
            if p:
                self.file_opened.emit(p)
        except (OSError, ValueError):
            pass

    def nativeEventFilter(self, event_type, message):
        if event_type == b'windows_generic_MSG':
            msg = wt.MSG.from_address(int(message))
            if msg.message == self._msg_id:
                self.raised.emit()
                self._consume_open_file()
        return False, 0

    def close(self):
        if self.first:
            for p in (self._marker, self._open_file):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass
        if self._mutex:
            _k32.CloseHandle(self._mutex)
            self._mutex = None
