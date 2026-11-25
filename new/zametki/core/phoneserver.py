# -*- coding: utf-8 -*-
"""Режим «Телефон»: локальный веб-сервер для работы с заметками со смартфона.

Работает только в домашней сети (тот же Wi-Fi), доступ по токену из настроек.
Внешние облака не используются; пока сервер включён — заметки на телефоне
и в приложении синхронны (общее хранилище). Телефон редактирует текст
(без форматирования): при сохранении с телефона html пересобирается из текста.
"""
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from PySide6.QtCore import QObject, Signal

from . import store as st
from . import versions
from .store import note_plain_parts

MAX_BODY_BYTES = 2 * 1024 * 1024   # 2 МБ на запрос от телефона


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('192.168.255.255', 1))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return '127.0.0.1'


def plain_to_html(plain: str) -> str:
    def esc(s):
        return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    lines = plain.split('\n')
    if not any(ln.strip() for ln in lines):
        return '<p></p>'
    return ''.join(f'<p style="margin-top:0px;">{esc(ln) if ln else "<br>"}</p>' for ln in lines)


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Заметки</title><style>
body{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;margin:0;background:#f3f2ef;color:#1d1d1f}
#bar{position:sticky;top:0;background:#ffcf33;padding:12px 16px;font-weight:700;display:flex;justify-content:space-between;align-items:center}
#bar button{border:0;background:#fff;border-radius:8px;padding:6px 12px;font-size:15px}
ul{list-style:none;margin:0;padding:8px} li{background:#fff;border-radius:10px;padding:10px 14px;margin:6px 0}
li b{display:block;font-size:16px} li span{color:#6b6a66;font-size:13px}
textarea{width:100%;height:60vh;border:0;font-size:17px;padding:14px;box-sizing:border-box;background:#fff;color:#1d1d1f}
#edit{display:none} #edit #tools{display:flex;gap:8px;padding:8px;background:#ecebe8}
#edit #tools button{flex:1;border:0;border-radius:9px;padding:10px;font-size:15px;background:#fff;color:#1d1d1f}
#hint{padding:10px 14px;color:#6b6a66;font-size:12px}
@media (prefers-color-scheme: dark){
  body{background:#1b1b1e;color:#f5f5f7}
  #bar{background:#5a4a12;color:#f5f5f7}
  #bar button,li,textarea,#edit #tools button{background:#2a2a2e;color:#f5f5f7}
  li span,#hint{color:#a9a9ae}
  #edit #tools{background:#232326}
}
</style></head><body>
<div id="bar"><span>Заметки</span><button onclick="newNote()">＋ Заметка</button></div>
<div id="hint">Правка текста с телефона: форматирование (картинки, списки) на телефоне не редактируется.</div>
<ul id="list"></ul>
<div id="edit">
 <div id="tools"><button onclick="saveNote()">Сохранить</button><button onclick="back()">Назад</button>
 <button onclick="delNote()" style="background:#ffe1dd;color:#7a1c14">В корзину</button></div>
 <textarea id="ta"></textarea></div>
<script>
const T = new URLSearchParams(location.search).get('t') || localStorage.getItem('t') || '';
if (T) localStorage.setItem('t', T);
const api = (p, o) => fetch(p + (p.includes('?') ? '&' : '?') + 't=' + encodeURIComponent(T), o);
let cur = null;
async function load() {
  try {
    const r = await api('/api/notes');
    if (r.status === 401) { document.body.innerHTML = '<div style="padding:30px">Неверный токен. Откройте адрес с ?t=ТОКЕН из настроек приложения.</div>'; return; }
    if (!r.ok) { alert('Ошибка загрузки списка: ' + r.status); return; }
    const ns = await r.json();
    const ul = document.getElementById('list'); ul.innerHTML = '';
    for (const n of ns) { const li = document.createElement('li');
      li.innerHTML = '<b></b><span></span>'; li.querySelector('b').textContent = n.title || 'Новая заметка';
      li.querySelector('span').textContent = n.snippet || '';
      li.onclick = () => openNote(n.id); ul.appendChild(li); }
  } catch (e) { alert('Нет связи с приложением на ПК'); }
}
async function openNote(id) {
  try {
    const r = await api('/api/note/' + encodeURIComponent(id));
    if (!r.ok) { alert('Не удалось открыть заметку'); return; }
    const n = await r.json();
    cur = id; document.getElementById('ta').value = n.plain;
    document.getElementById('list').style.display = 'none'; document.getElementById('hint').style.display = 'none';
    document.getElementById('edit').style.display = 'block';
  } catch (e) { alert('Нет связи с приложением на ПК'); }
}
function back() { cur = null; document.getElementById('edit').style.display = 'none';
  document.getElementById('list').style.display = 'block'; document.getElementById('hint').style.display = 'block'; load(); }
async function saveNote() { if (cur == null) return;
  try {
    const r = await api('/api/save', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: cur, plain: document.getElementById('ta').value})});
    if (!r.ok) { alert('Ошибка сохранения: ' + r.status); return; }
    back();
  } catch (e) { alert('Не удалось сохранить: нет связи с ПК'); }
}
async function newNote() {
  try {
    const r = await api('/api/new', {method: 'POST'});
    if (!r.ok) { alert('Ошибка создания заметки'); return; }
    const n = await r.json(); await load(); openNote(n.id);
  } catch (e) { alert('Нет связи с приложением на ПК'); }
}
async function delNote() { if (cur == null) return;
  if (!confirm('Переместить заметку в корзину?')) return;
  try {
    const r = await api('/api/trash', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: cur})});
    if (!r.ok) { alert('Ошибка удаления'); return; }
    back();
  } catch (e) { alert('Нет связи с приложением на ПК'); }
}
load();
</script></body></html>"""


class PhoneServer(QObject):
    changed = Signal()          # заметки изменены с телефона — обновить списки

    def __init__(self, store, port: int = 8787, parent=None):
        QObject.__init__(self, parent)
        self.store = store
        self.port = port
        saved = str(store.setting('phone_token', '') or '').strip()
        if len(saved) >= 12:
            self.token = saved
        else:
            self.token = secrets.token_urlsafe(12)
            store.set_setting('phone_token', self.token)
        self._httpd = None
        self._thread = None
        self.running = False

    def rotate_token(self) -> str:
        self.token = secrets.token_urlsafe(12)
        self.store.set_setting('phone_token', self.token)
        return self.token

    def url(self) -> str:
        return f'http://{lan_ip()}:{self.port}/?t={self.token}'

    # ---------- API ----------
    def _api_notes(self):
        with self.store._lock:
            ns = sorted((n for n in self.store.notes.values() if not n['deleted']),
                        key=lambda n: n.get('modified', 0), reverse=True)
            return [{'id': n['id'], 'title': n.get('title') or '',
                     'snippet': n.get('snippet') or ''} for n in ns]

    def _api_note(self, nid):
        with self.store._lock:
            n = self.store.notes.get(nid)
            if not n or n['deleted']:
                return None
            return {'id': nid, 'plain': n.get('plain') or ''}

    def _api_save(self, nid, plain):
        if not isinstance(nid, str) or not isinstance(plain, str):
            return False
        with self.store._lock:
            n = self.store.notes.get(nid)
            if not n or n['deleted']:
                return False
            if plain == (n.get('plain') or ''):
                return True   # текст не менялся — не трогаем форматирование
            versions.snapshot(self.store.root, nid, n.get('html') or '')
            title, snippet = note_plain_parts(plain)
            n['plain'] = plain
            n['html'] = plain_to_html(plain)
            n['title'] = title
            n['snippet'] = snippet
            n['modified'] = time.time()
            self.store.save_note(n)
        self.changed.emit()
        return True

    def _api_new(self):
        n = self.store.create_note()
        self.changed.emit()
        return {'id': n['id']}

    def _api_trash(self, nid):
        if not isinstance(nid, str):
            return False
        with self.store._lock:
            n = self.store.notes.get(nid)
            if not n or n['deleted']:
                return False
            self.store.trash_note(n)
        self.changed.emit()
        return True

    def _api_sync_info(self):
        with self.store._lock:
            cnt = sum(1 for n in self.store.notes.values() if not n.get('deleted'))
        return {
            'device_name': (self.store.setting('device_name', '') or st.default_device_name()).strip(),
            'owner_name': (self.store.setting('owner_name', '') or '').strip(),
            'count': cnt,
            'server_time': time.time(),
        }

    def _api_sync_pull(self):
        with self.store._lock:
            notes = [dict(n) for n in self.store.notes.values()]
        return {
            'device_name': (self.store.setting('device_name', '') or st.default_device_name()).strip(),
            'owner_name': (self.store.setting('owner_name', '') or '').strip(),
            'server_time': time.time(),
            'notes': notes,
        }

    def _api_sync_push(self, payload: dict):
        incoming = payload.get('notes')
        if not isinstance(incoming, list):
            return {'ok': False, 'accepted': 0}
        dev_name = str(payload.get('device_name') or 'Android').strip()
        snd_name = str(payload.get('sender_name') or '').strip()
        dev_type = str(payload.get('device_type') or 'phone').strip()
        accepted = 0
        with self.store._lock:
            for raw in incoming:
                if not isinstance(raw, dict) or not st.is_valid_note_id(raw.get('id')):
                    continue
                nid = str(raw['id'])
                local = self.store.notes.get(nid)
                in_mod = st._to_ts(raw.get('modified'))
                loc_mod = float((local or {}).get('modified') or 0.0)
                if local is not None and in_mod <= loc_mod + 0.5:
                    continue
                if local is not None:
                    versions.snapshot(self.store.root, nid, local.get('html') or '')
                merged = st.make_note(str(raw.get('folder') or st.DEFAULT_FOLDER))
                merged.update(raw)
                merged['id'] = nid
                merged['created'] = st._to_ts(merged.get('created')) or time.time()
                merged['modified'] = in_mod or time.time()
                merged['deleted_at'] = st._to_ts(merged.get('deleted_at'))
                merged['reminder_at'] = st._to_ts(merged.get('reminder_at'))
                if not merged.get('html') and merged.get('plain'):
                    merged['html'] = plain_to_html(str(merged['plain']))
                title, snippet = note_plain_parts(str(merged.get('plain') or ''))
                merged['title'] = title
                merged['snippet'] = snippet
                if not merged.get('origin'):
                    merged['origin'] = {
                        'source_type': dev_type,
                        'sender_name': snd_name,
                        'device_name': dev_name,
                        'sent_at': merged['modified'],
                        'received_at': time.time(),
                    }
                self.store.save_note(merged)
                accepted += 1
        if accepted:
            self.changed.emit()
        return {'ok': True, 'accepted': accepted, 'server_time': time.time()}

    # ---------- HTTP ----------
    def start(self):
        if self.running:
            return True
        srv = self

        class Handler(BaseHTTPRequestHandler):
            timeout = 10

            def log_message(self, *a):
                pass

            def _json(self, obj, code=200):
                import json as _j
                body = _j.dumps(obj, ensure_ascii=False).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self):
                q = parse_qs(urlparse(self.path).query)
                got = q.get('t', [''])[0]
                return secrets.compare_digest(got, srv.token)

            def do_GET(self):
                path = urlparse(self.path).path
                if path == '/' or path == '/index.html':
                    body = PAGE.encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif path.startswith('/api/') and not self._authorized():
                    self._json({'error': 'unauthorized'}, 401)
                elif path == '/api/notes':
                    self._json(srv._api_notes())
                elif path == '/api/sync/info':
                    self._json(srv._api_sync_info())
                elif path == '/api/sync/pull':
                    self._json(srv._api_sync_pull())
                elif path.startswith('/api/note/'):
                    nid = path.rsplit('/', 1)[-1]
                    data = srv._api_note(nid)
                    self._json(data) if data else self._json({'error': 'not found'}, 404)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                path = urlparse(self.path).path
                if not self._authorized():
                    self._json({'error': 'unauthorized'}, 401)
                    return
                try:
                    length = int(self.headers.get('Content-Length', 0) or 0)
                except ValueError:
                    self._json({'error': 'bad content-length'}, 400)
                    return
                if length < 0 or length > MAX_BODY_BYTES:
                    self._json({'error': 'payload too large'}, 413)
                    return
                import json as _j
                try:
                    payload = _j.loads(self.rfile.read(length) or b'{}')
                except ValueError:
                    payload = {}
                if not isinstance(payload, dict):
                    self._json({'error': 'bad json'}, 400)
                    return
                if path == '/api/save':
                    ok = srv._api_save(payload.get('id', ''), payload.get('plain', ''))
                    self._json({'ok': ok})
                elif path == '/api/new':
                    self._json(srv._api_new())
                elif path == '/api/trash':
                    ok = srv._api_trash(payload.get('id', ''))
                    self._json({'ok': ok})
                elif path == '/api/sync/push':
                    self._json(srv._api_sync_push(payload))
                else:
                    self._json({'error': 'unknown'}, 404)

        try:
            self._httpd = ThreadingHTTPServer(('0.0.0.0', self.port), Handler)
            self._httpd.daemon_threads = True
            self._httpd.timeout = 2.0
            self.port = self._httpd.server_address[1]   # фактический порт (0 = любой свободный)
        except OSError as e:
            self.running = False
            raise OSError(f'Порт {self.port} занят: {e}')
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        kwargs={'poll_interval': 0.5}, daemon=True)
        self._thread.start()
        self.running = True
        return True

    def stop(self):
        httpd = self._httpd
        self._httpd = None
        self.running = False
        if httpd:
            threading.Thread(
                target=lambda: (httpd.shutdown(), httpd.server_close()),
                daemon=True,
            ).start()
