# -*- coding: utf-8 -*-
"""Тесты переноса похода в журнал калибровки."""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

sys.path.insert(0, APP)

import journal  # noqa: E402
import track  # noqa: E402
import walk2journal as w2j  # noqa: E402


def make_walk(km=3.0, finds=(), place="Фрязино", biotope="березняк"):
    w = track.Walk(place=place, biotope=biotope)
    t = time.time()
    lat, lon = 55.96, 38.04
    step = 20.0
    n = max(2, int(km * 1000 / step))
    for i in range(n):
        lat += step / 111320.0
        w.add_point(lat, lon, 10.0, t + i * 20)
    for key in finds:
        w.add_find(lat, lon, key)
    return w


# --------------------------------------------------------------------------- #
#  Оценка обилия
# --------------------------------------------------------------------------- #

def test_score_zero_for_nothing():
    assert w2j.score_for(0, 5.0) == 0


def test_score_grows_with_density():
    assert w2j.score_for(1, 5.0) == 1        # единично
    assert w2j.score_for(10, 5.0) == 2       # мало
    assert w2j.score_for(30, 5.0) == 3       # умеренно
    assert w2j.score_for(100, 5.0) == 5      # массово


def test_same_count_scores_lower_on_long_walk():
    """Пять белых на километр и на десять — разные события."""
    assert w2j.score_for(5, 1.0) > w2j.score_for(5, 10.0)


def test_short_walk_does_not_explode_density():
    """Двести метров и ведро грибов не должны дать деление на ноль."""
    assert 1 <= w2j.score_for(20, 0.05) <= 5


def test_any_find_scores_at_least_one():
    assert w2j.score_for(1, 100.0) >= 1


# --------------------------------------------------------------------------- #
#  Записи
# --------------------------------------------------------------------------- #

def test_one_entry_per_species():
    w = make_walk(finds=["белый", "белый", "лисичка"])
    entries = w2j.entries_from_walk(w)
    keys = sorted(e.key for e in entries)
    assert keys == ["белый", "лисичка"]


def test_counts_are_summed_per_species():
    w = make_walk(km=2.0, finds=["белый"] * 8)
    e = [x for x in w2j.entries_from_walk(w) if x.key == "белый"][0]
    assert "8 шт." in e.note
    assert e.score >= 2


def test_empty_walk_is_recorded_too():
    """Промах — тоже данные: без них модель обучится только на удачах."""
    w = make_walk(km=5.0)
    entries = w2j.entries_from_walk(w)
    assert len(entries) == 1
    assert entries[0].score == 0
    assert entries[0].key == ""
    assert "пусто" in entries[0].note


def test_walk_without_points_gives_nothing():
    w = track.Walk(place="тест")
    assert w2j.entries_from_walk(w) == []


def test_coordinates_are_centroid_of_finds():
    w = make_walk(finds=["белый"])
    e = w2j.entries_from_walk(w)[0]
    f = w.finds[0]
    assert e.lat == pytest.approx(f.lat)
    assert e.lon == pytest.approx(f.lon)


def test_place_and_biotope_carried_over():
    w = make_walk(finds=["лисичка"])
    e = w2j.entries_from_walk(w)[0]
    assert e.place == "Фрязино"
    assert e.biotope == "березняк"


def test_typo_in_biotope_raises_instead_of_silent_substitution():
    """journal.Entry подменяет незнакомый биотоп на «смешанный» молча —
    в журнал ушли бы данные не про тот лес."""
    w = make_walk(finds=["белый"])
    with pytest.raises(ValueError, match="берёзовый"):
        w2j.entries_from_walk(w, biotope="берёзовый")


def test_explicit_place_overrides_walk():
    w = make_walk(finds=["лисичка"])
    e = w2j.entries_from_walk(w, place="Гребнево")[0]
    assert e.place == "Гребнево"


def test_unknown_species_ignored():
    w = make_walk(finds=["", "не гриб"])
    entries = w2j.entries_from_walk(w)
    assert len(entries) == 1 and entries[0].score == 0


# --------------------------------------------------------------------------- #
#  Запись в файл
# --------------------------------------------------------------------------- #

def test_export_appends_readable_csv(tmp_path):
    w = make_walk(km=4.0, finds=["белый", "белый", "подосиновик"])
    path = str(tmp_path / "journal.csv")
    n = w2j.export(w, path=path)
    assert n == 2

    entries = journal.read(path)
    assert len(entries) == 2
    assert {e.key for e in entries} == {"белый", "подосиновик"}
    assert all(e.place == "Фрязино" for e in entries)


def test_export_twice_accumulates(tmp_path):
    path = str(tmp_path / "journal.csv")
    w2j.export(make_walk(finds=["белый"]), path=path)
    w2j.export(make_walk(finds=["лисичка"]), path=path)
    assert len(journal.read(path)) == 2


def test_summary_reads_naturally():
    w = make_walk(km=3.0, finds=["белый"] * 5)
    s = w2j.summary(w)
    assert "Белый" in s or "белый" in s
    assert w2j.summary(make_walk(km=5.0)).startswith("Пустой выход")


# --------------------------------------------------------------------------- #
#  Регрессия: пустой трек под пологом леса
# --------------------------------------------------------------------------- #

def test_weak_signal_still_records_track():
    """Симптом из поля: точка на карте есть, трека нет.

    Под пологом ельника приёмник рапортует точность 60-80 м, а строгий фильтр
    отбрасывал всё хуже 50 — маршрут оставался пустым весь поход.
    """
    w = track.Walk(place="ельник")
    t = time.time()
    lat, lon = 55.96, 38.04
    for i in range(20):
        lat += 15.0 / 111320.0
        w.add_point(lat, lon, 70.0, t + i * 15)

    assert len(w.points) >= 2, "трек снова пустой при слабом сигнале"
    assert w.rough > 0, "точки должны помечаться как грубые"
    assert w.distance > 100


def test_hopeless_signal_reports_state():
    """Точность 200 м — писать нечего, но человек должен знать почему."""
    w = track.Walk(place="тест")
    t = time.time()
    for i in range(10):
        w.add_point(55.96, 38.04, 200.0, t + i)
    assert not w.points
    assert "слабый" in w.signal_state()


def test_good_signal_says_nothing():
    w = track.Walk(place="тест")
    t = time.time()
    lat = 55.96
    for i in range(10):
        lat += 15.0 / 111320.0
        w.add_point(lat, 38.04, 8.0, t + i * 15)
    assert w.signal_state() == ""
