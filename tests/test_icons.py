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

import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "android")
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

# Знаки, которых нет в шрифте Kivy на Android. Список пополнять по мере
# находок: каждый такой символ на телефоне превращается в пустой квадрат.
MISSING_IN_FONT = "♥≡♦♣♠✓✕★☆⚑⌂"


def test_buttons_do_not_rely_on_missing_glyphs():
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        src = f.read()
    for line in src.splitlines():
        if "text=" not in line:
            continue
        bad = [ch for ch in MISSING_IN_FONT if ch in line]
        assert not bad, f"символа {bad} нет в шрифте на Android: {line.strip()}"


def test_icon_button_is_used_for_donate_and_journal():
    """Кнопки доната и журнала должны брать значок из icons.py."""
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        src = f.read()
    assert re.search(r'IconButton\(icon="heart"', src)
    assert re.search(r'IconButton\(icon="journal"', src)
