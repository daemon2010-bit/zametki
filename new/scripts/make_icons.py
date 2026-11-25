# -*- coding: utf-8 -*-
"""Подготовка SVG-иконок приложения (по умолчанию
P:\\Настенька\\Иконки к заметкам).

Запуск: python scripts/make_icons.py [путь_к_папке_с_svg]

Копирует SVG в zametki/ui/icons_svg/ — они идут в exe и рисуются
в рантайме через QtSvg (векторно, без растровых заготовок).
Для «Удалить.svg» stroke утолщается (2.8px вместо 1) — на маленьких
размерах крестик заметнее.
"""
import os
import re
import sys

DEFAULT_SRC = r'P:\Настенька\Иконки к заметкам'
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT, 'zametki', 'ui', 'icons_svg')

# файл -> дополнительный CSS (утолщение штрихов крестика)
PATCHES = {
    'Удалить.svg': '<style>*{stroke-width:2.8px;}</style>',
}


def inject(svg_text: str, css: str) -> str:
    return re.sub(r'(<svg[^>]*>)', r'\1' + css, svg_text, count=1)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    files = sorted(f for f in os.listdir(src) if f.lower().endswith('.svg'))
    os.makedirs(OUT_DIR, exist_ok=True)
    for name in files:
        with open(os.path.join(src, name), 'r', encoding='utf-8-sig') as f:
            text = f.read()
        css = PATCHES.get(name)
        if css:
            text = inject(text, css)
        with open(os.path.join(OUT_DIR, name), 'w', encoding='utf-8') as f:
            f.write(text)
    print(f'Скопировано {len(files)} SVG -> {OUT_DIR}')


if __name__ == '__main__':
    main()
