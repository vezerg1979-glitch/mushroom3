# -*- coding: utf-8 -*-
"""Тесты палитры.

Экран открывают в лесу: солнце в стекле, яркость сбита ради батареи, поверх
плёнка с отпечатками. Подобрать цвет на мониторе и решить, что «читается», —
самый дешёвый способ сделать приложение бесполезным именно там, где оно нужно.
Поэтому пары «текст на фоне» проверяются арифметикой WCAG, а не глазом.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

sys.path.insert(0, APP)

import palette  # noqa: E402


# --------------------------------------------------------------------------- #
#  Арифметика
# --------------------------------------------------------------------------- #

def test_contrast_extremes():
    assert palette.contrast("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.05)
    assert palette.contrast("#777777", "#777777") == pytest.approx(1.0, abs=0.01)


def test_contrast_is_symmetric():
    a = palette.contrast(palette.INK, palette.CARD)
    assert a == pytest.approx(palette.contrast(palette.CARD, palette.INK))


def test_luminance_rejects_short_form():
    with pytest.raises(ValueError):
        palette.luminance("#FFF")


# --------------------------------------------------------------------------- #
#  Текст
# --------------------------------------------------------------------------- #

# Тем две, и пороги для них одинаковые. Тёмная тема, набранная на глаз,
# обычно проваливает контраст сильнее светлой: на чёрном фоне серый текст
# кажется читаемым, пока не выйдешь с телефоном на солнце. Поэтому каждая
# проверка ниже гоняется по обеим темам, а не по той, что включена сейчас.
THEMES = sorted(palette.THEMES)


@pytest.fixture(params=THEMES)
def theme(request):
    было = palette.current()
    palette.use(request.param)
    yield request.param
    palette.use(было)


@pytest.mark.parametrize("fg", ["INK", "MUTED", "ACCENT_TEXT"])
@pytest.mark.parametrize("bg", ["BG", "CARD", "SOFT"])
def test_text_readable_on_every_surface(theme, fg, bg):
    ratio = palette.contrast(getattr(palette, fg), getattr(palette, bg))
    assert ratio >= palette.MIN_CONTRAST, (
        f"{theme}: {fg} на {bg}: {ratio:.2f}, нужно {palette.MIN_CONTRAST}")


@pytest.mark.parametrize("bg", ["ACCENT", "BLUE", "RED"])
def test_white_readable_on_coloured_buttons(theme, bg):
    ratio = palette.contrast(palette.ON_DARK, getattr(palette, bg))
    assert ratio >= palette.MIN_CONTRAST_LARGE, f"{theme}: {bg} {ratio:.2f}"


# --------------------------------------------------------------------------- #
#  Шкала индекса
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", THEMES)
def test_index_number_readable_on_every_plate(name):
    """Цифра индекса читается на плашке в любой теме."""
    for threshold, bg, fg in palette.THEMES[name][1]:
        ratio = palette.contrast(fg, bg)
        assert ratio >= palette.MIN_CONTRAST, (
            f"{name}: порог {threshold}, {ratio:.2f}")


def test_night_species_curves_stand_out_from_the_dark_card():
    """Коричневые дневные цвета на почти чёрном сливаются в одну линию.

    Проверяется только ночной набор. У дневного слабое место своё и давнее:
    жёлтая лисичка на белом даёт 2.17, и трогать это здесь — значит менять
    привычный вид графика заодно с темой. Отдельная задача.
    """
    colors, _, species, _ = palette.THEMES["ночь"]
    for vid, color in species.items():
        ratio = palette.contrast(color, colors["CARD"])
        assert ratio >= 2.5, f"{vid}: {ratio:.2f}"


def test_night_species_are_lighter_than_day_ones():
    for vid, night in palette.SPECIES_NIGHT.items():
        assert palette.luminance(night) > palette.luminance(
            palette.SPECIES_DAY[vid]), vid


@pytest.mark.parametrize("name", THEMES)
def test_night_is_actually_dark(name):
    """Сторож против «тёмной темы», которая светлее дневной.

    Проверяются обе: правка, осветлившая ночной фон или затемнившая
    дневной, ломает весь смысл переключения.
    """
    day = palette.THEMES["день"][0]
    night = palette.THEMES["ночь"][0]
    assert palette.luminance(night["BG"]) < 0.05
    assert palette.luminance(day["BG"]) > 0.7
    assert palette.luminance(night["INK"]) > palette.luminance(night["BG"])


@pytest.mark.parametrize("name", THEMES)
def test_every_theme_defines_the_same_names(name):
    """Недостающий цвет в теме — это AttributeError на экране."""
    assert set(palette.THEMES[name][0]) == set(palette.DAY)
    assert len(palette.THEMES[name][1]) == len(palette.LEVELS_DAY)
    assert set(palette.THEMES[name][2]) == set(palette.SPECIES_DAY)


def test_switching_back_and_forth_restores_colours():
    было = palette.current()
    day = palette.BG
    palette.use("ночь")
    assert palette.BG != day
    palette.use("день")
    assert palette.BG == day
    palette.use(было)


def test_unknown_theme_is_an_error():
    with pytest.raises(ValueError):
        palette.use("сумерки")


@pytest.mark.parametrize("threshold,bg,fg", palette.LEVELS_DAY)
def test_index_number_readable_on_its_plate(threshold, bg, fg):
    """Цифра индекса — главное число на экране, включая ноль.

    Две пары раньше не проходили: 68 «обильно» давала 2.96 (белым по
    светло-зелёному), а нулевая плашка 2.39. То есть хуже всего читались
    ровно те два случая, ради которых прогноз и открывают: «ехать стоит»
    и «ехать незачем».
    """
    ratio = palette.contrast(fg, bg)
    assert ratio >= palette.MIN_CONTRAST, (
        f"уровень {threshold}: {ratio:.2f}")


def test_levels_go_down_to_zero():
    thresholds = [t for t, _, _ in palette.LEVELS]
    assert thresholds == sorted(thresholds, reverse=True)
    assert thresholds[-1] == 0


def test_level_colors_covers_whole_range():
    for v in (-5, 0, 7, 17, 32, 49, 67, 84, 100, 140):
        bg, fg = palette.level_colors(v)
        assert palette.contrast(fg, bg) >= palette.MIN_CONTRAST


# --------------------------------------------------------------------------- #
#  Единая палитра
# --------------------------------------------------------------------------- #

def test_species_colours_cover_the_engine():
    """Вид без цвета рисуется серым и сливается с соседями на графике."""
    import mushroom_forecast as engine
    missing = [s.name for s in engine.SPECIES.values()
               if s.name not in palette.SPECIES]
    assert not missing, f"нет цвета для: {missing}"


def test_no_hard_coded_colours_left_in_ui():
    """Цвет, выписанный в файле экрана, рано или поздно разойдётся с палитрой.

    Проверка ищет шестизначные литералы в вызовах hexc: любой такой цвет
    должен переехать в palette.py и получить имя.
    """
    import re
    root = APP
    found = {}
    for name in ("main.py", "walkscreen.py", "navwidget.py"):
        with open(os.path.join(root, name), encoding="utf-8") as f:
            hits = re.findall(r'hexc\("#[0-9A-Fa-f]{6}"\)', f.read())
        if hits:
            found[name] = hits
    assert not found, found


def test_donate_window_uses_the_same_palette():
    import donate
    assert donate.INK_HEX == palette.INK
    assert donate.MUTED_HEX == palette.MUTED
    assert donate.contrast is palette.contrast
