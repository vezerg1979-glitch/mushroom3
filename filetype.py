# -*- coding: utf-8 -*-
"""Заглушка вместо пакета filetype. НЕ УДАЛЯТЬ.

Kivy 2.3.1 при импорте `kivy.graphics` тянет `kivy.core.image`, а тот делает
`import filetype`. Без этого модуля приложение падает на старте:

    ModuleNotFoundError: No module named 'filetype'

и умирает ещё до создания окна — пользователь видит только заставку «Loading»,
а встроенный обработчик ошибок не успевает сработать, потому что находится
ниже по файлу.

Настоящий пакет с PyPI в requirements не добавлен намеренно: рецепта под него
у python-for-android нет, и сборка обрывается на этапе create. Приложению эта
библиотека не нужна — картинок в нём нет, определять форматы нечему.
"""

__version__ = "0.0.0-stub"


def guess(_obj=None):
    return None


def guess_mime(_obj=None):
    return None


def guess_extension(_obj=None):
    return None


def get_type(**_kw):
    return None


def image_match(_obj=None):
    return None


def is_image(_obj=None):
    return False
