# -*- coding: utf-8 -*-
"""Слой прошлых походов на карте.

Смысл слоя: грибник ходит по одним и тем же местам, и приложение уже знает,
где он брал. Проверяется то, от чего зависит польза этого знания в лесу —
что маршрут после прореживания остаётся тем же маршрутом, что находки у
одной ели не превращаются в кляксу, и что карта не пытается нарисовать
десятки тысяч точек на каждый тик GPS.

Виджеты Kivy без экрана не поднять, поэтому рисование проверяется разбором
исходника, а вся арифметика — напрямую.
"""

import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

ROOT = APP
sys.path.insert(0, ROOT)

import history  # noqa: E402
import places  # noqa: E402
import track  # noqa: E402


@pytest.fixture
def data_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(places, "_DATA_DIR", tmp)
        yield tmp


def _find(lat, lon, species="белый", count=1, t=None):
    return track.Find(lat=lat, lon=lon, t=t or time.time(),
                      species=species, count=count)


# --------------------------------------------------------------------------- #
#  Прореживание
# --------------------------------------------------------------------------- #

def test_straight_line_collapses_to_its_ends():
    """На прямой просеке промежуточные точки не несут ничего."""
    pts = [(55.90 + i * 0.001, 38.00) for i in range(20)]
    out = history.simplify(pts, tol_m=12.0)
    assert out == [pts[0], pts[-1]]


def test_corner_survives():
    """Поворот — единственное, ради чего линию вообще рисуют."""
    pts = [(55.900, 38.000), (55.901, 38.000), (55.902, 38.000),
           (55.902, 38.002), (55.902, 38.004)]
    out = history.simplify(pts, tol_m=12.0)
    assert (55.902, 38.000) in out
    assert out[0] == pts[0] and out[-1] == pts[-1]


def test_simplify_keeps_ends_and_order():
    pts = [(55.9 + i * 0.0002, 38.0 + (i % 3) * 0.0003) for i in range(200)]
    out = history.simplify(pts, tol_m=12.0)
    assert out[0] == pts[0] and out[-1] == pts[-1]
    assert len(out) < len(pts)
    assert out == [p for p in pts if p in out]          # порядок не нарушен


def test_jitter_of_a_standing_receiver_is_dropped():
    """Час у костра — это сотни точек в круге пяти метров."""
    pts = [(55.9 + (i % 2) * 0.00002, 38.0 + (i % 3) * 0.00002)
           for i in range(300)]
    assert len(history.simplify(pts, tol_m=12.0)) <= 3


def test_simplify_survives_a_very_long_track():
    """Рекурсивная версия падала по пределу вложенности — на карте в лесу."""
    pts = [(55.9 + i * 0.00003, 38.0 + i * 0.00003) for i in range(20000)]
    out = history.simplify(pts, tol_m=1.0)
    assert out[0] == pts[0] and out[-1] == pts[-1]


def test_thin_caps_the_number_of_points():
    pts = [(55.9 + i * 0.0001, 38.0) for i in range(5000)]
    out = history.thin(pts, limit=300)
    assert len(out) == 300
    assert out[0] == pts[0] and out[-1] == pts[-1]


def test_thin_leaves_short_tracks_alone():
    pts = [(55.9, 38.0), (55.91, 38.01)]
    assert history.thin(pts, limit=300) == pts


# --------------------------------------------------------------------------- #
#  Слияние находок
# --------------------------------------------------------------------------- #

def test_finds_at_one_spruce_become_one_spot():
    """Иначе пять меток у одной ели рисуются кляксой в полэкрана."""
    finds = [_find(55.90000, 38.00000, count=2),
             _find(55.90010, 38.00010, count=3),
             _find(55.90005, 38.00005, count=1)]
    spots = history.merge(finds, radius_m=30.0)
    assert len(spots) == 1
    assert spots[0].count == 6
    assert spots[0].visits == 3


def test_distant_finds_stay_apart():
    """Два конца поляны — это два места, а не одно."""
    spots = history.merge([_find(55.900, 38.000), _find(55.910, 38.010)],
                          radius_m=30.0)
    assert len(spots) == 2


def test_spot_center_is_the_average():
    """Одна неточная координата под пологом не должна утащить место."""
    spots = history.merge([_find(55.90000, 38.00000),
                           _find(55.90020, 38.00000)], radius_m=50.0)
    assert spots[0].lat == pytest.approx(55.9001, abs=1e-5)


def test_dominant_species_wins_the_colour():
    """Цвет точки — по тому, чего здесь брали больше."""
    spots = history.merge([_find(55.9, 38.0, "лисичка", 2),
                           _find(55.90005, 38.0, "белый", 9)], radius_m=30.0)
    assert spots[0].species == "белый"
    assert spots[0].kinds == {"лисичка": 2, "белый": 9}


def test_spots_are_sorted_so_the_richest_draws_last():
    finds = [_find(55.900, 38.000, count=1), _find(55.950, 38.050, count=40)]
    spots = history.merge(finds, radius_m=30.0)
    assert [s.count for s in spots] == [1, 40]


def test_merge_order_does_not_matter():
    finds = [_find(55.9, 38.0, "белый", 2, t=100),
             _find(55.90008, 38.00008, "белый", 5, t=200),
             _find(55.93, 38.03, "лисичка", 7, t=150)]
    a = history.merge(finds, 30.0)
    b = history.merge(list(reversed(finds)), 30.0)
    assert [(s.count, s.species) for s in a] == [(s.count, s.species) for s in b]


def test_plain_marks_have_no_species():
    """«Просто метка» — тоже ориентир, но вид у неё пустой."""
    spots = history.merge([_find(55.9, 38.0, species="", count=1)], 30.0)
    assert spots[0].species == ""


# --------------------------------------------------------------------------- #
#  Загрузка
# --------------------------------------------------------------------------- #

def _saved_walk(started, pts, finds=()):
    w = track.Walk(started=started, place="Ельник")
    w.points = [track.Point(lat, lon, started + i * 10)
                for i, (lat, lon) in enumerate(pts)]
    w.finds = list(finds)
    track.save(w)
    return w


def test_load_returns_trails_and_spots(data_dir):
    now = time.time()
    _saved_walk(now - 86400 * 30,
                [(55.90 + i * 0.0005, 38.00) for i in range(50)],
                [_find(55.905, 38.000, "белый", 4)])
    _saved_walk(now - 86400 * 400,
                [(55.95 + i * 0.0005, 38.10) for i in range(50)],
                [_find(55.955, 38.100, "лисичка", 6)])
    h = history.load()
    assert len(h.trails) == 2
    assert len(h.spots) == 2
    assert all(len(t.points) >= 2 for t in h.trails)
    assert bool(h) is True


def test_load_skips_the_current_walk(data_dir):
    """Живой трек рисуется ярко; блёклая копия поверх него — «запись раздвоилась»."""
    now = time.time()
    _saved_walk(now - 3600, [(55.90 + i * 0.001, 38.0) for i in range(10)])
    _saved_walk(now - 86400, [(55.80 + i * 0.001, 38.0) for i in range(10)])
    assert len(history.load(skip_started=now - 3600).trails) == 1


def test_load_ignores_walks_without_a_route(data_dir):
    """Поход из одной точки — не линия; находки из него всё равно нужны."""
    _saved_walk(time.time() - 7200, [(55.9, 38.0)],
                [_find(55.9, 38.0, "подберёзовик", 3)])
    h = history.load()
    assert h.trails == []
    assert len(h.spots) == 1


def test_load_is_bounded(data_dir):
    """Сотня сезонов не должна открывать окно похода полминуты."""
    now = time.time()
    for i in range(12):
        _saved_walk(now - 86400 * (i + 1),
                    [(55.9 + i * 0.01, 38.0), (55.9 + i * 0.01, 38.01)])
    assert len(history.load(max_walks=5).trails) == 5


def test_empty_history_is_falsy(data_dir):
    h = history.load()
    assert not h
    assert h.summary() == "Прошлых походов пока нет"


def test_summary_counts_in_russian(data_dir):
    now = time.time()
    _saved_walk(now - 86400, [(55.9, 38.0), (55.9, 38.01)],
                [_find(55.9, 38.0)])
    s = history.load().summary()
    assert "1 маршрут," in s
    assert "1 место находок" in s


def test_broken_track_file_does_not_break_the_layer(data_dir):
    """Один битый файл не должен лишать человека всей подложки."""
    _saved_walk(time.time() - 86400, [(55.9, 38.0), (55.9, 38.01)])
    with open(os.path.join(data_dir, track.TRACKS_DIR, "2020-01-01_0000.json"),
              "w", encoding="utf-8") as f:
        f.write("{это не json")
    assert len(history.load().trails) == 1


# --------------------------------------------------------------------------- #
#  Карта
# --------------------------------------------------------------------------- #

def _src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_map_draws_history_under_the_live_track():
    """Подложка не должна спорить с сегодняшним треком и своей точкой."""
    src = _src("mapview.py")
    body = src[src.index("    def redraw(self"):]
    layer = body.index("self._draw_history()")
    live = body.index("# траектория похода")
    here = body.index("# текущее положение")
    assert layer < live < here


def test_history_layer_can_be_switched_off():
    assert "def toggle_history" in _src("walkscreen.py")
    assert "self.show_history" in _src("mapview.py")


def test_history_is_loaded_in_a_thread():
    """Окно похода открывают, стоя у машины: ждать чтения архива нельзя."""
    src = _src("walkscreen.py")
    i = src.index("def _load_history")
    assert "threading.Thread" in src[i:i + 900]


def test_tapping_an_old_spot_opens_it_instead_of_moving_the_marker():
    src = _src("mapview.py")
    i = src.index("spot = self._spot_at")
    j = src.index("self.set_marker(*self._latlon(*touch.pos))", i)
    assert "return True" in src[i:j]


def test_old_spot_can_become_a_named_place():
    """Грибной угол должен уметь стать местом с собственным прогнозом.

    Иначе точка живёт только внутри похода: со стартового экрана её не
    видно и погоду по ней не посчитать — а именно за этим человек и
    вернётся в следующий раз.
    """
    src = _src("walkscreen.py")
    assert "def _keep_spot" in src
    i = src.index("def _keep_spot")
    assert "places_mod.add(" in src[i:i + 700]


def test_new_place_gets_a_ready_made_name():
    """Ввод текста мокрыми руками в лесу — гарантия, что не сохранят вовсе."""
    src = _src("walkscreen.py")
    i = src.index("def spot_name")
    body = src[i:i + 700]
    assert "engine.SPECIES.get" in body
    assert "%d.%m.%Y" in body
