# -*- coding: utf-8 -*-
"""Хранилище данных: папка данных, заметки (JSON), папки, настройки.

Совместимо со старым приложением: заметки в notes/*.json, folders.json,
settings.json; переменная окружения ZAMETKI_HOME остаётся старшим приоритетом.
Все записи на диск атомарные (через .tmp + os.replace).
"""
import base64
import json
import os
import re
import socket
import sys
import threading
import time
import uuid

VALID_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def is_valid_note_id(nid) -> bool:
    return isinstance(nid, str) and bool(VALID_ID_RE.match(nid))


def protect_secret(plain: str) -> str:
    """Шифрует секрет (пароль WebDAV) средствами Windows DPAPI текущего пользователя."""
    if not plain:
        return ''
    if plain.startswith('dpapi:'):
        return plain
    if sys.platform != 'win32':
        return plain
    try:
        import ctypes
        import ctypes.wintypes as wt

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wt.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

        raw = plain.encode('utf-8')
        buf = ctypes.create_string_buffer(raw, len(raw))
        blob_in = DATA_BLOB(len(raw), buf)
        blob_out = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        k32 = ctypes.windll.kernel32
        if crypt32.CryptProtectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
            try:
                enc = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                return 'dpapi:' + base64.b64encode(enc).decode('ascii')
            finally:
                k32.LocalFree(blob_out.pbData)
    except Exception:
        pass
    return plain


def unprotect_secret(stored: str) -> str:
    """Расшифровывает секрет, сохранённый через protect_secret()."""
    if not stored:
        return ''
    if not stored.startswith('dpapi:'):
        return stored
    if sys.platform != 'win32':
        return ''
    try:
        import ctypes
        import ctypes.wintypes as wt

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wt.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

        raw = base64.b64decode(stored[6:])
        buf = ctypes.create_string_buffer(raw, len(raw))
        blob_in = DATA_BLOB(len(raw), buf)
        blob_out = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        k32 = ctypes.windll.kernel32
        if crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
            try:
                return ctypes.string_at(blob_out.pbData, blob_out.cbData).decode('utf-8')
            finally:
                k32.LocalFree(blob_out.pbData)
    except Exception:
        pass
    return ''


def default_device_name() -> str:
    try:
        return socket.gethostname() or 'Мой ПК'
    except Exception:
        return 'Мой ПК'

APP_DIR_DEFAULT = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'Заметки')
POINTER_FILE = os.path.join(APP_DIR_DEFAULT, 'data-location.txt')
ENV_VAR = 'ZAMETKI_HOME'

DEFAULT_FOLDER = 'notes'   # идентификатор папки «Заметки» (как в старом приложении)
TRASH = 'trash'            # виртуальная папка «Недавно удалённые»


def data_dir() -> str:
    """Текущая папка данных: ZAMETKI_HOME > указатель > папка по умолчанию."""
    env = os.environ.get(ENV_VAR, '').strip()
    if env:
        return os.path.abspath(env)
    try:
        with open(POINTER_FILE, 'r', encoding='utf-8') as f:
            p = f.read().strip()
        if p and os.path.isdir(p):
            return os.path.abspath(p)
    except OSError:
        pass
    return APP_DIR_DEFAULT


def new_id() -> str:
    return str(uuid.uuid4())


_WRITE_LOCK = threading.RLock()   # записи и чтение из GUI и веб-сервера не должны смешиваться


def _atomic_write(path: str, text: str) -> None:
    tmp = path + '.tmp'
    with _WRITE_LOCK:
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write(text)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            # на Windows антивирус/индексатор может на мгновение занять файл
            for attempt in range(5):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.05)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise


def _read_json(path: str, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def make_note(folder: str = DEFAULT_FOLDER) -> dict:
    now = time.time()
    return {
        'id': new_id(),
        'folder': folder,
        'title': '',
        'html': '',
        'plain': '',
        'snippet': '',
        'created': now,
        'modified': now,
        'deleted': False,
        'deleted_at': 0.0,
        'pinned': False,
        # новые поля (старый exe их игнорирует)
        'color': '',
        'attachments': [],
        'reminder_at': 0.0,
        'title_size': 0.0,   # размер заголовка первой строки (0 — авто 17pt)
        'origin': None,      # происхождение: {'source_type','sender_name','device_name','sent_at','received_at'}
    }


def _to_ts(value):
    """Дата/время -> float. Терпит ISO-строки старого приложения и мусор."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return 0.0
        try:
            return float(s)
        except ValueError:
            pass
        try:
            from datetime import datetime
            return datetime.fromisoformat(s).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def num_or_zero(value) -> float:
    """Число или 0.0 — для безопасной сортировки."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def note_plain_parts(plain: str):
    """Заголовок и сниппет из plain-текста: первая строка — заголовок."""
    lines = [ln.strip() for ln in plain.splitlines()]
    lines = [ln for ln in lines if ln]
    title = lines[0] if lines else ''
    rest = ' '.join(lines[1:])
    return title, rest[:200]


class Store:
    def __init__(self, root: str = None):
        self.root = os.path.abspath(root) if root else data_dir()
        self.notes_dir = os.path.join(self.root, 'notes')
        self.attach_dir = os.path.join(self.root, 'attachments')
        self.versions_root = os.path.join(self.root, 'versions')
        os.makedirs(self.notes_dir, exist_ok=True)
        os.makedirs(self.attach_dir, exist_ok=True)
        self._lock = _WRITE_LOCK
        self.notes = {}       # id -> dict
        self.folders = []     # [{'id','name','created'}]
        self.settings = {}
        self._recover_tmp()
        self._load_settings()
        self._load_folders()
        self._load_notes()

    # ---------- восстановление после сбоя ----------
    def _recover_tmp(self):
        for name in os.listdir(self.notes_dir):
            if not name.endswith('.json.tmp'):
                continue
            base_path = os.path.join(self.notes_dir, name[:-4])
            tmp_path = os.path.join(self.notes_dir, name)
            ok = False
            try:
                with open(tmp_path, 'r', encoding='utf-8') as f:
                    json.load(f)
                ok = True
            except (OSError, ValueError):
                ok = False
            if ok and not os.path.exists(base_path):
                os.replace(tmp_path, base_path)   # недописанная заметка — подбираем
            else:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    # ---------- загрузка ----------
    def _load_settings(self):
        self.settings = _read_json(os.path.join(self.root, 'settings.json'), {}) or {}

    def _load_folders(self):
        data = _read_json(os.path.join(self.root, 'folders.json'), None)
        folders = []
        if isinstance(data, dict):
            for it in data.get('folders', []):
                if isinstance(it, dict) and it.get('id') and it.get('name'):
                    folders.append({'id': str(it['id']), 'name': str(it['name']),
                                    'created': float(it.get('created', 0.0))})
        if not any(f['id'] == DEFAULT_FOLDER for f in folders):
            folders.insert(0, {'id': DEFAULT_FOLDER, 'name': 'Заметки', 'created': time.time()})
        self.folders = folders
        if not isinstance(data, dict):
            self.save_folders()

    def _load_notes(self):
        self.notes = {}
        for name in os.listdir(self.notes_dir):
            if not name.endswith('.json'):
                continue
            note = _read_json(os.path.join(self.notes_dir, name), None)
            if not isinstance(note, dict) or not is_valid_note_id(note.get('id')):
                continue
            # нормализация полей (неизвестные поля сохраняем для прямой совместимости)
            base = make_note()
            base.update(note)
            for k, v in (('created', 0.0), ('modified', 0.0), ('deleted_at', 0.0),
                         ('pinned', False), ('deleted', False), ('color', ''),
                         ('reminder_at', 0.0), ('folder', DEFAULT_FOLDER)):
                if not base.get(k):
                    base[k] = v
            # даты: старое приложение могло писать их строками — приводим к числу
            for k in ('created', 'modified', 'deleted_at', 'reminder_at'):
                base[k] = _to_ts(base.get(k))
            # размер заголовка первой строки — число
            try:
                base['title_size'] = float(base.get('title_size', 0.0) or 0.0)
            except (TypeError, ValueError):
                base['title_size'] = 0.0
            # текстовые поля — строго строки
            for k in ('title', 'html', 'plain', 'snippet', 'color', 'folder'):
                base[k] = str(base.get(k) or '')
            self.notes[base['id']] = base

    # ---------- сохранение ----------
    def save_settings(self):
        with self._lock:
            _atomic_write(os.path.join(self.root, 'settings.json'),
                          json.dumps(self.settings, ensure_ascii=False, indent=1))

    def save_folders(self):
        with self._lock:
            _atomic_write(os.path.join(self.root, 'folders.json'),
                          json.dumps({'folders': self.folders}, ensure_ascii=False, indent=1))

    def save_note(self, note: dict):
        nid = note.get('id')
        if not is_valid_note_id(nid):
            raise ValueError(f'Некорректный ID заметки: {nid!r}')
        with self._lock:
            self.notes[nid] = note
            _atomic_write(os.path.join(self.notes_dir, nid + '.json'),
                          json.dumps(note, ensure_ascii=False, indent=1))

    # ---------- заметки ----------
    def create_note(self, folder: str = DEFAULT_FOLDER) -> dict:
        with self._lock:
            note = make_note(folder)
            self.save_note(note)
            return note

    def duplicate_note(self, src: dict) -> dict:
        with self._lock:
            note = {k: v for k, v in src.items()}
            note['attachments'] = list(src.get('attachments') or [])
            note['id'] = new_id()
            note['created'] = note['modified'] = time.time()
            note['pinned'] = False
            note['deleted'] = False
            note['deleted_at'] = 0.0
            note['reminder_at'] = 0.0
            old_prefix = f'attachments/{src["id"]}/'
            new_prefix = f'attachments/{note["id"]}/'
            if old_prefix in (note.get('html') or ''):
                note['html'] = note['html'].replace(old_prefix, new_prefix)
            # копия вложений
            src_dir = os.path.join(self.attach_dir, src['id'])
            if os.path.isdir(src_dir):
                dst_dir = os.path.join(self.attach_dir, note['id'])
                try:
                    os.makedirs(dst_dir, exist_ok=True)
                    for name in os.listdir(src_dir):
                        with open(os.path.join(src_dir, name), 'rb') as fi:
                            data = fi.read()
                        with open(os.path.join(dst_dir, name), 'wb') as fo:
                            fo.write(data)
                except OSError:
                    pass
            self.save_note(note)
            return note

    def trash_note(self, note: dict):
        with self._lock:
            now = time.time()
            note['deleted'] = True
            note['deleted_at'] = now
            note['modified'] = now
            note['pinned'] = False
            self.save_note(note)

    def restore_note(self, note: dict):
        with self._lock:
            note['deleted'] = False
            note['deleted_at'] = 0.0
            note['modified'] = time.time()
            if note['folder'] not in {f['id'] for f in self.folders}:
                note['folder'] = DEFAULT_FOLDER
            self.save_note(note)

    def purge_note(self, note: dict):
        nid = note.get('id')
        if not is_valid_note_id(nid):
            return
        with self._lock:
            self.notes.pop(nid, None)
            try:
                os.remove(os.path.join(self.notes_dir, nid + '.json'))
            except OSError:
                pass
            import shutil
            for d in (os.path.join(self.attach_dir, nid),
                      os.path.join(self.versions_root, nid)):
                shutil.rmtree(d, ignore_errors=True)

    def purge_expired_trash(self, days: int = 30) -> int:
        """Удаляет навсегда заметки из корзины старше указанного числа дней."""
        cutoff = time.time() - max(1, int(days)) * 86400
        with self._lock:
            expired = [
                n for n in list(self.notes.values())
                if n.get('deleted') and (n.get('deleted_at') or 0) > 0 and n['deleted_at'] < cutoff
            ]
            for n in expired:
                self.purge_note(n)
            return len(expired)

    # ---------- папки ----------
    def add_folder(self, name: str) -> dict:
        f = {'id': new_id(), 'name': name, 'created': time.time()}
        self.folders.append(f)
        self.save_folders()
        return f

    def rename_folder(self, fid: str, name: str):
        for f in self.folders:
            if f['id'] == fid:
                f['name'] = name
        self.save_folders()

    def delete_folder(self, fid: str):
        """Заметки папки перемещаются в корзину."""
        if fid == DEFAULT_FOLDER:
            return
        for note in list(self.notes.values()):
            if note['folder'] == fid and not note['deleted']:
                self.trash_note(note)
        self.folders = [f for f in self.folders if f['id'] != fid]
        self.save_folders()

    # ---------- подсчёты ----------
    def count(self, fid: str) -> int:
        with self._lock:
            n = 0
            for note in self.notes.values():
                if note['deleted']:
                    continue
                if fid == TRASH:
                    continue
                if note['folder'] == fid:
                    n += 1
            return n

    def trash_count(self) -> int:
        with self._lock:
            return sum(1 for n in self.notes.values() if n['deleted'])

    def folder_name(self, fid: str) -> str:
        for f in self.folders:
            if f['id'] == fid:
                return f['name']
        return 'Заметки'

    # ---------- настройки-хелперы ----------
    def setting(self, key: str, default):
        return self.settings.get(key, default)

    def set_setting(self, key: str, value):
        with self._lock:
            self.settings[key] = value
            self.save_settings()

    def set_settings(self, vals: dict):
        with self._lock:
            self.settings.update(vals)
            self.save_settings()
