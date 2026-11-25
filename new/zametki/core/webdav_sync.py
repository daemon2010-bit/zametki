# -*- coding: utf-8 -*-
"""Синхронизация заметок через интернет по WebDAV (Яндекс Диск, Nextcloud и др.).

Только стандартная библиотека Python (urllib/http.client + xml.etree), без
внешних пакетов. Единый формат JSON совместим с Android-клиентом.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from . import store as st
from . import versions
from .phoneserver import plain_to_html


def _auth_header(user: str, password: str) -> str:
    raw = f'{user}:{password}'.encode('utf-8')
    return 'Basic ' + base64.b64encode(raw).decode('ascii')


def _dav_request(url: str, method: str, user: str, password: str,
                 data: bytes = None, headers: dict = None, timeout: int = 20):
    hdrs = {'Authorization': _auth_header(user, password)}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def _ensure_dir(base_url: str, rel: str, user: str, password: str):
    rel_clean = rel.strip('/')
    url = base_url.rstrip('/') + (f'/{rel_clean}/' if rel_clean else '/')
    try:
        _dav_request(url, 'MKCOL', user, password)
    except urllib.error.HTTPError as e:
        if e.code not in (201, 301, 302, 405):
            raise


def _list_remote_json(notes_url: str, user: str, password: str) -> list:
    body = b'<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:"><d:prop><d:getlastmodified/></d:prop></d:propfind>'
    _status, data = _dav_request(
        notes_url.rstrip('/') + '/', 'PROPFIND', user, password,
        data=body, headers={'Depth': '1', 'Content-Type': 'application/xml'},
    )
    out = []
    root = ET.fromstring(data)
    for resp in root.iter():
        if resp.tag.endswith('href') and resp.text:
            href = urllib.parse.unquote(resp.text.rstrip('/'))
            name = href.rsplit('/', 1)[-1]
            if name.endswith('.json'):
                out.append(name)
    return out


def sync_webdav(store: st.Store, base_url: str, user: str, password: str) -> dict:
    """Двусторонняя синхронизация заметок с WebDAV-папкой.
    Возвращает {'pushed': int, 'pulled': int, 'errors': list[str]}."""
    base_url = (base_url or '').strip().rstrip('/')
    if not base_url:
        raise ValueError('Не указан адрес WebDAV')
    my_device = (store.setting('device_name', '') or st.default_device_name()).strip()
    my_name = (store.setting('owner_name', '') or '').strip()
    _ensure_dir(base_url, '', user, password)
    _ensure_dir(base_url, 'notes', user, password)
    notes_url = base_url + '/notes'
    remote_files = set(_list_remote_json(notes_url, user, password))

    pushed, pulled, errors = 0, 0, []
    with store._lock:
        local_map = dict(store.notes)

    all_ids = set(local_map.keys()) | {f[:-5] for f in remote_files if st.is_valid_note_id(f[:-5])}
    for nid in all_ids:
        if not st.is_valid_note_id(nid):
            continue
        fname = nid + '.json'
        local_note = local_map.get(nid)
        remote_note = None
        if fname in remote_files:
            try:
                _st, raw = _dav_request(f'{notes_url}/{fname}', 'GET', user, password)
                parsed = json.loads(raw.decode('utf-8'))
                if not isinstance(parsed, dict):
                    errors.append(f'pull {nid}: bad json')
                    continue
                remote_note = parsed
            except Exception as e:
                errors.append(f'pull {nid}: {e}')
                continue

        local_mod = st._to_ts((local_note or {}).get('modified'))
        remote_mod = st._to_ts((remote_note or {}).get('modified'))

        if remote_note and (local_note is None or remote_mod > local_mod + 0.5):
            # удалённая версия новее -> сохраняем локальную в историю версий и принимаем
            if local_note is not None:
                versions.snapshot(store.root, nid, local_note.get('html') or '')
            merged = st.make_note(str(remote_note.get('folder') or st.DEFAULT_FOLDER))
            merged.update(remote_note)
            merged['id'] = nid
            merged['created'] = st._to_ts(merged.get('created')) or time.time()
            merged['modified'] = remote_mod or time.time()
            merged['deleted_at'] = st._to_ts(merged.get('deleted_at'))
            merged['reminder_at'] = st._to_ts(merged.get('reminder_at'))
            if not merged.get('html') and merged.get('plain'):
                merged['html'] = plain_to_html(str(merged['plain']))
            r_dev = str(remote_note.get('last_device') or '').strip()
            r_snd = str(remote_note.get('last_sender') or '').strip()
            if r_dev and r_dev != my_device and not merged.get('origin'):
                merged['origin'] = {
                    'source_type': str(remote_note.get('last_device_type') or 'pc'),
                    'sender_name': r_snd,
                    'device_name': r_dev,
                    'sent_at': remote_mod,
                    'received_at': time.time(),
                }
            store.save_note(merged)
            pulled += 1
        elif local_note is not None and (remote_note is None or local_mod > remote_mod + 0.5):
            payload = dict(local_note)
            payload['last_device'] = my_device
            payload['last_device_type'] = 'pc'
            payload['last_sender'] = my_name
            try:
                body = json.dumps(payload, ensure_ascii=False, indent=1).encode('utf-8')
                _dav_request(f'{notes_url}/{fname}', 'PUT', user, password,
                             data=body, headers={'Content-Type': 'application/json; charset=utf-8'})
                pushed += 1
            except Exception as e:
                errors.append(f'push {nid}: {e}')

    return {'pushed': pushed, 'pulled': pulled, 'errors': errors}
