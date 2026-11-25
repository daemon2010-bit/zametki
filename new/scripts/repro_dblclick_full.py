# -*- coding: utf-8 -*-
"""Репро на реальном MainWindow: серия жестов по заголовку + контроль стиля."""
import os
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from zametki.core.store import Store
from zametki.ui.main_window import MainWindow
from zametki.ui.theme import ThemeManager


def fmt_line(editor):
    doc = editor.document()
    block = doc.firstBlock()
    segs = []
    it = block.begin()
    while not it.atEnd():
        fr = it.fragment()
        if fr.isValid():
            f = fr.charFormat().font()
            segs.append((fr.text(), f.pointSize(), f.bold()))
        it += 1
    return segs


def check(step, editor):
    segs = fmt_line(editor)
    ok = all(s[1] == 17 and s[2] for s in segs if s[0].strip()) if segs else True
    print(f'{step:32s} {"OK " if ok else "BREAK"}: {segs}')
    return ok


def main():
    app = QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix='zam_full_')
    store = Store(tmp)
    note = store.create_note()
    note['html'] = ('<html><body style=" font-family:\'Segoe UI\'; font-size:11pt;">'
                    '<p>Проверка заголовка текст</p>'
                    '<p>вторая строка тела</p>'
                    '</body></html>')
    note['plain'] = 'Проверка заголовка текст\nвторая строка тела'
    store.save_note(note)

    win = MainWindow(store, ThemeManager(), None)
    win.resize(1100, 700)
    win.show()
    app.processEvents()
    # выбрать заметку
    win.notes_list.setCurrentRow(0)
    app.processEvents()
    QTest.qWait(300)

    ed = win.editor
    vp = ed.viewport()

    def center_of_word(word_idx):
        block = ed.document().firstBlock()
        words = block.text().split(' ')
        pos = block.position() + sum(len(w) + 1 for w in words[:word_idx]) + len(words[word_idx]) // 2
        cur = ed.textCursor()
        cur.setPosition(pos)
        return ed.cursorRect(cur).center()

    c1 = center_of_word(0)   # "Проверка"
    c2 = center_of_word(1)   # "заголовка"
    print('точки:', c1, c2, 'DPR:', vp.devicePixelRatioF())

    # 1. одиночный двойной клик по первому слову
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c1)
    QTest.qWait(100)
    check('двойной клик слово1', ed)

    # 2. двойной клик по второму слову (двойное выделение подряд)
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c2)
    QTest.qWait(100)
    check('двойной клик слово2', ed)

    # 3. двойной клик + набор текста (замена слова)
    QTest.keyClicks(ed, 'NEWTXT')
    QTest.qWait(100)
    check('двойной клик + ввод', ed)

    # 4. тройной клик (двойной двойной = выделение строки)
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c1)
    QTest.qWait(50)
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c1)
    QTest.qWait(100)
    check('двойной двойной клик', ed)

    # 5. двойной клик + перетаскивание слова внутри строки (move-drop)
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c2)
    QTest.qWait(50)
    drag_to = QPoint(c2.x() + 120, c2.y())
    QTest.mouseMove(vp, drag_to)
    QTest.mouseMove(vp, QPoint(drag_to.x() + 5, drag_to.y()))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, drag_to)
    QTest.qWait(100)
    check('двойной клик + drag', ed)

    # 6. двойной клик по первому слову + ввод
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c1)
    QTest.qWait(50)
    QTest.keyClicks(ed, 'Z')
    QTest.qWait(200)
    check('клик слово1 + ввод', ed)

    shutil.rmtree(tmp, ignore_errors=True)
    QTimer.singleShot(50, app.quit)
    app.exec()


if __name__ == '__main__':
    main()
