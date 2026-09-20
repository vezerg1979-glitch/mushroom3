# -*- coding: utf-8 -*-
"""Conservative ranking of distinct, successfully calculated heatmap areas.

A heatmap cell is a weather-model estimate, not a verified mushroom location.
This module never substitutes a missing cell with zero and never interprets
an index as a probability of finding mushrooms.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

EARTH_KM = 6371.0088


@dataclass(frozen=True)
class Hotspot:
    lat: float
    lon: float
    index: float
    species: str
    distance_km: float
    biotope: str
    relief: str
    cell_km: float


def distance_km(lat0: float, lon0: float, lat1: float, lon1: float) -> float:
    """Great-circle distance, with longitude wrapping at the antimeridian."""
    a, b = math.radians(lat0), math.radians(lat1)
    dlat = b - a
    dlon = math.radians((lon1 - lon0 + 180.0) % 360.0 - 180.0)
    h = math.sin(dlat / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(max(0.0, h))))


def top_areas(grid, origin_lat: float, origin_lon: float, limit: int = 3,
              min_separation_km: float | None = None) -> list[Hotspot]:
    """Return up to `limit` spatially separated candidate areas.

    Ranking uses the model index, with proximity as a deterministic tie-break.
    Neighbouring cells closer than a cell width represent one area rather
    than several independent recommendations. No GPS/route accessibility is
    inferred. The selected species is already accounted for by heatgrid.
    """
    if not (math.isfinite(origin_lat) and -90 <= origin_lat <= 90 and
            math.isfinite(origin_lon) and -180 <= origin_lon <= 180):
        return []
    if not isinstance(limit, int) or limit <= 0:
        return []
    candidates = []
    for cell in grid.cells:
        if cell.error or cell.index is None:
            continue
        if not all(math.isfinite(v) for v in (cell.lat, cell.lon, cell.index, cell.half_km)):
            continue
        if not (-90 <= cell.lat <= 90 and -180 <= cell.lon <= 180 and
                0 <= cell.index <= 100 and cell.half_km > 0):
            continue
        candidates.append(Hotspot(
            cell.lat, cell.lon, float(cell.index), cell.species,
            distance_km(origin_lat, origin_lon, cell.lat, cell.lon),
            cell.auto_biotope or grid.biotope,
            cell.auto_relief or grid.relief, cell.half_km * 2,
        ))
    candidates.sort(key=lambda c: (-c.index, c.distance_km, c.lat, c.lon))
    result = []
    for item in candidates:
        if all(distance_km(item.lat, item.lon, prev.lat, prev.lon) >=
               (min_separation_km if min_separation_km is not None else
                max(item.cell_km, prev.cell_km)) for prev in result):
            result.append(item)
            if len(result) >= limit:
                break
    return result
