# -*- coding: utf-8 -*-
"""Ежедневный резервный архив данных (zip, ротация 7 копий). Никогда не роняет приложение."""
import os
import threading
import time
import zipfile

KEEP = 7
_STORED_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.zip', '.pdf'}


def run_daily(root: str):
    tmp_path = None
    try:
        backups = os.path.join(root, 'backups')
        os.makedirs(backups, exist_ok=True)
        today = time.strftime('%Y-%m-%d')
        if any(f.startswith('backup-' + today) and f.endswith('.zip') for f in os.listdir(backups)):
            return
        path = os.path.join(backups, f'backup-{today}.zip')
        tmp_path = path + '.tmp'
        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as z:
            for name in ('folders.json', 'settings.json'):
                p = os.path.join(root, name)
                if os.path.isfile(p):
                    z.write(p, name)
            notes_dir = os.path.join(root, 'notes')
            if os.path.isdir(notes_dir):
                for f in os.listdir(notes_dir):
                    if f.endswith('.json'):
                        z.write(os.path.join(notes_dir, f), 'notes/' + f)
            att_dir = os.path.join(root, 'attachments')
            if os.path.isdir(att_dir):
                for dirpath, _dirs, files in os.walk(att_dir):
                    for f in files:
                        if f.endswith('.tmp'):
                            continue
                        full = os.path.join(dirpath, f)
                        rel = os.path.relpath(full, root).replace(os.sep, '/')
                        ext = os.path.splitext(f)[1].lower()
                        comp = zipfile.ZIP_STORED if ext in _STORED_EXTS else zipfile.ZIP_DEFLATED
                        z.write(full, rel, compress_type=comp)
        os.replace(tmp_path, path)
        tmp_path = None
        # ротация
        zips = sorted(f for f in os.listdir(backups) if f.startswith('backup-') and f.endswith('.zip'))
        for old in zips[:-KEEP]:
            try:
                os.remove(os.path.join(backups, old))
            except OSError:
                pass
    except (OSError, ValueError, zipfile.BadZipFile):
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def run_daily_async(root: str):
    """Запускает ежедневный бэкап в фоновом потоке, не блокируя интерфейс."""
    t = threading.Thread(target=run_daily, args=(root,), daemon=True)
    t.start()
    return t
