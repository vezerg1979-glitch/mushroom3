#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mushroom_forecast.py — прогноз роста грибов по погоде.

Модель:
  1) Водный баланс лесной подстилки (резервуар, осадки - эвапотранспирация).
  2) Температура почвы (сглаженная температура воздуха, лаг ~2-3 суток).
  3) Суточная "скорость развития мицелия" g = f(влага) * f(T почвы).
  4) Свёртка g с лаговым ядром вида (примордии -> плодовое тело за 3-16 сут).
  5) Поправки: сезон, заморозки, суховей, для опят — осеннее похолодание.

Данные: Open-Meteo (https://open-meteo.com), лицензия CC-BY, без API-ключа.

Примеры:
    python mushroom_forecast.py
    python mushroom_forecast.py --place "Фрязино" --days 10
    python mushroom_forecast.py --lat 56.02 --lon 38.28 --species белый опёнок
    python mushroom_forecast.py --demo          # без интернета, синтетическая погода
    python mushroom_forecast.py --json > out.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

VERSION = "2.9"

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

PAST_DAYS = 31          # глубина истории (нужна для лагов и накопления влаги)
CAPACITY_MM = 55.0      # влагоёмкость подстилки + верхнего слоя почвы, мм
CANOPY = 0.55           # доля ET0 под пологом леса
INTERCEPT = 0.85        # доля осадков, доходящая до подстилки
BASE = 0.30             # фоновая закладка примордиев при сырой подстилке
GAIN = 1.25             # калибровка шкалы индекса (0..100)


# --------------------------------------------------------------------------- #
#  Виды
# --------------------------------------------------------------------------- #

@dataclass
class Species:
    key: str = field(default="", init=False, repr=False)
    name: str
    latin: str
    t_opt: float            # оптимум температуры почвы, °C
    t_sigma: float          # ширина температурного окна
    m_min: float            # влагозапас, ниже которого рост не идёт (доля ёмкости)
    m_opt: float            # влагозапас насыщения
    lag_min: int            # мин. лаг «стимул -> плодовое тело», сут
    lag_max: int            # макс. лаг, сут
    months: dict            # сезонный вес по месяцам
    cold_snap: bool = False # нужен триггер осеннего похолодания
    spring: bool = False    # плодоношение привязано к сходу снега
    gdd_opt: float = 150.0  # накопленное тепло от схода снега до слоя, °C·сут
    gdd_sigma: float = 70.0 # ширина окна по накопленному теплу
    base_share: float = 0.0 # своя доля фоновой закладки; 0 — общая BASE
    note: str = ""


SPECIES: dict[str, Species] = {
    "белый": Species(
        "Белый гриб", "Boletus edulis", 16.0, 5.0, 0.30, 0.60, 6, 12,
        {6: 0.55, 7: 0.85, 8: 1.00, 9: 1.00, 10: 0.45},
        note="Слои: колосовик (июнь), жнивник (июль), листопадник (авг-сен)."),
    "подберёзовик": Species(
        "Подберёзовик", "Leccinum scabrum", 15.0, 6.0, 0.28, 0.58, 4, 9,
        {5: 0.3, 6: 0.75, 7: 0.90, 8: 1.00, 9: 0.90, 10: 0.40},
        note="Первым отзывается на дождь, растёт быстро — быстро и стареет."),
    "подосиновик": Species(
        "Подосиновик", "Leccinum aurantiacum", 14.5, 5.5, 0.30, 0.60, 5, 10,
        {6: 0.6, 7: 0.85, 8: 1.00, 9: 1.00, 10: 0.50}),
    "лисичка": Species(
        "Лисичка", "Cantharellus cibarius", 17.0, 6.5, 0.22, 0.50, 3, 8,
        {6: 0.80, 7: 1.00, 8: 1.00, 9: 0.85, 10: 0.35},
        note="Засухоустойчива: пережидает сушь и оживает после первого дождя."),
    "маслёнок": Species(
        "Маслёнок", "Suillus luteus", 14.0, 6.0, 0.26, 0.55, 3, 7,
        {6: 0.65, 7: 0.80, 8: 0.90, 9: 1.00, 10: 0.70},
        note="Молодые сосняки, реагирует раньше других — 4-6 дней после дождя."),
    "опёнок": Species(
        "Опёнок осенний", "Armillaria mellea", 11.0, 4.0, 0.30, 0.55, 8, 16,
        {8: 0.45, 9: 1.00, 10: 0.85, 11: 0.30}, cold_snap=True,
        note="Волна запускается похолоданием: ночи ниже +10 °C после тёплого периода."),
    "груздь": Species(
        "Груздь настоящий", "Lactarius resimus", 12.5, 4.5, 0.35, 0.68, 6, 12,
        {7: 0.65, 8: 1.00, 9: 1.00, 10: 0.35},
        note="Самый влаголюбивый — нужен устойчиво сырой верхний слой."),
    "сыроежка": Species(
        "Сыроежка", "Russula spp.", 16.0, 7.0, 0.24, 0.52, 3, 7,
        {6: 0.85, 7: 0.95, 8: 1.00, 9: 0.90, 10: 0.45}),
    "вешенка": Species(
        "Вешенка", "Pleurotus ostreatus", 9.0, 5.0, 0.18, 0.45, 5, 12,
        {4: 0.55, 5: 0.35, 9: 0.70, 10: 1.00, 11: 0.80},
        note="Дереворазрушающий: меньше зависит от почвы, любит холод и сырость."),
    "сморчок": Species(
        "Сморчок", "Morchella spp.", 10.0, 4.5, 0.30, 0.62, 5, 12,
        {4: 0.85, 5: 1.00, 6: 0.25}, spring=True, gdd_opt=155.0, gdd_sigma=70.0,
        base_share=0.70,
        note="Слой привязан к сходу снега: примерно через две-три недели после "
             "того, как почва оттаяла и набрала тепло. Любит гари и старые сады."),
    "строчок": Species(
        "Строчок обыкновенный", "Gyromitra esculenta", 8.0, 4.0, 0.28, 0.60, 4, 10,
        {4: 1.00, 5: 0.80, 6: 0.15}, spring=True, gdd_opt=85.0, gdd_sigma=55.0,
        base_share=0.70,
        note="Идёт раньше сморчка, у самой кромки сошедшего снега. Требует "
             "обязательного отваривания: содержит гиромитрин."),
}


for _k, _sp in SPECIES.items():
    _sp.key = _k


# --------------------------------------------------------------------------- #
#  Погода
# --------------------------------------------------------------------------- #

@dataclass
class Day:
    d: date
    tmax: float
    tmin: float
    tmean: float
    precip: float
    et0: float
    rh: float | None = None
    soil_t: float | None = None      # температура почвы 0-7 см, °C (из модели)
    soil_w: float | None = None      # объёмная влажность почвы, м³/м³
    snow: float | None = None        # высота снежного покрова, м


@dataclass
class Place:
    name: str
    lat: float
    lon: float


# Наборы почвенных переменных: разные погодные модели отдают разные слои,
# поэтому кандидаты перебираются до первого успешного ответа.
SOIL_CANDIDATES = [
    ("soil_temperature_0_to_7cm", "soil_moisture_0_to_7cm"),
    ("soil_temperature_6cm", "soil_moisture_1_to_3cm"),
    ("soil_temperature_0_to_10cm", "soil_moisture_0_to_10cm"),
    ("soil_temperature_0cm", "soil_moisture_0_to_1cm"),
]

# Границы доступной растениям влаги для суглинка: влажность завядания и
# полевая влагоёмкость. Нужны, чтобы перевести м³/м³ в долю 0..1.
THETA_WILT, THETA_FC = 0.10, 0.36

SNOW_KEY = "snow_depth"          # высота снега, м (почасовая переменная)
SNOW_GONE = 0.02                 # ниже этого считаем, что снег сошёл
GDD_BASE = 5.0                   # база для накопления тепла после схода снега


def _get_json(url: str, params: dict) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "mushroom-forecast/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e",
    "ю": "yu", "я": "ya",
}


def translit(name: str) -> str:
    """Кириллица -> латиница: база геокодера (GeoNames) часто знает только её."""
    out = []
    for ch in name:
        low = ch.lower()
        rep = _TRANSLIT.get(low, ch)
        out.append(rep.capitalize() if ch.isupper() and rep else rep)
    return "".join(out)


def geocode(name: str) -> Place:
    """Поиск точки по названию. Пробует кириллицу, латиницу и без типа пункта."""
    name = name.strip()
    bare = name
    for prefix in ("село ", "деревня ", "посёлок ", "поселок ", "г. ", "с. ", "д. ", "пос. "):
        if bare.lower().startswith(prefix):
            bare = bare[len(prefix):].strip()
    variants, seen = [], set()
    for q in (name, bare, translit(bare)):
        if q and q.lower() not in seen:
            seen.add(q.lower())
            variants.append(q)

    for q in variants:
        try:
            data = _get_json(GEO_URL, {"name": q, "count": 1, "language": "ru",
                                       "format": "json"})
        except (urllib.error.HTTPError, urllib.error.URLError):
            if q is variants[-1]:
                raise
            continue
        res = data.get("results") or []
        if res:
            r = res[0]
            label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x)
            return Place(label, float(r["latitude"]), float(r["longitude"]))

    raise LookupError(f"Не найден населённый пункт: {name}. Пробовал варианты: "
                      f"{', '.join(variants)}. Укажите координаты в виде «55.9606, 38.0456» "
                      f"или название ближайшего города — погодная сетка всё равно "
                      f"крупнее нескольких километров.")


def apply_calibration(data: dict) -> None:
    """Применяет подобранные коэффициенты к глобальным константам и видам."""
    global GAIN, BASE, CAPACITY_MM, CANOPY, THETA_WILT, THETA_FC
    g = data.get("global", {})
    GAIN = float(g.get("GAIN", GAIN))
    BASE = float(g.get("BASE", BASE))
    CAPACITY_MM = float(g.get("CAPACITY_MM", CAPACITY_MM))
    CANOPY = float(g.get("CANOPY", CANOPY))
    THETA_WILT = float(g.get("THETA_WILT", THETA_WILT))
    THETA_FC = float(g.get("THETA_FC", THETA_FC))
    for key, over in (data.get("species") or {}).items():
        sp = SPECIES.get(key)
        if sp is None:
            continue
        for field, value in over.items():
            if hasattr(sp, field) and field != "months":
                setattr(sp, field, type(getattr(sp, field))(value))
    global CALIBRATION
    CALIBRATION = data


CALIBRATION: dict | None = None


def load_calibration(path: str | None = None) -> bool:
    """Подхватывает calibration.json рядом с модулем, если он есть."""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "calibration.json")
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            apply_calibration(json.load(f))
        return True
    except (OSError, ValueError):
        return False


def calibration_info() -> str:
    """Строка для интерфейса: откалибрована модель или работает на константах."""
    if not CALIBRATION:
        return "константы по умолчанию (литературные)"
    meta = CALIBRATION.get("meta", {})
    return (f"калибровка от {meta.get('date', '?')} по {meta.get('records', '?')} "
            f"наблюдениям, RMSE {meta.get('rmse_test', '?')}")


@dataclass
class Biotope:
    """Тип леса: почвенные константы, затенение и пригодность для видов."""
    key: str
    name: str
    theta_wilt: float           # влажность завядания, м³/м³
    theta_fc: float             # полевая влагоёмкость, м³/м³
    capacity: float             # влагоёмкость подстилки, мм (резервный расчёт)
    canopy: float               # доля испарения под пологом
    t_offset: float             # поправка к температуре почвы, °C
    weight: dict                # множители пригодности по видам
    note: str = ""


BIOTOPES: dict[str, Biotope] = {
    "смешанный": Biotope(
        "смешанный", "Смешанный лес", 0.10, 0.36, 55.0, 0.55, 0.0, {},
        note="Профиль по умолчанию: суглинок, умеренное затенение."),
    "сосняк": Biotope(
        "сосняк", "Сосняк на песке", 0.05, 0.21, 35.0, 0.50, 0.8,
        {"маслёнок": 1.30, "лисичка": 1.15, "белый": 1.00, "сыроежка": 1.00,
         "подберёзовик": 0.55, "подосиновик": 0.45, "груздь": 0.40,
         "опёнок": 0.65, "вешенка": 0.30, "сморчок": 0.60},
        note="Песок держит втрое меньше воды и быстро сохнет: слой короткий, "
             "начинается раньше и раньше кончается."),
    "березняк": Biotope(
        "березняк", "Березняк, суглинок", 0.11, 0.37, 58.0, 0.58, 0.0,
        {"подберёзовик": 1.30, "белый": 1.00, "подосиновик": 1.00, "груздь": 1.15,
         "сыроежка": 1.05, "лисичка": 0.90, "маслёнок": 0.30, "опёнок": 1.00,
         "вешенка": 1.00, "сморчок": 1.10},
        note="Самый отзывчивый на дождь тип: подберёзовик выскакивает первым."),
    "ельник": Biotope(
        "ельник", "Ельник", 0.13, 0.41, 68.0, 0.72, -1.5,
        {"белый": 1.05, "груздь": 1.10, "лисичка": 0.85, "опёнок": 1.10,
         "маслёнок": 0.35, "подберёзовик": 0.50, "подосиновик": 0.70,
         "сыроежка": 0.95, "вешенка": 0.90, "сморчок": 0.70},
        note="Густой полог: сохнет медленно, почва холоднее — слой сдвинут позже."),
    "низина": Biotope(
        "низина", "Низина, пойма, сырой лес", 0.14, 0.44, 78.0, 0.62, -1.0,
        {"груздь": 1.25, "опёнок": 1.20, "вешенка": 1.20, "подосиновик": 1.05,
         "белый": 0.75, "лисичка": 0.70, "маслёнок": 0.35, "подберёзовик": 0.85,
         "сыроежка": 0.90, "сморчок": 1.15},
        note="Влага держится долго, зато в сушь тут единственное место с грибами; "
             "в мокрый год, наоборот, заливает."),
}

CURRENT_BIOTOPE: Biotope = BIOTOPES["смешанный"]


def set_biotope(key: str) -> Biotope:
    """Переключает почвенные константы под выбранный тип леса."""
    global CURRENT_BIOTOPE, THETA_WILT, THETA_FC, CAPACITY_MM, CANOPY
    b = BIOTOPES.get((key or "").strip().lower())
    if b is None:
        raise LookupError(f"Неизвестный тип леса: {key}. "
                          f"Доступно: {', '.join(BIOTOPES)}")
    CURRENT_BIOTOPE = b
    THETA_WILT, THETA_FC = b.theta_wilt, b.theta_fc
    CAPACITY_MM, CANOPY = b.capacity, b.canopy
    return b


def biotope_weight(sp: Species) -> float:
    return float(CURRENT_BIOTOPE.weight.get(getattr(sp, "key", ""), 1.0))


def _daily_mean(times: list[str], values: list) -> dict[date, float]:
    """Почасовой ряд -> суточные средние."""
    acc: dict[date, list[float]] = {}
    for t, v in zip(times, values or []):
        if v is None:
            continue
        acc.setdefault(date.fromisoformat(t[:10]), []).append(float(v))
    return {d: sum(vs) / len(vs) for d, vs in acc.items() if vs}


def fetch_weather(place: Place, forecast_days: int) -> list[Day]:
    daily = ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
             "precipitation_sum", "et0_fao_evapotranspiration", "relative_humidity_2m_mean"]
    base = {
        "latitude": place.lat, "longitude": place.lon,
        "timezone": "auto",
        "past_days": PAST_DAYS, "forecast_days": max(3, min(16, forecast_days)),
    }

    data, soil_keys, has_snow = None, None, False
    for t_key, w_key in SOIL_CANDIDATES:
        for extra in (f",{SNOW_KEY}", ""):
            params = dict(base, daily=",".join(daily),
                          hourly=f"{t_key},{w_key}{extra}")
            try:
                data = _get_json(FORECAST_URL, params)
                soil_keys, has_snow = (t_key, w_key), bool(extra)
                break
            except urllib.error.HTTPError:
                continue
        if data is not None:
            break
    if data is None:
        # ни один набор слоёв не поддержан — работаем на суточных данных
        try:
            data = _get_json(FORECAST_URL, dict(base, daily=",".join(daily)))
        except urllib.error.HTTPError:
            data = _get_json(FORECAST_URL, dict(base, daily=",".join(daily[:-1])))

    soil_t_map: dict[date, float] = {}
    soil_w_map: dict[date, float] = {}
    snow_map: dict[date, float] = {}
    if soil_keys and "hourly" in data:
        h = data["hourly"]
        soil_t_map = _daily_mean(h.get("time", []), h.get(soil_keys[0]))
        soil_w_map = _daily_mean(h.get("time", []), h.get(soil_keys[1]))
        if has_snow:
            snow_map = _daily_mean(h.get("time", []), h.get(SNOW_KEY))

    dl = data["daily"]
    out = []
    for i, t in enumerate(dl["time"]):
        def g(key, default=0.0):
            v = dl.get(key, [None] * len(dl["time"]))[i]
            return default if v is None else float(v)
        tmax, tmin = g("temperature_2m_max"), g("temperature_2m_min")
        tmean = dl.get("temperature_2m_mean", [None] * len(dl["time"]))[i]
        tmean = (tmax + tmin) / 2 if tmean is None else float(tmean)
        rh = dl.get("relative_humidity_2m_mean", [None] * len(dl["time"]))[i]
        d = date.fromisoformat(t)
        out.append(Day(d, tmax, tmin, tmean,
                       g("precipitation_sum"), g("et0_fao_evapotranspiration", 2.0),
                       None if rh is None else float(rh),
                       soil_t_map.get(d), soil_w_map.get(d), snow_map.get(d)))
    return out


def demo_weather(forecast_days: int, seed: int = 7) -> tuple[Place, list[Day]]:
    """Синтетическая погода — чтобы скрипт можно было проверить без интернета."""
    rnd = random.Random(seed)
    today = date.today()
    start = today - timedelta(days=PAST_DAYS)
    days = []
    for i in range(PAST_DAYS + forecast_days):
        d = start + timedelta(days=i)
        base = 19 - 6 * math.sin(i / 9.0) + rnd.uniform(-2, 2)
        # два дождевых эпизода: -18..-16 и -9..-7 суток от сегодня
        k = i - PAST_DAYS
        if -18 <= k <= -16:
            p = rnd.uniform(8, 16)
        elif -9 <= k <= -7:
            p = rnd.uniform(10, 22)
        elif rnd.random() < 0.18:
            p = rnd.uniform(0.5, 4)
        else:
            p = 0.0
        tmean = base - (3 if p > 5 else 0)
        days.append(Day(d, tmean + 5, tmean - 5, tmean, p,
                        max(0.6, 3.4 - 0.12 * p - 0.05 * (20 - tmean)), 78 + rnd.uniform(-8, 12)))
    return Place("ДЕМО-режим (синтетическая погода)", 56.0, 38.0), days


# --------------------------------------------------------------------------- #
#  Модель
# --------------------------------------------------------------------------- #

def _filled(days: list[Day], attr: str, min_share: float = 0.9) -> list[float] | None:
    """Ряд из данных модели, если он почти полный; пропуски интерполируются."""
    vals = [getattr(d, attr) for d in days]
    known = [i for i, v in enumerate(vals) if v is not None]
    if len(known) < min_share * len(vals) or not known:
        return None
    out = list(vals)
    for i in range(len(out)):
        if out[i] is not None:
            continue
        left = max((k for k in known if k < i), default=None)
        right = min((k for k in known if k > i), default=None)
        if left is None:
            out[i] = vals[right]
        elif right is None:
            out[i] = vals[left]
        else:
            w = (i - left) / (right - left)
            out[i] = vals[left] * (1 - w) + vals[right] * w
    return [float(v) for v in out]


def sources(days: list[Day]) -> tuple[str, str]:
    """Откуда взяты влага и температура почвы — для честного отображения."""
    w = "модель почвы (Open-Meteo)" if _filled(days, "soil_w") else \
        "оценка по осадкам и испарению"
    t = "модель почвы (Open-Meteo)" if _filled(days, "soil_t") else \
        "оценка по температуре воздуха"
    return w, t


def water_balance(days: list[Day], init: float = 0.5) -> list[float]:
    """Доля доступной влаги в верхнем слое, 0..1.

    Если модель погоды отдаёт объёмную влажность почвы (м³/м³), она переводится
    в долю доступной влаги между влажностью завядания и полевой влагоёмкостью.
    Иначе считается резервуар подстилки по осадкам и эвапотранспирации.
    """
    theta = _filled(days, "soil_w")
    if theta is not None:
        span = THETA_FC - THETA_WILT
        return [max(0.0, min(1.0, (v - THETA_WILT) / span)) for v in theta]

    w = CAPACITY_MM * init
    out = []
    for d in days:
        w = min(CAPACITY_MM, w + INTERCEPT * d.precip)
        beta = 0.30 + 0.70 * (w / CAPACITY_MM)      # сухая подстилка сохнет медленнее
        w = max(0.0, w - CANOPY * d.et0 * beta)
        out.append(w / CAPACITY_MM)
    return out


def soil_temperature(days: list[Day], alpha: float = 0.32) -> list[float]:
    """Температура почвы на 5-10 см.

    Берётся из модели погоды; при её отсутствии приближается сглаживанием
    температуры воздуха с лагом около трёх суток и поправкой на затенение.
    """
    off = CURRENT_BIOTOPE.t_offset
    st = _filled(days, "soil_t")
    if st is not None:
        return [v + off for v in st]

    t = days[0].tmean
    out = []
    for d in days:
        t += alpha * (d.tmean - t)
        out.append(t - 1.2 + off)
    return out


def snowmelt_gdd(days: list[Day], ts: list[float]) -> tuple[list[float], date | None]:
    """Накопленное тепло с момента схода снега, °C·сут.

    Дата схода определяется по высоте снежного покрова, а при её отсутствии —
    по первому устойчивому переходу температуры почвы через нуль. После этого
    считается сумма (T почвы − 5 °C) по суткам: именно она задаёт срок весенних
    видов лучше, чем календарь.
    """
    snow = _filled(days, "snow", min_share=0.7)
    melt_i = None
    if snow is not None:
        for i in range(len(days) - 1, -1, -1):
            if snow[i] >= SNOW_GONE:
                melt_i = min(i + 1, len(days) - 1)
                break
        else:
            melt_i = 0
    else:
        for i in range(2, len(days)):
            if ts[i] > 0.5 and ts[i - 1] > 0.5 and ts[i - 2] <= 0.5:
                melt_i = i
                break

    out = [0.0] * len(days)
    if melt_i is None:
        return out, None
    acc = 0.0
    for i in range(melt_i, len(days)):
        acc += max(0.0, ts[i] - GDD_BASE)
        out[i] = acc
    return out, days[melt_i].d


def spring_factor(sp: Species, i: int, gdd: list[float], melt: date | None) -> float:
    """Насколько накопленное после схода снега тепло подходит виду."""
    if melt is None:
        return 0.35
    return max(0.05, _gauss(gdd[i], sp.gdd_opt, sp.gdd_sigma))


def _gauss(x: float, mu: float, sigma: float) -> float:
    return math.exp(-0.5 * ((x - mu) / sigma) ** 2)


def _ramp(x: float, lo: float, hi: float) -> float:
    if x <= lo:
        return 0.0
    if x >= hi:
        return 1.0
    u = (x - lo) / (hi - lo)
    return u * u * (3 - 2 * u)          # плавный smoothstep


def rain_pulse(days: list[Day]) -> list[float]:
    """Импульс увлажнения: сумма осадков за 3 суток, нормированная 3..22 мм."""
    out = []
    for i in range(len(days)):
        s = sum(days[j].precip for j in range(max(0, i - 2), i + 1))
        out.append(_ramp(s, 3.0, 22.0))
    return out


def growth_rate(sp: Species, m: list[float], ts: list[float], days: list[Day]) -> list[float]:
    """Суточная скорость закладки примордиев, 0..1.

    Плодоношение — импульсный отклик на увлажнение (BASE — фоновая закладка
    при устойчиво сырой подстилке, PULSE — реакция на конкретный дождь).
    """
    pulse = rain_pulse(days)
    base = sp.base_share or BASE          # весной толчок даёт талая вода, не дождь
    out = []
    for i, d in enumerate(days):
        f_m = _ramp(m[i], sp.m_min, sp.m_opt)
        f_t = _gauss(ts[i], sp.t_opt, sp.t_sigma)
        f_fr = 0.0 if d.tmin < -5 else (0.6 if d.tmin < -1 else 1.0)
        out.append(f_m * f_t * f_fr * (base + (1 - base) * pulse[i]))
    return out


def lag_kernel(sp: Species) -> list[float]:
    """Треугольное ядро задержки плодообразования, нормированное на 1."""
    span = list(range(sp.lag_min, sp.lag_max + 1))
    peak = (sp.lag_min + sp.lag_max) / 2
    half = max(1.0, (sp.lag_max - sp.lag_min) / 2 + 0.5)
    w = [max(0.0, 1 - abs(k - peak) / half) + 0.15 for k in span]
    s = sum(w)
    return [x / s for x in w]


def surface_factor(i: int, days: list[Day], m: list[float]) -> float:
    """Сохранность уже выросших плодовых тел на поверхности."""
    f = 1.0
    tmin = min(days[j].tmin for j in range(max(0, i - 1), i + 1))
    if tmin < -4:
        f *= 0.15
    elif tmin < -1:
        f *= 0.55
    if m[i] < 0.20:
        f *= 0.45
    if days[i].tmax > 30:
        f *= 0.70
    return f


def cold_snap_factor(i: int, days: list[Day], ts: list[float]) -> float:
    """Для опят: произошёл ли осенний спад температуры почвы.

    Триггером служит не резкий скачок за трое суток (осеннее остывание идёт
    плавно, около 0.15 °C в сутки), а накопленное падение относительно тёплого
    максимума предшествующего периода. Волна отсчитывается от начала спада
    и затухает примерно за полтора месяца.
    """
    lo, hi = max(0, i - 50), max(0, i - 6)
    if hi - lo < 8:
        return 0.5
    warm = ts[lo]
    for j in range(lo, hi + 1):
        warm = max(warm, ts[j])
        if warm - ts[j] >= 4.0 and ts[j] <= 13.5 and days[j].tmin <= 12.0:
            age = i - j
            return 0.35 + 0.65 * (1.0 - _ramp(age, 18, 42))
    return 0.30


def species_index(sp: Species, days: list[Day], m: list[float], ts: list[float]) -> list[float]:
    g = growth_rate(sp, m, ts, days)
    gdd, melt = snowmelt_gdd(days, ts) if sp.spring else ([], None)
    ker = lag_kernel(sp)
    span = list(range(sp.lag_min, sp.lag_max + 1))
    idx = []
    for i in range(len(days)):
        if i < sp.lag_max:
            idx.append(float("nan"))
            continue
        acc = min(1.0, GAIN * sum(w * g[i - k] for w, k in zip(ker, span)))
        season = sp.months.get(days[i].d.month, 0.0)
        f = acc * season * surface_factor(i, days, m) * biotope_weight(sp)
        if sp.cold_snap:
            f *= cold_snap_factor(i, days, ts)
        if sp.spring:
            f *= spring_factor(sp, i, gdd, melt)
        idx.append(100.0 * min(1.0, f))
    return idx


def explain(sp: Species, i: int, days: list[Day], m: list[float],
            ts: list[float]) -> list[tuple[str, float, str]]:
    """Разложение индекса на сомножители: [(фактор, 0..1, пояснение)].

    Значения по окну закладки усредняются с тем же ядром, что и в species_index,
    поэтому произведение факторов даёт итоговый индекс (с точностью до GAIN).
    """
    span = list(range(sp.lag_min, sp.lag_max + 1))
    ker = lag_kernel(sp)
    pulse = rain_pulse(days)
    wsum = sum(w for w, k in zip(ker, span) if i - k >= 0) or 1.0

    def avg(fn):
        return sum(w * fn(i - k) for w, k in zip(ker, span) if i - k >= 0) / wsum

    f_m = avg(lambda j: _ramp(m[j], sp.m_min, sp.m_opt))
    f_t = avg(lambda j: _gauss(ts[j], sp.t_opt, sp.t_sigma))
    _b = sp.base_share or BASE
    f_p = avg(lambda j: _b + (1 - _b) * pulse[j])
    t_win = avg(lambda j: ts[j])
    m_win = avg(lambda j: m[j])
    season = sp.months.get(days[i].d.month, 0.0)
    surf = surface_factor(i, days, m)

    out = [
        ("Влага в подстилке", f_m,
         f"в период закладки {m_win * 100:.0f}% ёмкости, виду нужно от "
         f"{sp.m_min * 100:.0f}%, оптимум {sp.m_opt * 100:.0f}%"),
        ("Температура почвы", f_t,
         f"в период закладки {t_win:.1f} °C, оптимум вида {sp.t_opt:.0f} °C"),
        ("Дожди как толчок", f_p,
         "плодоношение запускает событие увлажнения, а не просто сырость"
         + (" (весной эту роль берёт на себя талая вода)" if sp.spring else "")),
        ("Сезон", season,
         f"{RU_MONTHS[days[i].d.month]}: сезонный вес вида {season:.2f}"),
        ("Сохранность урожая", surf,
         "заморозок, жара или пересыхание губят уже выросшие плодовые тела"),
    ]
    if sp.spring:
        gdd, melt = snowmelt_gdd(days, ts)
        val = spring_factor(sp, i, gdd, melt)
        if melt is None:
            why = "не удалось определить дату схода снега"
        else:
            why = (f"снег сошёл {melt.strftime('%d.%m')}, с тех пор накоплено "
                   f"{gdd[i]:.0f} °C·сут, виду нужно около {sp.gdd_opt:.0f}")
        out.append(("Тепло после схода снега", val, why))
    if sp.cold_snap:
        out.append(("Осеннее похолодание", cold_snap_factor(i, days, ts),
                    "волна запускается падением температуры после тёплого периода"))
    bw = biotope_weight(sp)
    if abs(bw - 1.0) > 0.01:
        out.append((f"Тип леса: {CURRENT_BIOTOPE.name.lower()}", min(1.0, bw),
                    f"пригодность биотопа для вида — множитель {bw:.2f}"
                    + (f"; {CURRENT_BIOTOPE.note}" if CURRENT_BIOTOPE.note else "")))
    return out


def plain_summary(sp: Species, i: int, days: list[Day], m: list[float],
                  ts: list[float], value: float) -> str:
    """Объяснение прогноза обычными словами."""
    fx = explain(sp, i, days, m, ts)
    weak = sorted(fx, key=lambda x: x[1])
    dsr = days_since_rain(i, days)

    if value >= 68:
        lead = f"{sp.name}: условия сложились."
    elif value >= 33:
        lead = f"{sp.name}: условия средние."
    elif value >= 18:
        lead = f"{sp.name}: скорее пусто, возможны единичные находки."
    else:
        lead = f"{sp.name}: условий нет."

    good = []
    if dsr is not None and sp.lag_min <= dsr <= sp.lag_max:
        good.append(f"дождь был {dsr} сут назад — это ровно срок вида "
                    f"({sp.lag_min}–{sp.lag_max} сут от дождя до гриба)")
    elif dsr is not None and dsr < sp.lag_min:
        good.append(f"дождь прошёл {dsr} сут назад — грибы ещё не успели вырасти, "
                    f"виду нужно {sp.lag_min}–{sp.lag_max} сут")
    if m[i] >= sp.m_opt:
        good.append(f"подстилка сырая ({m[i] * 100:.0f}% ёмкости)")
    if abs(ts[i] - sp.t_opt) <= sp.t_sigma * 0.6:
        good.append(f"температура почвы {ts[i]:.0f} °C — в оптимуме вида")

    bad = [f"{n.lower()}: {why}" for n, v, why in weak[:2] if v < 0.6]

    parts = [lead]
    if good:
        parts.append("В плюс: " + "; ".join(good) + ".")
    if bad:
        parts.append("В минус: " + "; ".join(bad) + ".")
    return " ".join(parts)


def limiting_factor(sp: Species, i: int, days: list[Day], m: list[float], ts: list[float]) -> str:
    span = list(range(sp.lag_min, sp.lag_max + 1))
    js = [i - k for k in span if 0 <= i - k]
    if not js:
        return "мало данных"
    f_m = sum(_ramp(m[j], sp.m_min, sp.m_opt) for j in js) / len(js)
    f_t = sum(_gauss(ts[j], sp.t_opt, sp.t_sigma) for j in js) / len(js)
    season = sp.months.get(days[i].d.month, 0.0)
    surf = surface_factor(i, days, m)
    cands = [(min(1.0, biotope_weight(sp)), f"вид мало свойственен биотопу "
              f"«{CURRENT_BIOTOPE.name.lower()}»"),
             (f_m, "нехватка влаги в период закладки"),
             (f_t, "температура почвы вне оптимума"),
             (season, "не сезон для этого вида"),
             (surf, "погода губит уже выросшие грибы (заморозок/сушь/жара)")]
    if sp.cold_snap:
        cands.append((cold_snap_factor(i, days, ts), "не было похолодания — волна не запущена"))
    if sp.spring:
        gdd, melt = snowmelt_gdd(days, ts)
        cands.append((spring_factor(sp, i, gdd, melt),
                      "почва после схода снега ещё не набрала (или уже перебрала) тепло"))
    val, txt = min(cands, key=lambda x: x[0])
    return "всё в норме" if val > 0.75 else txt


# --------------------------------------------------------------------------- #
#  Вывод
# --------------------------------------------------------------------------- #

LEVELS = [(85, "массовый слой"), (68, "обильно"), (50, "хорошо"),
          (33, "умеренно"), (18, "единично"), (8, "почти нет"), (0, "нет")]
RU_WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
RU_MONTHS = ["", "январь", "февраль", "март", "апрель", "май", "июнь", "июль",
             "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def level(v: float) -> str:
    for th, txt in LEVELS:
        if v >= th:
            return txt
    return "нет"


def bar(v: float, width: int = 20) -> str:
    n = int(round(width * max(0.0, min(100.0, v)) / 100))
    return "█" * n + "·" * (width - n)


def days_since_rain(i: int, days: list[Day], thr: float = 5.0) -> int | None:
    for k in range(0, i + 1):
        if days[i - k].precip >= thr:
            return k
    return None


def report(place: Place, days: list[Day], forecast_days: int,
           chosen: list[Species], today_idx: int) -> None:
    m = water_balance(days)
    ts = soil_temperature(days)
    table = {sp.name: species_index(sp, days, m, ts) for sp in chosen}

    print(f"\n  ПРОГНОЗ ПЛОДОНОШЕНИЯ ГРИБОВ")
    print(f"  {place.name}   ({place.lat:.3f}, {place.lon:.3f})")
    print(f"  расчёт на {days[today_idx].d.strftime('%d.%m.%Y')}")
    print("=" * 74)

    lo = max(0, today_idx - 2)
    hi = min(len(days), today_idx + forecast_days)

    print("\n  ОБЩИЙ ИНДЕКС ПО ДНЯМ (лучший из выбранных видов)\n")
    print(f"  {'дата':<11}{'осад':>6}{'T возд':>8}{'T почв':>8}{'влага':>7}   индекс")
    best_day, best_val = None, -1.0
    for i in range(lo, hi):
        d = days[i]
        vals = [table[sp.name][i] for sp in chosen if not math.isnan(table[sp.name][i])]
        v = max(vals) if vals else 0.0
        lead = max(chosen, key=lambda s: (table[s.name][i] if not math.isnan(table[s.name][i]) else -1))
        if i >= today_idx and v > best_val:
            best_val, best_day = v, d
        mark = "→" if i == today_idx else " "
        print(f" {mark}{d.d.strftime('%d.%m'):<6}{RU_WD[d.d.weekday()]:<5}"
              f"{d.precip:>5.1f}{d.tmean:>8.1f}{ts[i]:>8.1f}{m[i]*100:>6.0f}%   "
              f"{bar(v)} {v:>4.0f}  {level(v)}"
              + (f"  · {lead.name.lower()}" if v >= 18 else ""))

    print("\n  ПО ВИДАМ\n")
    hdr = "".join(f"{days[i].d.strftime('%d.%m'):>7}" for i in range(today_idx, hi))
    print(f"  {'вид':<20}{hdr}")
    for sp in chosen:
        row = "".join(
            f"{'  —  ':>7}" if math.isnan(table[sp.name][i]) else f"{table[sp.name][i]:>7.0f}"
            for i in range(today_idx, hi))
        print(f"  {sp.name:<20}{row}")

    print("\n  ДИАГНОСТИКА\n")
    dsr = days_since_rain(today_idx, days)
    p14 = sum(days[j].precip for j in range(max(0, today_idx - 13), today_idx + 1))
    print(f"  Влагозапас подстилки .... {m[today_idx]*100:.0f}% от ёмкости ({m[today_idx]*CAPACITY_MM:.0f} мм)")
    print(f"  Осадки за 14 суток ...... {p14:.1f} мм")
    print(f"  Последний дождь ≥5 мм ... " + (f"{dsr} сут назад" if dsr is not None else "не было за месяц"))
    print(f"  Температура почвы ....... {ts[today_idx]:.1f} °C")
    src_w, src_t = sources(days)
    print(f"  Источник влаги .......... {src_w}")
    print(f"  Источник T почвы ........ {src_t}")
    print(f"  Настройка модели ........ {calibration_info()}")
    print(f"  Тип леса ................ {CURRENT_BIOTOPE.name} "
          f"(θ {CURRENT_BIOTOPE.theta_wilt:.2f}–{CURRENT_BIOTOPE.theta_fc:.2f} м³/м³)")
    for sp in chosen:
        v = table[sp.name][today_idx]
        v = 0.0 if math.isnan(v) else v
        print(f"  · {sp.name}: {v:.0f} — {limiting_factor(sp, today_idx, days, m, ts)}")

    if best_day is not None and best_val >= 33:
        print(f"\n  ➜ Лучший день из ближайших: {best_day.d.strftime('%d.%m')} "
              f"({best_val:.0f}, {level(best_val)}).")
    elif best_val >= 18:
        print(f"\n  ➜ Ближайшие дни — только единичные находки.")
    else:
        print(f"\n  ➜ В ближайшие дни выхода не ожидается.")

    notes = [sp for sp in chosen if sp.note]
    if notes:
        print("\n  ПРИМЕЧАНИЯ\n")
        for sp in notes:
            print(f"  {sp.name}: {sp.note}")
    print()


def as_json(place: Place, days: list[Day], forecast_days: int,
            chosen: list[Species], today_idx: int) -> str:
    m = water_balance(days)
    ts = soil_temperature(days)
    table = {sp.name: species_index(sp, days, m, ts) for sp in chosen}
    hi = min(len(days), today_idx + forecast_days)
    out = {
        "place": {"name": place.name, "lat": place.lat, "lon": place.lon},
        "generated": datetime.now().isoformat(timespec="seconds"),
        "days": [],
    }
    for i in range(today_idx, hi):
        vals = {sp.name: (None if math.isnan(table[sp.name][i]) else round(table[sp.name][i], 1))
                for sp in chosen}
        num = [v for v in vals.values() if v is not None]
        out["days"].append({
            "date": days[i].d.isoformat(),
            "precip_mm": round(days[i].precip, 1),
            "t_air_mean": round(days[i].tmean, 1),
            "t_soil": round(ts[i], 1),
            "moisture": round(m[i], 3),
            "index": round(max(num), 1) if num else 0.0,
            "level": level(max(num) if num else 0.0),
            "species": vals,
        })
    return json.dumps(out, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #

load_calibration()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Прогноз роста грибов по погоде (Open-Meteo).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Виды: " + ", ".join(SPECIES))
    ap.add_argument("--place", default="Фрязино",
                    help="населённый пункт (по умолчанию Фрязино)")
    ap.add_argument("--lat", type=float, help="широта (вместо --place)")
    ap.add_argument("--lon", type=float, help="долгота")
    ap.add_argument("--days", type=int, default=7, help="глубина прогноза, сут (3..16)")
    ap.add_argument("--species", nargs="*", default=None, help="ключи видов через пробел")
    ap.add_argument("--all", action="store_true", help="все виды, включая внесезонные")
    ap.add_argument("--biotope", default="смешанный",
                    help="тип леса: " + ", ".join(BIOTOPES))
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    ap.add_argument("--ensemble", action="store_true",
                    help="коридор P10-P90 по ансамблю погодных сценариев")
    ap.add_argument("--demo", action="store_true", help="синтетическая погода, без сети")
    ap.add_argument("--version", action="version", version=f"mushroom-forecast {VERSION}")
    a = ap.parse_args(argv)

    fdays = max(3, min(16, a.days))
    try:
        set_biotope(a.biotope)
    except LookupError as e:
        print(str(e), file=sys.stderr)
        return 1

    if a.demo:
        place, days = demo_weather(fdays)
    else:
        try:
            place = (Place(f"{a.lat:.3f}, {a.lon:.3f}", a.lat, a.lon)
                     if a.lat is not None and a.lon is not None else geocode(a.place))
            days = fetch_weather(place, fdays)
        except LookupError as e:
            print(str(e), file=sys.stderr)
            return 1
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"Нет доступа к сети ({e}). Запустите с --demo для проверки модели.",
                  file=sys.stderr)
            return 2

    today = date.today()
    today_idx = next((i for i, d in enumerate(days) if d.d >= today), len(days) - fdays)

    if a.species:
        chosen = []
        for k in a.species:
            key = k.lower().replace("ё", "ё")
            sp = SPECIES.get(key) or next((v for kk, v in SPECIES.items() if kk.startswith(key)), None)
            if sp is None:
                print(f"Неизвестный вид: {k}. Доступно: {', '.join(SPECIES)}", file=sys.stderr)
                return 1
            chosen.append(sp)
    else:
        month = days[today_idx].d.month
        chosen = [sp for sp in SPECIES.values() if a.all or sp.months.get(month, 0) > 0]
        if not chosen:
            chosen = list(SPECIES.values())

    if a.json:
        print(as_json(place, days, fdays, chosen, today_idx))
    else:
        report(place, days, fdays, chosen, today_idx)
        if a.ensemble and not a.demo:
            _ensemble_block(place, days, chosen, today_idx, fdays)
    return 0


def _ensemble_block(place, days, chosen, today_idx, fdays):
    """Разброс индекса по сценариям погоды."""
    try:
        import ensemble
    except ImportError:
        print("  Модуль ensemble.py не найден.")
        return
    m = water_balance(days)
    ts = soil_temperature(days)
    lead = max(chosen, key=lambda sp: max(
        (v for v in species_index(sp, days, m, ts)[today_idx:] if v == v), default=0))
    print(f"\n  РАЗБРОС СЦЕНАРИЕВ — {lead.name.lower()}\n")
    try:
        members = ensemble.fetch_members(place, fdays)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"  Ансамбль недоступен ({e}).")
        return
    if not members:
        print("  Ансамблевые данные для этой точки не отдаются.")
        return
    bnd = ensemble.band(days, members, lead)
    print(f"  Сценариев: {len(members)}\n")
    print(f"  {'дата':<11}{'P10':>6}{'P50':>6}{'P90':>6}   комментарий")
    for i in range(today_idx, min(len(days), today_idx + fdays)):
        v = bnd.get(days[i].d)
        if v:
            print(f"  {days[i].d.strftime('%d.%m'):<11}{v[0]:>6.0f}{v[1]:>6.0f}"
                  f"{v[2]:>6.0f}   {ensemble.spread_text(bnd, days[i].d)}")
    print(f"\n  {ensemble.reliability(bnd, days, today_idx)}")


if __name__ == "__main__":
    raise SystemExit(main())
