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
    colors, _, species, _, _ = palette.THEMES["ночь"]
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


# --------------------------------------------------------------------------- #
#  Раскраска карты по погоде
# --------------------------------------------------------------------------- #

def test_heat_color_endpoints_match_the_gradient_definition():
    r, g, b, a = palette.heat_color(0)
    assert (round(r, 3), round(g, 3), round(b, 3)) == tuple(
        round(c, 3) for c in palette._hex_rgb(palette.HEAT_GRADIENT[0][1]))
    assert a == palette.HEAT_GRADIENT[0][2]

    r, g, b, a = palette.heat_color(100)
    assert (round(r, 3), round(g, 3), round(b, 3)) == tuple(
        round(c, 3) for c in palette._hex_rgb(palette.HEAT_GRADIENT[-1][1]))
    assert a == palette.HEAT_GRADIENT[-1][2]


def test_heat_color_clamps_out_of_range_values():
    """Сеть может дать выброс на стыке дней — обрывать отрисовку нельзя."""
    assert palette.heat_color(-40) == palette.heat_color(0)
    assert palette.heat_color(500) == palette.heat_color(100)


def test_heat_color_interpolates_smoothly_between_stops():
    """Соседние клетки разного индекса не должны давать резкий скачок
    цвета — иначе граница между ними режет глаз сильнее самого рельефа."""
    было = None
    for v in range(0, 101, 2):
        r, g, b, a = palette.heat_color(v)
        if было is not None:
            шаг = max(abs(r - было[0]), abs(g - было[1]),
                      abs(b - было[2]), abs(a - было[3]))
            assert шаг < 0.06, f"скачок цвета на значении {v}: {шаг:.3f}"
        было = (r, g, b, a)


def test_heat_color_gets_more_opaque_as_the_value_grows():
    """Низкий индекс должен еле подсвечивать клетку, а не красить её тем
    же по силе цветом, что и высокий — иначе «ярче» не про что говорить."""
    _, _, _, a_low = palette.heat_color(0)
    _, _, _, a_mid = palette.heat_color(50)
    _, _, _, a_high = palette.heat_color(100)
    assert a_low < a_mid < a_high


def test_heat_gradient_is_brighter_than_the_plate_scale():
    """Ради чего затевалась вся правка: клетка карты не должна быть такой
    же бледной, как нижняя плашка индекса (#F2F2EE — почти белый).

    Сравнение имеет смысл только днём: там нижняя плашка и правда почти
    белая, и именно она терялась на бежевой подложке карты. Ночью нижняя
    плашка сама тёмно-зелёная (#242A20) — там другая забота: не белизна,
    а чтобы низ шкалы не сливался с и так тёмной картой, и это отдельная
    проверка ниже, не сравнение с плашкой.
    """
    было = palette.current()
    try:
        palette.use("день")
        плашка_низ = palette.luminance(palette.LEVELS[-1][1])
        r, g, b, _ = palette.heat_color(60)
        карта_средняя = 0.2126 * r + 0.7152 * g + 0.0722 * b
        assert карта_средняя < плашка_низ
    finally:
        palette.use(было)


def test_night_heat_gradient_stays_visible_against_the_dark_map():
    """Ночью подложка карты и так тёмная (MAP_DIM) — низ градиента не
    должен провалиться в тот же почти-чёрный, иначе клетка с индексом 0
    от пустого места не отличить."""
    было = palette.current()
    try:
        palette.use("ночь")
        r, g, b, _ = palette.heat_color(0)
        яркость = 0.2126 * r + 0.7152 * g + 0.0722 * b
        assert яркость > palette.luminance(palette.MAP_BASE)
    finally:
        palette.use(было)


def test_both_themes_define_a_five_stop_gradient_from_zero_to_hundred():
    for name in ("день", "ночь"):
        grad = palette.THEMES[name][4]
        assert grad[0][0] == 0
        assert grad[-1][0] == 100
        значения = [v for v, _, _ in grad]
        assert значения == sorted(значения), f"{name}: значения должны идти по возрастанию"


def test_heat_gradient_survives_theme_switching():
    было = palette.current()
    try:
        palette.use("день")
        день = palette.heat_color(80)
        palette.use("ночь")
        ночь = palette.heat_color(80)
        assert день != ночь, "ночной градиент должен отличаться от дневного"
        palette.use("день")
        assert palette.heat_color(80) == день
    finally:
        palette.use(было)



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


def test_berry_colours_cover_the_engine():
    """То же самое правило для ягод — свой список, та же дыра возможна."""
    import mushroom_forecast as engine
    missing = [b.name for b in engine.BERRIES.values()
              if b.name not in palette.SPECIES_DAY
              or b.name not in palette.SPECIES_NIGHT]
    assert not missing, f"нет цвета для ягод: {missing}"


def test_berry_colours_are_distinct_from_mushroom_colours():
    """Ягода не должна красться цветом гриба — иначе на графике их не
    различить по легенде на глаз, только по подписи."""
    import mushroom_forecast as engine
    berry_colors = {palette.SPECIES_DAY[b.name] for b in engine.BERRIES.values()}
    mushroom_colors = {palette.SPECIES_DAY[s.name] for s in engine.SPECIES.values()}
    assert not (berry_colors & mushroom_colors)


def test_berry_curves_are_readable_on_the_card():
    """Тот же порог читаемости, что и у грибов, в обеих темах."""
    import mushroom_forecast as engine
    было = palette.current()
    try:
        for тема in ("день", "ночь"):
            palette.use(тема)
            for b in engine.BERRIES.values():
                ratio = palette.contrast(palette.SPECIES[b.name], palette.CARD)
                assert ratio >= 2.5, f"{тема}: {b.name} {ratio:.2f}"
    finally:
        palette.use(было)


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
