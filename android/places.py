#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
places.py — сохранённые места и офлайн-кэш прогнозов.

Место — это точка с именем, координатами и типом леса: «Дальний бор», сосняк,
55.9606, 38.0456. Прогноз для каждого места считается со своим профилем почвы,
а последний удачный расчёт кладётся в кэш, чтобы в лесу без связи приложение
показало хотя бы вчерашние цифры с честной пометкой о давности.

Файлы лежат в каталоге данных: ~/.mushroom-forecast (или заданном через
переменную MUSHROOM_DATA_DIR, а на Android — через set_data_dir()).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

import mushroom_forecast as engine

PLACES_FILE = "places.json"
CACHE_DIR = "cache"
CACHE_MAX_HOURS = 96

_DATA_DIR: str | None = None


def set_data_dir(path: str) -> str:
    """На Android вызывается с App.user_data_dir до первого обращения.

    Явно заданная переменная MUSHROOM_DATA_DIR имеет приоритет: так удобно
    прогонять тесты и держать данные в своём каталоге.
    """
    global _DATA_DIR
    _DATA_DIR = os.environ.get("MUSHROOM_DATA_DIR") or path
    os.makedirs(_DATA_DIR, exist_ok=True)
    return _DATA_DIR


def data_dir() -> str:
    """Каталог данных. Один и тот же в приложении и в фоновом сервисе.

    Фоновый сервис — отдельный процесс: set_data_dir() там никто не вызывает,
    а HOME в нём python-for-android не выставляет, поэтому expanduser("~")
    указывает не туда, куда пишет приложение. Раньше из-за этого сервис
    складывал трек в свой каталог, приложение читало пустоту и решало, что
    сервис не отозвался. ANDROID_PRIVATE выставляют оба процесса, и он
    совпадает с App.user_data_dir — по нему и равняемся.
    """
    global _DATA_DIR
    if _DATA_DIR is None:
        base = (os.environ.get("MUSHROOM_DATA_DIR")
                or os.environ.get("ANDROID_PRIVATE")
                or os.path.join(os.path.expanduser("~"), ".mushroom-forecast"))
        os.makedirs(base, exist_ok=True)
        _DATA_DIR = base
    return _DATA_DIR


# --------------------------------------------------------------------------- #
#  Места
# --------------------------------------------------------------------------- #

@dataclass
class Spot:
    name: str
    lat: float
    lon: float
    biotope: str = "смешанный"
    note: str = ""

    def as_place(self) -> engine.Place:
        return engine.Place(self.name, self.lat, self.lon)

    @property
    def coords(self) -> str:
        return f"{self.lat:.5f}, {self.lon:.5f}"

    def same_point(self, other: "Spot", tol: float = 3e-4) -> bool:
        return abs(self.lat - other.lat) < tol and abs(self.lon - other.lon) < tol


def _path(name: str) -> str:
    return os.path.join(data_dir(), name)


def load() -> list[Spot]:
    path = _path(PLACES_FILE)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for item in raw.get("spots", []):
        try:
            out.append(Spot(str(item["name"]), float(item["lat"]), float(item["lon"]),
                            str(item.get("biotope", "смешанный")),
                            str(item.get("note", ""))))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def save(spots: list[Spot]) -> str:
    path = _path(PLACES_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "saved": datetime.now().isoformat(timespec="seconds"),
                   "spots": [asdict(s) for s in spots]}, f,
                  ensure_ascii=False, indent=2)
    os.replace(tmp, path)                       # атомарная замена
    return path


def add(spot: Spot) -> list[Spot]:
    """Добавляет место; совпадающее имя или точка обновляются."""
    spots = load()
    for i, s in enumerate(spots):
        if s.name.lower() == spot.name.lower() or s.same_point(spot):
            spots[i] = spot
            break
    else:
        spots.append(spot)
    save(spots)
    return spots


def remove(name: str) -> list[Spot]:
    spots = [s for s in load() if s.name.lower() != name.lower()]
    save(spots)
    return spots


# --------------------------------------------------------------------------- #
#  Кэш прогнозов
# --------------------------------------------------------------------------- #

def _cache_path(spot: Spot) -> str:
    d = os.path.join(data_dir(), CACHE_DIR)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{spot.lat:.4f}_{spot.lon:.4f}.json")


def cache_forecast(spot: Spot, days: list[engine.Day]) -> str:
    path = _cache_path(spot)
    rows = [{"d": x.d.isoformat(), "tmax": x.tmax, "tmin": x.tmin, "tmean": x.tmean,
             "precip": x.precip, "et0": x.et0, "rh": x.rh,
             "soil_t": x.soil_t, "soil_w": x.soil_w} for x in days]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"stamp": datetime.now().isoformat(timespec="seconds"),
                   "name": spot.name, "lat": spot.lat, "lon": spot.lon,
                   "biotope": spot.biotope, "days": rows}, f, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def cached_forecast(spot: Spot, max_hours: int = CACHE_MAX_HOURS):
    """Возвращает (days, время расчёта) или None, если кэша нет или он стар."""
    path = _cache_path(spot)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        stamp = datetime.fromisoformat(raw["stamp"])
        if (datetime.now() - stamp).total_seconds() > max_hours * 3600:
            return None
        days = [engine.Day(date.fromisoformat(r["d"]), r["tmax"], r["tmin"], r["tmean"],
                           r["precip"], r["et0"], r.get("rh"),
                           r.get("soil_t"), r.get("soil_w")) for r in raw["days"]]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return (days, stamp) if days else None


def cache_age_text(stamp: datetime) -> str:
    mins = (datetime.now() - stamp).total_seconds() / 60
    if mins < 90:
        return f"{mins:.0f} мин назад"
    if mins < 60 * 36:
        return f"{mins / 60:.0f} ч назад"
    return f"{mins / 1440:.0f} сут назад"


# --------------------------------------------------------------------------- #
#  Сравнение мест
# --------------------------------------------------------------------------- #

@dataclass
class SpotForecast:
    spot: Spot
    days: list = field(default_factory=list)
    today: int = 0
    idx: dict = field(default_factory=dict)
    stale: datetime | None = None
    error: str = ""

    def best(self, i: int, names: list[str]):
        vals = [(self.idx[n][i], n) for n in names
                if n in self.idx and self.idx[n][i] == self.idx[n][i]]
        return max(vals) if vals else (0.0, "")


def forecast_spot(spot: Spot, fdays: int, allow_cache: bool = True) -> SpotForecast:
    """Считает прогноз для одного места; при отказе сети берёт кэш."""
    saved = engine.CURRENT_BIOTOPE.key
    stale = None
    try:
        engine.set_biotope(spot.biotope)
    except LookupError:
        engine.set_biotope("смешанный")
    try:
        days = engine.fetch_weather(spot.as_place(), fdays)
        cache_forecast(spot, days)
    except Exception as e:                                        # noqa: BLE001
        got = cached_forecast(spot) if allow_cache else None
        if got is None:
            engine.set_biotope(saved)
            return SpotForecast(spot, error=str(e))
        days, stale = got

    today = date.today()
    ti = next((i for i, d in enumerate(days) if d.d >= today), max(0, len(days) - fdays))
    m = engine.water_balance(days)
    ts = engine.soil_temperature(days)
    idx = {sp.name: engine.species_index(sp, days, m, ts)
           for sp in engine.SPECIES.values()}
    engine.set_biotope(saved)
    return SpotForecast(spot, days, ti, idx, stale)


def compare(spots: list[Spot], fdays: int = 7) -> list[SpotForecast]:
    return [forecast_spot(s, fdays) for s in spots]


def season_names() -> list[str]:
    month = date.today().month
    return [sp.name for sp in engine.SPECIES.values() if sp.months.get(month, 0) > 0] \
        or [sp.name for sp in engine.SPECIES.values()]


def recommend(forecasts: list[SpotForecast], names: list[str] | None = None) -> str:
    """Короткий ответ на вопрос «куда ехать»."""
    names = names or season_names()
    best = None
    for f in forecasts:
        if f.error or not f.days:
            continue
        for i in range(f.today, len(f.days)):
            v, who = f.best(i, names)
            if best is None or v > best[0]:
                best = (v, f, i, who)
    if best is None:
        return "Нет данных ни по одному месту."
    v, f, i, who = best
    when = "сегодня" if i == f.today else f.days[i].d.strftime("%d.%m")
    if v < 18:
        return "Ни в одном из мест выхода в ближайшие дни не ожидается."
    return (f"Лучший вариант: {f.spot.name}, {when} — {v:.0f} из 100 "
            f"({engine.level(v)}, {who.lower()}).")
