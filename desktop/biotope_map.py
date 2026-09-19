# -*- coding: utf-8 -*-
"""biotope_map.py — осторожное определение биотопа по OpenStreetMap.

Модуль намеренно распознаёт только то, что источник сказал достаточно
явно. Обычный ``wood/forest`` не превращается в придуманную породу дерева:
для него остаётся ручной профиль пользователя. Автоматически принимаются
явные genus/species (Pinus/Picea/Betula), mixed forest, bog/swamp и
clearcut. Один bbox-запрос покрывает всю heatmap; при любой сетевой ошибке
прогноз продолжает работать с ручным биотопом.
"""
from __future__ import annotations

import math

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MAX_MATCH_KM = 4.0


def classify_tags(tags: dict | None) -> str | None:
    """Возвращает ключ BIOTOPES только для достаточно однозначных тегов."""
    t = {str(k).lower(): str(v).lower() for k, v in (tags or {}).items()}
    blob = " ".join(t.get(k, "") for k in
                    ("species", "species:en", "genus", "genus:en", "taxon", "name"))
    if any(x in blob for x in ("betula", "берез", "birch")):
        return "березняк"
    if any(x in blob for x in ("picea", "ель", "spruce")):
        return "ельник"
    if any(x in blob for x in ("pinus", "сосн", "pine")):
        return "сосняк"

    wet = t.get("wetland", "")
    if wet in {"bog", "raised_bog"}:
        return "болото"
    if wet in {"swamp", "wet_meadow", "marsh"}:
        return "низина"

    forest_type = " ".join((t.get("forest:type", ""), t.get("landuse", ""),
                            t.get("natural", ""), t.get("leaf_type", "")))
    if any(x in forest_type for x in ("clearcut", "clear_cut", "logging")):
        return "вырубка"
    if t.get("leaf_type") == "mixed":
        return "смешанный"
    return None


def _center(el: dict):
    c = el.get("center") or {}
    lat, lon = c.get("lat"), c.get("lon")
    if lat is None or lon is None:
        lat, lon = el.get("lat"), el.get("lon")
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def features_from_overpass(data: dict | None) -> list[tuple[float, float, str]]:
    out = []
    for el in (data or {}).get("elements", []):
        key = classify_tags(el.get("tags"))
        center = _center(el)
        if key and center:
            out.append((center[0], center[1], key))
    return out


def _distance_km(lat1, lon1, lat2, lon2):
    # Для нескольких километров equirectangular точнее, чем нужно heatmap.
    y = math.radians(lat2 - lat1)
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return 6371.0088 * math.hypot(x, y)


def assign(cells: list, features: list, max_km: float = MAX_MATCH_KM) -> int:
    """Назначает ближайший уверенно распознанный объект; возвращает число клеток."""
    done = 0
    for cell in cells:
        best = None
        for lat, lon, key in features:
            d = _distance_km(cell.lat, cell.lon, lat, lon)
            if d <= max_km and (best is None or d < best[0]):
                best = (d, key)
        if best:
            cell.auto_biotope = best[1]
            done += 1
    return done


def overpass_query(cells: list) -> str:
    south = min(c.lat for c in cells); north = max(c.lat for c in cells)
    west = min(c.lon for c in cells); east = max(c.lon for c in cells)
    # Небольшой запас, чтобы центры крупных лесных полигонов у края не потерялись.
    pad = 0.03
    bbox = f"{south-pad:.5f},{west-pad:.5f},{north+pad:.5f},{east+pad:.5f}"
    return ("[out:json][timeout:12];("
            f"nwr[natural=wood]({bbox});"
            f"nwr[landuse=forest]({bbox});"
            f"nwr[natural=wetland]({bbox});"
            f"nwr[wetland]({bbox});"
            ");out center tags;")
