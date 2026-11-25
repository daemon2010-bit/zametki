# -*- coding: utf-8 -*-
"""Диалог настроек: папка данных (с переносом), тема, сортировка, хоткей, трей."""
import os

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QKeySequenceEdit, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QVBoxLayout)

from ..core import datafolder
from ..core import i18n
from ..core import store as st


def _qr_pixmap(text: str, size: int = 128) -> QPixmap:
    """Генерирует чёткий QR-код через qrcode.QRCode без зависимости от Pillow."""
    try:
        import qrcode
        qr = qrcode.QRCode(border=2, box_size=1)
        qr.add_data(text)
        qr.make(fit=True)
        matrix = qr.get_matrix()
    except Exception:
        return QPixmap()
    n = len(matrix)
    if n <= 0:
        return QPixmap()
    scale = max(2, size // n)
    px = n * scale
    pm = QPixmap(px, px)
    pm.fill(QColor('#FFFFFF'))
    p = QPainter(pm)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor('#1D1D1F'))
    for r, row in enumerate(matrix):
        for c, val in enumerate(row):
            if val:
                p.drawRect(c * scale, r * scale, scale, scale)
    p.end()
    return pm


class SettingsDialog(QDialog):
    settings_changed = Signal(dict)   # {'theme','sort','tray','hotkey'} — применить live

    def __init__(self, store: st.Store, parent=None):
        super().__init__(parent)
        lang = i18n.normalize_lang(store.setting('lang', 'ru'))
        self.setWindowTitle(i18n.tr('settings_title', lang))
        self.setMinimumWidth(480)
        self.store = store
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        # --- папка данных ---
        self.lbl_dir = QLabel()
        self.lbl_dir.setWordWrap(True)
        self._update_dir_label()
        row = QHBoxLayout()
        self.btn_choose = QPushButton('Выбрать папку…')
        self.btn_open = QPushButton('Открыть в проводнике')
        self.btn_reset = QPushButton('Вернуть обычную')
        row.addWidget(self.btn_choose)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_reset)
        self.chk_migrate = QCheckBox('Перенести заметки в новую папку (старая останется как резервная копия)')
        self.chk_migrate.setChecked(True)
        form.addRow(QLabel('<b>Папка данных</b>'))
        form.addRow(self.lbl_dir)
        form.addRow(row)
        form.addRow('', self.chk_migrate)
        self.btn_choose.clicked.connect(self._choose_dir)
        self.btn_open.clicked.connect(self._open_dir)
        self.btn_reset.clicked.connect(self._reset_dir)

        # --- язык интерфейса ---
        self.cmb_lang = QComboBox()
        self.cmb_lang.addItems(['Русский', 'English'])
        self.cmb_lang.setCurrentIndex({'ru': 0, 'en': 1}.get(lang, 0))
        form.addRow(i18n.tr('language', lang), self.cmb_lang)

        # --- тема: день / ночь / как в Windows ---
        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(
            ['System (Windows)', 'Light', 'Dark'] if lang == 'en'
            else ['Как в Windows', 'Светлая (день)', 'Тёмная (ночь)']
        )
        self.cmb_theme.setCurrentIndex({'system': 0, 'light': 1, 'dark': 2}.get(
            store.setting('theme', 'system'), 0))
        form.addRow(i18n.tr('theme', lang), self.cmb_theme)

        # --- сортировка ---
        self.cmb_sort = QComboBox()
        self.cmb_sort.addItems(
            ['By modified date', 'By created date', 'By title'] if lang == 'en'
            else ['По дате изменения', 'По дате создания', 'По названию']
        )
        self.cmb_sort.setCurrentIndex({'modified': 0, 'created': 1, 'title': 2}.get(
            store.setting('sort', 'modified'), 0))
        form.addRow(i18n.tr('sort', lang), self.cmb_sort)

        # --- хоткей ---
        self.ks_hotkey = QKeySequenceEdit(QKeySequence(store.setting('hotkey', 'Ctrl+Alt+N')))
        form.addRow(i18n.tr('hotkey', lang), self.ks_hotkey)

        # --- трей и корзина ---
        self.chk_tray = QCheckBox(i18n.tr('tray_chk', lang))
        self.chk_tray.setChecked(bool(store.setting('tray', False)))
        form.addRow('', self.chk_tray)

        self.chk_auto_purge = QCheckBox(i18n.tr('auto_purge_chk', lang))
        self.chk_auto_purge.setChecked(bool(store.setting('auto_purge_trash', True)))
        form.addRow('', self.chk_auto_purge)

        # --- телефон ---
        form.addRow(QLabel('<b>Телефон</b>'))
        self.chk_phone = QCheckBox('Открыть доступ заметкам со смартфона (локальная сеть)')
        self.chk_phone.setChecked(bool(store.setting('phone', False)))
        form.addRow('', self.chk_phone)
        self.lbl_phone = QLabel()
        self.lbl_phone.setWordWrap(True)
        self.lbl_phone.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._phone_url = getattr(parent, 'phone_url', lambda: '')() if parent else ''
        phone_row = QHBoxLayout()
        phone_row.addWidget(self.lbl_phone, 1)
        self.btn_copy_phone = QPushButton('Копировать')
        self.btn_copy_phone.clicked.connect(self._copy_phone_url)
        self.btn_copy_phone.setVisible(bool(self._phone_url))
        phone_row.addWidget(self.btn_copy_phone)
        self.lbl_phone.setText(self._phone_url if store.setting('phone', False) else
                               'Адрес для телефона появится здесь после включения.')
        form.addRow('Адрес', phone_row)
        self.lbl_qr = QLabel()
        self.lbl_qr.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if self._phone_url:
            pm = _qr_pixmap(self._phone_url, 128)
            if not pm.isNull():
                self.lbl_qr.setPixmap(pm)
                form.addRow('QR-код', self.lbl_qr)
        note = QLabel('Телефон в том же Wi-Fi. Внешний интернет не используется, '
                      'доступ по постоянному токену. Правка с телефона - текстом без форматирования.')
        note.setWordWrap(True)
        note.setStyleSheet('font-size: 8pt;')
        form.addRow('', note)

        # --- устройство, обмен .zametka и WebDAV ---
        form.addRow(QLabel('<b>Устройство и обмен</b>'))
        self.ed_owner = QLineEdit(str(store.setting('owner_name', '') or ''))
        self.ed_owner.setPlaceholderText('Например: Алексей (для подписи отправляемых заметок)')
        form.addRow('Ваше имя', self.ed_owner)
        self.ed_device = QLineEdit(str(store.setting('device_name', '') or st.default_device_name()))
        form.addRow('Имя этого ПК', self.ed_device)
        self.btn_assoc = QPushButton('Открывать файлы .zametka двойным кликом в Windows')
        self.btn_assoc.clicked.connect(self._associate_zametka)
        form.addRow('', self.btn_assoc)

        form.addRow(QLabel('<b>Синхронизация через интернет (WebDAV)</b>'))
        self.ed_dav_url = QLineEdit(str(store.setting('webdav_url', '') or ''))
        self.ed_dav_url.setPlaceholderText('https://webdav.yandex.ru/Zametki')
        form.addRow('Адрес WebDAV', self.ed_dav_url)
        self.ed_dav_user = QLineEdit(str(store.setting('webdav_user', '') or ''))
        form.addRow('Логин', self.ed_dav_user)
        self.ed_dav_pass = QLineEdit(st.unprotect_secret(str(store.setting('webdav_pass', '') or '')))
        self.ed_dav_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('Пароль приложения', self.ed_dav_pass)

        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_dir_label(self):
        cur = st.data_dir()
        suffix = ' (по умолчанию)' if os.path.abspath(cur) == os.path.abspath(st.APP_DIR_DEFAULT) else ''
        self.lbl_dir.setText(cur + suffix)

    def _choose_dir(self):
        start = st.data_dir()
        path = QFileDialog.getExistingDirectory(self, 'Выбрать папку данных', start)
        if not path:
            return
        ok, msg = datafolder.validate_dir(path)
        if not ok:
            QMessageBox.warning(self, 'Папка данных', msg)
            return
        self._pending_dir = path
        self._pending_reset = False
        self.lbl_dir.setText('Новая папка: ' + os.path.abspath(path) +
                             ' (применится по кнопке «OK»)')

    def _reset_dir(self):
        self._pending_dir = None
        self._pending_reset = True
        self.lbl_dir.setText(st.APP_DIR_DEFAULT + ' (по умолчанию, применится по кнопке «OK»)')

    def _copy_phone_url(self):
        if not self._phone_url:
            return
        QApplication.clipboard().setText(self._phone_url)
        self.btn_copy_phone.setText('Скопировано!')
        if not hasattr(self, '_copy_timer'):
            self._copy_timer = QTimer(self)
            self._copy_timer.setSingleShot(True)
            self._copy_timer.setInterval(1500)
            self._copy_timer.timeout.connect(lambda: self.btn_copy_phone.setText('Копировать'))
        self._copy_timer.start()

    def _associate_zametka(self):
        """Регистрирует .zametka в HKCU\\Software\\Classes (без прав администратора)."""
        import sys
        if sys.platform != 'win32':
            return
        try:
            import winreg
            exe = sys.executable
            cmd = f'"{exe}" "%1"' if getattr(sys, 'frozen', False) else f'"{exe}" "{os.path.abspath(sys.argv[0])}" "%1"'
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Classes\.zametka') as k:
                winreg.SetValueEx(k, '', 0, winreg.REG_SZ, 'Zametki.NotePackage')
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Classes\Zametki.NotePackage') as k:
                winreg.SetValueEx(k, '', 0, winreg.REG_SZ, 'Заметка (.zametka)')
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Classes\Zametki.NotePackage\shell\open\command') as k:
                winreg.SetValueEx(k, '', 0, winreg.REG_SZ, cmd)
            QMessageBox.information(self, 'Ассоциация файлов',
                                    'Готово! Файлы .zametka теперь открываются в Заметках двойным кликом.')
        except OSError as e:
            QMessageBox.warning(self, 'Ассоциация файлов', f'Не удалось записать в реестр: {e}')

    def _open_dir(self):
        os.startfile(st.data_dir())

    def _apply(self):
        # 1) смена или сброс папки данных
        if getattr(self, '_pending_reset', False):
            datafolder.clear_pointer()
            QMessageBox.information(self, 'Папка данных',
                                    'Указатель сброшен. После перезапуска приложение вернётся к папке по умолчанию.')
        new_dir = getattr(self, '_pending_dir', None)
        if new_dir:
            if self.chk_migrate.isChecked():
                ok, msg = datafolder.migrate(st.data_dir(), new_dir)
                if not ok:
                    QMessageBox.warning(self, 'Папка данных', 'Перенос не выполнен: ' + msg)
                    return
                datafolder.set_pointer(new_dir)
                QMessageBox.information(self, 'Папка данных',
                                        msg + '.\nСтарая папка оставлена как резервная копия. Перезапустите приложение для работы с новой папкой.')
            else:
                datafolder.set_pointer(new_dir)
                QMessageBox.information(self, 'Папка данных',
                                        'Новая папка назначена без переноса. Перезапустите приложение для применения.')
        # 2) настройки
        new_lang = {0: 'ru', 1: 'en'}[self.cmb_lang.currentIndex()]
        theme = {0: 'system', 1: 'light', 2: 'dark'}[self.cmb_theme.currentIndex()]
        sort = {0: 'modified', 1: 'created', 2: 'title'}[self.cmb_sort.currentIndex()]
        hotkey = self.ks_hotkey.keySequence().toString() or ''
        vals = {'lang': new_lang, 'theme': theme, 'sort': sort, 'tray': self.chk_tray.isChecked(),
                'auto_purge_trash': self.chk_auto_purge.isChecked(),
                'hotkey': hotkey, 'phone': self.chk_phone.isChecked(),
                'owner_name': self.ed_owner.text().strip(),
                'device_name': self.ed_device.text().strip() or st.default_device_name(),
                'webdav_url': self.ed_dav_url.text().strip(),
                'webdav_user': self.ed_dav_user.text().strip(),
                'webdav_pass': st.protect_secret(self.ed_dav_pass.text())}
        self.settings_changed.emit(vals)
        if self.chk_phone.isChecked() and not self._phone_url:
            parent_win = self.parent()
            url = parent_win.phone_url() if hasattr(parent_win, 'phone_url') else ''
            if url:
                QMessageBox.information(self, 'Телефон',
                                        'Доступ открыт. Адрес для телефона:\n' + url)
        self.accept()
