# -*- coding: utf-8 -*-
"""
heatgrid.py — сетка индекса поверх видимого куска карты.

Отвечает на другой вопрос, чем места. Экран «Мои места» сравнивает
несколько точек, которые человек уже выбрал. Здесь наоборот: человек ещё
не выбрал ничего, он смотрит на карту и хочет увидеть — по погоде, не по
типу леса, — где вообще стоит искать. Тип леса намеренно не спрашивается:
считается смешанный лес везде. Кто где стоит и что там растёт, человек
знает сам — вопрос только в том, где было теплее и мокрее.

Сетка подстраивается под то, что видно, а не имеет фиксированный шаг в
километрах. Причина: у самой погодной модели есть собственное разрешение
(порядка нескольких километров), и спрашивать её чаще этого шага — не
точнее, а просто медленнее и втрое дороже по трафику ради одинаковых чисел
в соседних клетках. Поэтому размер клетки растёт вместе с отдалением карты
и не опускается ниже MIN_CELL_KM, а число клеток при этом не растёт
безгранично — стоимость одного расчёта всегда ограничена сверху
MAX_CELLS_SIDE² запросов, чем бы человек ни отдалил карту.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import mushroom_forecast as engine

#: Меньше этого шага между клетками смысла нет: соседние клетки погодной
#: модели всё равно вернут почти одно и то же число, а трафика уйдёт втрое.
MIN_CELL_KM = 2.0

#: Сторона сетки в клетках. И на пять километров вширь, и на полсотни —
#: клеток всегда не больше этого числа, дальше расширяется сама клетка.
MAX_CELLS_SIDE = 6

#: Один и тот же биотоп для всей сетки — намеренно, см. докстрок модуля.
GRID_BIOTOPE = "смешанный"

EARTH_R_KM = 6371.0088


@dataclass
class Cell:
    """Одна точка сетки: где она и что в ней посчиталось.

    index — None, пока не посчитано или если запрос не удался; клетка с
    None остаётся серой на карте, а не пропадает и не выдаёт себя за ноль.
    """

    lat: float
    lon: float
    half_km: float                  # половина стороны клетки — для отрисовки
    index: float | None = None
    species: str = ""                # чей индекс лучший в этой клетке
    error: str = ""


@dataclass
class Grid:
    cells: list = field(default_factory=list)
    cols: int = 0
    rows: int = 0

    def __bool__(self):
        return bool(self.cells)

    @property
    def done(self) -> int:
        return sum(1 for c in self.cells if c.index is not None or c.error)

    @property
    def total(self) -> int:
        return len(self.cells)


def _km_per_deg_lat() -> float:
    return math.pi * EARTH_R_KM / 180.0


def _km_per_deg_lon(lat: float) -> float:
    return _km_per_deg_lat() * math.cos(math.radians(lat))


def plan(lat0: float, lon0: float, lat1: float, lon1: float,
        max_side: int = MAX_CELLS_SIDE, min_km: float = MIN_CELL_KM) -> Grid:
    """Сетка для видимой области (lat0,lon0)–(lat1,lon1), любые углы.

    Число клеток по стороне снижается само, если область меньше, чем
    max_side клеток по min_km давали бы: мельчить дальше — только врать
    точностью, которой у погодной модели нет.
    """
    south, north = min(lat0, lat1), max(lat0, lat1)
    west, east = min(lon0, lon1), max(lon0, lon1)
    lat_c = (south + north) / 2.0

    height_km = (north - south) * _km_per_deg_lat()
    width_km = (east - west) * _km_per_deg_lon(lat_c)
    if height_km <= 0 or width_km <= 0:
        return Grid()

    side_km = max(height_km, width_km)
    # floor, а не ceil: ceil(5/2)=3 даёт клетку 1.67 км — мельче MIN_CELL_KM,
    # хотя вся сетка задумана не мельчить её никогда. floor(5/2)=2 даёт
    # клетку 2.5 км — уже не меньше порога.
    cols_by_size = max(1, math.floor(side_km / min_km))
    n = max(1, min(max_side, cols_by_size))

    cell_km = side_km / n
    dlat = cell_km / _km_per_deg_lat()
    per_lon = _km_per_deg_lon(lat_c)
    dlon = cell_km / per_lon if per_lon else 0.0
    half_km = cell_km / 2.0

    # Сетка квадратная по шагу клетки и центрирована на видимой области —
    # не «от угла», иначе прямоугольный экран (шире, чем выше) съезжал бы
    # клетками за одну сторону и пустовал за другой.
    lat_mid, lon_mid = (south + north) / 2.0, (west + east) / 2.0
    rows = min(max_side, max(1, round((north - south) / dlat))) if dlat else 1
    cols = min(max_side, max(1, round((east - west) / dlon))) if dlon else 1

    cells = []
    for i in range(rows):
        for j in range(cols):
            lat = lat_mid + (i - (rows - 1) / 2.0) * dlat
            lon = lon_mid + (j - (cols - 1) / 2.0) * dlon
            cells.append(Cell(lat=lat, lon=lon, half_km=half_km))
    return Grid(cells=cells, cols=cols, rows=rows)


def fill_cell(cell: Cell, days: list) -> Cell:
    """Считает индекс клетки по уже полученной погоде.

    Без сети внутри: откуда взялись days — забота heatfetch.py. Здесь
    только счёт, поэтому и проверяется без сети и без Android, как и весь
    остальной расчёт индекса.
    """
    if not days:
        cell.error = "нет данных"
        return cell
    saved = engine.CURRENT_BIOTOPE.key
    try:
        engine.set_biotope(GRID_BIOTOPE)
        m = engine.water_balance(days)
        ts = engine.soil_temperature(days)
        # Индекс на сегодня, а не на первый день ряда: days начинается с
        # PAST_DAYS назад, нужна погода фактическая до сегодня включительно.
        i_today = next((i for i, d in enumerate(days) if d.d >= date.today()),
                       len(days) - 1)
        best_v, best_name = 0.0, ""
        for sp in engine.SPECIES.values():
            idx = engine.species_index(sp, days, m, ts)
            v = idx[i_today] if i_today < len(idx) else 0.0
            if v == v and v > best_v:                       # v == v: не NaN
                best_v, best_name = v, sp.name
        cell.index, cell.species = best_v, best_name
    except Exception as e:                                    # noqa: BLE001
        cell.error = f"{type(e).__name__}: {e}"[:120]
    finally:
        engine.set_biotope(saved)
    return cell
