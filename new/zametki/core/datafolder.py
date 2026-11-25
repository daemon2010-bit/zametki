# -*- coding: utf-8 -*-
"""Переназначение папки данных: проверка, миграция, указатель.

Указатель хранится в файле data-location.txt в папке по умолчанию
(%APPDATA%\\Заметки), поэтому всегда находится при запуске.
"""
import os
import shutil

from . import store

_EXCLUDE = {'backups'}          # в новую папку не переносим бэкапы
_SERVICE = {'folders.json', 'settings.json'}


def get_pointer() -> str:
    try:
        with open(store.POINTER_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ''


def set_pointer(path: str):
    os.makedirs(store.APP_DIR_DEFAULT, exist_ok=True)
    tmp = store.POINTER_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(os.path.abspath(path))
    os.replace(tmp, store.POINTER_FILE)


def clear_pointer():
    try:
        os.remove(store.POINTER_FILE)
    except OSError:
        pass


def validate_dir(path: str):
    """Проверка пригодности папки. Возвращает (ok, сообщение)."""
    path = os.path.abspath(path)
    if not path or path.lower() == path.rstrip('\\') == path[:3]:
        pass
    drive = os.path.splitdrive(path)[0] + os.sep
    if os.path.abspath(path) == os.path.abspath(drive):
        return False, 'Нельзя использовать корень диска'
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, 'zametki-test.tmp')
        with open(probe, 'w') as f:
            f.write('ok')
        os.remove(probe)
    except OSError as e:
        return False, f'Папка недоступна для записи: {e}'
    if os.path.abspath(path) == os.path.abspath(store.APP_DIR_DEFAULT):
        return True, 'Это папка по умолчанию'
    return True, ''


def migrate(src_root: str, dst_root: str):
    """Перенос данных (копирование с проверкой). Возвращает (ok, сообщение).

    Копируются notes/, attachments/, versions/, folders.json, settings.json.
    Старая папка не изменяется и остаётся резервной копией.
    """
    ok, msg = validate_dir(dst_root)
    if not ok:
        return False, msg
    src_abs = os.path.abspath(src_root)
    dst_abs = os.path.abspath(dst_root)
    if src_abs == dst_abs:
        return False, 'Папка уже выбрана'
    try:
        if os.path.commonpath([src_abs, dst_abs]) == src_abs:
            return False, 'Нельзя переносить данные внутрь текущей папки данных'
    except ValueError:
        pass
    try:
        for name in ('notes', 'attachments', 'versions'):
            s = os.path.join(src_root, name)
            d = os.path.join(dst_root, name)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns('*.tmp'))
        for name in _SERVICE:
            s = os.path.join(src_root, name)
            if os.path.isfile(s):
                shutil.copy2(s, os.path.join(dst_root, name))
    except OSError as e:
        return False, f'Ошибка копирования: {e}'
    # проверка результата: количество и суммарный размер заметок
    s_n = os.path.join(src_root, 'notes')
    d_n = os.path.join(dst_root, 'notes')
    try:
        s_files = ({f: os.path.getsize(os.path.join(s_n, f))
                    for f in os.listdir(s_n) if f.endswith('.json')}
                   if os.path.isdir(s_n) else {})
        d_files = ({f: os.path.getsize(os.path.join(d_n, f))
                    for f in os.listdir(d_n) if f.endswith('.json')}
                   if os.path.isdir(d_n) else {})
    except OSError as e:
        return False, f'Ошибка проверки перенесённых заметок: {e}'
    for f, size in s_files.items():
        if d_files.get(f, -1) != size:
            return False, f'Проверка не прошла: {f} отличается'
    return True, f'Перенесено заметок: {len(s_files)}'
