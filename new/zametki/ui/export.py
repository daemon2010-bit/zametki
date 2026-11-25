# -*- coding: utf-8 -*-
"""Экспорт заметки (PDF/HTML/TXT/Markdown) и импорт TXT/HTML/Markdown."""
import os
import re

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QColor, QCursor, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox

from ..core import share
from ..core.phoneserver import plain_to_html
from ..core.store import note_plain_parts

_BAD_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def _safe_filename(title: str) -> str:
    clean = _BAD_FILENAME_RE.sub('_', (title or 'заметка').strip()).strip(' .')
    return (clean or 'заметка')[:60]


def _normalize_doc_for_print(doc: QTextDocument) -> None:
    """Перед печатью на белый лист PDF заменяет светлый текст тёмной темы
    (#F5F5F7/#FFFFFF) на тёмный #1D1D1F, чтобы текст не пропадал."""
    light_inks = {'#f5f5f7', '#ffffff', '#fff'}
    fixes = []
    b = doc.firstBlock()
    while b.isValid():
        it = b.begin()
        while not it.atEnd():
            fr = it.fragment()
            if fr.isValid():
                fmt = fr.charFormat()
                if not fmt.isImageFormat():
                    fg = fmt.foreground()
                    if fg.style() != Qt.BrushStyle.NoBrush and fg.color().name().lower() in light_inks:
                        fixes.append((fr.position(), fr.length(), fmt))
            it += 1
        b = b.next()
    for pos, length, fmt in fixes:
        clean = QTextCharFormat(fmt)
        clean.setForeground(QColor('#1D1D1F'))
        c = QTextCursor(doc)
        c.setPosition(pos)
        c.setPosition(pos + length, QTextCursor.MoveMode.KeepAnchor)
        c.setCharFormat(clean)


def _read_text_file(path: str) -> str:
    """Чтение текста с поддержкой UTF-8 (с BOM и без) и CP1251."""
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ('utf-8-sig', 'cp1251'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def export_note(parent, note) -> None:
    title = _safe_filename(note.get('title') or 'заметка')
    menu_items = (
        ('Пакет Заметки (*.zametka) - для друзей и Android', 'zametka'),
        ('PDF (*.pdf)', 'pdf'),
        ('HTML (*.html)', 'html'),
        ('Текст (*.txt)', 'txt'),
        ('Markdown (*.md)', 'md'),
    )
    menu = QMenu(parent)
    chosen = {}
    for label, kind in menu_items:
        act = menu.addAction(label)
        act.triggered.connect(lambda _=False, k=kind: chosen.__setitem__('k', k))
    anchor = getattr(parent, 'btn_export', None)
    if anchor is not None and anchor.isVisible():
        pos = anchor.mapToGlobal(anchor.rect().bottomLeft())
    else:
        pos = QCursor.pos()
    menu.exec(pos)
    kind = chosen.get('k')
    if not kind:
        return
    filters = {
        'zametka': 'Пакет Заметки (*.zametka)',
        'pdf': 'PDF (*.pdf)', 'html': 'HTML (*.html)',
        'txt': 'Текст (*.txt)', 'md': 'Markdown (*.md)',
    }
    exts = {'zametka': '.zametka', 'pdf': '.pdf', 'html': '.html', 'txt': '.txt', 'md': '.md'}
    path, _ = QFileDialog.getSaveFileName(parent, 'Экспорт заметки', title + exts[kind], filters[kind])
    if not path:
        return
    store = getattr(parent, 'store', None)
    root = getattr(store, 'root', None)
    try:
        if kind == 'zametka':
            if store is None:
                raise OSError('Хранилище недоступно')
            path = share.export_zametka(store, note, path)
        elif kind == 'pdf':
            doc = QTextDocument()
            if root:
                doc.setBaseUrl(QUrl.fromLocalFile(root + os.sep))
            doc.setHtml(note.get('html') or '')
            _normalize_doc_for_print(doc)
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(path)
            doc.print_(printer)
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                raise OSError('PDF-файл не был создан')
        elif kind == 'html':
            html_out = note.get('html') or ''
            if '<html' not in html_out.lower():
                html_out = f'<!doctype html><html><head><meta charset="utf-8"><title>{title}</title></head><body>{html_out}</body></html>'
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html_out)
        elif kind == 'txt':
            with open(path, 'w', encoding='utf-8') as f:
                f.write(note.get('plain') or '')
        elif kind == 'md':
            doc = QTextDocument()
            if root:
                doc.setBaseUrl(QUrl.fromLocalFile(root + os.sep))
            doc.setHtml(note.get('html') or '')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(doc.toMarkdown())
    except OSError as e:
        QMessageBox.warning(parent, 'Экспорт', f'Не удалось сохранить файл: {e}')
        return
    QMessageBox.information(parent, 'Экспорт', f'Сохранено: {os.path.abspath(path)}')


def import_notes(parent, store) -> int:
    """Импорт .zametka/TXT/HTML/Markdown в новые заметки. Возвращает количество."""
    paths, _ = QFileDialog.getOpenFileNames(
        parent, 'Импорт заметок', '',
        'Заметки (*.zametka *.txt *.html *.htm *.md);;Все файлы (*)')
    if not paths:
        return 0
    count = 0
    for path in paths:
        if share.is_zametka_file(path):
            try:
                share.import_zametka(store, path)
                count += 1
            except Exception:
                pass
            continue
        try:
            content = _read_text_file(path)
        except OSError:
            continue
        note = store.create_note()
        ext = os.path.splitext(path)[1].lower()
        if ext in ('.html', '.htm'):
            doc = QTextDocument()
            doc.setHtml(content)
            html, plain = doc.toHtml(), doc.toPlainText()
        elif ext == '.md':
            doc = QTextDocument()
            doc.setMarkdown(content)
            html, plain = doc.toHtml(), doc.toPlainText()
        else:
            html = plain_to_html(content)
            plain = content
        title, snippet = note_plain_parts(plain)
        note['html'] = html
        note['plain'] = plain
        note['title'] = title or os.path.splitext(os.path.basename(path))[0]
        note['snippet'] = snippet[:200]
        store.save_note(note)
        count += 1
    return count
