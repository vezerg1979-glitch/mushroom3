#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Единая точка входа: python main.py

Сам выбирает лучший доступный интерфейс:
  1. PySide6  -> полноценное окно с графиком по всем видам, матрицей,
                 разбором «почему такой прогноз» и справкой;
  2. Kivy     -> мобильный интерфейс (он же собирается в APK);
  3. ничего   -> консольный вывод из mushroom_forecast.py.

Принудительный выбор:
    python main.py --ui desktop
    python main.py --ui mobile
    python main.py --ui cli --place "Фрязино" --days 10
Все остальные аргументы передаются дальше без изменений.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.join(HERE, "desktop")
MOBILE = os.path.join(HERE, "android")


def _has(module: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _pop_ui_arg() -> str | None:
    """Достаёт --ui из argv, остальное оставляет нижележащему приложению."""
    for i, a in enumerate(sys.argv[1:], start=1):
        if a == "--ui" and i + 1 < len(sys.argv):
            val = sys.argv[i + 1]
            del sys.argv[i:i + 2]
            return val.lower()
        if a.startswith("--ui="):
            val = a.split("=", 1)[1]
            del sys.argv[i]
            return val.lower()
    return None


def run_desktop() -> int:
    sys.path.insert(0, DESKTOP)
    os.chdir(DESKTOP)
    import mushroom_gui
    return mushroom_gui.main()


def run_mobile() -> int:
    sys.path.insert(0, MOBILE)
    os.chdir(MOBILE)
    import main as mobile_app
    mobile_app.MushroomApp().run()
    return 0


def run_cli() -> int:
    sys.path.insert(0, DESKTOP)
    import mushroom_forecast
    return mushroom_forecast.main()


def main() -> int:
    want = _pop_ui_arg()

    if want in ("desktop", "gui", "pyside", "pyside6"):
        return run_desktop()
    if want in ("mobile", "kivy", "android"):
        return run_mobile()
    if want in ("cli", "console", "text"):
        return run_cli()
    if want:
        print(f"Неизвестное значение --ui: {want}. "
              f"Допустимо: desktop, mobile, cli.", file=sys.stderr)
        return 2

    if _has("PySide6"):
        return run_desktop()
    if _has("kivy"):
        print("PySide6 не найден — запускаю мобильный интерфейс.\n"
              "Полная версия ставится так:  pip install PySide6", file=sys.stderr)
        return run_mobile()

    print("Не найдено ни PySide6, ни Kivy — работаю в консоли.\n"
          "Полноценное окно:  pip install PySide6\n", file=sys.stderr)
    return run_cli()


if __name__ == "__main__":
    sys.exit(main())
