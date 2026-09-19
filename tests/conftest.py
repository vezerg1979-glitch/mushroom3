# -*- coding: utf-8 -*-
"""
conftest.py — что делать, когда Kivy на машине нет.

Дымовой файл поднимает настоящие окна, и внутри он уже защищён:
`pytest.importorskip("kivy")` пропускает его целиком. Но защита эта
работает, только если до неё дошло исполнение. Один импорт Kivy выше по
файлу — и pytest падает ещё на СБОРЕ, а падение на сборе прекращает весь
прогон: машина без графики перестаёт проверять даже то, для чего окна не
нужны. Так дважды вставала релизная сборка, где Kivy нет вовсе.

Поэтому решение перенесено на уровень выше: если Kivy не установлен, файл
не собирается вовсе — независимо от того, что в нём написано. Тест на
верхние импорты (test_module_api) при этом остаётся: он ловит причину, а
здесь убирается последствие.
"""

import os


def _kivy_available() -> bool:
    try:
        import kivy  # noqa: F401
    except Exception:                                             # noqa: BLE001
        return False
    return True


HAS_KIVY = _kivy_available()

#: Файлы, которым без Kivy делать нечего. Список короткий и явный: скрывать
#: от сбора что попало опасно — так тихо исчезают из прогона настоящие
#: тесты, и об этом никто не узнаёт.
NEEDS_KIVY = ("smoke_ui_test.py",)


def pytest_ignore_collect(collection_path, config):
    """Пропустить файл целиком, если Kivy нет."""
    if HAS_KIVY:
        return False
    return os.path.basename(str(collection_path)) in NEEDS_KIVY


def pytest_report_header(config):
    if not HAS_KIVY:
        return "Kivy не установлен: дымовые тесты с окнами пропущены"
    return None
