# -*- coding: utf-8 -*-
"""Поворот экрана: когда две колонки, когда столбец и когда пересобирать.

Правило простое, но три вещи в нём легко сделать неправильно, и все три
видны только на телефоне: развернуть в колонки узкий экран, где колонки
превращаются в огрызки; пересобирать экран на каждое событие размера (за
один поворот Android присылает их десятки); и забыть, что квадратное окно
бывает.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

sys.path.insert(0, APP)

import layout  # noqa: E402


# --------------------------------------------------------------------------- #
#  Что считается горизонтальным
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("w,h,ожидание", [
    (1080, 1920, False),      # телефон стоймя
    (1920, 1080, True),       # он же на боку
    (800, 1280, False),       # планшет стоймя
    (1280, 800, True),
    (1000, 1000, False),      # квадрат: одинаково плох в обеих раскладках
    (0, 0, False),            # окна ещё нет
])
def test_is_landscape(w, h, ожидание):
    assert layout.is_landscape(w, h) is ожидание


def test_narrow_landscape_stays_a_single_column():
    """Старый телефон шириной 320 точек: на боку это 560.

    Колонки вышли бы по 320 и 240, и подписи кнопок в правой начали бы
    ломаться по словам. Первая версия этого теста брала 640×360 и уверяла,
    что там «по 180 точек», — арифметика была моя, ошибка тоже: 640 на боку
    делится на вполне рабочие 370 и 270.
    """
    assert layout.is_landscape(560, 320)
    assert not layout.two_columns(560, 320)


def test_ordinary_phone_on_its_side_gets_two_columns():
    assert layout.two_columns(640, 360)


def test_wide_landscape_gets_two_columns():
    assert layout.two_columns(1280, 720)


def test_density_is_taken_into_account():
    """Пиксели и независимые точки — разные вещи.

    Экран 1600 пикселей при плотности 3 — это 533 dp, то есть узкий
    телефон на боку, а не планшет: считать надо в точках.
    """
    assert layout.two_columns(1600, 900, dp_scale=1.0)
    assert not layout.two_columns(1600, 900, dp_scale=3.0)
    assert not layout.two_columns(1000, 600, dp_scale=3.0)


def test_columns_share_the_whole_width():
    left, right = layout.split(1280)
    assert left + right == pytest.approx(1.0)
    assert left > right, "смотрят слева, нажимают справа"


def test_split_survives_nonsense():
    assert sum(layout.split(1280, 5.0)) == pytest.approx(1.0)
    assert sum(layout.split(1280, -1.0)) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
#  Когда пересобирать
# --------------------------------------------------------------------------- #

def test_rebuild_only_when_the_layout_actually_changes():
    """Android присылает десятки событий размера за один поворот.

    Пересборка на каждое — это моргание и потерянная прокрутка.
    """
    assert layout.changed((1080, 1920), (1920, 1080))
    assert not layout.changed((1080, 1920), (1080, 1900))
    assert not layout.changed((1920, 1080), (1900, 1070))


def test_narrow_rotation_does_not_rebuild():
    """На старом телефоне обе раскладки — столбец: пересобирать нечего."""
    assert not layout.changed((320, 560), (560, 320))


# --------------------------------------------------------------------------- #
#  Сторожа в исходниках
# --------------------------------------------------------------------------- #

def _src(name):
    with open(os.path.join(APP, name), encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("name", ["main.py", "walkscreen.py"])
def test_screens_arrange_parts_instead_of_building_twice(name):
    """Две отдельные сборки одного экрана разъезжаются молча.

    Кнопку добавят в одну раскладку и забудут в другой — и человек,
    повернувший телефон, её просто не найдёт.
    """
    src = _src(name)
    assert "def _arrange" in src
    assert "layout.two_columns" in src
    assert src.count("parts[") > 8


@pytest.mark.parametrize("name", ["main.py", "walkscreen.py"])
def test_every_part_is_placed_in_both_layouts(name):
    """Часть, забытая в одной из раскладок, пропадает с экрана."""
    import ast
    import re

    src = _src(name)
    кладут = set(re.findall(r'parts\["([a-z0-9_]+)"\] = ', src))
    берут = set(re.findall(r'parts\["([a-z0-9_]+)"\]', src)) - кладут
    tree = ast.parse(src)
    arrange = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_arrange")
    ключи = set()
    for node in ast.walk(arrange):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            ключи.add(node.value)
    пропали = кладут - ключи - берут
    assert not пропали, f"{name}: части не расставлены: {', '.join(sorted(пропали))}"


def test_spec_allows_rotation():
    with open(os.path.join(APP, "buildozer.spec"), encoding="utf-8") as f:
        spec = f.read()
    строка = [l for l in spec.splitlines() if l.startswith("orientation")]
    assert строка, "в spec нет orientation"
    assert "portrait" not in строка[0] or "all" in строка[0], строка[0]
