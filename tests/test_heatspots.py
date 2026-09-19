"""Spatial ranking of heatmap areas without network or Android dependencies."""
import math
import os
import sys

from apppath import APP
sys.path.insert(0, APP)
import heatspots
import heatgrid


def grid():
    g = heatgrid.Grid(biotope='смешанный', relief='ровно')
    g.cells = [
        heatgrid.Cell(55.0, 38.0, 1.0, index=80, species='Белый', auto_biotope='сосняк'),
        heatgrid.Cell(55.001, 38.001, 1.0, index=95, species='Белый'),
        heatgrid.Cell(55.04, 38.0, 1.0, index=70, species='Белый', auto_relief='север'),
        heatgrid.Cell(55.08, 38.0, 1.0, index=60, species='Белый'),
    ]
    return g


def test_top_areas_are_spatially_distinct_and_sorted():
    areas = heatspots.top_areas(grid(), 55, 38)
    assert [a.index for a in areas] == [95, 70, 60]
    assert areas[1].relief == 'север'
    assert areas[0].biotope == 'смешанный'


def test_invalid_and_failed_cells_are_not_ranked():
    g = grid()
    g.cells[1].error = 'network error'
    g.cells[2].index = float('nan')
    g.cells[3].index = None
    areas = heatspots.top_areas(g, 55, 38)
    assert len(areas) == 1 and areas[0].biotope == 'сосняк'


def test_empty_and_invalid_origin():
    assert heatspots.top_areas(grid(), float('nan'), 38) == []
    assert heatspots.top_areas(grid(), 55, 38, limit=0) == []
    assert heatspots.top_areas(heatgrid.Grid(), 55, 38) == []


def test_distance_wraps_antimeridian():
    assert 20 < heatspots.distance_km(0, 179.9, 0, -179.9) < 25
    assert heatspots.distance_km(55, 38, 55, 38) == 0


def test_limit_and_separation_override():
    assert len(heatspots.top_areas(grid(), 55, 38, limit=2)) == 2
    assert len(heatspots.top_areas(grid(), 55, 38, min_separation_km=100)) == 1
