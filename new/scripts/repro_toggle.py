# -*- coding: utf-8 -*-
"""Репро: кнопки форматирования при выделении — включают и не снимают."""
import os
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from zametki.core.store import Store
from zametki.ui.main_window import MainWindow
from zametki.ui.theme import ThemeManager


def frag_line(editor, block):
    segs = []
    it = block.begin()
    while not it.atEnd():
        fr = it.fragment()
        if fr.isValid():
            f = fr.charFormat().font()
            segs.append((fr.text(), f.pointSize(), int(f.weight()),
                         f.italic(), f.underline()))
        it += 1
    return segs


def main():
    app = QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix='zam_toggle_')
    store = Store(tmp)
    note = store.create_note()
    note['html'] = ('<html><body style=" font-family:\'Segoe UI\'; font-size:11pt;">'
                    '<p>Заголовок заметки</p>'
                    '<p>Обычный текст тела для проверки</p>'
                    '</body></html>')
    note['plain'] = 'Заголовок заметки\nОбычный текст тела для проверки'
    store.save_note(note)

    win = MainWindow(store, ThemeManager(), None)
    win.resize(1100, 700)
    win.show()
    app.processEvents()
    win.notes_list.setCurrentRow(0)
    app.processEvents()
    QTest.qWait(300)

    ed = win.editor
    vp = ed.viewport()
    body = ed.document().lastBlock()

    def word_center(word_idx):
        words = body.text().split(' ')
        pos = body.position() + sum(len(w) + 1 for w in words[:word_idx]) + len(words[word_idx]) // 2
        cur = ed.textCursor()
        cur.setPosition(pos)
        return ed.cursorRect(cur).center()

    print('=== A: двойной клик мышью по слову тела + кнопка B дважды')
    c = word_center(0)   # «Обычный»
    print('до           :', frag_line(ed, body))
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c)
    QTest.qWait(100)
    win.toggle_bold()
    QTest.qWait(100)
    print('после B(1)   :', frag_line(ed, body))
    win.toggle_bold()
    QTest.qWait(100)
    print('после B(2)   :', frag_line(ed, body))
    win.toggle_bold()
    QTest.qWait(100)
    print('после B(3)   :', frag_line(ed, body))

    print('=== B: то же, но кнопка B через реальный клик QTest по кнопке')
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c)
    QTest.qWait(100)
    QTest.mouseClick(win.fmt_buttons['bold'], Qt.MouseButton.LeftButton)
    QTest.qWait(100)
    print('после B(1)   :', frag_line(ed, body))
    QTest.mouseClick(win.fmt_buttons['bold'], Qt.MouseButton.LeftButton)
    QTest.qWait(100)
    print('после B(2)   :', frag_line(ed, body))

    print('=== C: выделение программное + toggle_italic дважды')
    cur = ed.textCursor()
    cur.setPosition(body.position() + 8)
    cur.setPosition(body.position() + 12, QTextCursor.MoveMode.KeepAnchor)
    ed.setTextCursor(cur)
    win.toggle_italic()
    QTest.qWait(100)
    print('после I(1)   :', frag_line(ed, body))
    win.toggle_italic()
    QTest.qWait(100)
    print('после I(2)   :', frag_line(ed, body))

    print('=== D: подчёркнутый дважды (программное выделение)')
    ed.setTextCursor(cur)
    win.toggle_under()
    QTest.qWait(100)
    print('после U(1)   :', frag_line(ed, body))
    win.toggle_under()
    QTest.qWait(100)
    print('после U(2)   :', frag_line(ed, body))

    shutil.rmtree(tmp, ignore_errors=True)
    QTimer.singleShot(50, app.quit)
    app.exec()


if __name__ == '__main__':
    main()
