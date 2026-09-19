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


def test_grid_keeps_requested_biotope():
    g = heatgrid.plan(*_box(20), biotope="сосняк")
    assert g.biotope == "сосняк"


def test_unknown_grid_biotope_falls_back_to_mixed():
    g = heatgrid.plan(*_box(20), biotope="марсианский лес")
    assert g.biotope == "смешанный"


def test_fill_cell_can_use_selected_biotope_and_restores_global():
    days = _synthetic_days()
    engine.set_biotope("ельник")
    try:
        pine = heatgrid.Cell(lat=LAT, lon=LON, half_km=1.0)
        mixed = heatgrid.Cell(lat=LAT, lon=LON, half_km=1.0)
        heatgrid.fill_cell(pine, days, "сосняк")
        heatgrid.fill_cell(mixed, days, "смешанный")
        assert engine.CURRENT_BIOTOPE.key == "ельник"
        # Не требуем, какой профиль обязан быть лучше: важно, что профиль
        # реально участвует в расчёте и может изменить результат/лидера.
        assert (pine.index, pine.species) != (mixed.index, mixed.species)
    finally:
        engine.set_biotope("смешанный")

def test_grid_keeps_requested_relief():
    g = heatgrid.plan(*_box(20), biotope="сосняк", relief="север")
    assert g.relief == "север"


def test_unknown_grid_relief_falls_back_to_flat():
    g = heatgrid.plan(*_box(20), relief="кратер")
    assert g.relief == "ровно"


def test_relief_changes_cell_and_is_restored():
    days = _synthetic_days()
    engine.set_biotope("смешанный")
    engine.set_relief("возвышенность")
    try:
        north = heatgrid.Cell(lat=LAT, lon=LON, half_km=1.0)
        south = heatgrid.Cell(lat=LAT, lon=LON, half_km=1.0)
        heatgrid.fill_cell(north, days, "смешанный", "север")
        heatgrid.fill_cell(south, days, "смешанный", "юг")
        assert engine.CURRENT_RELIEF.key == "возвышенность"
        assert (north.index, north.species) != (south.index, south.species)
    finally:
        engine.set_relief("ровно")


def _terrain_grid(vals, rows=3, cols=3):
    cells=[]
    for i,z in enumerate(vals):
        cells.append(heatgrid.Cell(lat=55+i//cols*.01, lon=37+i%cols*.01,
                                   half_km=0.5, elevation=z))
    return heatgrid.Grid(cells=cells, rows=rows, cols=cols, relief="ровно")


def test_auto_terrain_detects_local_depression_and_ridge():
    g=_terrain_grid([100,100,100,100,90,100,100,100,100])
    heatgrid.infer_relief(g)
    assert g.cells[4].auto_relief == "низина"
    g=_terrain_grid([100,100,100,100,110,100,100,100,100])
    heatgrid.infer_relief(g)
    assert g.cells[4].auto_relief == "возвышенность"


def test_auto_terrain_detects_north_and_south_aspect():
    # rows grow northward. Higher north => downhill/facing south.
    g=_terrain_grid([90,90,90,100,100,100,110,110,110])
    heatgrid.infer_relief(g)
    assert g.cells[4].auto_relief == "юг"
    g=_terrain_grid([110,110,110,100,100,100,90,90,90])
    heatgrid.infer_relief(g)
    assert g.cells[4].auto_relief == "север"


def test_auto_terrain_falls_back_when_elevation_missing():
    g=_terrain_grid([None]*9)
    heatgrid.infer_relief(g)
    assert not g.terrain_auto
    assert all(not c.auto_relief for c in g.cells)

# --------------------------------------------------------------------------- #
#  Автоматический биотоп по картографическим тегам (v3.28)
# --------------------------------------------------------------------------- #
import biotope_map


def test_biotope_classifier_only_accepts_confident_tags():
    assert biotope_map.classify_tags({"genus": "Betula"}) == "березняк"
    assert biotope_map.classify_tags({"species": "Picea abies"}) == "ельник"
    assert biotope_map.classify_tags({"species:en": "Scots pine"}) == "сосняк"
    assert biotope_map.classify_tags({"natural": "wetland", "wetland": "bog"}) == "болото"
    assert biotope_map.classify_tags({"landuse": "forest", "leaf_type": "mixed"}) == "смешанный"
    # Просто forest/wood недостаточно, чтобы выдумывать породу дерева.
    assert biotope_map.classify_tags({"landuse": "forest"}) is None
    assert biotope_map.classify_tags({"natural": "wood", "leaf_type": "needleleaved"}) is None


def test_biotope_assign_uses_nearest_confident_feature_and_keeps_fallback():
    cells = [heatgrid.Cell(lat=55.000, lon=37.000, half_km=1),
             heatgrid.Cell(lat=55.100, lon=37.100, half_km=1)]
    features = [(55.001, 37.001, "березняк")]
    n = biotope_map.assign(cells, features, max_km=3.0)
    assert n == 1
    assert cells[0].auto_biotope == "березняк"
    assert cells[1].auto_biotope == ""


def test_finalize_uses_auto_biotope_but_does_not_change_manual_grid_profile(monkeypatch):
    g = heatgrid.Grid(cells=[heatgrid.Cell(lat=LAT, lon=LON, half_km=1,
                                           auto_biotope="сосняк",
                                           _days=_synthetic_days())],
                      rows=1, cols=1, biotope="ельник")
    seen = {}
    original = heatgrid.fill_cell
    def spy(cell, days, biotope="смешанный", relief="ровно"):
        seen["biotope"] = biotope
        return original(cell, days, biotope, relief)
    monkeypatch.setattr(heatgrid, "fill_cell", spy)
    heatgrid.finalize_cells(g)
    assert seen["biotope"] == "сосняк"
    assert g.biotope == "ельник"

# --------------------------------------------------------------------------- #
#  Карта конкретного вида (v3.29)
# --------------------------------------------------------------------------- #
def test_plan_keeps_valid_target_species_and_rejects_unknown():
    g = heatgrid.plan(55.0, 37.0, 55.1, 37.1, target_species="белый")
    assert g.target_species == "белый"
    g2 = heatgrid.plan(55.0, 37.0, 55.1, 37.1, target_species="несуществующий")
    assert g2.target_species == ""


def test_fill_cell_specific_species_is_not_best_species():
    days = _synthetic_days()
    c = heatgrid.Cell(lat=LAT, lon=LON, half_km=1)
    heatgrid.fill_cell(c, days, target_species="лисичка")
    assert c.species == engine.SPECIES["лисичка"].name
    assert c.index is not None


def test_finalize_passes_target_species(monkeypatch):
    g = heatgrid.Grid(cells=[heatgrid.Cell(lat=LAT, lon=LON, half_km=1,
                                           _days=_synthetic_days())],
                      rows=1, cols=1, target_species="белый")
    seen = {}
    original = heatgrid.fill_cell
    def spy(cell, days, biotope="смешанный", relief="ровно", target_species=""):
        seen["target_species"] = target_species
        return original(cell, days, biotope, relief, target_species)
    monkeypatch.setattr(heatgrid, "fill_cell", spy)
    heatgrid.finalize_cells(g)
    assert seen["target_species"] == "белый"
    assert g.cells[0].species == engine.SPECIES["белый"].name
