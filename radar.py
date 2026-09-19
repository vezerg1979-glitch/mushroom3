# -*- coding: utf-8 -*-
"""Короткая сводка по грибным волнам из уже рассчитанных индексов.

Модуль ничего не предсказывает поверх ядра: он переводит форму ряда 0..100
в фазу (ожидание/рост/пик/спад) и компактную матрицу по дням.
"""
from __future__ import annotations
import math

LOW = 18.0
ACTIVE = 33.0
PEAK = 60.0
SLOPE = 4.0


def _v(values, i):
    try:
        v = float(values[i])
    except (TypeError, ValueError, IndexError):
        return 0.0
    return 0.0 if math.isnan(v) else max(0.0, min(100.0, v))


def phase(values, i: int) -> str:
    """Фаза текущей волны по уровню и локальному направлению ряда."""
    now = _v(values, i)
    prev = _v(values, i - 1) if i > 0 else now
    nxt = _v(values, i + 1) if i + 1 < len(values) else now
    trend = nxt - prev
    if now < LOW:
        # Уже видимый будущий подъём отличаем от полного затишья.
        future = max((_v(values, j) for j in range(i + 1, min(len(values), i + 6))), default=0)
        return "зарождение" if future >= ACTIVE else "ожидание"
    if now >= PEAK and abs(trend) < SLOPE:
        return "пик"
    if trend >= SLOPE:
        return "рост"
    if trend <= -SLOPE:
        return "спад"
    return "плато" if now >= ACTIVE else "зарождение"


def rows(days, idx_by_name: dict, today: int, names=None, horizon: int = 7) -> list[dict]:
    """Строки радара, отсортированные по лучшему значению на горизонте."""
    names = list(names) if names is not None else list(idx_by_name)
    end = min(len(days), today + max(1, horizon))
    out = []
    for name in names:
        values = idx_by_name.get(name)
        if not values or today >= len(values):
            continue
        vals = [_v(values, j) for j in range(today, min(end, len(values)))]
        if not vals:
            continue
        best_off = max(range(len(vals)), key=vals.__getitem__)
        out.append({"name": name, "phase": phase(values, today), "values": vals,
                    "best": vals[best_off], "best_day": best_off})
    out.sort(key=lambda r: (-r["best"], r["best_day"], r["name"]))
    return out


def _mark(v: float) -> str:
    if v >= 68: return "++"
    if v >= 50: return "+"
    if v >= 33: return "~"
    return "·"


def text(days, idx_by_name: dict, today: int, names=None, horizon: int = 7,
         limit: int = 8) -> str:
    """Читаемая моноширинно-независимая сводка для popup Android."""
    rr = rows(days, idx_by_name, today, names, horizon)
    if not rr:
        return "Недостаточно данных для радара."
    n = min(horizon, max(len(r["values"]) for r in rr))
    head = ["[b]Грибной радар[/b]", "Условные знаки: ++ отлично, + хорошо, ~ умеренно, · слабо", ""]
    dates = "  ".join(days[today+j].d.strftime("%d.%m") for j in range(n) if today+j < len(days))
    head += ["[b]Дни:[/b] " + dates, ""]
    for r in rr[:limit]:
        marks = "   ".join(_mark(v) for v in r["values"][:n])
        peak_i = today + r["best_day"]
        peak_date = days[peak_i].d.strftime("%d.%m") if peak_i < len(days) else ""
        head.append(f"[b]{r['name']}[/b] — {r['phase']}; лучший день {peak_date}: {r['best']:.0f}/100")
        head.append(marks)
    head += ["", "[size=11sp]Радар показывает форму уже рассчитанного прогноза, а не вероятность находки.[/size]"]
    return "\n".join(head)


def icon_grade(value: float) -> str:
    """Категория маленькой иконки гриба для семидневного радара."""
    value = _v([value], 0)
    if value >= 68: return "high"
    if value >= 50: return "good"
    if value >= 33: return "medium"
    return "low"
