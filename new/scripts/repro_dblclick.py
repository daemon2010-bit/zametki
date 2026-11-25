# -*- coding: utf-8 -*-
"""Репро: двойной щелчок по заголовку (первой строке) редактора.

Проверяем, меняет ли Qt (или наши обработчики) символы первой строки.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from zametki.ui.editor import NoteEditor


def fmt_line(editor):
    """[(текст, размер, жирность)] — сегменты первой строки."""
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


def main():
    app = QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix='zam_repro_')

    class FakeStore:
        root = tmp
        attach_dir = os.path.join(tmp, 'attachments')

    html = ('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0//EN" "http://www.w3.org/TR/REC-html40/strict.dtd">'
            '<html><head><meta name="qrichtext" content="1" /><meta charset="utf-8" /></head>'
            '<body style=" font-family:\'Segoe UI\'; font-size:11pt; font-weight:400;">'
            '<p style=" margin-top:0px; margin-bottom:0px;">Проверка заголовка текст</p>'
            '<p style=" margin-top:0px; margin-bottom:0px;">вторая строка</p>'
            '</body></html>')
    editor = NoteEditor(lambda: {'text': '#1D1D1F', 'text2': '#6B6A66', 'sel': '#FFE18F'})
    editor.set_store(FakeStore())
    editor.resize(600, 400)
    editor.show()
    editor.load_note({'id': 'test', 'html': html})
    app.processEvents()

    print('ПОСЛЕ ЗАГРУЗКИ :', fmt_line(editor))

    # координаты первого слова: поднимаемся из начала блока
    rect = editor.cursorRect(editor.textCursor())
    block = editor.document().firstBlock()
    cur = editor.textCursor()
    cur.setPosition(block.position() + 3)   # внутри слова "Проверка"
    r = editor.cursorRect(cur)
    pos = r.center()
    print('точка щелчка   :', pos)

    QTest.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    app.processEvents()
    print('после клика    :', fmt_line(editor))

    QTest.mouseDClick(editor.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    app.processEvents()
    print('после 2х клика :', fmt_line(editor))
    print('выделение      :', editor.textCursor().selectedText())

    # сценарий А: после двойного клика сразу ввести текст (замена слова)
    cur = editor.textCursor()
    print('текущий формат ввода:', editor.currentCharFormat().font().pointSize(),
          editor.currentCharFormat().font().bold())
    cur.insertText('замена')
    app.processEvents()
    print('после ввода    :', fmt_line(editor))

    QTimer.singleShot(100, app.quit)
    app.exec()


if __name__ == '__main__':
    main()
