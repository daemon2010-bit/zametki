# -*- coding: utf-8 -*-
"""Глобальная горячая клавиша Windows (RegisterHotKey через ctypes, без сторонних библиотек)."""
import ctypes
import ctypes.wintypes as wt

from PySide6.QtCore import QObject, QAbstractNativeEventFilter, Signal

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000

_u32 = ctypes.WinDLL('user32', use_last_error=True)
_u32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
_u32.RegisterHotKey.restype = wt.BOOL
_u32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
_u32.UnregisterHotKey.restype = wt.BOOL
_u32.VkKeyScanW.argtypes = [wt.WCHAR]
_u32.VkKeyScanW.restype = ctypes.c_short

_NAMED_VK = {
    'space': 0x20, 'tab': 0x09, 'return': 0x0D, 'enter': 0x0D,
    'esc': 0x1B, 'escape': 0x1B, 'backspace': 0x08, 'insert': 0x2D,
    'ins': 0x2D, 'delete': 0x2E, 'del': 0x2E, 'home': 0x24, 'end': 0x23,
    'pgup': 0x21, 'pageup': 0x21, 'pgdown': 0x22, 'pagedown': 0x22,
    'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28,
}


def sequence_to_vk_mod(sequence_text: str):
    """'Ctrl+Alt+N' -> (vk, modifiers) или None, если не удалось."""
    text = (sequence_text or '').strip()
    if not text:
        return None
    parts = [p.strip().lower() for p in text.split('+') if p.strip()]
    mods = 0
    key = ''
    for p in parts:
        if p in ('ctrl', 'control'):
            mods |= MOD_CONTROL
        elif p == 'alt':
            mods |= MOD_ALT
        elif p == 'shift':
            mods |= MOD_SHIFT
        elif p in ('meta', 'win'):
            mods |= 0x8  # MOD_WIN
        else:
            key = p
    if not key:
        return None
    if key in _NAMED_VK:
        return _NAMED_VK[key], mods | MOD_NOREPEAT
    if len(key) > 3:
        return None
    # буквы и цифры: VK-код совпадает с ASCII и не зависит от раскладки
    up = key.upper()
    if len(up) == 1 and 'A' <= up <= 'Z':
        vk = ord(up)
    elif len(up) == 1 and '0' <= up <= '9':
        vk = ord(up)
    elif up.startswith('F') and up[1:].isdigit() and 1 <= int(up[1:]) <= 24:
        vk = 0x70 + int(up[1:]) - 1   # F1..F24
    else:
        # знаки — через текущую раскладку
        vk = _u32.VkKeyScanW(key[0]) & 0xFF
        if vk == 0xFF:
            return None
    return vk, mods | MOD_NOREPEAT


class GlobalHotkey(QAbstractNativeEventFilter, QObject):
    triggered = Signal()

    def __init__(self):
        QAbstractNativeEventFilter.__init__(self)
        QObject.__init__(self)
        self._registered = False
        self._hwnd = None

    def register(self, hwnd, sequence_text: str) -> bool:
        self.unregister()
        parsed = sequence_to_vk_mod(sequence_text)
        if not parsed:
            return False
        vk, mods = parsed
        if not _u32.RegisterHotKey(wt.HWND(int(hwnd)), 1, mods, vk):
            return False
        self._registered = True
        self._hwnd = int(hwnd)
        return True

    def unregister(self):
        if self._registered and self._hwnd is not None:
            _u32.UnregisterHotKey(wt.HWND(self._hwnd), 1)
        self._registered = False

    def nativeEventFilter(self, event_type, message):
        if event_type == b'windows_generic_MSG':
            msg = wt.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == 1:
                self.triggered.emit()
        return False, 0
