#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ensemble.py — коридор неопределённости по ансамблю погодных сценариев.

Зачем: детерминированный прогноз на 12–16 суток — это одна реализация из многих
возможных. Единственная линия индекса выглядит убедительнее, чем она есть.
Ансамблевый API Open-Meteo отдаёт три-четыре десятка равноправных сценариев;
индекс считается по каждому, и на график ложится полоса P10–P90 вместо линии.

Полезное свойство: ближние дни у всех сценариев сходятся, потому что индекс
определяется уже выпавшим дождём. Расходиться прогноз начинает за пределами
лага вида — то есть грибной прогноз предсказуем дальше, чем сама погода.

Важно: у членов ансамбля нет почвенных полей, поэтому влага для них считается
резервным способом (резервуар подстилки). Полоса показывает разброс погодных
сценариев, а не полную неопределённость модели.
"""

from __future__ import annotations

import math
import re
import urllib.error
from datetime import date

import mushroom_forecast as engine

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
MODELS = ["icon_seamless", "gfs_seamless"]
MEMBER_RE = re.compile(r"^(temperature_2m|precipitation)(?:_member(\d+))?$")

WIDE = 35.0        # разброс шире этого считается большим, баллов индекса
NARROW = 12.0      # уже этого — сценарии практически согласованы


# --------------------------------------------------------------------------- #
#  Загрузка сценариев
# --------------------------------------------------------------------------- #

def fetch_members(place: engine.Place, forecast_days: int,
                  past_days: int = 20) -> list[dict[date, tuple[float, float]]]:
    """Список сценариев: для каждого — словарь дата -> (средняя T, сумма осадков)."""
    params = {
        "latitude": place.lat, "longitude": place.lon,
        "hourly": "temperature_2m,precipitation", "timezone": "auto",
        "past_days": past_days, "forecast_days": max(3, min(16, forecast_days)),
    }
    data = None
    for model in MODELS:
        try:
            data = engine._get_json(ENSEMBLE_URL, dict(params, models=model))
            break
        except urllib.error.HTTPError:
            continue
    if not data or "hourly" not in data:
        return []

    h = data["hourly"]
    times = h.get("time", [])
    members: dict[str, dict[str, list]] = {}
    for key, values in h.items():
        m = MEMBER_RE.match(key)
        if not m or not isinstance(values, list):
            continue
        members.setdefault(m.group(2) or "00", {})[m.group(1)] = values

    out = []
    for _, series in sorted(members.items()):
        temp, prec = series.get("temperature_2m"), series.get("precipitation")
        if not temp or not prec:
            continue
        acc: dict[date, list] = {}
        for t, tv, pv in zip(times, temp, prec):
            if tv is None:
                continue
            rec = acc.setdefault(date.fromisoformat(t[:10]), [0.0, 0, 0.0])
            rec[0] += float(tv)
            rec[1] += 1
            rec[2] += float(pv or 0.0)
        out.append({d: (v[0] / v[1], v[2]) for d, v in acc.items() if v[1]})
    return out


# --------------------------------------------------------------------------- #
#  Расчёт коридора
# --------------------------------------------------------------------------- #

def _member_days(base: list[engine.Day], member: dict) -> list[engine.Day]:
    """Ряд суток по сценарию: история из основного прогноза, будущее — из члена."""
    today = date.today()
    out = []
    for d in base:
        if d.d < today or d.d not in member:
            out.append(engine.Day(d.d, d.tmax, d.tmin, d.tmean, d.precip, d.et0,
                                  d.rh, None, None))
            continue
        tmean, precip = member[d.d]
        spread = (d.tmax - d.tmin) / 2 if d.tmax > d.tmin else 5.0
        out.append(engine.Day(d.d, tmean + spread, tmean - spread, tmean,
                              precip, d.et0, d.rh, None, None))
    return out


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def band(base: list[engine.Day], members: list[dict], sp: engine.Species,
         quantiles=(0.1, 0.5, 0.9)) -> dict[date, tuple]:
    """Квантили индекса по дням: {дата: (P10, P50, P90)}."""
    if not members:
        return {}
    series = []
    for member in members:
        days = _member_days(base, member)
        m = engine.water_balance(days)
        ts = engine.soil_temperature(days)
        series.append(engine.species_index(sp, days, m, ts))

    out = {}
    for i, d in enumerate(base):
        vals = [idx[i] for idx in series if i < len(idx) and idx[i] == idx[i]]
        if len(vals) >= 3:
            out[d.d] = tuple(_quantile(vals, q) for q in quantiles)
    return out


def spread_text(bnd: dict, d: date) -> str:
    """Формулировка разброса для конкретного дня."""
    v = bnd.get(d)
    if not v:
        return ""
    lo, mid, hi = v
    width = hi - lo
    if width < NARROW:
        return f"сценарии сходятся: {lo:.0f}–{hi:.0f}"
    if width < WIDE:
        return f"умеренный разброс: {lo:.0f}–{hi:.0f}, вероятнее {mid:.0f}"
    return (f"сценарии сильно расходятся: {lo:.0f}–{hi:.0f} — "
            f"прогноз на этот день ненадёжен")


def reliability(bnd: dict, days, start: int) -> str:
    """До какого дня прогнозу можно верить."""
    for i in range(start, len(days)):
        v = bnd.get(days[i].d)
        if v and v[2] - v[0] > WIDE:
            n = (days[i].d - days[start].d).days
            if n <= 1:
                return ("Погодные сценарии расходятся уже с завтрашнего дня — "
                        "верить можно только сегодняшнему.")
            return (f"Сценарии согласованы примерно на {n} суток вперёд, "
                    f"дальше ({days[i].d.strftime('%d.%m')}) разброс большой.")
    return "Сценарии согласованы на всём горизонте прогноза."
