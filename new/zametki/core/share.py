# -*- coding: utf-8 -*-
"""Обмен заметками пакетом .zametka (ZIP: note.json + attachments + origin).

Файл .zametka можно пересылать через MAX, Telegram, WhatsApp, почту и открывать
на ПК (Windows) и Android. При импорте автоматически сохраняется происхождение
(от кого / с какого устройства / когда получена) с возможностью очистить метку.
"""
import base64
import json
import os
import time
import zipfile
import zlib

from . import store as st

MANIFEST_NAME = 'zametka-manifest.json'
NOTE_NAME = 'note.json'
FORMAT_VERSION = 1
MAX_JSON_BYTES = 2 * 1024 * 1024        # 2 МБ на JSON (защита от Zip-бомб)
MAX_ATTACH_TOTAL_BYTES = 25 * 1024 * 1024  # 25 МБ суммарно на вложения
MAX_ATTACH_COUNT = 50
QR_PREFIX = 'zametka1:'
MAX_QR_PAYLOAD_LEN = 2200


def encode_note_qr(store: st.Store, note: dict):
    """Кодирует заметку для офлайн QR-кода (zlib + urlsafe base64).
    Возвращает (payload_str, error_msg). При успехе error_msg == ''."""
    plain = str(note.get('plain') or '').strip()
    if not plain:
        return '', 'Заметка пуста'
    data = {
        'p': plain,
        'c': str(note.get('color') or ''),
        's': (store.setting('owner_name', '') or '').strip(),
        'd': (store.setting('device_name', '') or st.default_device_name()).strip(),
        't': int(time.time()),
    }
    raw = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    comp = zlib.compress(raw, level=9)
    payload = QR_PREFIX + base64.urlsafe_b64encode(comp).decode('ascii')
    if len(payload) > MAX_QR_PAYLOAD_LEN:
        return '', 'Заметка слишком большая для офлайн QR-кода - используйте Wi-Fi синхронизацию или файл .zametka'
    return payload, ''


def decode_note_qr(payload: str) -> dict:
    """Декодирует офлайн QR-строку zametka1:... обратно в словарь заметки."""
    if not isinstance(payload, str) or not payload.startswith(QR_PREFIX):
        raise ValueError('Неверный формат QR-кода заметки')
    raw_b64 = payload[len(QR_PREFIX):].strip()
    comp = base64.urlsafe_b64decode(raw_b64.encode('ascii'))
    raw = zlib.decompress(comp, bufsize=65536)
    if len(raw) > 256 * 1024:
        raise ValueError('Слишком большой объём данных в QR')
    obj = json.loads(raw.decode('utf-8'))
    if not isinstance(obj, dict) or not isinstance(obj.get('p'), str):
        raise ValueError('Повреждённые данные QR')
    return obj


def _read_zip_limited(zf: zipfile.ZipFile, name: str, max_bytes: int) -> bytes:
    """Читает элемент ZIP порциями с жёстким лимитом распакованного размера."""
    chunks = []
    total = 0
    with zf.open(name, 'r') as src:
        while True:
            chunk = src.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f'Элемент {name} превышает лимит {max_bytes} байт')
            chunks.append(chunk)
    return b''.join(chunks)


def export_zametka(store: st.Store, note: dict, dst_path: str,
                   sender_name: str = '', device_name: str = '') -> str:
    """Упаковывает заметку и её вложения в один файл .zametka."""
    if not dst_path.lower().endswith('.zametka'):
        dst_path += '.zametka'
    sender = (sender_name or store.setting('owner_name', '') or '').strip()
    device = (device_name or store.setting('device_name', '') or st.default_device_name()).strip()
    manifest = {
        'format': FORMAT_VERSION,
        'app': 'zametki',
        'exported_at': time.time(),
        'origin': {
            'source_type': 'friend' if sender else 'pc',
            'sender_name': sender,
            'device_name': device,
            'sent_at': time.time(),
        },
    }
    payload = dict(note)
    # при экспорте очищаем локальный статус корзины/напоминания
    payload['deleted'] = False
    payload['deleted_at'] = 0.0
    payload['reminder_at'] = 0.0
    tmp = dst_path + '.tmp'
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=1))
            z.writestr(NOTE_NAME, json.dumps(payload, ensure_ascii=False, indent=1))
            att_dir = os.path.join(store.attach_dir, note['id'])
            if os.path.isdir(att_dir):
                for fname in os.listdir(att_dir):
                    full = os.path.join(att_dir, fname)
                    if os.path.isfile(full) and not fname.endswith('.tmp'):
                        z.write(full, f'attachments/{fname}', compress_type=zipfile.ZIP_STORED)
        os.replace(tmp, dst_path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise
    return dst_path


def is_zametka_file(path: str) -> bool:
    """Проверяет, что файл является пакетом .zametka (по содержимому ZIP)."""
    if not path or not os.path.isfile(path):
        return False
    try:
        with zipfile.ZipFile(path, 'r') as z:
            names = set(z.namelist())
            return NOTE_NAME in names and MANIFEST_NAME in names
    except (OSError, zipfile.BadZipFile):
        return False


def import_zametka(store: st.Store, src_path: str) -> dict:
    """Импортирует пакет .zametka как новую заметку с меткой происхождения origin."""
    with zipfile.ZipFile(src_path, 'r') as z:
        manifest = json.loads(_read_zip_limited(z, MANIFEST_NAME, MAX_JSON_BYTES).decode('utf-8'))
        raw_note = json.loads(_read_zip_limited(z, NOTE_NAME, MAX_JSON_BYTES).decode('utf-8'))
        old_id = str(raw_note.get('id') or '')
        note = st.make_note(st.DEFAULT_FOLDER)
        for k in ('title', 'html', 'plain', 'snippet', 'color', 'title_size'):
            if k in raw_note and raw_note[k] is not None:
                note[k] = raw_note[k]
        if not note['plain'] and note['html']:
            note['plain'] = note['title'] or ''
        title, snippet = st.note_plain_parts(note['plain'])
        if title:
            note['title'] = title
        if snippet:
            note['snippet'] = snippet
        # переписываем пути вложений на новый id (с защитой от Zip-бомб)
        new_id = note['id']
        att_members = [m for m in z.namelist()
                       if m.startswith('attachments/') and not m.endswith('/')]
        if len(att_members) > MAX_ATTACH_COUNT:
            raise ValueError('Слишком много вложений в пакете .zametka')
        if att_members:
            dst_att = os.path.join(store.attach_dir, new_id)
            os.makedirs(dst_att, exist_ok=True)
            att_total = 0
            for member in att_members:
                fname = os.path.basename(member)
                if not fname:
                    continue
                remain = MAX_ATTACH_TOTAL_BYTES - att_total
                if remain <= 0:
                    raise ValueError('Суммарный размер вложений превышает 25 МБ')
                data = _read_zip_limited(z, member, remain)
                att_total += len(data)
                with open(os.path.join(dst_att, fname), 'wb') as out:
                    out.write(data)
            if old_id and f'attachments/{old_id}/' in note['html']:
                note['html'] = note['html'].replace(
                    f'attachments/{old_id}/', f'attachments/{new_id}/')
        # фиксируем происхождение (от кого / с какого устройства / когда получена)
        m_origin = manifest.get('origin') if isinstance(manifest, dict) else {}
        if not isinstance(m_origin, dict):
            m_origin = {}
        sender = str(m_origin.get('sender_name') or '').strip()
        device = str(m_origin.get('device_name') or '').strip()
        src_type = str(m_origin.get('source_type') or ('friend' if sender else 'pc'))
        note['origin'] = {
            'source_type': src_type,
            'sender_name': sender,
            'device_name': device,
            'sent_at': float(m_origin.get('sent_at') or manifest.get('exported_at') or 0.0),
            'received_at': time.time(),
        }
        note['created'] = note['modified'] = time.time()
        store.save_note(note)
        return note
