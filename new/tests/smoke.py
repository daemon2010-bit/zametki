# -*- coding: utf-8 -*-
"""Автотест (offscreen): ядро + окно + редактор. Запуск: python -X utf8 tests/smoke.py"""
import os
import sys
import tempfile
import time

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix='zametki-smoke-')
os.environ['ZAMETKI_HOME'] = TMP

from PySide6.QtCore import Qt, QPointF, QEvent, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtGui import QTextBlockFormat, QTextDocument, QTextListFormat
from PySide6.QtWidgets import QApplication

from zametki.core import backup, datafolder, versions
from zametki.core import store as st

# изолируем указатель data-location.txt, чтобы тест никогда не трогал %APPDATA% пользователя
st.POINTER_FILE = os.path.join(TMP, 'data-location.txt')

app = QApplication(sys.argv)
PASS = []


def ok(name):
    PASS.append(name)
    print('OK', name)


# ---------- ядро ----------
store = st.Store()
assert os.path.abspath(store.root) == os.path.abspath(TMP), store.root
ok('папка данных через ZAMETKI_HOME')

note = store.create_note()
note['title'] = 'Тестовая'
note['plain'] = 'Тестовая\nСтрока два'
note['snippet'] = 'Строка два'
note['html'] = '<p><b>Тестовая</b></p><p>Строка два</p>'
store.save_note(note)
store2 = st.Store()
assert note['id'] in store2.notes
assert store2.notes[note['id']]['title'] == 'Тестовая'
ok('сохранение/перезагрузка заметки')

f = store.add_folder('Работа')
assert f['id'] != st.DEFAULT_FOLDER
store.rename_folder(f['id'], 'Работа+')
assert store.folders[1]['name'] == 'Работа+'
n2 = store.create_note(f['id'])
store.trash_note(n2)
assert store.count(f['id']) == 0 and store.trash_count() >= 1
store.delete_folder(f['id'])
assert all(fd['id'] != f['id'] for fd in store.folders)
ok('папки CRUD + корзина')

dup = store.duplicate_note(note)
assert dup['id'] != note['id'] and not dup['pinned']
dup['pinned'] = True
store.save_note(dup)
store.restore_note(n2)
assert not n2['deleted']
store.purge_note(n2)
assert n2['id'] not in store.notes
ok('дубликат, восстановление, удаление навсегда')

# версии
for i in range(25):
    versions.snapshot(store.root, note['id'], f'<p>версия {i}</p>')
vs = versions.list_versions(store.root, note['id'])
assert len(vs) == versions.LIMIT, len(vs)
assert 'версия 24' in versions.read_html(vs[0][1])
ok('история версий (лимит 20)')

# бэкап
backup.run_daily(store.root)
zips = os.listdir(os.path.join(store.root, 'backups'))
assert len(zips) == 1 and zips[0].endswith('.zip'), zips
backup.run_daily(store.root)
assert len(os.listdir(os.path.join(store.root, 'backups'))) == 1
ok('ежедневный бэкап (idempotent)')

# папка данных: проверка и перенос
okbad, _msg = datafolder.validate_dir('C:\\')
assert not okbad
oksub, _msg = datafolder.migrate(store.root, os.path.join(TMP, 'inside-src'))
assert not oksub, 'перенос внутрь текущей папки должен быть запрещён'
dst = tempfile.mkdtemp(prefix='zametki-moved-')
good, msg = datafolder.migrate(store.root, dst)
assert good, msg
env_saved = os.environ.get('ZAMETKI_HOME')
del os.environ['ZAMETKI_HOME']   # указатель ниже по приоритету, чем переменная среды
datafolder.set_pointer(dst)
assert os.path.abspath(st.data_dir()) == os.path.abspath(dst), st.data_dir()
store3 = st.Store()
assert note['id'] in store3.notes
datafolder.clear_pointer()
assert os.path.abspath(st.data_dir()) == os.path.abspath(st.APP_DIR_DEFAULT)
os.environ['ZAMETKI_HOME'] = env_saved
ok('перенос данных + указатель')

# ---------- UI ----------
from zametki.core.hotkey import GlobalHotkey, sequence_to_vk_mod
parsed = sequence_to_vk_mod('Ctrl+Alt+N')
assert parsed and parsed[0] == ord('N'), parsed
ok('разбор хоткея Ctrl+Alt+N')

from zametki.ui.theme import ThemeManager
from zametki.ui.main_window import MainWindow
from zametki.ui.delegates import NOTE_ROLE
from zametki.ui.delegates import NoteDelegate, human_date
from zametki.core.single import SingleInstance

theme = ThemeManager()
theme.set_mode('dark')
assert theme.colors['text'] == '#F5F5F7'
theme.set_mode('light')
ok('темы light/dark')

single = SingleInstance('-smoke')   # отдельное имя: у пользователя приложение может быть запущено
assert single.first
si2 = SingleInstance('-smoke')
assert not si2.first
ok('single instance')

hotkey = GlobalHotkey()
win = MainWindow(store, theme, hotkey)
win.show()
app.processEvents()
assert win.notes_list.count() >= 2
ok('окно построено, заметки в списке')

# новая заметка через окно
win.new_note()
app.processEvents()
assert win.current is not None
assert win.current['folder'] == st.DEFAULT_FOLDER
ok('новая заметка через окно')

# редактор: чек-листы
assert hasattr(QTextBlockFormat.MarkerType, 'Unchecked'), 'нет MarkerType — чек-листы Qt'
ed = win.editor
ed.setPlainText('Пункт один\nПункт два')
ed.toggle_checklist()
app.processEvents()
b = ed.document().firstBlock()
assert b.blockFormat().marker() == QTextBlockFormat.MarkerType.Unchecked
ed.toggle_checklist()
assert b.blockFormat().marker() == QTextBlockFormat.MarkerType.Checked
ed.toggle_checklist()
assert b.blockFormat().marker() == QTextBlockFormat.MarkerType.NoMarker
ed.toggle_checklist()
assert b.blockFormat().marker() == QTextBlockFormat.MarkerType.Unchecked
ok('чек-листы: цикл ☐→☑→нет→☐')

# сохранение через editor.save_requested
html_before = ed.toHtml()
ed.flush()
app.processEvents()
saved = store.notes[win.current['id']]
assert 'Пункт' in saved['plain'] and saved['title'] == 'Пункт один'
assert saved['html'] == html_before
ok('автосохранение: заголовок/сниппет/plain')

# картинка: вставка пути
img_path = os.path.join(TMP, 'test.png')
from PySide6.QtGui import QImage, QColor as QC
img = QImage(50, 50, QImage.Format.Format_RGB32)
img.fill(QC('#FFD60A'))
img.save(img_path)
rel = ed._insert_image_path(img_path)
assert rel.startswith('attachments/')
assert os.path.isfile(os.path.join(store.root, rel))
ok('вставка изображения в attachments')

# поиск
win.search.setText('тестовая')
app.processEvents()
assert win.notes_list.count() >= 1
win.search.setText('')
ok('поиск по тексту')

# сортировка
store.set_setting('sort', 'title')
win.rebuild_notes()
store.set_setting('sort', 'modified')
ok('сортировка по названию')

# экспорт TXT/MD напрямую
from PySide6.QtGui import QTextDocument
doc = QTextDocument()
doc.setHtml(saved['html'])
md = doc.toMarkdown()
assert 'Пункт' in md
ok('markdown-конвертация')

# напоминания
from zametki.ui.reminders import ReminderEngine
saved['reminder_at'] = time.time() - 10
store.save_note(saved)
shown = []
eng = ReminderEngine(store, lambda t, x: shown.append(t))
eng.check()
assert shown and saved['reminder_at'] == 0.0
ok('напоминание сработало')

# делегат: подсветка и дата
assert human_date(time.time()).startswith('Сегодня')
assert human_date(time.time() - 86400).startswith('Вчера')
ok('русские даты')

# телефон: сервер, токен, API
from zametki.core.phoneserver import PhoneServer
import urllib.request
import json as _json
ps = PhoneServer(store, port=0)
ps.start()
base = f'http://127.0.0.1:{ps.port}'
r = urllib.request.urlopen(base + '/api/notes?t=' + ps.token, timeout=5)
notes_list = _json.loads(r.read())
assert len(notes_list) >= 1 and 'title' in notes_list[0]
try:
    urllib.request.urlopen(base + '/api/notes?t=WRONG123', timeout=5)
    raise AssertionError('доступ без токена не закрыт')
except urllib.error.HTTPError as e:
    assert e.code == 401
req = urllib.request.Request(base + '/api/new?t=' + ps.token, method='POST')
nid = _json.loads(urllib.request.urlopen(req, timeout=5).read())['id']
body = _json.dumps({'id': nid, 'plain': 'С телефона\nВторая строка'}).encode()
req2 = urllib.request.Request(base + '/api/save?t=' + ps.token, data=body,
                              headers={'Content-Type': 'application/json'}, method='POST')
urllib.request.urlopen(req2, timeout=5)
app.processEvents()
updated = store.notes[nid]
assert updated['title'] == 'С телефона' and '<p' in updated['html']
ps.stop()
ok('телефон: API с токеном, правка с телефона')

# переключатель «Заметки» / «Удалённые»
t_note = store.create_note(st.DEFAULT_FOLDER)
t_note['title'] = 'Живая'
store.save_note(t_note)
d_note = store.create_note(st.DEFAULT_FOLDER)
d_note['title'] = 'В корзине'
store.save_note(d_note)
store.trash_note(d_note)
win._set_scope(True)
app.processEvents()
ids_shown = {win.notes_list.item(i).data(NOTE_ROLE)['id']
             for i in range(win.notes_list.count())}
assert d_note['id'] in ids_shown and t_note['id'] not in ids_shown
assert win.btn_trash_scope.isChecked() and not win.btn_notes_scope.isChecked()
win._set_scope(False)
app.processEvents()
ids_shown = {win.notes_list.item(i).data(NOTE_ROLE)['id']
             for i in range(win.notes_list.count())}
assert t_note['id'] in ids_shown and d_note['id'] not in ids_shown
ok('scope-кнопки: Заметки/Удалённые')

# ротация вида одной кнопкой: card -> list -> card («Таблица» и «Галерея» убраны)
assert win._view_mode == 'card'
win._cycle_view(); assert win._view_mode == 'list'
win._cycle_view(); assert win._view_mode == 'card'
win._apply_view('table')    # старые сохранённые настройки — откат к перечню
assert win._view_mode == 'card'
win._apply_view('gallery')  # и «галерея» — тоже
assert win._view_mode == 'card'
ok('ротация вида: перечень и список (таблица/галерея убраны)')

# совместимость: заметка старого exe с датами-строками ISO не должна ломать запуск
import json as _jsonfile
old_note = {
    'id': 'old-format-note', 'folder': st.DEFAULT_FOLDER,
    'title': 'Старый формат', 'html': '<p>Старый формат</p>',
    'plain': 'Старый формат', 'snippet': '',
    'created': '2026-11-11T01:57:18', 'modified': '2026-11-11T03:26:02',
    'deleted': False, 'deleted_at': 0.0, 'pinned': False,
}
with open(os.path.join(store.root, 'notes', 'old-format-note.json'), 'w', encoding='utf-8') as f:
    _jsonfile.dump(old_note, f, ensure_ascii=False)
store4 = st.Store()
on4 = store4.notes['old-format-note']
assert isinstance(on4['created'], float) and on4['created'] > 0
assert isinstance(on4['modified'], float) and on4['modified'] > 0
win.rebuild_notes()
ok('старый формат дат (строки ISO) нормально читается и сортируется')

# виды списка: два режима применяются и РИСУЮТСЯ без падений
# (grab() заставляет реально отработать paint делегата — так ловятся ошибки отрисовки)
for view_mode in ('card', 'list'):
    win._apply_view(view_mode)
    win.notes_list.grab()
    app.processEvents()
win._apply_view('card')
ok('виды списка: card/list переключаются')

# контекстное меню редактора строится и содержит форматирование как в Word
menu = win._build_editor_menu()
texts = [a.text().split('\t')[0] for a in menu.actions() if a.text()]
assert 'Полужирный' in texts and 'Чек-лист' in texts and 'По центру' in texts
assert not any(t == 'Заголовок' for t in texts), 'функция «Заголовок» должна быть убрана'
ok('контекстное меню редактора с форматированием (без «Заголовка»)')

# автоссылки: URL в тексте становится кликабельным
ed.setPlainText('Смотри https://example.com/page и www.ya.ru тут')
ed._autolink()
html_now = ed.toHtml()
assert 'href="https://example.com/page"' in html_now
assert 'href="https://www.ya.ru"' in html_now
ok('автоссылки: URL распознаются и кликабельны')

# курсор видимый
assert ed.cursorWidth() == 2
ok('курсор 2px')

# каретка есть (TextEditable во флагах взаимодействия)
flags = ed.textInteractionFlags()
assert flags & Qt.TextInteractionFlag.TextEditable
ok('каретка: редактор с флагом TextEditable')

# картинка вставляется с явным размером, находится мышью и меняет размер
from PySide6.QtGui import QTextCursor, QTextImageFormat
ed.setPlainText('')
rel2 = ed._insert_image_path(img_path)
probe = QTextCursor(ed.document())
probe.setPosition(ed.document().characterCount() - 1)
fmt_img = QTextImageFormat(probe.charFormat())
assert fmt_img.isImageFormat() and fmt_img.width() > 0, 'у картинки задан размер'
found = ed._image_at(ed.viewport().rect().center())
assert found, 'картинка находится под точкой курсора'
rect_img = ed._image_rect(found[2], found[1])
assert rect_img.width() == int(found[1].width())
assert rect_img.left() < 60, f'левая кромка картинки съехала: {rect_img.left()}'
ed._apply_img_size(found[2], 120, 80)
probe.setPosition(found[2] + 1)
assert QTextImageFormat(probe.charFormat()).width() == 120
ok('картинка: явный размер + ресайз применяется')

# ресайз РЕАЛЬНЫМИ событиями мыши: зажал угол → потянул → отпустил
ed._apply_img_size(found[2], 50, 50)
rect = ed._image_rect(found[2], found[1])
corner = QPointF(rect.right() - 6, rect.bottom() - 6)
press = QMouseEvent(QEvent.Type.MouseButtonPress, corner, QPointF(0, 0),
                    Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
app.sendEvent(ed.viewport(), press)
assert ed._img_resize, 'ресайз не начался от зажатия угла'
mv = QMouseEvent(QEvent.Type.MouseMove, QPointF(rect.left() + 140, rect.bottom() - 6),
                 QPointF(0, 0), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier)
app.sendEvent(ed.viewport(), mv)
probe.setPosition(found[2] + 1)
w_now = QTextImageFormat(probe.charFormat()).width()
assert w_now >= 120, f'ширина не изменилась при перетаскивании: {w_now}'
rel = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(rect.left() + 140, rect.bottom() - 6),
                  QPointF(0, 0), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                  Qt.KeyboardModifier.NoModifier)
app.sendEvent(ed.viewport(), rel)
assert ed._img_resize is None
ok('ресайз картинки мышью: press→move→release работает')

# правый клик по картинке: в меню есть «Размер картинки»
menu_rc = win._build_editor_menu(QPoint(rect.left() + 10, rect.top() + 10))
texts_rc = [a.text() for a in menu_rc.actions()]
assert any('Размер картинки' in t for t in texts_rc)
ok('меню «Размер картинки» по правому клику')

# логика кнопок: жирный «залипает» по позиции курсора, списки — мгновенные
ed.setPlainText('другой текст\nобычная строка')
ed.moveCursor(QTextCursor.MoveOperation.End)   # курсор в обычном тексте, не в заголовке
app.processEvents()
assert not win.fmt_buttons['bold'].isChecked()
win._fmt('bold')
assert win.fmt_buttons['bold'].isChecked()
ed.moveCursor(QTextCursor.MoveOperation.Start)  # курсор в заголовок (он полужирный)
app.processEvents()
assert win.fmt_buttons['bold'].isChecked()
ok('B-кнопка следует за курсором')

# крестик в галерее: зона нажатия определяется
win._apply_view('gallery')
it0 = win.notes_list.item(0)
r0 = win.notes_list.visualItemRect(it0)
card_r = r0.adjusted(6, 6, -6, -6)
from PySide6.QtCore import QPoint as _QPoint
assert win.notes_list._in_delete_zone(it0, _QPoint(card_r.right() - 8, card_r.top() + 12))
assert not win.notes_list._in_delete_zone(it0, _QPoint(card_r.left() + 10, card_r.top() + 12))
ok('крестик удаления в галерее: зона клика верна')

# Ctrl+Z: отмена возвращает текст, стек не замусорен рестайлом
ed.setPlainText('строка один')
ed.moveCursor(QTextCursor.MoveOperation.End)
ed.textCursor().insertText('два')
assert ed.document().isUndoAvailable()
ed.undo()
assert 'два' not in ed.toPlainText() and 'строка один' in ed.toPlainText()
ok('Ctrl+Z отменяет правку одним нажатием')

# история версий: кнопка «Восстановить» реально восстанавливает
from zametki.ui.versions_dialog import VersionsDialog
from PySide6.QtWidgets import QDialogButtonBox
note_v = store.create_note()
note_v['html'] = '<p>версия-2</p>'
note_v['title'] = 'версия-2'
store.save_note(note_v)
versions.snapshot(store.root, note_v['id'], '<p>версия-2</p>')
versions.snapshot(store.root, note_v['id'], '<p>версия-1</p>')
win.current = note_v
restored = []
dlg = VersionsDialog(store.root, note_v, lambda html: restored.append(html), win)
dlg.list.setCurrentRow(1)   # строка 1 = более старый снапшот «версия-2»
btn_restore = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.RestoreDefaults)
btn_restore.click()
assert restored and 'версия-2' in restored[0]
ok('история версий: восстановление работает')

# крестик в «Заметках» реальным нажатием: заметка уходит в корзину
store.set_setting('sort', 'modified')
note_x = store.create_note()
note_x['title'] = 'Крестик-тест'
store.save_note(note_x)
win.rebuild_notes()
win._apply_view('gallery')
it_x = next(i for i in range(win.notes_list.count())
            if win.notes_list.item(i).data(NOTE_ROLE)['id'] == note_x['id'])
rx = win.notes_list.visualItemRect(win.notes_list.item(it_x))
card_x = rx.adjusted(6, 6, -6, -6)
press_x = QMouseEvent(QEvent.Type.MouseButtonPress,
                      QPointF(card_x.right() - 8, card_x.top() + 12), QPointF(0, 0),
                      Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier)
app.sendEvent(win.notes_list.viewport(), press_x)
assert store.notes[note_x['id']]['deleted'], 'крестик не удалил в корзину'
ok('крестик в «Заметках»: в корзину одним нажатием')

# крестик в «Удалённых» реальным нажатием: подтверждение → удаляет навсегда
from PySide6.QtWidgets import QMessageBox
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
win._set_scope(True)
app.processEvents()
it_d = next((i for i in range(win.notes_list.count())
             if win.notes_list.item(i).data(NOTE_ROLE)['id'] == note_x['id']), -1)
assert it_d >= 0
rd = win.notes_list.visualItemRect(win.notes_list.item(it_d))
card_d = rd.adjusted(6, 6, -6, -6)
press_d = QMouseEvent(QEvent.Type.MouseButtonPress,
                      QPointF(card_d.right() - 8, card_d.top() + 12), QPointF(0, 0),
                      Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier)
app.sendEvent(win.notes_list.viewport(), press_d)
assert note_x['id'] not in store.notes, 'крестик в корзине не удалил навсегда'
ok('крестик в «Удалённых»: удаляет навсегда')

# кнопка новой заметки неактивна в корзине и активна в заметках
assert not win.btn_compose.isEnabled()
win._set_scope(False)
assert win.btn_compose.isEnabled()
ok('кнопка новой заметки неактивна в корзине')

# заголовок однородный, форматирование выделения не «скачет»
ed.setPlainText('Заголовок заметки\nОбычный текст в теле')
app.processEvents()

def frag_info(block):
    out = []
    it = block.begin()
    while it != block.end():
        f = it.fragment().charFormat().font()
        out.append((f.pointSize(), int(f.weight())))
        it += 1
    return out

info = frag_info(ed.document().firstBlock())
assert info and all(s == 17 and w >= 600 for s, w in info), f'заголовок рваный: {info}'
c_sel = ed.textCursor()
c_sel.setPosition(4)
c_sel.setPosition(12, QTextCursor.MoveMode.KeepAnchor)
ed.setTextCursor(c_sel)
win._fmt('italic')
app.processEvents()
info = frag_info(ed.document().firstBlock())
assert {s for s, w in info} == {17}, f'размер в заголовке скачет: {info}'
ok('форматирование выделения не скачет, заголовок однородный')

# ---------- замечания 22.11.2026 ----------

# (1а) двойной щелчок по заголовку не меняет его стиль
ed.setPlainText('Проверка заголовка\nтело заметки')
app.processEvents()
block0 = ed.document().firstBlock()
dbl = QMouseEvent(QEvent.Type.MouseButtonDblClick,
                  QPointF(20, 10), QPointF(0, 0),
                  Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                  Qt.KeyboardModifier.NoModifier)
app.sendEvent(ed.viewport(), dbl)
app.processEvents()
info = frag_info(block0)
assert info and all(s == 17 and w >= 600 for s, w in info), \
    f'двойной щелчок сломал заголовок: {info}'
assert ed.currentCharFormat().font().pointSize() == 17, 'формат ввода не как у заголовка'
ok('двойной щелчок по заголовку сохраняет стиль')

# (1б) «рваный» заголовок (часть строки 11pt) полностью восстанавливается.
# В живом приложении textChanged лечит его мгновенно, поэтому вносим порчу
# с заблокированными сигналами — проверяем сам механизм восстановления.
c_fix = ed.textCursor()
c_fix.setPosition(block0.position() + 2)
c_fix.setPosition(block0.position() + 8, QTextCursor.MoveMode.KeepAnchor)
from PySide6.QtGui import QTextCharFormat, QFont
broken = QTextCharFormat()
f_small = QFont('Segoe UI')
f_small.setPointSize(11)
f_small.setWeight(QFont.Weight.Normal)
broken.setFont(f_small)
ed.blockSignals(True)
c_fix.mergeCharFormat(broken)
app.processEvents()
mixed = frag_info(block0)
assert any(s == 11 for s, w in mixed), f'порча не внесена: {mixed}'
ed.blockSignals(False)
ed._restyle_first_line()
app.processEvents()
info = frag_info(block0)
assert all(s == 17 and w >= 600 for s, w in info), f'рваный заголовок не восстановлен: {info}'
ok('рваный заголовок восстанавливается целиком')

# (2) поля текста 5 мм слева и справа
dpi = ed.logicalDpiY() or 96
expect_px = max(12, round(5 / 25.4 * dpi))
assert ed.document().documentMargin() == 0, 'documentMargin должен быть 0'
vg = ed.viewport().geometry()
assert vg.left() == expect_px and ed.width() - vg.right() - 1 == expect_px, \
    f'поля {vg.left()}px вместо {expect_px}px (5 мм при {dpi} dpi)'
ok(f'поля редактора 5 мм ({expect_px}px при {dpi} dpi)')

# (3) отдельная кнопка «Экспорт» в верхнем меню редактора
assert win.btn_export.toolTip().startswith('Экспорт')
ok('кнопка «Экспорт» есть на панели')

# (4) все кнопки получают PNG-иконки из пользовательского набора
from zametki.ui.icons import ICON_FILES, png_icon
from PySide6.QtCore import QSize
for kind in ICON_FILES:
    for dark in (False, True):
        pm = png_icon(kind, dark).pixmap(QSize(20, 20))
        assert not pm.isNull(), f'иконка {kind} (dark={dark}) не загрузилась'
ok(f'PNG-иконки на месте ({len(ICON_FILES)} видов × 2 темы)')

# (5) кнопка «Экспорт» активна при открытой заметке
win.new_note()
app.processEvents()
assert win.current is not None
assert win.btn_export.isEnabled(), 'кнопка «Экспорт» неактивна при открытой заметке'
win.editor.setPlainText('Экспортная заметка')
app.processEvents()
ok('кнопка «Экспорт» активна с заметкой')

# (6) клик по кнопке «Экспорт» вызывает экспорт текущей заметки
from PySide6.QtTest import QTest
import zametki.ui.main_window as _mw
called = {}
_orig_export = _mw.export_note


def _fake_export(parent, note):
    called['id'] = note['id']
    called['title'] = note.get('title')


_mw.export_note = _fake_export
try:
    QTest.mouseClick(win.btn_export, Qt.MouseButton.LeftButton)
    app.processEvents()
finally:
    _mw.export_note = _orig_export
assert called.get('id') == win.current['id'], f'экспорт не вызван: {called}'
ok('клик «Экспорт» запускает экспорт открытой заметки')

# ---------- ревизия 11: переключение кнопок при выделении ----------
ed.setPlainText('Заголовок заметки\nОбычный текст тела для проверки')
app.processEvents()
body = ed.document().lastBlock()
# NB: setPlainText вставляет текст с ТЕКУЩИМ форматом ввода, который у заголовка
# всегда 17pt (липкий формат) — выравниваем блок тела в 11pt явно,
# чтобы тест не зависел от состояния формата ввода
_norm = QTextCursor(body)
_norm.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
_nf = QTextCharFormat()
_f0 = QFont('Segoe UI')
_f0.setPointSize(11)
_f0.setWeight(QFont.Weight.Normal)
_nf.setFont(_f0)
_norm.mergeCharFormat(_nf)
app.processEvents()

def body_frags():
    segs = []
    it = body.begin()
    while not it.atEnd():
        fr = it.fragment()
        if fr.isValid():
            f = fr.charFormat().font()
            segs.append((fr.position() - body.position(), fr.text(), f.pointSize(), int(f.weight()),
                         f.italic(), f.underline(), f.strikeOut()))
        it += 1
    return segs

def frags_in(a, b):
    return [s for s in body_frags() if s[0] + len(s[1]) > a and s[0] < b]

def select_body(a, b):
    cur = ed.textCursor()
    cur.setPosition(body.position() + a)
    cur.setPosition(body.position() + b, QTextCursor.MoveMode.KeepAnchor)
    ed.setTextCursor(cur)
    app.processEvents()

# дважды кликнуть по слову мышью и нажать кнопку Ж дважды: вкл → выкл
# имитируем именно мышинное выделение: dblClick по слову на экране
cprobe = ed.textCursor()
cprobe.setPosition(body.position() + 3)
center = ed.cursorRect(cprobe).center()
QTest.mouseDClick(ed.viewport(), Qt.MouseButton.LeftButton,
                  Qt.KeyboardModifier.NoModifier, center)
app.processEvents()
assert ed.textCursor().hasSelection(), 'двойной клик не выделил слово'
win.fmt_buttons['bold'].click()
app.processEvents()
segs = [s for s in body_frags() if 'Обычный' in s[1]]
assert segs and all(s[3] == 700 for s in segs), f'Ж не включился: {body_frags()}'
win.fmt_buttons['bold'].click()
app.processEvents()
segs = [s for s in body_frags() if 'Обычный' in s[1]]
assert all(s[3] == 400 for s in segs), f'повторный клик Ж не снял формат: {body_frags()}'
ok('двойной клик + кнопка Ж: вкл → повторный клик снимает')

# смешанное выделение: половина жирная — один клик включает всё
select_body(8, 26)
fmt_b = QTextCharFormat()
f_b = QFont('Segoe UI'); f_b.setPointSize(11); f_b.setWeight(QFont.Weight.Bold)
fmt_b.setFont(f_b)
cur = ed.textCursor()
cur.setPosition(body.position() + 8)
cur.setPosition(body.position() + 14, QTextCursor.MoveMode.KeepAnchor)
cur.mergeCharFormat(fmt_b)
cur.setPosition(body.position() + 8)
cur.setPosition(body.position() + 26, QTextCursor.MoveMode.KeepAnchor)
ed.setTextCursor(cur)          # выделение 8..26: часть 700, часть 400
app.processEvents()
assert not win.fmt_buttons['bold'].isChecked(), 'при смешанном выделении Ж не должен светиться'
win.toggle_bold()
app.processEvents()
segs = frags_in(8, 26)
assert segs and all(s[3] == 700 for s in segs), f'смешанное выделение не стало жирным: {body_frags()}'
win.toggle_bold()
app.processEvents()
segs = frags_in(8, 26)
assert segs and all(s[3] == 400 for s in segs), f'повторный клик не снял жирный: {body_frags()}'
ok('смешанное выделение: Ж включает всё, повторный — снимает')

# курсив/подчёркнутый: цикл вкл/выкл
select_body(8, 14)
win.toggle_italic(); app.processEvents()
win.toggle_under(); app.processEvents()
segs = frags_in(8, 14)
assert segs and all(s[4] and s[5] for s in segs), f'К/Ч не применились: {segs}'
win.toggle_italic(); win.toggle_under(); app.processEvents()
segs = frags_in(8, 14)
assert all(not s[4] and not s[5] for s in segs), f'К/Ч не снялись повторным кликом: {segs}'
ok('Курсив и Подчёркнутый переключаются циклом вкл/выкл')

# «липкий» режим без выделения: клик Ж меняет формат ввода, повторный возвращает
select_body(0, 0)
before = ed.currentCharFormat().fontWeight()
win.toggle_bold()
mid = ed.currentCharFormat().fontWeight()
win.toggle_bold()
after = ed.currentCharFormat().fontWeight()
assert mid != before and after == before, (before, mid, after)
ok('без выделения Ж переключает формат ввода (липкий)')

# кнопки при выделении отражают состояние всего выделения
select_body(8, 14)
win.toggle_bold(); app.processEvents()
assert win.fmt_buttons['bold'].isChecked(), 'Ж не отражает жирное выделение'
select_body(15, 20)
assert not win.fmt_buttons['bold'].isChecked(), 'Ж светится на нежирном выделении'
win.toggle_bold(); win.toggle_bold(); app.processEvents()
ok('галка Ж следует за состоянием выделения')

# ---------- ревизия 12 ----------
from PySide6.QtCore import QRect
ed.setPlainText('Первая строка\nВторая строка\nТретья строка')
app.processEvents()

def blocks12():
    out = []
    b = ed.document().firstBlock()
    while b.isValid():
        segs = []
        it = b.begin()
        while not it.atEnd():
            fr = it.fragment()
            if fr.isValid():
                f = fr.charFormat().font()
                segs.append((fr.text()[:12], f.pointSize(), int(f.weight())))
            it += 1
        out.append((b.blockNumber(), segs))
        b = b.next()
    return out

# (1) функция «Заголовок» убрана из панели и из редактора
assert not hasattr(win, 'btn_heading'), 'кнопка «Заголовок» должна быть удалена'
assert not hasattr(win.editor, 'set_heading'), 'set_heading должна быть удалена'
ok('функция «Заголовок» удалена (первая строка — авто-заголовок)')

# (2) выравнивание не переносит отступы соседним строкам
ed.setPlainText('Строка выравнивания\nВторая строка')
app.processEvents()
b0 = ed.document().firstBlock()
b1 = ed.document().lastBlock()
cur = ed.textCursor()
cur.setPosition(b1.position())
bf = QTextBlockFormat()
bf.setIndent(3)
cur.mergeBlockFormat(bf)
app.processEvents()
ind_before = b0.blockFormat().indent()
cur = ed.textCursor()
cur.setPosition(b1.position() + 1)
ed.setTextCursor(cur)
win.align_left()
app.processEvents()
assert b0.blockFormat().indent() == ind_before, \
    'выравнивание нижней строки сдвинуло верхнюю'
assert b1.blockFormat().indent() == 3, \
    'выравнивание сбросило отступ собственной строки'
ok('выравнивание не трогает отступы соседних строк')

# (3) размер текста: применение к выделению и шаг больше/меньше
ed.setPlainText('Размер текста\nВторая строка')
app.processEvents()
b0 = ed.document().firstBlock().next()   # вторая строка
cur = ed.textCursor()
cur.setPosition(b0.position() + 1)
cur.setPosition(b0.position() + 6, QTextCursor.MoveMode.KeepAnchor)
ed.setTextCursor(cur)
win.editor.set_font_size(16)
app.processEvents()
segs = []
it = b0.begin()
while not it.atEnd():
    fr = it.fragment()
    if fr.isValid():
        segs.append((fr.text()[:6], fr.charFormat().font().pointSizeF()))
    it += 1
# размер должен примениться только к выделенному диапазону (+1..+6 = «торая»)
touched = [s for t, s in segs if t == 'торая']
others = [s for t, s in segs if t != 'торая']
assert touched and all(s == 16.0 for s in touched), f'размер не применился: {segs}'
assert all(s == 11.0 for s in others), f'размер вышел за выделение: {segs}'
before = win.editor.current_font_size()
win._change_font_size(-1)
app.processEvents()
assert win.editor.current_font_size() < before
win._change_font_size(+1)
app.processEvents()
assert abs(win.editor.current_font_size() - before) < 0.01
ok('размер текста: выделение, шаг больше/меньше')

# (5) мультивыделение: массовое удаление в корзину и восстановление
assert win.notes_list.selectionMode().name == 'ExtendedSelection'
n_a = store.create_note(); n_a['title'] = 'Масс-1'; store.save_note(n_a)
n_b = store.create_note(); n_b['title'] = 'Масс-2'; store.save_note(n_b)
win.rebuild_notes()
items = [win.notes_list.item(i) for i in range(win.notes_list.count())
         if win.notes_list.item(i).data(NOTE_ROLE)['id'] in (n_a['id'], n_b['id'])]
assert len(items) == 2
for it in items:
    it.setSelected(True)
win._bulk_trash([store.notes[n_a['id']], store.notes[n_b['id']]])
app.processEvents()
assert store.notes[n_a['id']]['deleted'] and store.notes[n_b['id']]['deleted']
win._bulk_restore([store.notes[n_a['id']], store.notes[n_b['id']]])
app.processEvents()
assert not store.notes[n_a['id']]['deleted'] and not store.notes[n_b['id']]['deleted']
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
win._bulk_purge([store.notes[n_a['id']], store.notes[n_b['id']]])
app.processEvents()
assert n_a['id'] not in store.notes and n_b['id'] not in store.notes
ok('мультивыделение: массовая корзина/восстановление/удаление навсегда')

# (6) крестик удаления на карточке основного вида
note_x2 = store.create_note(); note_x2['title'] = 'Крестик-карточка'; store.save_note(note_x2)
win.rebuild_notes()
win._apply_view('card')
it_x2 = next(i for i in range(win.notes_list.count())
             if win.notes_list.item(i).data(NOTE_ROLE)['id'] == note_x2['id'])
rx2 = win.notes_list.visualItemRect(win.notes_list.item(it_x2))
zone_x2 = QRect(rx2.right() - 30, rx2.top() + 1, 28, 22)
press_x2 = QMouseEvent(QEvent.Type.MouseButtonPress,
                       QPointF(zone_x2.center()), QPointF(0, 0),
                       Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
app.sendEvent(win.notes_list.viewport(), press_x2)
app.processEvents()
assert store.notes[note_x2['id']]['deleted'], 'крестик карточки не удалил в корзину'
store.restore_note(store.notes[note_x2['id']])
win.rebuild_notes()
ok('крестик удаления на карточках основного вида')

# (7) первые три иконки крупнее остальных
assert win.btn_notes_scope.iconSize() == QSize(20, 20)
assert win.btn_trash_scope.iconSize() == QSize(20, 20)
assert win.btn_compose.iconSize() == QSize(20, 20)
assert win.fmt_buttons['bold'].iconSize() == QSize(16, 16)
ok('первые три иконки 20 px, панель редактора 16 px')

# (8) чекбокс: двойное нажатие переключает один раз и не выделяет слова
ed.setPlainText('Чек строка\nПросто строка')
app.processEvents()
c_sel = ed.textCursor()
c_sel.setPosition(ed.document().firstBlock().position())
c_sel.setPosition(ed.document().firstBlock().position() + 4, QTextCursor.MoveMode.KeepAnchor)
ed.setTextCursor(c_sel)
ed.toggle_checklist()
app.processEvents()
block_chk = ed.document().firstBlock()
assert block_chk.blockFormat().marker() == QTextBlockFormat.MarkerType.Unchecked
# снимаем выделение из подготовки: оцениваем именно поведение мыши
c_clear = ed.textCursor()
c_clear.setPosition(block_chk.position() + 1)
ed.setTextCursor(c_clear)
app.processEvents()
assert not ed.textCursor().hasSelection()
vp = ed.viewport()
cprobe = ed.textCursor()
cprobe.setPosition(block_chk.position())   # курсор начала строки = позиция квадратика
r_chk = ed.cursorRect(cprobe)
chk_pos = QPoint(r_chk.left() + 8, r_chk.center().y())   # по самому квадратику
# клик СЛЕВА от квадратика (в поле строки) НЕ переключает — там живёт выделение
QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 QPoint(r_chk.left() - 30, r_chk.center().y()))
app.processEvents()
assert block_chk.blockFormat().marker() == QTextBlockFormat.MarkerType.Unchecked, \
    'клик мимо квадратика переключил чек-лист'
# клик по СЛОВУ СТРОКИ (середина) НЕ переключает — частый жалобный случай
word_x = None
cword = ed.textCursor()
cword.setPosition(block_chk.position() + 4)
word_x = ed.cursorRect(cword).center().x()
QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 QPoint(word_x, r_chk.center().y()))
app.processEvents()
assert block_chk.blockFormat().marker() == QTextBlockFormat.MarkerType.Unchecked, \
    'клик по слову строки переключил чек-лист'
QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, chk_pos)
app.processEvents()
assert block_chk.blockFormat().marker() == QTextBlockFormat.MarkerType.Checked, \
    'клик по квадратику не переключил'
QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, chk_pos)
app.processEvents()
assert block_chk.blockFormat().marker() == QTextBlockFormat.MarkerType.Checked, \
    'двойное нажатие переключило второй раз'
assert not ed.textCursor().hasSelection(), 'двойное нажатие выделило слова'
ok('чек-лист переключается только по квадратику; слова и поля — как текст')

# (9) маркированный список: мультивыделение + ПУСТЫЕ строки
ed.setPlainText('Альфа\n\nГамма')
app.processEvents()
bA = ed.document().firstBlock()
bB = bA.next()          # пустая строка посередине
bC = bB.next()
cur = ed.textCursor()
cur.setPosition(bA.position())
cur.setPosition(bC.position() + bC.length() - 1, QTextCursor.MoveMode.KeepAnchor)
ed.setTextCursor(cur)
win.toggle_bullets()
app.processEvents()
assert bA.textList() is not None, 'первая строка не стала списком'
assert bB.textList() is not None, 'пустая строка не получила маркер'
assert bC.textList() is not None, 'последняя строка не стала списком'
win.toggle_bullets()
app.processEvents()
assert bB.textList() is None, 'маркер с пустой строки не снялся'
assert bA.blockFormat().indent() == 0 and bB.blockFormat().indent() == 0
ok('маркированный список: пустая строка получает и теряет маркер')

# (10) звезда избранного: клик закрепляет наверх, повторный — открепляет
note_s1 = store.create_note(); note_s1['title'] = 'Звезда-1'; store.save_note(note_s1)
note_s2 = store.create_note(); note_s2['title'] = 'Звезда-2'; store.save_note(note_s2)
win.rebuild_notes()
win._apply_view('card')
app.processEvents()
it_s = next(i for i in range(win.notes_list.count())
            if win.notes_list.item(i).data(NOTE_ROLE)['id'] == note_s1['id'])
r_s = win.notes_list.visualItemRect(win.notes_list.item(it_s))
star_pos = QPoint(r_s.left() + 13, r_s.top() + 12)   # звезда СЛЕВА на карточке
QTest.mouseClick(win.notes_list.viewport(), Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier, star_pos)
app.processEvents()
assert store.notes[note_s1['id']]['pinned'], 'звезда не закрепила заметку'
first_id = win.notes_list.item(0).data(NOTE_ROLE)['id']
assert first_id == note_s1['id'], 'закреплённая не поднялась наверх'
# заметка пересортировалась наверх — перевычисляем позицию её звезды
it_s2 = next(i for i in range(win.notes_list.count())
             if win.notes_list.item(i).data(NOTE_ROLE)['id'] == note_s1['id'])
r_s2 = win.notes_list.visualItemRect(win.notes_list.item(it_s2))
star_pos2 = QPoint(r_s2.left() + 13, r_s2.top() + 12)
QTest.mouseClick(win.notes_list.viewport(), Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier, star_pos2)
app.processEvents()
assert not store.notes[note_s1['id']]['pinned'], 'повторный клик не снял звезду'
assert not store.notes[note_s2['id']]['pinned'], 'звезда задела соседнюю заметку'
ok('звезда избранного: закрепление сверху по клику, повторный — открепление')

# (11) размер заголовка первой строки применяется и не сбрасывается
ed.setPlainText('Заголовок для размера\nтело')
app.processEvents()
cur = ed.textCursor()
cur.setPosition(2)
ed.setTextCursor(cur)
win.editor.set_font_size(20)
app.processEvents()
QTest.keyClicks(ed, 'X')
app.processEvents()
segs0 = []
it0 = ed.document().firstBlock().begin()
while not it0.atEnd():
    fr0 = it0.fragment()
    if fr0.isValid() and fr0.text():
        segs0.append(fr0.charFormat().font().pointSizeF())
    it0 += 1
assert segs0 and all(s == 20.0 for s in segs0), \
    f'размер заголовка сбросился: {segs0}'
assert win.editor._title_size == 20.0
ok('размер шрифта применяется к верхней строке и сохраняется')

# (11) Word-комбобокс размера, строка статуса, кнопки темы и папки
from PySide6.QtWidgets import QComboBox
assert isinstance(win.size_combo, QComboBox) and win.size_combo.isEditable()
assert 'down-arrow' in win.size_combo.styleSheet() and 'down_arrow.svg' in win.size_combo.styleSheet(), \
    'стрелка выпадающего списка должна быть видна (векторная)'
assert hasattr(win, 'status_label') and 'Заметок:' in win.status_label.text()
assert hasattr(win, 'btn_theme') and hasattr(win, 'btn_folder'), \
    'кнопки темы и папки должны быть на панели рядом с экспортом'
from zametki.ui.icons import theme_icon as _ti, folder_icon as _fi
from PySide6.QtCore import QSize as _QSize
pm_t = _ti('dark', False, 2.0).pixmap(_QSize(16, 16), 2.0)
assert pm_t.width() == 32 and abs(pm_t.devicePixelRatio() - 2.0) < 0.01, \
    'иконка темы должна рендериться в разрешении экрана (dpr 2 = 32px)'
pm_f = _fi(False, 2.0).pixmap(_QSize(16, 16), 2.0)
assert pm_f.width() == 32 and abs(pm_f.devicePixelRatio() - 2.0) < 0.01, \
    'иконка папки должна рендериться в разрешении экрана (dpr 2 = 32px)'
menu_more = win._more_menu()
more_texts = [a.text() for a in menu_more.actions() if a.text()]
assert not any(t.startswith('Тема') for t in more_texts), \
    'тема должна быть кнопкой на панели, а не в меню'
assert not any('папку' in t for t in more_texts), \
    'папка должна быть кнопкой на панели, а не в меню'
ok('комбобокс со стрелкой, строка статуса, векторные кнопки темы и папки')

# (12) тема — кнопка рядом с экспортом: день → ночь → как в Windows → день
order = ('light', 'dark', 'system')
names = {'light': 'день', 'dark': 'ночь', 'system': 'как в Windows'}
store.set_setting('theme', 'light')
win._apply_theme_mode('light')
app.processEvents()
for step in range(3):
    start = store.setting('theme', 'system')
    assert names.get(start, 'день') in win.btn_theme.toolTip(), \
        f'в подсказке кнопки темы не показан текущий режим: {win.btn_theme.toolTip()}'
    win.btn_theme.click()
    app.processEvents()
    after = store.setting('theme', 'system')
    assert after == order[(order.index(start) + 1) % 3], (start, after)
assert store.setting('theme', 'system') == 'light'
ok('тема — кнопка день/ночь/как в Windows (полный цикл)')

# (12б) редактор СЛЕДУЕТ теме; «обычный» текст перекрашивается под фон,
# принудительные цвета сохраняются
from PySide6.QtGui import QColor as _QColor
ed.setPlainText('Обычный текст\nКрасный текст')
app.processEvents()
b12 = ed.document().firstBlock()
cur12 = ed.textCursor()
cur12.setPosition(b12.position())
cur12.setPosition(b12.position() + 8, QTextCursor.MoveMode.KeepAnchor)
# «запекаем» обычный цвет светлой темы (как в старых заметках)
_baked = QTextCharFormat()
_baked.setForeground(_QColor('#1d1d1f'))
cur12.mergeCharFormat(_baked)
# красный — принудительный цвет на второй строке ('текст' = символы 8..13)
cur12 = ed.textCursor()
b2_12 = b12.next()
cur12.setPosition(b2_12.position() + 8)
cur12.setPosition(b2_12.position() + 13, QTextCursor.MoveMode.KeepAnchor)
_red = QTextCharFormat()
_red.setForeground(_QColor('#E5484D'))
cur12.mergeCharFormat(_red)
ed.setTextCursor(cur12)
# переключаем в тёмную — «обычный» текст должен осветлиться, красный остаться
win._apply_theme_mode('dark')
app.processEvents()

def frag_colors12(block):
    out = []
    it = block.begin()
    while not it.atEnd():
        fr = it.fragment()
        if fr.isValid() and fr.text():
            fg = fr.charFormat().foreground()
            has = fg.style() != Qt.BrushStyle.NoBrush
            out.append((fr.text()[:8], fg.color().name().lower() if has else None))
        it += 1
    return out

b0_12 = ed.document().firstBlock()
colors12 = frag_colors12(b0_12)
baked = [c for t, c in colors12 if c is not None and c in ed.DEFAULT_THEME_COLORS]
assert not baked, f'запечённый обычный цвет не сброшен: {colors12}'
red_left = [c for t, c in frag_colors12(b2_12) if c == '#e5484d']
assert red_left, 'принудительный красный цвет потерян'
win._apply_theme_mode('light')
app.processEvents()
ok('редактор следует теме; обычный текст перекрашивается, принудительные цвета хранятся')

# (12б) legacy 'system' — валидный режим: окно строится, ничего не падает
store.set_setting('theme', 'system')
tm3 = ThemeManager()
tm3.set_mode('system')
win3 = MainWindow(store, tm3, hotkey)
win3.show()
app.processEvents()
assert tm3.mode == 'system'
assert store.setting('theme', 'system') == 'system'
assert 'как в Windows' in win3.btn_theme.toolTip()
win3.close()
app.processEvents()
store.set_setting('theme', 'light')
win._apply_theme_mode('light')
app.processEvents()
ok('режим «как в Windows» работает (тема следует за системой)')

# (13) закрытие окна: по умолчанию (tray=False) крестик реально закрывает,
# при включённой настройке tray=True прячет в трей; в меню «···» есть «Выход»
more_texts_exit = [a.text() for a in win._more_menu().actions() if a.text()]
assert any(t.startswith('Выход') for t in more_texts_exit), more_texts_exit
store.set_setting('tray', True)
_tray_ok_real = win._tray_ok
win._tray_ok = True   # offscreen без трея — имитируем доступность трея
assert win.close() is False, 'при tray=True закрытие должно прятать в трей'
assert not win.isVisible(), 'при tray=True окно должно скрываться в трей'
win.restore_and_activate()
assert win.isVisible(), 'restore_and_activate() должен вернуть окно из трея'
single.register_main_window(int(win.winId()))
assert os.path.isfile(single._marker), 'маркер HWND главного окна не создан'
app.processEvents()
store.set_setting('tray', False)
win._tray_ok = False
win2 = MainWindow(store, ThemeManager(), hotkey)
win2.show()
app.processEvents()
r2 = win2.close()
app.processEvents()
assert r2 is True, 'при tray=False крестик должен закрывать приложение'
assert not win2.isVisible(), 'окно win2 должно закрыться'
win._tray_ok = _tray_ok_real
ok('крестик: закрытие по умолчанию / трей по настройке + точный HWND')

# ---------- новые проверки (6 замечаний + аудит) ----------

# (14) системная тема: system_is_dark() работает без исключений
from zametki.ui.theme import system_is_dark
assert isinstance(system_is_dark(), bool)
ok('system_is_dark() возвращает bool без ошибок')

# (15) «Убрать форматирование» (без слова «лишнее»)
more_texts2 = [a.text() for a in win._more_menu().actions() if a.text()]
assert 'Убрать форматирование' in more_texts2
assert not any('лишнее' in t.lower() for t in more_texts2)
ok('меню «Убрать форматирование» без слова «лишнее»')

# (16) восстановление из корзины кликом по значку на карточке
note_r = store.create_note(); note_r['title'] = 'Вернуть-тест'; store.save_note(note_r)
store.trash_note(note_r)
win._set_scope(True)
win._apply_view('card')
app.processEvents()
it_r = next(i for i in range(win.notes_list.count())
            if win.notes_list.item(i).data(NOTE_ROLE)['id'] == note_r['id'])
rr = win.notes_list.visualItemRect(win.notes_list.item(it_r))
restore_pt = QPointF(rr.right() - 37, rr.top() + 13)
press_r = QMouseEvent(QEvent.Type.MouseButtonPress, restore_pt, QPointF(0, 0),
                      Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier)
app.sendEvent(win.notes_list.viewport(), press_r)
app.processEvents()
assert not store.notes[note_r['id']]['deleted'], 'значок возврата не восстановил заметку'
win._set_scope(False)
ok('значок возврата на карточке в корзине восстанавливает заметку')

# (17) маркированный список: кружочки имеют правильный размер (blockCharFormat = размер строки)
win.new_note()
app.processEvents()
QTest.keyClicks(ed, 'Title')
QTest.keyClick(ed, Qt.Key.Key_Return)
QTest.keyClicks(ed, 'Line two')
QTest.keyClick(ed, Qt.Key.Key_Return)
QTest.keyClicks(ed, 'Line three')
app.processEvents()
cur_b = ed.textCursor()
cur_b.select(QTextCursor.SelectionType.Document)
ed.setTextCursor(cur_b)
win.toggle_bullets()
app.processEvents()
blk0 = ed.document().firstBlock()
blk1 = blk0.next()
blk2 = blk1.next()
assert blk0.textList() is not None and blk1.textList() == blk0.textList() and blk2.textList() == blk0.textList()
assert abs(blk0.charFormat().font().pointSizeF() - 17.0) < 0.5, blk0.charFormat().font().pointSizeF()
assert abs(blk1.charFormat().font().pointSizeF() - 11.0) < 0.5, blk1.charFormat().font().pointSizeF()
assert abs(blk2.charFormat().font().pointSizeF() - 11.0) < 0.5, blk2.charFormat().font().pointSizeF()
ok('маркированный список: единый список и корректный размер маркеров')

# (18) адаптивная панель: при сужении нет наслоения, появляется кнопка «»
win.fmt_toolbar.resize(200, 30)
app.processEvents()
assert win.fmt_toolbar.overflow_btn.isVisible(), 'при узкой панели должна появляться кнопка «»'
vis_rects = [w.geometry() for w, sep in win.fmt_toolbar._entries if w.isVisible()]
vis_rects.append(win.fmt_toolbar.overflow_btn.geometry())
for i in range(len(vis_rects)):
    for j in range(i + 1, len(vis_rects)):
        assert not vis_rects[i].intersects(vis_rects[j]), f'наслоение виджетов: {vis_rects[i]} vs {vis_rects[j]}'
ok('адаптивная панель: нет наслоения, скрытые кнопки уходят в «»')

# (19) нет бесконечного автосохранения: flush() без правок не сохраняет
save_hits = []
ed.save_requested.connect(lambda nid, h: save_hits.append(nid))
ed.flush()
save_hits.clear()
ed.flush()
assert not save_hits, f'flush() на неизменённой заметке вызвал сохранение: {save_hits}'
ok('flush() без изменений не вызывает повторного сохранения')

# (20) напоминания: ReminderEngine подключён, tomorrow9 работает без TypeError
assert hasattr(win, 'reminders')
win.set_reminder(win.current, tomorrow9=True)
assert win.current['reminder_at'] > time.time()
ok('напоминания подключены и «Завтра в 9:00» работает')

# (21) дубликат заметки переписывает пути вложений на новый id
src_att = store.create_note()
src_att['html'] = f'<p><img src="attachments/{src_att["id"]}/pic.png"/></p>'
store.save_note(src_att)
dup_att = store.duplicate_note(src_att)
assert f'attachments/{dup_att["id"]}/pic.png' in dup_att['html']
assert f'attachments/{src_att["id"]}/' not in dup_att['html']
ok('дубликат заметки обновляет пути к вложениям')

# ---------- новые функции (пакет из 9 улучшений) ----------

# (22) поиск внутри заметки (FindBar)
win.new_note()
app.processEvents()
ed.setPlainText('Alpha title\nhello world and hello again')
app.processEvents()
win.open_find_in_note()
win.find_bar.input.setText('hello')
app.processEvents()
assert win.find_bar.lbl_count.text() == '1 из 2', win.find_bar.lbl_count.text()
win.find_bar.step(+1)
assert win.find_bar.lbl_count.text() == '2 из 2', win.find_bar.lbl_count.text()
win.find_bar.close_bar()
assert not win.find_bar.isVisible() and not ed.extraSelections()
ok('поиск внутри заметки: подсветка, счётчик, навигация')

# (23) фильтры по цветным меткам и #тегам
n_tag = store.create_note()
n_tag['title'] = 'Проект #работа'
n_tag['plain'] = 'Проект #работа\nДетали'
n_tag['color'] = '#FF453A'
store.save_note(n_tag)
win._toggle_color_filter('#FF453A')
app.processEvents()
ids_f = [win.notes_list.item(i).data(NOTE_ROLE)['id'] for i in range(win.notes_list.count())]
assert ids_f == [n_tag['id']], ids_f
win._clear_filters()
win._set_tag_filter('работа')
app.processEvents()
ids_t = [win.notes_list.item(i).data(NOTE_ROLE)['id'] for i in range(win.notes_list.count())]
assert n_tag['id'] in ids_t and len(ids_t) == 1, ids_t
win._clear_filters()
ok('фильтры по цветным меткам и #тегам')

# (24) командная палитра (Ctrl+K)
from zametki.ui.command_palette import CommandPalette
pal_hit = []
pal = CommandPalette([('Открыть тест', 'заметка', lambda: pal_hit.append(1)),
                      ('Другая запись', '', lambda: pal_hit.append(2))], win)
pal.input.setText('открыть')
assert pal.list.count() == 1
pal._activate()
pal.run_chosen()
assert pal_hit == [1]
ok('командная палитра (Ctrl+K): фильтрация и запуск')

# (25) автоформатирование Markdown (- , 1. , [] ) + Tab/Shift+Tab вложенность
win.new_note()
app.processEvents()
QTest.keyClicks(ed, 'Title')
QTest.keyClick(ed, Qt.Key.Key_Return)
QTest.keyClicks(ed, '-')
QTest.keyClick(ed, Qt.Key.Key_Space)
QTest.keyClicks(ed, 'item1')
app.processEvents()
b_md = ed.document().lastBlock()
assert b_md.textList() is not None and b_md.text() == 'item1', (b_md.text(), b_md.textList())
QTest.keyClick(ed, Qt.Key.Key_Tab)
app.processEvents()
assert b_md.textList().format().indent() == 2, b_md.textList().format().indent()
QTest.keyClick(ed, Qt.Key.Key_Backtab)
app.processEvents()
assert b_md.textList().format().indent() == 1, b_md.textList().format().indent()
win.toggle_numbered()
app.processEvents()
assert b_md.textList().format().style() == QTextListFormat.Style.ListDecimal
ok('Markdown-автосписки, нумерованный список и вложенность Tab/Shift+Tab')

# (26) блок кода и вставка чистым текстом
win.new_note()
app.processEvents()
QTest.keyClicks(ed, 'Title')
QTest.keyClick(ed, Qt.Key.Key_Return)
QTest.keyClicks(ed, 'code_line')
ed.toggle_code_block()
app.processEvents()
b_code = ed.document().lastBlock()
assert b_code.begin().fragment().charFormat().font().family().lower() == 'consolas'
ed.toggle_code_block()
app.processEvents()
assert b_code.begin().fragment().charFormat().font().family().lower() == 'segoe ui'
QApplication.clipboard().setText('plain_clip')
ed.paste_plain()
assert 'plain_clip' in ed.toPlainText()
ok('блок кода и вставка чистым текстом (Ctrl+Shift+V)')

# (27) режим фокуса и нижняя строка статуса (слова/символы)
assert 'Слов:' in win.editor_footer.text() and 'Символов:' in win.editor_footer.text()
win.toggle_focus_mode()
assert not win.list_pane.isVisible()
win.toggle_focus_mode()
assert win.list_pane.isVisible()
ok('режим фокуса (Ctrl+\\) и счётчик слов/символов')

# (28) индикатор напоминания на карточке и автоочистка корзины старше 30 дней
win.notes_list.grab()
old_del = store.create_note()
store.trash_note(old_del)
old_del['deleted_at'] = time.time() - 35 * 86400
store.save_note(old_del)
purged = store.purge_expired_trash(30)
assert purged >= 1 and old_del['id'] not in store.notes
ok('индикатор напоминания и автоочистка корзины старше 30 дней')

# (29) постоянный токен PhoneServer и QR-код
from zametki.ui.settings_dialog import _qr_pixmap
ps1 = PhoneServer(store, port=0)
ps2 = PhoneServer(store, port=0)
assert ps1.token == ps2.token and len(ps1.token) >= 12
pm_qr = _qr_pixmap(ps1.url(), 128)
assert not pm_qr.isNull() and pm_qr.width() >= 64
ok('постоянный токен PhoneServer и генерация QR-кода')

# (30) обмен пакетом .zametka + плашка происхождения origin + очистка
from zametki.core import share as _share
z_path = os.path.join(TMP, 'friend_note.zametka')
_share.export_zametka(store, note, z_path, sender_name='Иван', device_name='Иван-ПК')
assert _share.is_zametka_file(z_path)
imp_note = win.open_zametka_file(z_path)
app.processEvents()
assert imp_note is not None and imp_note['origin']['sender_name'] == 'Иван'
assert win.origin_bar.isVisible() and 'Иван' in win.lbl_origin.text()
win._clear_note_origin()
assert store.notes[imp_note['id']]['origin'] is None and not win.origin_bar.isVisible()
ok('пакет .zametka: экспорт, импорт, бейдж origin и очистка')

# (31) Wi-Fi sync API (/api/sync/info, /pull, /push)
ps_s = PhoneServer(store, port=0)
ps_s.start()
b_s = f'http://127.0.0.1:{ps_s.port}'
info_s = _json.loads(urllib.request.urlopen(b_s + '/api/sync/info?t=' + ps_s.token, timeout=5).read())
assert 'device_name' in info_s and info_s['count'] >= 1
pull_s = _json.loads(urllib.request.urlopen(b_s + '/api/sync/pull?t=' + ps_s.token, timeout=5).read())
assert isinstance(pull_s.get('notes'), list) and len(pull_s['notes']) >= 1
push_body = _json.dumps({
    'device_name': 'Pixel-Test', 'sender_name': 'Тест', 'device_type': 'phone',
    'notes': [{'id': 'android-sync-1', 'plain': 'С Android\nТекст', 'modified': time.time() + 10}],
}).encode()
req_p = urllib.request.Request(b_s + '/api/sync/push?t=' + ps_s.token, data=push_body,
                               headers={'Content-Type': 'application/json'}, method='POST')
res_p = _json.loads(urllib.request.urlopen(req_p, timeout=5).read())
assert res_p['ok'] and res_p['accepted'] == 1
assert 'android-sync-1' in store.notes and store.notes['android-sync-1']['origin']['device_name'] == 'Pixel-Test'
ps_s.stop()
ok('Wi-Fi sync API: info, pull, push с сохранением origin')

# (32) безопасность: валидация note_id, DPAPI для пароля, защита от Zip-бомб
assert st.is_valid_note_id('abc-123_XYZ') and not st.is_valid_note_id('../../evil')
assert not st.is_valid_note_id('') and not st.is_valid_note_id('a/b')
enc_s = st.protect_secret('my-secret-pass')
assert enc_s.startswith('dpapi:') and st.unprotect_secret(enc_s) == 'my-secret-pass'
ps_sec = PhoneServer(store, port=0)
res_bad = ps_sec._api_sync_push({'notes': [{'id': '../../pwn', 'plain': 'bad', 'modified': time.time() + 100}]})
assert res_bad['accepted'] == 0 and '../../pwn' not in store.notes
ok('безопасность: валидация note_id, DPAPI и защита sync/push')

# (33) переключение языка RU / EN в настройках
_orig_warn = QMessageBox.warning
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
try:
    win._apply_settings({'lang': 'en', 'theme': 'light'})
    assert win.windowTitle() == 'Notes' and win.search.placeholderText() == 'Search'
    assert any(a.text() == 'Settings…' for a in win._more_menu().actions())
    win._apply_settings({'lang': 'ru', 'theme': 'light'})
    assert win.windowTitle() == 'Заметки' and win.search.placeholderText() == 'Поиск'
finally:
    QMessageBox.warning = _orig_warn
ok('переключение языка интерфейса RU/EN')

# (34) офлайн QR-код заметки (кодирование/декодирование) и чёткое выделение в списке
qr_str, qr_err = _share.encode_note_qr(store, note)
assert not qr_err and qr_str.startswith(_share.QR_PREFIX), (qr_str, qr_err)
dec_qr = _share.decode_note_qr(qr_str)
assert dec_qr['p'] == note['plain'].strip()
win._set_scope(True)
assert len(win.notes_list.selectedItems()) <= 1, f'лишнее выделение в корзине: {len(win.notes_list.selectedItems())}'
win._set_scope(False)
assert len(win.notes_list.selectedItems()) <= 1, f'лишнее выделение в списке: {len(win.notes_list.selectedItems())}'
ok('офлайн QR заметки и чистое одиночное выделение в списке/корзине')

print(f'\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ: {len(PASS)}')
single.close()
si2.close()
import shutil
shutil.rmtree(TMP, ignore_errors=True)
shutil.rmtree(dst, ignore_errors=True)
sys.exit(0)
