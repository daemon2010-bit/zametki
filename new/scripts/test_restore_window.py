# -*- coding: utf-8 -*-
"""Проверка замечания 1: повторный запуск восстанавливает окно.

Сценарий:
  A) окно открыто -> второй экземпляр -> окно поднято, второй завершился;
  B) окно закрыто (X, скрыто в трей) -> второй экземпляр -> окно снова видно.
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(os.environ, ZAMETKI_HOME=os.path.join(os.path.dirname(PROJECT), '_scratch', 'store_single'))
os.makedirs(ENV['ZAMETKI_HOME'], exist_ok=True)

u32 = ctypes.WinDLL('user32', use_last_error=True)


def find_window() -> int:
    return u32.FindWindowW(None, 'Заметки') or 0


def is_visible(hwnd: int) -> bool:
    return bool(u32.IsWindowVisible(wt.HWND(hwnd)))


def is_iconic(hwnd: int) -> bool:
    return bool(u32.IsIconic(wt.HWND(hwnd)))


def foreground() -> int:
    return u32.GetForegroundWindow() or 0


def launch():
    return subprocess.Popen([sys.executable, 'main.py'], cwd=PROJECT, env=ENV)


def wait_window(timeout=20.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = find_window()
        if hwnd and is_visible(hwnd):
            return hwnd
        time.sleep(0.3)
    return 0


def main():
    print('1) Запуск первого экземпляра…')
    a = launch()
    hwnd = wait_window()
    assert hwnd, 'окно первого экземпляра не появилось'
    print('   окно видно: hwnd=%s' % hwnd)

    print('2) Второй экземпляр при открытом окне…')
    t0 = time.time()
    b = launch()
    b.wait(timeout=30)
    dt = time.time() - t0
    assert b.returncode == 0, f'второй экземпляр вернул {b.returncode}'
    assert dt < 15, f'второй экземпляр висел {dt:.1f}с'
    assert a.poll() is None, 'первый экземпляр умер'
    time.sleep(1.5)
    hwnd2 = find_window()
    assert hwnd2 == hwnd, 'окно пересоздалось?'
    assert is_visible(hwnd2), 'окно скрылось после второго запуска'
    print(f'   второй завершился за {dt:.1f}с, окно видно и поднято (fg={foreground() == hwnd2})')

    print('3) Закрытие окна (X) — сворачивание НА ПАНЕЛЬ ЗАДАЧ…')
    u32.SendMessageW(wt.HWND(hwnd), 0x0010, 0, 0)   # WM_CLOSE
    time.sleep(1.5)
    assert a.poll() is None, 'приложение завершилось'
    hwnd3 = find_window()
    assert hwnd3, 'окно исчезло с панели задач'
    assert is_visible(hwnd3), 'окно скрыто — должно быть видно на панели задач'
    assert is_iconic(hwnd3), 'окно не свернулось'
    print('   окно свернуто, но ВИДНО на панели задач')

    print('4) Повторный запуск при скрытом окне — восстановление…')
    c = launch()
    c.wait(timeout=30)
    assert c.returncode == 0
    deadline = time.time() + 15
    visible = False
    while time.time() < deadline:
        hwnd4 = find_window()
        if hwnd4 and is_visible(hwnd4) and not is_iconic(hwnd4):
            visible = True
            break
        time.sleep(0.3)
    assert visible, 'окно не восстановилось из трея повторным запуском'
    print('   окно восстановлено и не свёрнуто')

    a.terminate()
    a.wait(timeout=10)
    print('ВСЁ ОК')


if __name__ == '__main__':
    main()
