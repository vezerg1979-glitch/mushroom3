# -*- coding: utf-8 -*-
"""Тесты навигации. Запуск: pytest -q

Проверяются не формулы ради формул, а сценарии из леса: ушёл по кривой —
вернись напрямую; стоишь — курса нет; дошёл — не веди дальше.
"""

import math
import os
import sys
from dataclasses import dataclass

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "android"))

import nav  # noqa: E402

# Фрязино, откуда автор ездит по грибы
LAT, LON = 55.9606, 38.0456


@dataclass
class P:
    lat: float
    lon: float


def north(lat, lon, m):
    """Точка в m метрах строго на север."""
    return lat + m / 111320.0, lon


def east(lat, lon, m):
    """Точка в m метрах строго на восток."""
    return lat, lon + m / (111320.0 * math.cos(math.radians(lat)))


# --------------------------------------------------------------------------- #
#  Геометрия
# --------------------------------------------------------------------------- #

def test_distance_matches_known_offset():
    lat2, lon2 = north(LAT, LON, 1000)
    assert nav.haversine(LAT, LON, lat2, lon2) == pytest.approx(1000, abs=5)


def test_bearing_cardinal_directions():
    assert nav.bearing(LAT, LON, *north(LAT, LON, 500)) == pytest.approx(0, abs=1)
    assert nav.bearing(LAT, LON, *east(LAT, LON, 500)) == pytest.approx(90, abs=1)


def test_rumb_wraps_around_north():
    assert nav.rumb(0) == "север"
    assert nav.rumb(350) == "север"       # 350° — это ещё север, не северо-запад
    assert nav.rumb(46) == "северо-восток"
    assert nav.rumb(180, short=True) == "Ю"


def test_relative_is_signed_and_short():
    assert nav.relative(10, 350) == pytest.approx(20)     # через ноль, вправо
    assert nav.relative(350, 10) == pytest.approx(-20)    # через ноль, влево
    assert abs(nav.relative(200, 20)) == pytest.approx(180)


def test_turn_hint_reads_naturally():
    assert nav.turn_hint(0, 0) == "прямо"                 # цель по курсу
    assert "направо" in nav.turn_hint(90, 0)
    assert "налево" in nav.turn_hint(270, 0)
    assert "назад" in nav.turn_hint(180, 0)


# --------------------------------------------------------------------------- #
#  Курс движения
# --------------------------------------------------------------------------- #

def test_course_none_when_standing_still():
    """Дрожание приёмника на месте не должно выглядеть как ходьба."""
    pts = [P(LAT + i * 1e-6, LON - i * 1e-6) for i in range(6)]
    assert nav.course_over_ground(pts) is None


def test_course_from_straight_walk():
    pts = [P(*north(LAT, LON, i * 20)) for i in range(6)]
    assert nav.course_over_ground(pts) == pytest.approx(0, abs=3)


def test_course_needs_two_points():
    assert nav.course_over_ground([]) is None
    assert nav.course_over_ground([P(LAT, LON)]) is None


# --------------------------------------------------------------------------- #
#  Сценарии
# --------------------------------------------------------------------------- #

def test_return_to_car_after_loop():
    """Ушёл петлёй на километр — обратно ведёт по прямой, а не по следу."""
    pts = [P(LAT, LON)]
    for i in range(1, 30):                       # на север
        pts.append(P(*north(LAT, LON, i * 40)))
    far = pts[-1]
    for i in range(1, 20):                       # затем на восток
        pts.append(P(*east(far.lat, far.lon, i * 40)))

    fix = nav.guide_to_start(_walk(pts))
    assert fix is not None
    assert fix.distance == pytest.approx(1440, abs=120)
    # старт остался на юго-западе
    assert 200 < fix.bearing < 260
    assert not fix.arrived
    assert "км" in fix.text


def test_arrived_stops_guiding():
    pts = [P(LAT, LON), P(*north(LAT, LON, 5))]
    fix = nav.guide_to_start(_walk(pts))
    assert fix.arrived
    assert fix.text == "вы на месте"
    assert fix.detail == ""


def test_text_uses_turn_when_moving_and_rumb_when_standing():
    target = north(LAT, LON, 800)

    standing = nav.guide(LAT, LON, *target, points=[P(LAT, LON)])
    assert "на север" in standing.text
    assert "курс появится" in standing.detail

    walking = nav.guide(LAT, LON, *target,
                        points=[P(*north(LAT, LON, i * 20)) for i in range(5)])
    assert walking.text.startswith("прямо")
    assert "курс появится" not in walking.detail


def test_arrow_relative_when_moving():
    """Идём на север, цель на востоке — стрелка вправо, 90°."""
    pts = [P(*north(LAT, LON, i * 20)) for i in range(5)]
    here = pts[-1]
    fix = nav.guide(here.lat, here.lon, *east(here.lat, here.lon, 500), points=pts)
    assert fix.arrow_deg == pytest.approx(90, abs=3)


def test_guide_to_start_needs_points():
    assert nav.guide_to_start(_walk([])) is None


# --------------------------------------------------------------------------- #
#  Выбор ближайшей цели и формат
# --------------------------------------------------------------------------- #

def test_nearest_picks_closest_spot():
    a, b = P(*north(LAT, LON, 900)), P(*north(LAT, LON, 300))
    best, d = nav.nearest(LAT, LON, [a, b])
    assert best is b
    assert d == pytest.approx(300, abs=10)


def test_nearest_of_empty_list():
    best, d = nav.nearest(LAT, LON, [])
    assert best is None and d == float("inf")


def test_distance_format_rounds_sensibly():
    assert nav.fmt_distance(7) == "10 м"          # точнее GPS всё равно не знает
    assert nav.fmt_distance(344) == "340 м"
    assert nav.fmt_distance(1240) == "1,2 км"


def test_walk_minutes_never_zero():
    assert nav.walk_minutes(5) == 1
    assert nav.walk_minutes(2500) == pytest.approx(60, abs=2)


def test_spread_is_max_departure_not_path_length():
    pts = [P(LAT, LON), P(*north(LAT, LON, 500)), P(LAT, LON)]
    assert nav.spread(pts) == pytest.approx(500, abs=10)


def _walk(points):
    class W:
        pass
    w = W()
    w.points = points
    return w
