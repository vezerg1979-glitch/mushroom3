# -*- coding: utf-8 -*-
"""Сетка индекса поверх карты: размер клетки, число клеток, счёт по клетке.

Разбираем отдельно от сети (heatfetch.py, если появится) и от Android:
здесь только арифметика и вызов уже проверенного расчёта индекса. Если
сетка когда-нибудь начнёт врать числом клеток или размером — просить
телефон об этом узнать дороже, чем поймать здесь.
"""

import math
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

sys.path.insert(0, APP)

import heatgrid  # noqa: E402
import mushroom_forecast as engine  # noqa: E402

# Фрязино и окрестности
LAT, LON = 55.96, 38.04


def _box(side_km, lat=LAT, lon=LON):
    """Квадратная область стороной side_km вокруг точки, в градусах."""
    dlat = side_km / (math.pi * heatgrid.EARTH_R_KM / 180.0)
    dlon = side_km / (math.pi * heatgrid.EARTH_R_KM / 180.0
                      * math.cos(math.radians(lat)))
    return lat - dlat / 2, lon - dlon / 2, lat + dlat / 2, lon + dlon / 2


# --------------------------------------------------------------------------- #
#  Планирование сетки
# --------------------------------------------------------------------------- #

def test_grid_covers_a_typical_view():
    g = heatgrid.plan(*_box(20))
    assert g.total > 1
    assert g.rows <= heatgrid.MAX_CELLS_SIDE
    assert g.cols <= heatgrid.MAX_CELLS_SIDE


def test_grid_count_never_exceeds_the_cap_however_wide_the_view():
    """Насколько бы человек ни отдалил карту, запросов не становится больше."""
    для_100_км = heatgrid.plan(*_box(100)).total
    для_2000_км = heatgrid.plan(*_box(2000)).total
    assert для_100_км <= heatgrid.MAX_CELLS_SIDE ** 2
    assert для_2000_км <= heatgrid.MAX_CELLS_SIDE ** 2


def test_cell_size_grows_with_the_visible_area():
    """Шире область — крупнее клетка, а не гуще сетка одного размера."""
    узкая = heatgrid.plan(*_box(10))
    широкая = heatgrid.plan(*_box(200))
    assert широкая.cells[0].half_km > узкая.cells[0].half_km


def test_cell_never_shrinks_below_the_weather_models_own_resolution():
    """Мельче шага погодной модели — не точнее, а просто дороже трафиком:
    соседние клетки вернут одно и то же число."""
    for side in (5, 10, 20, 40, 80):
        g = heatgrid.plan(*_box(side))
        assert g.cells[0].half_km * 2 >= heatgrid.MIN_CELL_KM - 1e-6, side


def test_tiny_area_collapses_to_one_cell():
    """Приблизил вплотную — сетка это не «36 клеток на дворе», а одна."""
    g = heatgrid.plan(*_box(0.5))
    assert g.total == 1


def test_zero_size_view_yields_an_empty_grid():
    """Вырожденный прямоугольник (например, экран ещё не отрисован) не
    должен уронить планировщик."""
    g = heatgrid.plan(55.0, 38.0, 55.0, 38.0)
    assert g.total == 0
    assert bool(g) is False


def test_plan_accepts_corners_in_any_order():
    """Углы приходят с экрана как есть — не гарантировано «юго-запад,
    северо-восток» по порядку."""
    a = heatgrid.plan(*_box(20))
    юг, зап, сев, вос = _box(20)
    b = heatgrid.plan(сев, вос, юг, зап)          # переставили углы местами
    assert a.total == b.total


def test_grid_is_roughly_centred_on_the_view():
    box = _box(30)
    g = heatgrid.plan(*box)
    юг, зап, сев, вос = box
    центр_лат = sum(c.lat for c in g.cells) / len(g.cells)
    центр_лон = sum(c.lon for c in g.cells) / len(g.cells)
    assert abs(центр_лат - (юг + сев) / 2) < 0.05
    assert abs(центр_лон - (зап + вос) / 2) < 0.05


def test_progress_counts_only_finished_cells():
    g = heatgrid.plan(*_box(20))
    assert g.done == 0
    g.cells[0].index = 42.0
    g.cells[1].error = "нет сети"
    assert g.done == 2
    assert g.total == len(g.cells)


# --------------------------------------------------------------------------- #
#  Счёт по клетке
# --------------------------------------------------------------------------- #

def _synthetic_days(n=45, rain_every=5, biotope_marker=False):
    today = date.today()
    return [engine.Day(today - timedelta(days=n - 1 - i), 18.0, 10.0, 14.0,
                       3.0 if i % rain_every == 0 else 0.2, 3.0, 80.0, 12.0, 0.6)
            for i in range(n)]


def test_fill_cell_produces_a_real_index():
    cell = heatgrid.Cell(lat=LAT, lon=LON, half_km=1.0)
    heatgrid.fill_cell(cell, _synthetic_days())
    assert cell.index is not None
    assert cell.index >= 0
    assert cell.species
    assert cell.error == ""


def test_fill_cell_without_data_leaves_the_cell_grey():
    """Пустые данные — ошибка, а не молчаливый ноль: ноль на карте читался
    бы как «здесь точно нет грибов», а не «не удалось узнать»."""
    cell = heatgrid.Cell(lat=LAT, lon=LON, half_km=1.0)
    heatgrid.fill_cell(cell, [])
    assert cell.index is None
    assert cell.error


def test_fill_cell_restores_the_global_biotope():
    """Счёт по клетке идёт со смешанным лесом, но не должен подменить
    биотоп, который человек выбрал для себя на главном экране."""
    engine.set_biotope("ельник")
    try:
        cell = heatgrid.Cell(lat=LAT, lon=LON, half_km=1.0)
        heatgrid.fill_cell(cell, _synthetic_days())
        assert engine.CURRENT_BIOTOPE.key == "ельник"
    finally:
        engine.set_biotope("смешанный")


def test_fill_cell_restores_biotope_even_after_an_error():
    engine.set_biotope("сосняк")
    try:
        cell = heatgrid.Cell(lat=LAT, lon=LON, half_km=1.0)
        heatgrid.fill_cell(cell, None)          # заведомо ломает расчёт
        assert engine.CURRENT_BIOTOPE.key == "сосняк"
    finally:
        engine.set_biotope("смешанный")


def test_fill_cell_uses_mixed_forest_regardless_of_current_choice():
    """Один и тот же ряд погоды должен давать один и тот же индекс клетки
    независимо от того, какой биотоп выбран на главном экране сейчас —
    иначе карта расскажет не про погоду, а про то, что забыли переключить."""
    days = _synthetic_days()
    engine.set_biotope("ельник")
    try:
        a = heatgrid.Cell(lat=LAT, lon=LON, half_km=1.0)
        heatgrid.fill_cell(a, days)
    finally:
        engine.set_biotope("смешанный")

    engine.set_biotope("сосняк")
    try:
        b = heatgrid.Cell(lat=LAT, lon=LON, half_km=1.0)
        heatgrid.fill_cell(b, days)
    finally:
        engine.set_biotope("смешанный")

    assert a.index == pytest.approx(b.index)
    assert a.species == b.species


def test_fill_cell_reports_a_broken_computation_without_raising():
    cell = heatgrid.Cell(lat=LAT, lon=LON, half_km=1.0)
    сломанные_дни = ["не похоже на Day"] * 10
    heatgrid.fill_cell(cell, сломанные_дни)      # не должно бросить исключение
    assert cell.index is None
    assert cell.error
