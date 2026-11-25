# -*- coding: utf-8 -*-
"""История версий заметок: снапшоты html с лимитом на заметку."""
import hashlib
import json
import os
import time

LIMIT = 20


def _dir(root: str, note_id: str) -> str:
    return os.path.join(root, 'versions', note_id)


def snapshot(root: str, note_id: str, html: str, min_interval: float = 0.0):
    """Сохранить снапшот, если текст изменился. Файл <timestamp>.json."""
    d = _dir(root, note_id)
    tmp_path = None
    try:
        os.makedirs(d, exist_ok=True)
        files = sorted(f for f in os.listdir(d) if f.endswith('.json'))
        h = hashlib.sha1(html.encode('utf-8')).hexdigest()
        last_ts = 0
        if files:
            try:
                last_ts = int(files[-1][:-5])
            except ValueError:
                last_ts = 0
            try:
                with open(os.path.join(d, files[-1]), 'r', encoding='utf-8') as f:
                    last = json.load(f)
                if isinstance(last, dict) and last.get('hash') == h:
                    return False
                if min_interval > 0 and last_ts > 0:
                    if (time.time() * 1000 - last_ts) < min_interval * 1000:
                        return False
            except (OSError, ValueError):
                pass
        ts = int(time.time() * 1000)   # миллисекунды: несколько снапшотов в одну секунду
        if ts <= last_ts:
            ts = last_ts + 1
        tmp_path = os.path.join(d, f'{ts}.json.tmp')
        dst_path = os.path.join(d, f'{ts}.json')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump({'ts': ts, 'hash': h, 'html': html}, f, ensure_ascii=False)
        os.replace(tmp_path, dst_path)
        tmp_path = None
        files = sorted(f for f in os.listdir(d) if f.endswith('.json'))
        for old in files[:-LIMIT]:
            try:
                os.remove(os.path.join(d, old))
            except OSError:
                pass
        return True
    except (OSError, ValueError):
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False


def list_versions(root: str, note_id: str):
    """Список снапшотов: [(ts, путь)] по убыванию времени."""
    d = _dir(root, note_id)
    out = []
    try:
        for f in os.listdir(d):
            if f.endswith('.json'):
                try:
                    out.append((int(f[:-5]), os.path.join(d, f)))
                except ValueError:
                    pass
    except OSError:
        pass
    return sorted(out, reverse=True)


def read_html(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f).get('html', '')
    except (OSError, ValueError):
        return ''
