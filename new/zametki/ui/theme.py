# -*- coding: utf-8 -*-
"""Темы: светлая, тёмная, системная (следование настройке Windows)."""
import sys

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    'bg': '#F3F2EF', 'sidebar': '#ECEBE8', 'list': '#F7F6F3', 'editor': '#FFFFFF',
    'sel': '#FFE18F', 'sel_text': '#1D1D1F', 'hover': '#E9E7E2', 'text': '#1D1D1F',
    'text2': '#6B6A66', 'line': '#DBDAD5', 'accent': '#B8860B', 'danger': '#C0392B',
}
DARK = {
    'bg': '#232326', 'sidebar': '#1B1B1E', 'list': '#232326', 'editor': '#2A2A2E',
    'sel': '#5A4A12', 'sel_text': '#F5F5F7', 'hover': '#2E2E33', 'text': '#F5F5F7',
    'text2': '#A9A9AE', 'line': '#3C3C41', 'accent': '#FFD60A', 'danger': '#FF6B5E',
}


def _windows_apps_dark():
    """Чтение настройки темы приложений Windows (AppsUseLightTheme: 0 = тёмная)."""
    if sys.platform != 'win32':
        return None
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize',
        ) as key:
            val, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
            return val == 0
    except Exception:
        return None


def system_is_dark() -> bool:
    win_dark = _windows_apps_dark()
    if win_dark is not None:
        return win_dark
    try:
        return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def resolve(mode: str) -> dict:
    if mode == 'dark':
        return DARK
    if mode == 'light':
        return LIGHT
    return DARK if system_is_dark() else LIGHT


def apply_window_titlebar_theme(window, dark: bool) -> None:
    """Перекрашивает системный заголовок окна Windows (DWM) под светлую/тёмную тему."""
    if sys.platform != 'win32' or window is None:
        return
    try:
        import ctypes
        hwnd = int(window.winId())
        val = ctypes.c_int(1 if dark else 0)
        dwmapi = ctypes.windll.dwmapi
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (Win10 20H1+/Win11), 19 = старые сборки Win10
        res = dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
        if res != 0:
            dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def build_palette(c: dict) -> QPalette:
    """Палитра Qt: отвечает за нативные элементы (чекбоксы, плейсхолдеры,
    маркеры чек-листов в QTextBrowser, диалоги и всплывающие списки)."""
    pal = QPalette()
    bg = QColor(c['bg'])
    editor = QColor(c['editor'])
    text = QColor(c['text'])
    text2 = QColor(c['text2'])
    sel = QColor(c['sel'])
    sel_text = QColor(c['sel_text'])
    line = QColor(c['line'])
    hover = QColor(c['hover'])

    pal.setColor(QPalette.ColorRole.Window, bg)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, editor)
    pal.setColor(QPalette.ColorRole.AlternateBase, bg)
    pal.setColor(QPalette.ColorRole.ToolTipBase, editor)
    pal.setColor(QPalette.ColorRole.ToolTipText, text)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.Button, editor)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.BrightText, text)
    pal.setColor(QPalette.ColorRole.Highlight, sel)
    pal.setColor(QPalette.ColorRole.HighlightedText, sel_text)
    pal.setColor(QPalette.ColorRole.PlaceholderText, text2)
    pal.setColor(QPalette.ColorRole.Mid, line)
    pal.setColor(QPalette.ColorRole.Dark, line)
    pal.setColor(QPalette.ColorRole.Midlight, hover)
    pal.setColor(QPalette.ColorRole.Link, QColor('#60A5FA' if text.lightnessF() > 0.5 else '#2563EB'))

    # Неактивные элементы остаются читаемыми, но приглушёнными
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, text2)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, text2)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, text2)
    return pal


def build_qss(c: dict) -> str:
    return f"""
    * {{ font-family: 'Segoe UI'; }}
    QWidget {{ background: {c['bg']}; color: {c['text']}; font-size: 9pt; }}
    QLineEdit {{
        background: {c['editor']}; border: 1px solid {c['line']};
        border-radius: 9px; padding: 4px 10px; color: {c['text']}; font-size: 9pt;
        selection-background-color: {c['sel']}; selection-color: {c['sel_text']};
    }}
    QListWidget {{
        background: {c['editor']}; border: 1px solid {c['line']}; border-radius: 8px; outline: 0;
    }}
    QListWidget::item {{ color: {c['text']}; padding: 4px 8px; border-radius: 5px; }}
    QListWidget::item:selected {{ background: {c['sel']}; color: {c['sel_text']}; }}
    QListWidget::item:hover {{ background: {c['hover']}; }}
    QListWidget#notes_list {{
        background: transparent; border: none; outline: 0;
    }}
    QListWidget#notes_list::item {{ color: {c['text']}; background: transparent; padding: 0; }}
    QListWidget#notes_list::item:selected {{ background: transparent; }}
    QListWidget#notes_list::item:hover {{ background: transparent; }}
    QTextBrowser {{
        background: {c['editor']}; border: none; color: {c['text']}; font-size: 11pt;
        selection-background-color: {c['sel']}; selection-color: {c['sel_text']};
    }}
    QToolButton {{
        background: transparent; border: none; border-radius: 7px;
        padding: 3px 5px; font-size: 9pt; font-weight: normal; color: {c['text']};
    }}
    QToolButton:hover {{ background: {c['hover']}; }}
    QToolButton:checked {{ background: {c['sel']}; color: {c['sel_text']}; font-weight: 600; }}
    QToolButton:disabled {{ color: {c['text2']}; }}
    QToolButton::menu-indicator {{ image: none; }}
    QFrame#vsep {{
        color: {c['line']}; background: {c['line']};
        min-width: 1px; max-width: 1px; margin: 4px 2px;
    }}
    QPushButton {{
        background: {c['editor']}; color: {c['text']}; border: 1px solid {c['line']};
        border-radius: 9px; padding: 5px 14px; font-size: 9pt;
    }}
    QPushButton:hover {{ background: {c['hover']}; }}
    QPushButton:disabled {{ color: {c['text2']}; }}
    QComboBox, QKeySequenceEdit, QDateTimeEdit {{
        background: {c['editor']}; color: {c['text']}; border: 1px solid {c['line']};
        border-radius: 9px; padding: 4px 8px; font-size: 9pt;
    }}
    QComboBox QAbstractItemView {{
        background: {c['editor']}; color: {c['text']}; border: 1px solid {c['line']};
        border-radius: 8px; padding: 3px;
        selection-background-color: {c['sel']}; selection-color: {c['sel_text']};
        outline: 0;
    }}
    QComboBox QAbstractItemView::item {{
        color: {c['text']}; padding: 4px 10px; min-height: 20px; border-radius: 5px;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background: {c['sel']}; color: {c['sel_text']};
    }}
    QComboBox QAbstractItemView::item:hover {{
        background: {c['hover']}; color: {c['text']};
    }}
    QComboBox QLineEdit {{
        background: transparent; border: none; padding: 0; color: {c['text']};
    }}
    QCheckBox {{ background: transparent; color: {c['text']}; spacing: 7px; }}
    QDialog, QMessageBox {{ background: {c['bg']}; color: {c['text']}; }}
    QLabel {{ background: transparent; color: {c['text']}; }}
    QToolTip {{
        background: {c['editor']}; color: {c['text']};
        border: 1px solid {c['line']}; padding: 4px 7px; border-radius: 5px;
    }}
    QMenu {{
        background: {c['editor']}; color: {c['text']}; border: 1px solid {c['line']};
        border-radius: 10px; padding: 4px; font-size: 9pt;
    }}
    QMenu::item {{ padding: 5px 26px 5px 14px; border-radius: 6px; color: {c['text']}; }}
    QMenu::item:selected {{ background: {c['sel']}; color: {c['sel_text']}; }}
    QMenu::item:disabled {{ color: {c['text2']}; }}
    QMenu::separator {{ height: 1px; background: {c['line']}; margin: 4px 8px; }}
    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['line']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {c['line']}; border-radius: 4px; min-width: 30px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QSplitter::handle {{ background: {c['line']}; width: 1px; }}
    """


class ThemeManager(QObject):
    changed = Signal(dict)

    def __init__(self):
        QObject.__init__(self)
        self.mode = 'system'   # system | light | dark
        self.colors = LIGHT
        hints = QApplication.styleHints()
        hints.colorSchemeChanged.connect(lambda *_: self.reapply())

    def set_mode(self, mode: str):
        self.mode = mode if mode in ('system', 'light', 'dark') else 'system'
        self.reapply()

    def reapply(self):
        self.colors = resolve(self.mode)
        app = QApplication.instance()
        if app is not None:
            app.setPalette(build_palette(self.colors))
            app.setStyleSheet(build_qss(self.colors))
        self.changed.emit(self.colors)
