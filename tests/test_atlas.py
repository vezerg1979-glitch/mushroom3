# -*- coding: utf-8 -*-
"""Тесты эталонных изображений грибов.

Виджеты Kivy без экрана не поднять, поэтому здесь проверяется то, что от
экрана не зависит: геометрия рисунков, разбор примитивов, полнота таблиц и
сторожа в исходниках — чтобы картинка не пропала из окна «Что нашли?»
следующей правкой.

Главная проверка — выпуклость многоугольников. Заливка идёт веером
треугольников из центра тяжести, и у невыпуклой фигуры веер вылезает за
контур. На телефоне это выглядит как лишний угол у шляпки: ошибка, которую
принимают за задумку и не чинят месяцами.
"""

import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "android")
sys.path.insert(0, ROOT)

import atlas  # noqa: E402
import mushroom_forecast as engine  # noqa: E402
import palette  # noqa: E402

KEYS = sorted(atlas.PICTURES)


def _src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------- #
#  Полнота
# --------------------------------------------------------------------------- #

def test_every_species_has_a_picture():
    """Вид без картинки — пустая клетка в списке выбора."""
    assert set(atlas.PICTURES) == set(engine.SPECIES)


def test_no_orphan_pictures():
    """Картинка без вида означает, что вид переименовали, а атлас забыли."""
    for key in atlas.PICTURES:
        assert key in engine.SPECIES, key


def test_every_species_has_slug_and_features():
    for key in engine.SPECIES:
        assert key in atlas.SLUG, key
        assert key in atlas.FEATURES, key


def test_slugs_are_ascii_and_unique():
    """Кириллица в путях внутри APK ведёт себя по-разному на прошивках."""
    slugs = list(atlas.SLUG.values())
    assert len(slugs) == len(set(slugs))
    for slug in slugs:
        assert re.fullmatch(r"[a-z0-9_]+", slug), slug


@pytest.mark.parametrize("key", KEYS)
def test_features_are_filled_in(key):
    """Признаки и двойники — обязательная часть эталона.

    Картинка отвечает на вопрос «на какую кнопку жать», а не «съедобно ли
    это». Пустой список двойников читается как «двойников нет», хотя значит
    «никто не проверял», поэтому у каждого вида он непустой: там, где
    двойников действительно нет, так и написано словами.
    """
    info = atlas.FEATURES[key]
    assert len(info.get("marks", [])) >= 2
    assert len(info.get("twins", [])) >= 1
    for line in info["marks"] + info["twins"]:
        assert line.strip() and len(line) > 15


def test_deadly_twins_are_named_where_they_exist():
    """Сторож: для сыроежки и опёнка смертельный двойник назван прямо.

    Оба вида собирают вёдрами и на автомате. Если из карточки пропадёт
    бледная поганка или галерина, ошибку заметит только тот, кто уже
    отравился.
    """
    assert "поганк" in " ".join(atlas.FEATURES["сыроежка"]["twins"]).lower()
    assert "галерин" in " ".join(atlas.FEATURES["опёнок"]["twins"]).lower()


def test_warning_says_picture_is_not_a_determinant():
    """Предупреждение обязано стоять в карточке, а не просто лежать в модуле."""
    assert "не берите" in atlas.WARNING.lower()
    src = _src("atlas.py")
    assert src.count("WARNING") >= 2, "предупреждение объявлено, но не показано"


# --------------------------------------------------------------------------- #
#  Геометрия
# --------------------------------------------------------------------------- #

def _polys(items):
    return [it[2] for it in items if it[0] == "poly"]


def bounds(items):
    """Описанный прямоугольник всех примитивов, с учётом толщины линий."""
    xs, ys = [], []
    for it in items:
        kind = it[0]
        if kind == "poly":
            pts = it[2]
            xs += list(pts[0::2])
            ys += list(pts[1::2])
        elif kind in ("dome", "ellipse"):
            _, _, cx, cy, rx, ry = it
            xs += [cx - rx, cx + rx]
            # У полукупола низа нет: рисуется только верхняя половина.
            ys += [cy if kind == "dome" else cy - ry, cy + ry]
        elif kind == "line":
            pts, lw = it[2], it[3]
            xs += [v - lw / 2 for v in pts[0::2]] + [v + lw / 2 for v in pts[0::2]]
            ys += [v - lw / 2 for v in pts[1::2]] + [v + lw / 2 for v in pts[1::2]]
        else:
            raise AssertionError(f"неизвестный примитив {kind!r}")
    return min(xs), min(ys), max(xs), max(ys)


@pytest.mark.parametrize("key", KEYS)
def test_polygons_are_convex(key):
    """Иначе веер треугольников зальёт то, чего на рисунке нет."""
    for pts in _polys(atlas.shapes(key, 0.0, 0.0, 100.0, 100.0)):
        n = len(pts) // 2
        assert n >= 3
        signs = set()
        for i in range(n):
            ax, ay = pts[2 * i], pts[2 * i + 1]
            bx, by = pts[2 * ((i + 1) % n)], pts[2 * ((i + 1) % n) + 1]
            cx, cy = pts[2 * ((i + 2) % n)], pts[2 * ((i + 2) % n) + 1]
            cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
            if abs(cross) > 1e-9:
                signs.add(cross > 0)
        assert len(signs) == 1, f"{key}: невыпуклый многоугольник {pts}"


@pytest.mark.parametrize("key", KEYS)
def test_picture_stays_inside_its_box(key):
    x0, y0, x1, y1 = bounds(atlas.shapes(key, 10.0, 20.0, 100.0, 100.0))
    assert x0 >= 10.0 - 0.01 and x1 <= 110.0 + 0.01
    assert y0 >= 20.0 - 0.01 and y1 <= 120.0 + 0.01


@pytest.mark.parametrize("key", KEYS)
def test_picture_fills_most_of_its_box(key):
    """Мелкий гриб посреди пустой плашки читается как «картинка не загрузилась»."""
    x0, y0, x1, y1 = bounds(atlas.shapes(key, 0.0, 0.0, 100.0, 100.0))
    assert (x1 - x0) > 60.0, key
    assert (y1 - y0) > 60.0, key


@pytest.mark.parametrize("key", KEYS)
def test_picture_is_square_and_centred(key):
    """На широкой строке гриб не растягивается в блин, а садится по центру."""
    x0, _, x1, _ = bounds(atlas.shapes(key, 0.0, 0.0, 200.0, 100.0))
    assert x0 > 45.0 and x1 < 155.0
    assert abs((x0 + x1) / 2 - 100.0) < 6.0


@pytest.mark.parametrize("key", KEYS)
def test_colors_are_hex(key):
    for it in atlas.shapes(key, 0.0, 0.0, 10.0, 10.0):
        palette.luminance(it[1])            # бросит ValueError на кривом цвете


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("bg", [palette.CARD, palette.SOFT])
def test_silhouette_reads_on_its_backing(key, bg):
    """Хоть один цвет должен отличаться от подложки, на которой рисунок стоит.

    Подложек две: белая в строке выбора и светло-серая в карточке метки.
    Груздь и сыроежка сами белые, и на первой из них бледная заливка
    пропадала совсем — на телефоне в бликах вместо гриба пустая плашка.
    Порог невысокий: это силуэт, а не текст.
    """
    best = max(palette.contrast(it[1], bg)
               for it in atlas.shapes(key, 0.0, 0.0, 10.0, 10.0))
    assert best >= 2.0, key


def test_pictures_are_not_copies_of_each_other():
    """Сторож против копипасты: одинаковые наборы цветов — почти наверняка
    забытая правка после дублирования функции."""
    seen = {}
    for key in KEYS:
        palette_of = frozenset(it[1] for it in atlas.shapes(key, 0, 0, 10, 10))
        assert palette_of not in seen, f"{key} и {seen.get(palette_of)}"
        seen[palette_of] = key


def test_unknown_species_is_an_error_not_an_empty_picture():
    with pytest.raises(ValueError):
        atlas.shapes("мухомор", 0, 0, 10, 10)


# --------------------------------------------------------------------------- #
#  Разбор примитивов
# --------------------------------------------------------------------------- #

def test_plan_handles_every_primitive_that_shapes_produces():
    """Тот же разбор, что делает виджет. Ловит рассинхрон полей кортежа."""
    kinds = set()
    for key in KEYS:
        for item in atlas.shapes(key, 0.0, 0.0, 64.0, 64.0):
            what, color, kwargs = atlas.plan(item)
            assert what in ("mesh", "ellipse", "line")
            assert isinstance(kwargs, dict) and kwargs
            palette.luminance(color)
            kinds.add(item[0])
    assert kinds == {"poly", "dome", "ellipse", "line"}


def test_plan_rejects_nonsense():
    with pytest.raises(ValueError):
        atlas.plan(("клякса", "#000000", 1, 2))


def test_poly_becomes_a_closed_fan():
    """Вершин должно быть на две больше: центр веера и замыкающая точка."""
    what, _, kwargs = atlas.plan(("poly", "#123456", (0.0, 0.0, 4.0, 0.0, 0.0, 3.0)))
    assert what == "mesh" and kwargs["mode"] == "triangle_fan"
    assert len(kwargs["vertices"]) == (3 + 2) * 4
    assert kwargs["vertices"][0:2] == [4.0 / 3.0, 1.0]          # центр тяжести
    assert kwargs["vertices"][-4:-2] == [0.0, 0.0]              # замыкание
    assert kwargs["indices"] == list(range(5))


def test_dome_draws_only_the_upper_half():
    _, _, kwargs = atlas.plan(("dome", "#123456", 10.0, 20.0, 4.0, 3.0))
    assert kwargs["pos"] == (6.0, 17.0) and kwargs["size"] == (8.0, 6.0)
    assert kwargs["angle_start"] == -90 and kwargs["angle_end"] == 90


def test_line_width_is_halved_for_kivy():
    """Kivy рисует линию вдвое толще: width=1 даёт два пикселя."""
    _, _, kwargs = atlas.plan(("line", "#123456", (0.0, 0.0, 1.0, 1.0), 4.0))
    assert kwargs["width"] == 2.0


# --------------------------------------------------------------------------- #
#  Свои фотографии
# --------------------------------------------------------------------------- #

def test_photo_path_is_none_without_a_file():
    assert atlas.photo_path("белый") is None or os.path.exists(
        atlas.photo_path("белый"))


def test_photo_path_picks_up_a_dropped_in_file(tmp_path, monkeypatch):
    """Фотографию кладут в assets и пересобирают APK, не трогая код."""
    monkeypatch.setattr(atlas, "ASSETS", str(tmp_path))
    assert atlas.photo_path("лисичка") is None
    (tmp_path / "lisichka.jpg").write_bytes(b"")
    assert atlas.photo_path("лисичка").endswith("lisichka.jpg")


def test_photo_path_ignores_unknown_species():
    assert atlas.photo_path("мухомор") is None


# --------------------------------------------------------------------------- #
#  Сторожа в исходниках
# --------------------------------------------------------------------------- #

def test_species_dialog_shows_pictures():
    """Список выбора вида не должен вернуться к голым надписям."""
    src = _src("atlas.py")
    assert "class SpeciesRow" in src and "SpeciesPicture(key=key" in src


def test_only_one_species_list_in_the_app():
    """Список видов строится в одном месте.

    Мест, где выбирают вид, стало два: постановка метки и исправление уже
    поставленной. Второй список, собранный на месте, разъезжается с первым
    незаметно — в одном одиннадцать видов, в другом девять.
    """
    for name in ("walkscreen.py", "finddialog.py"):
        src = _src(name)
        assert "atlas.picker" in src, name
        assert "SPECIES.items()" not in src, f"{name}: свой список видов"


def test_whole_row_is_the_tap_target():
    """Картинка не должна становиться отдельной кнопкой внутри строки:
    маленькая мишень рядом с большой — промах в перчатке."""
    src = _src("atlas.py")
    assert "class SpeciesPicture(Widget)" in src
    assert "class SpeciesPicture(ButtonBehavior" not in src
    assert "SpeciesPicture(ButtonBehavior, Widget)" not in src


def test_find_card_offers_the_reference():
    src = _src("finddialog.py")
    assert "_fill_reference" in src and "atlas.card" in src


def test_species_can_be_changed_without_losing_the_find():
    """Исправление вида не должно проходить через удаление метки.

    Вместе с меткой уходили бы снимки, заметка и координаты — то есть всё,
    ради чего её ставили; а переснять срезанный гриб уже нельзя.
    """
    src = _src("finddialog.py")
    assert "_set_species" in src
    assert "on_change=self._ask_species" in src
    atlas_src = _src("atlas.py")
    assert "on_change" in atlas_src and "Это другой вид" in atlas_src


def test_assets_folder_is_packed_into_apk():
    """Без jpg и png в include_exts подложенная фотография не уедет в APK."""
    with open(os.path.join(ROOT, "buildozer.spec"), encoding="utf-8") as f:
        spec = f.read()
    line = re.search(r"^source\.include_exts\s*=\s*(.+)$", spec, re.M).group(1)
    assert "jpg" in line and "png" in line
