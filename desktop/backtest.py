#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest.py — прогон модели по архиву погоды за прошлые сезоны.

Зачем: прежде чем калибровать константы, надо понять, врёт ли модель
систематически. Инструмент считает индекс за каждый день выбранных сезонов
и сводит результат в календарную карту «год × дата» плюс таблицу метрик:
сколько было грибных дней, когда первая волна, когда пик.

Данные: архив Open-Meteo (ERA5, с 1940 года), тот же набор переменных,
что и в прогнозе, включая почвенные слои. Ответы кэшируются на диск,
повторные прогоны идут мгновенно и не нагружают сервис.

Примеры:
    python backtest.py --lat 55.9606 --lon 38.0456 --from 2015 --to 2025
    python backtest.py --place "Фрязино" --species белый опёнок --open
    python backtest.py --from 2010 --to 2024 --csv out.csv
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import urllib.error
from datetime import date, timedelta

import mushroom_forecast as engine

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".mushroom-backtest-cache")

SEASON_START = (4, 1)      # с запасом на лаги и накопление влаги
SEASON_END = (11, 15)
ANALYSIS_START = (5, 1)    # с какой даты считаются метрики


# --------------------------------------------------------------------------- #
#  Загрузка архива
# --------------------------------------------------------------------------- #

def fetch_season(place: engine.Place, year: int) -> list[engine.Day]:
    """Суточный ряд за сезон года с кэшированием на диск."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = f"{place.lat:.3f}_{place.lon:.3f}_{year}.json"
    path = os.path.join(CACHE_DIR, key)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return _parse(json.load(f))

    start = date(year, *SEASON_START)
    end = min(date(year, *SEASON_END), date.today() - timedelta(days=6))
    if start >= end:
        return []

    daily = ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
             "precipitation_sum", "et0_fao_evapotranspiration"]
    base = {"latitude": place.lat, "longitude": place.lon,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "timezone": "auto", "daily": ",".join(daily)}

    data = None
    for t_key, w_key in engine.SOIL_CANDIDATES:
        try:
            data = engine._get_json(ARCHIVE_URL, dict(base, hourly=f"{t_key},{w_key}"))
            data["_soil"] = [t_key, w_key]
            break
        except urllib.error.HTTPError:
            continue
    if data is None:
        data = engine._get_json(ARCHIVE_URL, base)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return _parse(data)


def _parse(data: dict) -> list[engine.Day]:
    dl = data["daily"]
    st = sw = {}
    keys = data.get("_soil")
    if keys and "hourly" in data:
        h = data["hourly"]
        st = engine._daily_mean(h.get("time", []), h.get(keys[0]))
        sw = engine._daily_mean(h.get("time", []), h.get(keys[1]))

    out = []
    for i, t in enumerate(dl["time"]):
        def g(k, default=0.0):
            v = dl.get(k, [None] * len(dl["time"]))[i]
            return default if v is None else float(v)
        tmax, tmin = g("temperature_2m_max"), g("temperature_2m_min")
        tmean = dl.get("temperature_2m_mean", [None] * len(dl["time"]))[i]
        tmean = (tmax + tmin) / 2 if tmean is None else float(tmean)
        d = date.fromisoformat(t)
        out.append(engine.Day(d, tmax, tmin, tmean, g("precipitation_sum"),
                              g("et0_fao_evapotranspiration", 2.5), None,
                              st.get(d), sw.get(d)))
    return out


# --------------------------------------------------------------------------- #
#  Анализ сезона
# --------------------------------------------------------------------------- #

class SeasonStats:
    def __init__(self, year, days, idx, m, ts, start_i):
        self.year = year
        self.days = days
        self.idx = idx
        self.m = m
        self.ts = ts
        self.start = start_i

        vals = [v for v in idx[start_i:] if v == v]                 # без nan
        self.good = sum(1 for v in vals if v >= 50)
        self.some = sum(1 for v in vals if v >= 33)
        self.peak = max(vals) if vals else 0.0
        self.total = sum(vals) / 100.0 if vals else 0.0             # «грибных единиц»
        self.rain = sum(d.precip for d in days[start_i:])

        self.peak_date = None
        self.first_date = None
        for i in range(start_i, len(idx)):
            v = idx[i]
            if v != v:
                continue
            if self.first_date is None and v >= 50:
                self.first_date = days[i].d
            if v == self.peak and self.peak >= 18:
                self.peak_date = days[i].d
        self.waves = _count_waves(idx[start_i:], [d.d for d in days[start_i:]])


def _count_waves(idx, dates, thr=50.0, gap=7):
    """Число обособленных волн: подъёмы выше порога, разделённые провалами."""
    waves, active, last = 0, False, None
    for v, d in zip(idx, dates):
        if v != v:
            continue
        if v >= thr and not active:
            if last is None or (d - last).days >= gap:
                waves += 1
            active = True
        elif v < thr * 0.7 and active:
            active, last = False, d
    return waves


def analyze(place, years, species_keys):
    out = {}
    for key in species_keys:
        sp = engine.SPECIES[key]
        out[key] = []
    for year in years:
        days = fetch_season(place, year)
        if len(days) < 60:
            continue
        m = engine.water_balance(days)
        ts = engine.soil_temperature(days)
        start_i = next((i for i, d in enumerate(days)
                        if (d.d.month, d.d.day) >= ANALYSIS_START), 0)
        for key in species_keys:
            sp = engine.SPECIES[key]
            idx = engine.species_index(sp, days, m, ts)
            out[key].append(SeasonStats(year, days, idx, m, ts, start_i))
    return out


# --------------------------------------------------------------------------- #
#  Отчёт
# --------------------------------------------------------------------------- #

LEVEL_FILL = [(85, "#2E7D32"), (68, "#66A63C"), (50, "#A6CC72"), (33, "#CFE3A3"),
              (18, "#E6EDCB"), (8, "#F0F1EA"), (0, "#F7F7F5")]


def _fill(v):
    for th, col in LEVEL_FILL:
        if v >= th:
            return col
    return LEVEL_FILL[-1][1]


def heatmap_svg(stats: list[SeasonStats], title: str) -> str:
    """Календарная карта: строка — сезон, столбец — дата."""
    if not stats:
        return ""
    left, top, cell, row_h = 46, 34, 3.0, 17
    first = min(s.days[s.start].d.timetuple().tm_yday for s in stats)
    last = max(s.days[-1].d.timetuple().tm_yday for s in stats)
    width = left + (last - first + 1) * cell + 16
    height = top + len(stats) * row_h + 26

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
         f'height="{height:.0f}" font-family="sans-serif">',
         f'<text x="{left}" y="16" font-size="12" font-weight="600" '
         f'fill="#2B2F27">{title}</text>']

    # подписи месяцев
    for mth in range(5, 12):
        doy = date(2001, mth, 1).timetuple().tm_yday
        if not (first <= doy <= last):
            continue
        x = left + (doy - first) * cell
        p.append(f'<line x1="{x:.1f}" y1="{top - 4}" x2="{x:.1f}" '
                 f'y2="{top + len(stats) * row_h}" stroke="#DFE1D8" stroke-width="1"/>')
        p.append(f'<text x="{x + 3:.1f}" y="{top - 6}" font-size="9" fill="#7B8272">'
                 f'{engine.RU_MONTHS[mth][:3]}</text>')

    for k, s in enumerate(stats):
        y = top + k * row_h
        p.append(f'<text x="4" y="{y + 12}" font-size="10" fill="#4A5142">{s.year}</text>')
        for i in range(s.start, len(s.days)):
            v = s.idx[i]
            if v != v:
                continue
            x = left + (s.days[i].d.timetuple().tm_yday - first) * cell
            p.append(f'<rect x="{x:.1f}" y="{y}" width="{cell:.1f}" height="{row_h - 3}" '
                     f'fill="{_fill(v)}"/>')
    # шкала
    yb = top + len(stats) * row_h + 14
    for j, (th, col) in enumerate(reversed(LEVEL_FILL)):
        p.append(f'<rect x="{left + j * 54}" y="{yb - 9}" width="52" height="10" '
                 f'fill="{col}"/>')
        p.append(f'<text x="{left + j * 54 + 26}" y="{yb + 10}" font-size="8" '
                 f'text-anchor="middle" fill="#7B8272">{th}</text>')
    p.append("</svg>")
    return "".join(p)


def html_report(place, results, path):
    blocks = []
    for key, stats in results.items():
        sp = engine.SPECIES[key]
        if not stats:
            continue
        good = [s.good for s in stats]
        med = statistics.median(good) if good else 0
        rows = []
        for s in sorted(stats, key=lambda s: s.year):
            mark = "выше нормы" if s.good > med * 1.3 else (
                "ниже нормы" if s.good < med * 0.7 else "около нормы")
            rows.append(
                f"<tr><td>{s.year}</td><td>{s.good}</td><td>{s.some}</td>"
                f"<td>{s.waves}</td>"
                f"<td>{s.first_date.strftime('%d.%m') if s.first_date else '—'}</td>"
                f"<td>{s.peak_date.strftime('%d.%m') if s.peak_date else '—'}</td>"
                f"<td>{s.peak:.0f}</td><td>{s.rain:.0f}</td><td>{mark}</td></tr>")
        blocks.append(f"""
<h2>{sp.name} <span style="font-weight:400;color:#7B8272">({sp.latin})</span></h2>
{heatmap_svg(sorted(stats, key=lambda s: s.year), "Индекс по дням сезона")}
<table>
<tr><th>Сезон</th><th>Дней ≥50</th><th>Дней ≥33</th><th>Волн</th>
<th>Первая волна</th><th>Пик</th><th>Максимум</th><th>Осадки, мм</th><th>Оценка</th></tr>
{''.join(rows)}
</table>
<p class="note">Медиана по «дням ≥50» за период: {med:.0f}. Отметки «выше/ниже нормы»
считаются от неё, отклонение более 30%.</p>""")

    html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<title>Прогон модели по архиву — {place.name}</title>
<style>
body {{ font-family: sans-serif; color:#2B2F27; max-width:1100px; margin:24px auto;
        padding:0 16px; line-height:1.45; }}
h1 {{ font-size:20px; margin-bottom:2px }}
h2 {{ font-size:16px; margin:26px 0 8px }}
table {{ border-collapse:collapse; margin-top:10px; font-size:13px }}
th, td {{ border:1px solid #DFE1D8; padding:4px 9px; text-align:right }}
th {{ background:#F2F3EE; font-weight:600; color:#5A6152 }}
td:first-child, td:last-child {{ text-align:left }}
.note {{ color:#7B8272; font-size:12px }}
.head {{ color:#7B8272; font-size:13px; margin-top:0 }}
</style></head><body>
<h1>Прогон модели по архиву погоды</h1>
<p class="head">{place.name} · {place.lat:.4f}, {place.lon:.4f} ·
источник: Open-Meteo Archive (ERA5) · модель mushroom-forecast {engine.VERSION} ·
тип леса: {engine.CURRENT_BIOTOPE.name}</p>
{''.join(blocks)}
<p class="note">Как читать: сравните годы, которые вы помните как грибные и пустые,
со столбцом «Дней ≥50». Если порядок совпадает — модель улавливает межгодовую
изменчивость, и можно переходить к калибровке констант. Если нет — сначала
разбираться, какой сомножитель врёт.</p>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def write_csv(results, path):
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["вид", "сезон", "дней_50", "дней_33", "волн", "первая_волна",
                    "пик_дата", "максимум", "осадки_мм", "сумма_индекса"])
        for key, stats in results.items():
            name = engine.SPECIES[key].name
            for s in sorted(stats, key=lambda s: s.year):
                w.writerow([name, s.year, s.good, s.some, s.waves,
                            s.first_date or "", s.peak_date or "",
                            f"{s.peak:.0f}", f"{s.rain:.0f}", f"{s.total:.1f}"])
    return path


# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Прогон модели плодоношения по архиву погоды.",
        epilog="Виды: " + ", ".join(engine.SPECIES))
    ap.add_argument("--place", default="Фрязино")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--from", dest="y0", type=int, default=date.today().year - 10)
    ap.add_argument("--to", dest="y1", type=int, default=date.today().year)
    ap.add_argument("--species", nargs="*", default=["белый", "подберёзовик", "опёнок"])
    ap.add_argument("--out", default="backtest.html")
    ap.add_argument("--csv")
    ap.add_argument("--biotope", default="смешанный",
                    help="тип леса: " + ", ".join(engine.BIOTOPES))
    ap.add_argument("--open", action="store_true", help="открыть отчёт в браузере")
    a = ap.parse_args(argv)

    try:
        engine.set_biotope(a.biotope)
    except LookupError as e:
        print(str(e), file=sys.stderr)
        return 1

    keys = []
    for k in a.species:
        kk = k.lower()
        if kk not in engine.SPECIES:
            kk = next((n for n in engine.SPECIES if n.startswith(kk)), None)
        if kk is None:
            print(f"Неизвестный вид: {k}", file=sys.stderr)
            return 1
        keys.append(kk)

    try:
        place = (engine.Place(f"{a.lat:.3f}, {a.lon:.3f}", a.lat, a.lon)
                 if a.lat is not None and a.lon is not None else engine.geocode(a.place))
    except LookupError as e:
        print(str(e), file=sys.stderr)
        return 1

    years = list(range(a.y0, a.y1 + 1))
    print(f"{place.name}: сезоны {years[0]}–{years[-1]}, видов {len(keys)}")
    print(f"Кэш архива: {CACHE_DIR}")
    try:
        results = analyze(place, years, keys)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"Нет доступа к архиву ({e}).", file=sys.stderr)
        return 2

    path = html_report(place, results, a.out)
    print(f"Отчёт: {os.path.abspath(path)}")
    if a.csv:
        print(f"Таблица: {os.path.abspath(write_csv(results, a.csv))}")

    for key, stats in results.items():
        if not stats:
            continue
        best = max(stats, key=lambda s: s.good)
        worst = min(stats, key=lambda s: s.good)
        print(f"  {engine.SPECIES[key].name}: лучший сезон {best.year} "
              f"({best.good} дней ≥50), худший {worst.year} ({worst.good})")

    if a.open:
        import webbrowser
        webbrowser.open("file://" + os.path.abspath(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
