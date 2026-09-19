# -*- coding: utf-8 -*-
"""Тесты значков на кнопках.

Повод. На кнопках доната и журнала стояли символы «♥» и «≡». В шрифте, который
Kivy кладёт в APK, их нет, и на телефоне обе кнопки выглядели как пустой
квадрат с крестом. Проверить это на глаз нельзя: на компьютере при отладке
подставляется системный шрифт и всё рисуется.

Поэтому здесь две вещи. Первая — арифметика значков: она не зависит от Kivy и
считается на компьютере. Вторая — сторож в исходнике, чтобы подпись-символ не
вернулась на кнопку следующей правкой.
"""

import ast
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

ROOT = APP
sys.path.insert(0, ROOT)

import icons  # noqa: E402

NAMES = sorted(icons.ICONS)


# --------------------------------------------------------------------------- #
#  Границы
# --------------------------------------------------------------------------- #

def bounds(shapes):
    """Описанный прямоугольник всех примитивов, с учётом толщины линий."""
    xs, ys = [], []
    for it in shapes:
        kind = it[0]
        if kind == "ellipse":
            x, y, w, h = it[1:]
            xs += [x, x + w]
            ys += [y, y + h]
        elif kind == "quad":
            p = it[1]
            xs += list(p[0::2])
            ys += list(p[1::2])
        elif kind == "line":
            p, lw = it[1], it[2]
            xs += [v - lw / 2 for v in p[0::2]] + [v + lw / 2 for v in p[0::2]]
            ys += [v - lw / 2 for v in p[1::2]] + [v + lw / 2 for v in p[1::2]]
        elif kind == "rrect":
            x, y, w, h, _r, lw = it[1:]
            xs += [x - lw / 2, x + w + lw / 2]
            ys += [y - lw / 2, y + h + lw / 2]
        elif kind == "arc":
            # Дуга оценивается по описанной окружности: с запасом, зато без
            # разбора углов — от теста нужна граница, а не точный контур.
            cx, cy, r, _a1, _a2, lw = it[1:]
            xs += [cx - r - lw / 2, cx + r + lw / 2]
            ys += [cy - r - lw / 2, cy + r + lw / 2]
        elif kind == "tri":
            p = it[1]
            xs += list(p[0::2])
            ys += list(p[1::2])
        else:
            raise AssertionError(f"неизвестный примитив {kind!r}")
    return min(xs), min(ys), max(xs), max(ys)


@pytest.mark.parametrize("name", NAMES)
def test_icon_fits_the_box(name):
    """Значок не вылезает за отведённый квадрат.

    Вылезший значок на кнопке 48 dp упирается в соседнюю и выглядит обрезком.
    """
    x0, y0, x1, y1 = bounds(icons.shapes(name, 10.0, 20.0, 100.0, 100.0))
    assert x0 >= 10.0 - 0.01 and y0 >= 20.0 - 0.01
    assert x1 <= 110.0 + 0.01 and y1 <= 120.0 + 0.01


@pytest.mark.parametrize("name", NAMES)
def test_icon_fills_the_box(name):
    """И не съёживается в точку посреди кнопки.

    Ошибка в делителе легко даёт значок втрое меньше нужного, а такой на
    экране в лесу просто не виден.
    """
    x0, y0, x1, y1 = bounds(icons.shapes(name, 0.0, 0.0, 100.0, 100.0))
    assert (x1 - x0) >= 70.0
    assert (y1 - y0) >= 70.0


@pytest.mark.parametrize("name", NAMES)
def test_icon_is_centered(name):
    x0, y0, x1, y1 = bounds(icons.shapes(name, 0.0, 0.0, 100.0, 100.0))
    assert (x0 + x1) / 2 == pytest.approx(50.0, abs=1.0)
    assert (y0 + y1) / 2 == pytest.approx(50.0, abs=1.0)


@pytest.mark.parametrize("name", NAMES)
def test_icon_scales_linearly(name):
    """Вдвое больший квадрат — вдвое большая фигура.

    Значок рисуется и в строке на 48 dp, и крупнее; жёстко вписанный размер
    заметен только на одном из экранов.
    """
    small = bounds(icons.shapes(name, 0.0, 0.0, 50.0, 50.0))
    big = bounds(icons.shapes(name, 0.0, 0.0, 100.0, 100.0))
    for a, b in zip(small, big):
        assert b == pytest.approx(a * 2, abs=0.01)


def test_unknown_icon_is_loud():
    """Опечатка в имени должна падать сразу, а не рисовать пустую кнопку."""
    with pytest.raises(ValueError):
        icons.shapes("серце", 0.0, 0.0, 10.0, 10.0)


# --------------------------------------------------------------------------- #
#  Сторож: буквы на кнопках
# --------------------------------------------------------------------------- #

# Знаки за пределами латиницы и кириллицы, которые в шрифте Kivy ЕСТЬ.
# Список получен разбором самого Roboto-Regular.ttf из поставки Kivy — того
# файла, который уезжает в APK. Всё, чего здесь нет, на телефоне становится
# пустым квадратом; на компьютере при отладке подставляется системный шрифт,
# и увидеть это до сборки нельзя.
FONT_HAS = set("≥−…—–·«»°±×÷§№")

# Модули, которые печатают в терминал, а не рисуют на телефоне: у консоли
# свой шрифт, и блоки со стрелками там выводятся нормально.
CONSOLE_ONLY = {"mushroom_forecast.py", "journal.py"}


def _visible_strings(path):
    """Строковые литералы модуля, кроме докстрок.

    Разбор через ast, а не поиск по тексту: комментарии и докстроки человеку
    на экране не показываются, и запрещать в них упоминание знака «♥» —
    значит запретить объяснить, почему его нельзя ставить на кнопку.
    """
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    docs = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            docs.add(id(body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docs):
            yield node.lineno, node.value


def _kivy_modules():
    for name in sorted(os.listdir(ROOT)):
        if name.endswith(".py") and name not in CONSOLE_ONLY:
            yield name


@pytest.mark.parametrize("name", list(_kivy_modules()))
def test_no_glyphs_the_bundled_font_lacks(name):
    """Ни одного знака, которого нет в шрифте, в видимых строках.

    Так уже дважды ловили пустые квадраты: сердце на кнопке доната, стрелки
    в подсказках навигации и полоска «почему такой индекс», набранная
    блочными знаками. Каждый раз это выяснялось на телефоне в лесу.
    """
    bad = []
    for no, text in _visible_strings(os.path.join(ROOT, name)):
        for ch in text:
            o = ord(ch)
            if o < 0x2000 or 0x0400 <= o <= 0x04FF:
                continue
            if ch not in FONT_HAS:
                bad.append((no, ch, hex(o), text[:50]))
    assert not bad, f"нет в шрифте: {bad[:4]}"


def test_icon_button_is_used_for_journal():
    """Кнопка журнала должна брать значок из icons.py.

    Раньше здесь же проверялась кнопка доната («heart»); её на главном
    экране заменила кнопка «Без рекламы» — текстовая, без значка, — когда
    донат уступил место покупке без рекламы. Значок сердца остался в
    icons.py как таковой (может пригодиться), просто на кнопку больше не
    навешан.
    """
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        src = f.read()
    assert re.search(r'IconButton\(icon="journal"', src)
