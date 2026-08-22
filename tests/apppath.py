# -*- coding: utf-8 -*-
"""
apppath.py — где лежит android/, если спрашивать не у рабочего каталога.

Все тесты искали исходники строкой `os.path.join(os.path.dirname(__file__),
"..", "android")`. Пока pytest запускали из корня проекта, это работало. В
релизной сборке он запускается иначе, `__file__` оказывается не тем, что
ожидалось, и путь превращается в `<корень>/../android` — каталог за
пределами проекта. Сборка встала на сборе тестов, не дойдя ни до одной
проверки.

Здесь тот же вопрос решается поиском, а не арифметикой: от файла теста
вверх, пока не найдётся каталог `android` с узнаваемым содержимым. Опознаётся
он по нескольким файлам сразу — иначе первый попавшийся каталог с таким
именем (а он бывает в .buildozer) сойдёт за исходники, и тесты будут молча
проверять чужую копию, отставшую на сборку.
"""

import os

#: Файлы, по которым каталог опознаётся как исходники приложения.
MARKERS = ("main.py", "palette.py", "buildozer.spec")


def find_app(start: str = None, levels: int = 6) -> str:
    """Каталог android/ проекта. Ошибка, если его нет, — а не пустой путь.

    Пустой или неверный путь молча превращает половину тестов в проверку
    пустоты: импорты падают, файлы не находятся, а причина выглядит как
    поломка приложения.
    """
    here = os.path.dirname(os.path.abspath(start or __file__))
    for _ in range(levels):
        candidate = os.path.join(here, "android")
        if all(os.path.isfile(os.path.join(candidate, m)) for m in MARKERS):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    raise RuntimeError(
        "каталог android/ не найден: тесты запущены вне проекта "
        f"(искали от {os.path.dirname(os.path.abspath(start or __file__))})")


#: Готовый путь: тесты берут его как есть.
APP = find_app()
