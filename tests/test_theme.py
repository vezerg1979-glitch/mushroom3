# -*- coding: utf-8 -*-
"""Смена темы: выбор, автоматика по солнцу и перечитывание цветов.

Отдельная забота здесь — функции `_apply_palette` в модулях интерфейса.
Они написаны однообразно и потому обманчиво просты: достаточно забыть одно
имя в `global`, и присваивание уйдёт в локальную переменную, а модуль
останется со старым цветом. На экране это выглядит не как ошибка, а как
наполовину перекрашенный интерфейс — и всплывает только глазами, на
телефоне. Один такой случай (LEVEL_COLORS в main.py) уже был.
"""

import ast
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

sys.path.insert(0, APP)

import palette  # noqa: E402
import prefs  # noqa: E402
import theme  # noqa: E402

T = 1_700_000_000.0
LAT, LON = 55.96, 38.04            # Фрязино


@pytest.fixture(autouse=True)
def свои_настройки(tmp_path, monkeypatch):
    """Настройки в своём каталоге: тесты не должны трогать чужие."""
    import places

    monkeypatch.setattr(places, "_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MUSHROOM_DATA_DIR", raising=False)
    было = palette.current()
    yield
    palette.use(было)


# --------------------------------------------------------------------------- #
#  Выбор режима
# --------------------------------------------------------------------------- #

def test_default_mode_is_auto():
    assert theme.mode() == "авто"


def test_explicit_modes_win_over_the_sun():
    assert theme.resolve("ночь", LAT, LON, T) == "ночь"
    assert theme.resolve("день", LAT, LON, T) == "день"


def test_auto_follows_the_sun():
    """Тёмная тема нужна не в определённые часы, а когда темно.

    В июне под Питером и в ноябре под Ростовом это разное время, поэтому
    часы для такого решения не годятся.
    """
    import sun
    from datetime import date, datetime

    d = date(2026, 9, 15)
    закат = sun.sunset(d, LAT, LON)
    восход = sun.sunrise(d, LAT, LON)
    полдень = (закат + восход) / 2
    assert theme.resolve("авто", LAT, LON, полдень) == "день"
    assert theme.resolve("авто", LAT, LON, закат + 600) == "ночь"
    assert theme.resolve("авто", LAT, LON, восход - 600) == "ночь"


def test_auto_without_coordinates_stays_light():
    """Гадать наугад хуже, чем показать привычное."""
    assert theme.resolve("авто", None, None, T) == "день"


def test_next_mode_goes_in_a_circle():
    assert theme.next_mode("авто") == "день"
    assert theme.next_mode("день") == "ночь"
    assert theme.next_mode("ночь") == "авто"


def test_set_mode_is_remembered():
    theme.set_mode("ночь", LAT, LON, T)
    assert prefs.get("theme") == "ночь"
    assert palette.current() == "ночь"
    theme.set_mode("день", LAT, LON, T)
    assert palette.current() == "день"


def test_unknown_mode_is_an_error():
    with pytest.raises(ValueError):
        theme.set_mode("сумерки")


def test_label_explains_what_auto_turned_into():
    """«Авто» без пояснения оставляет вопрос, почему экран тёмный."""
    theme.set_mode("ночь", LAT, LON, T)
    assert theme.label() == "Ночь"
    prefs.save(theme="авто")
    palette.use("ночь")
    assert theme.label() == "Авто · ночь"


def test_listeners_are_called_on_change():
    вызовы = []
    theme.register(lambda: вызовы.append(palette.current()))
    try:
        theme.set_mode("ночь", LAT, LON, T)
        theme.set_mode("день", LAT, LON, T)
        assert вызовы == ["ночь", "день"]
    finally:
        theme._listeners.pop()


def test_a_broken_listener_does_not_stop_the_others():
    """Один упрямый модуль не должен оставить остальные со старыми цветами:
    наполовину перекрашенный экран читается как поломка."""
    дошло = []

    def плохой():
        raise RuntimeError("сломался")

    theme.register(плохой)
    theme.register(lambda: дошло.append(1))
    try:
        theme.set_mode("ночь", LAT, LON, T)
        assert дошло == [1]
    finally:
        theme._listeners.pop()
        theme._listeners.pop()


# --------------------------------------------------------------------------- #
#  Перечитывание цветов в модулях
# --------------------------------------------------------------------------- #

def _modules_with_refresher():
    out = []
    for name in sorted(os.listdir(APP)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(APP, name), encoding="utf-8") as f:
            src = f.read()
        if "def _apply_palette" in src:
            out.append((name, src))
    return out


MODULES = _modules_with_refresher()


def test_every_ui_module_has_a_refresher():
    """Модуль с цветами, но без обновления, останется в старой теме."""
    имена = {n for n, _ in MODULES}
    for name in ("main.py", "walkscreen.py", "walkjournal.py", "finddialog.py",
                 "mapview.py", "backupscreen.py", "offlinemap.py"):
        assert name in имена, name


@pytest.mark.parametrize("name,src", MODULES, ids=[n for n, _ in MODULES])
def test_refresher_declares_every_name_it_assigns(name, src):
    """Забытое имя в global — это присваивание в никуда.

    Модуль остаётся со старым цветом, а экран — наполовину перекрашенным.
    Ровно так и случилось с LEVEL_COLORS в main.py: тесты молчали, ошибку
    показал скриншот.
    """
    tree = ast.parse(src)
    func = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "_apply_palette")
    объявлены = set()
    присвоены = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Global):
            объявлены |= set(node.names)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    присвоены.add(t.id)
    забыты = присвоены - объявлены
    assert not забыты, f"{name}: не объявлены global: {', '.join(sorted(забыты))}"


@pytest.mark.parametrize("name,src", MODULES, ids=[n for n, _ in MODULES])
def test_refresher_is_registered(name, src):
    assert "theme.register(_apply_palette)" in src, name


@pytest.mark.parametrize("name,src", MODULES, ids=[n for n, _ in MODULES])
def test_no_palette_colours_left_outside_the_refresher(name, src):
    """Цвет, скопированный мимо обновления, темы не заметит."""
    вне = []
    for i, line in enumerate(src.splitlines(), 1):
        if re.match(r"^[A-Z_]+ = (hexc\(palette\.|palette\.[A-Z_]+)", line):
            вне.append(f"{name}:{i}")
    assert not вне, "цвета вне _apply_palette: " + ", ".join(вне)


def test_main_repaints_instead_of_recolouring():
    """Перекрасить созданные виджеты нельзя: цвет выставлен при создании."""
    with open(os.path.join(APP, "main.py"), encoding="utf-8") as f:
        src = f.read()
    assert "def _build_ui" in src and "def _repaint" in src
    assert "self.res is not None" in src, "прогноз должен переживать пересборку"


# --------------------------------------------------------------------------- #
#  Карта ночью
# --------------------------------------------------------------------------- #

def test_map_is_dimmed_at_night():
    """Тайлы рисуются для дневного глаза и в темноте работают как фонарь.

    Привыкание к темноте сгорает за секунду, а под пологом леса после
    этого не видно ничего — поэтому карта затемняется пеленой.
    """
    with open(os.path.join(APP, "mapview.py"), encoding="utf-8") as f:
        src = f.read()
    assert "MAP_DIM" in src
    assert 'palette.current() == "ночь"' in src
    заслон = src.index("Color(0, 0, 0, MAP_DIM)")
    маршрут = src.index("# траектория похода")
    assert заслон < маршрут, "пелена должна лежать под маршрутом, а не поверх"


def test_map_base_colour_follows_the_theme():
    """Подложка под неподгруженными тайлами тоже не должна светиться."""
    assert palette.luminance(palette.THEMES["ночь"][0]["MAP_BASE"]) < 0.05
    assert palette.luminance(palette.THEMES["день"][0]["MAP_BASE"]) > 0.6
