# -*- coding: utf-8 -*-
"""
androidfake.py — поддельные jnius и android для проверки телефонных путей.

Зачем. Код, который трогает Android, на сборочной машине не исполняется
никогда: jnius там нет, все обёртки честно возвращают False, и тесты
проходят мимо. Дважды подряд это кончилось трассировкой в руках у человека:
сначала пропала функция целиком, потом cast получил питоновскую строку. Оба
раза — в двух строчках, которые не исполнил ни один из восьмисот тестов.

Что здесь есть. Заглушка, повторяющая НЕ поведение Android, а его строгость:

  * cast() переводит один Java-объект в другой и питоновскую строку не
    принимает — как настоящий pyjnius, слово в слово с тем же TypeError;
  * у объектов нет заранее заданных методов: вызывай что хочешь, вернётся
    такой же объект. Проверяется не логика Android, а то, что наш код
    доходит до конца, не спотыкаясь о типы и число аргументов.

Чего заглушка НЕ проверяет и проверить не может: примет ли система такой
Intent, найдётся ли программа для «Поделиться», хватит ли разрешений, не
убьёт ли процесс производитель. Это остаётся за живым телефоном. Задача
заглушки скромнее — чтобы до телефона доезжал код, который хотя бы
исполняется.
"""

from __future__ import annotations

import sys
import tempfile
import types

SDK_INT = 33          # Android 13: свежая система, но не самая новая


class JavaObject:
    """Что угодно из Java. Любой вызов возвращает такой же объект."""

    def __init__(self, name="object", value=None):
        self._name = name
        self._value = value

    def __getattr__(self, attr):
        if attr.startswith("_"):
            raise AttributeError(attr)
        return _Method(f"{self._name}.{attr}")

    def __call__(self, *a, **kw):
        return JavaObject(self._name)

    def __len__(self):
        return 0                      # поток «кончился»: циклы чтения завершатся

    def __int__(self):
        return 0

    def __or__(self, other):
        return self

    def __ror__(self, other):
        return self

    def __repr__(self):
        return f"<java {self._name}>"


class JavaValue(str):
    """Java-строка. Настоящий pyjnius отдаёт её как обычную str.

    Поэтому и здесь это str — иначе безобидное «"package:" + getPackageName()»
    падало бы в тесте, а на телефоне работало, и подделка ловила бы
    несуществующие ошибки вместо настоящих.
    """

    def __getattr__(self, attr):
        if attr.startswith("_"):
            raise AttributeError(attr)
        return _Method(f"str.{attr}")


#: Методы, у которых на телефоне заведомо строковый ответ, и он должен быть
#: правдоподобным: по этим строкам код собирает пути и адреса.
STRINGS = {
    "getPackageName": "ru.grezev.mushroomforecast",
    "getAbsolutePath": tempfile.gettempdir(),
    "getPath": tempfile.gettempdir(),
    "toString": "java-object",
}


class _Method:
    def __init__(self, name):
        self.name = name

    def __call__(self, *a, **kw):
        short = self.name.rsplit(".", 1)[-1]
        if short in STRINGS:
            return JavaValue(STRINGS[short])
        if short == "read":
            return JavaValue("")               # поток кончился
        return JavaObject(self.name + "()")

    def __getattr__(self, attr):
        return _Method(f"{self.name}.{attr}")


class JavaClass(JavaObject):
    """Класс: и вызывается как конструктор, и отдаёт статические поля."""

    def __init__(self, name):
        super().__init__(name)
        self._fields = {}

    def __getattr__(self, attr):
        if attr.startswith("_"):
            raise AttributeError(attr)
        if self._name == "android.os.Build$VERSION" and attr == "SDK_INT":
            return SDK_INT
        if attr == "mActivity":
            return JavaObject("activity")
        if attr.isupper():
            return JavaObject(f"{self._name}.{attr}")
        return _Method(f"{self._name}.{attr}")

    def __call__(self, *a, **kw):
        return JavaObject(self._name + "(new)")


def autoclass(name):
    return JavaClass(name)


def cast(signature, obj):
    """Как в pyjnius: питоновскую строку сюда передавать нельзя.

    Ошибка воспроизводится дословно, потому что именно её текст человек
    увидел на экране телефона: «Cannot convert str to jnius.JavaClass».
    """
    if isinstance(obj, (str, bytes, int, float, bool)) or obj is None:
        raise TypeError(f"Cannot convert {type(obj).__name__} "
                        f"to jnius.jnius.JavaClass")
    return obj


class PythonJavaClass:
    pass


def java_method(*a, **kw):
    def deco(f):
        return f
    return deco


def install():
    """Ставит подделки в sys.modules. Возвращает то, что было."""
    saved = {name: sys.modules.get(name)
             for name in ("jnius", "android", "android.activity",
                          "android.permissions")}

    jnius = types.ModuleType("jnius")
    jnius.autoclass = autoclass
    jnius.cast = cast
    jnius.PythonJavaClass = PythonJavaClass
    jnius.java_method = java_method
    jnius.JavaClass = JavaClass

    android = types.ModuleType("android")
    activity = types.ModuleType("android.activity")
    activity.bind = lambda **kw: None
    activity.unbind = lambda **kw: None
    android.activity = activity
    permissions = types.ModuleType("android.permissions")
    permissions.check_permission = lambda *a, **kw: True
    permissions.request_permissions = lambda *a, **kw: None
    permissions.Permission = JavaObject("Permission")
    android.permissions = permissions

    sys.modules["jnius"] = jnius
    sys.modules["android"] = android
    sys.modules["android.activity"] = activity
    sys.modules["android.permissions"] = permissions
    return saved


def restore(saved):
    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod
