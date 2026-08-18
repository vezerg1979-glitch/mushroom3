# -*- coding: utf-8 -*-
"""Вибрация рядом со старой находкой.

Проверяются в основном правила молчания, а не срабатывания. Так и задумано:
подсказка, дёргающая телефон не вовремя, раздражает сильнее, чем помогает, и
её выключат вместе с полезной — а выключенная подсказка не срабатывает уже
никогда.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "android"))

import history  # noqa: E402
import proximity  # noqa: E402

T0 = 1_700_000_000.0
LAT, LON = 55.9606, 38.0456


def _spot(dlat=0.0, dlon=0.0, count=5, species="белый", age_days=300.0):
    return history.Spot(lat=LAT + dlat, lon=LON + dlon, count=count,
                        visits=2, last_t=T0 - age_days * 86400,
                        species=species, kinds={species: count})


def _watcher(*spots, **kw):
    kw.setdefault("started", T0 - 3600)
    return proximity.Watcher(spots=list(spots), **kw)


def _m(metres):
    """Смещение по широте в градусах."""
    return metres / 111320.0


# --------------------------------------------------------------------------- #
#  Когда срабатывает
# --------------------------------------------------------------------------- #

def test_fires_near_an_old_spot():
    w = _watcher(_spot())
    hit = w.check(LAT + _m(15), LON, acc=8.0, t=T0)
    assert hit is not None
    assert hit.distance == pytest.approx(15, abs=2)
    assert "белый гриб" in hit.text


def test_stays_quiet_far_away():
    w = _watcher(_spot())
    assert w.check(LAT + _m(80), LON, acc=8.0, t=T0) is None


def test_picks_the_nearest_of_several():
    near = _spot(dlat=_m(10))
    far = _spot(dlat=_m(25))
    w = _watcher(far, near)
    hit = w.check(LAT, LON, acc=8.0, t=T0)
    assert hit.spot is near


# --------------------------------------------------------------------------- #
#  Когда молчит
# --------------------------------------------------------------------------- #

def test_one_spot_fires_once_per_walk():
    """Человек ходит вокруг куста, то входя в круг, то выходя."""
    w = _watcher(_spot())
    assert w.check(LAT + _m(10), LON, acc=8.0, t=T0) is not None
    assert w.check(LAT + _m(60), LON, acc=8.0, t=T0 + 600) is None
    assert w.check(LAT + _m(10), LON, acc=8.0, t=T0 + 1200) is None


def test_a_pause_between_any_two_alerts():
    """Места находок кучные: по старой делянке можно собрать пять подряд."""
    first = _spot(dlat=_m(10))
    second = _spot(dlat=_m(-10))
    w = _watcher(first, second)
    assert w.check(LAT, LON, acc=8.0, t=T0) is not None
    assert w.check(LAT, LON, acc=8.0, t=T0 + 30) is None
    assert w.check(LAT, LON, acc=8.0, t=T0 + proximity.QUIET_S + 1) is not None


def test_silence_at_the_start_of_the_walk():
    """Машину ставят там же, где в прошлый раз, а находки бывают у опушки.

    Без этой оговорки первое, что получил бы человек, нажав «Старт», —
    вибрацию про место, на котором он стоит.
    """
    w = _watcher(_spot(), started=T0)
    assert w.check(LAT, LON, acc=8.0, t=T0 + 10) is None
    assert w.check(LAT, LON, acc=8.0, t=T0 + proximity.GRACE_S + 1) is not None


def test_silence_when_the_signal_is_bad():
    """«В двадцати метрах» при точности ±60 м — выдумка."""
    w = _watcher(_spot())
    assert w.check(LAT + _m(10), LON, acc=60.0, t=T0) is None
    assert w.check(LAT + _m(10), LON, acc=8.0, t=T0) is not None


def test_a_single_lucky_find_is_not_a_spot():
    """Один гриб, взятый однажды, не означает грибницу."""
    w = _watcher(_spot(count=1))
    assert w.check(LAT, LON, acc=8.0, t=T0) is None


def test_nothing_to_watch_is_not_an_error():
    assert _watcher().check(LAT, LON, acc=8.0, t=T0) is None


def test_reset_arms_everything_again():
    w = _watcher(_spot())
    assert w.check(LAT, LON, acc=8.0, t=T0) is not None
    w.reset()
    assert w.check(LAT, LON, acc=8.0, t=T0) is not None


# --------------------------------------------------------------------------- #
#  Что написано под картой
# --------------------------------------------------------------------------- #

def test_text_names_species_amount_and_age():
    line = proximity.text(_spot(count=7, age_days=380), 18.0)
    assert "белый гриб" in line and "7 шт" in line and "сезон" in line


def test_text_rounds_the_distance():
    """«17,4 м» — точность, которой нет: приёмник врёт больше."""
    line = proximity.text(_spot(), 17.4)
    assert "15 м" in line or "20 м" in line


def test_text_does_not_order_the_person_around():
    """«Поищите вокруг» превращает подсказку в указание.

    Человек и так знает, что делать: он за этим сюда и пришёл.
    """
    line = proximity.text(_spot(), 20.0).lower()
    for word in ("поищ", "не пропуст", "обязательно", "!"):
        assert word not in line


@pytest.mark.parametrize("days,expected", [
    (3, "на днях"), (21, "недели назад"), (90, "месяца назад"),
    (370, "в прошлом сезоне"), (740, "два сезона назад"),
])
def test_age_wording(days, expected):
    assert expected in proximity._ago(days)


def test_unknown_species_still_gets_a_line():
    line = proximity.text(_spot(species=""), 20.0)
    assert "грибы" in line


# --------------------------------------------------------------------------- #
#  Связь с экраном
# --------------------------------------------------------------------------- #

def test_walk_screen_respects_the_setting():
    """Выключатель обязателен: кому-то это помеха, и терпеть её незачем."""
    with open(os.path.join(os.path.dirname(__file__), "..", "android",
                           "walkscreen.py"), encoding="utf-8") as f:
        src = f.read()
    assert 'prefs.get("near_buzz"' in src
    assert "proximity.Watcher" in src
    assert "buzz.tap()" in src
