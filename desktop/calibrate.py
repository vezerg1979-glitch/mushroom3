#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibrate.py — подгонка констант модели под ваш журнал наблюдений.

Что делает: для каждой записи журнала поднимает архивную погоду в этой точке,
считает индекс на дату выезда и подбирает коэффициенты так, чтобы расчёт
ложился на ваши оценки обилия. Результат пишется в calibration.json, который
ядро подхватывает автоматически при следующем запуске.

Метод: симплекс Нелдера-Мида, реализован прямо здесь, сторонних библиотек
не требуется. Часть записей откладывается в контрольную выборку и в подгонке
не участвует — иначе легко подогнать модель под шум и решить, что стало лучше.

Примеры:
    python calibrate.py                      подбор глобальных коэффициентов
    python calibrate.py --species белый      плюс параметры отдельных видов
    python calibrate.py --dry-run            посчитать, но не записывать
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import urllib.error
from datetime import date, datetime

import backtest
import journal
import mushroom_forecast as engine

# Что можно двигать: (имя, минимум, максимум, начальный шаг)
GLOBAL_BOUNDS = {
    "GAIN": (0.6, 2.2, 0.15),
    "BASE": (0.05, 0.7, 0.08),
}

# CAPACITY_MM и THETA_FC задаются профилем биотопа и здесь не двигаются:
# по журналу они определяются плохо, а ошибку тянут в обе стороны.
SPECIES_BOUNDS = {
    "t_opt": (5.0, 24.0, 1.5),
    "m_min": (0.10, 0.50, 0.05),
    "lag_shift": (-4.0, 4.0, 1.0),      # сдвиг окна лага, сутки
}
MIN_PER_SPECIES = 15


# --------------------------------------------------------------------------- #
#  Подготовка данных
# --------------------------------------------------------------------------- #

class Sample:
    """Одно наблюдение с уже поднятой погодой."""

    __slots__ = ("entry", "days", "i")

    def __init__(self, entry, days, i):
        self.entry, self.days, self.i = entry, days, i


def build_samples(entries) -> list[Sample]:
    """Группирует записи по точке и сезону, тянет архив, находит нужный день."""
    groups = {}
    for e in entries:
        groups.setdefault((round(e.lat, 3), round(e.lon, 3), e.d.year), []).append(e)

    out, missing = [], 0
    for (lat, lon, year), es in sorted(groups.items()):
        place = engine.Place(f"{lat}, {lon}", lat, lon)
        try:
            days = backtest.fetch_season(place, year)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as ex:
            print(f"  {lat}, {lon} {year}: архив недоступен ({ex})", file=sys.stderr)
            continue
        if len(days) < 60:
            continue
        pos = {d.d: i for i, d in enumerate(days)}
        for e in es:
            i = pos.get(e.d)
            if i is None or i < 20:
                missing += 1
                continue
            out.append(Sample(e, days, i))
        print(f"  {lat}, {lon} {year}: {len(days)} суток погоды, "
              f"{sum(1 for e in es if e.d in pos)} наблюдений")
    if missing:
        print(f"  пропущено {missing} записей: дата вне доступного сезона")
    return out


# --------------------------------------------------------------------------- #
#  Целевая функция
# --------------------------------------------------------------------------- #

def _set_params(vec, names, species_keys, backup):
    """Раскладывает вектор оптимизации по константам модели."""
    k = 0
    over_g = {}
    for n in names:
        over_g[n] = vec[k]
        k += 1
    engine.apply_calibration({"global": over_g})
    for key in species_keys:
        sp = engine.SPECIES[key]
        base = backup[key]
        for field in SPECIES_BOUNDS:
            val = vec[k]
            k += 1
            if field == "lag_shift":
                sh = int(round(val))
                sp.lag_min = max(1, base["lag_min"] + sh)
                sp.lag_max = max(sp.lag_min + 2, base["lag_max"] + sh)
            else:
                setattr(sp, field, val)
        sp.m_opt = max(sp.m_min + 0.08, base["m_opt"])


def predict(samples) -> list[float]:
    """Индекс для каждого наблюдения при текущих константах."""
    cache = {}
    out = []
    saved = engine.CURRENT_BIOTOPE.key
    for s in samples:
        key = (id(s.days), s.entry.key, s.entry.biotope)
        if key not in cache:
            engine.set_biotope(s.entry.biotope)
            m = engine.water_balance(s.days)
            ts = engine.soil_temperature(s.days)
            cache[key] = engine.species_index(engine.SPECIES[s.entry.key], s.days, m, ts)
        v = cache[key][s.i]
        out.append(0.0 if v != v else v)
    engine.set_biotope(saved)
    return out


def rmse(samples) -> float:
    pred = predict(samples)
    if not pred:
        return float("inf")
    return math.sqrt(sum((p - s.entry.target) ** 2
                         for p, s in zip(pred, samples)) / len(pred))


# --------------------------------------------------------------------------- #
#  Симплекс Нелдера-Мида
# --------------------------------------------------------------------------- #

def nelder_mead(fn, x0, steps, bounds, iters=220, tol=1e-3):
    n = len(x0)
    if n == 0:
        return list(x0), fn(x0)

    def clip(x):
        return [max(lo, min(hi, v)) for v, (lo, hi) in zip(x, bounds)]

    simplex = [clip(list(x0))]
    for i in range(n):
        p = list(x0)
        p[i] += steps[i]
        simplex.append(clip(p))
    vals = [fn(p) for p in simplex]

    for _ in range(iters):
        order = sorted(range(n + 1), key=lambda k: vals[k])
        simplex = [simplex[k] for k in order]
        vals = [vals[k] for k in order]
        if abs(vals[-1] - vals[0]) < tol:
            break
        centroid = [sum(p[i] for p in simplex[:-1]) / n for i in range(n)]
        xr = clip([centroid[i] + (centroid[i] - simplex[-1][i]) for i in range(n)])
        fr = fn(xr)
        if fr < vals[0]:
            xe = clip([centroid[i] + 2 * (centroid[i] - simplex[-1][i]) for i in range(n)])
            fe = fn(xe)
            simplex[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            simplex[-1], vals[-1] = xr, fr
        else:
            xc = clip([centroid[i] + 0.5 * (simplex[-1][i] - centroid[i]) for i in range(n)])
            fc = fn(xc)
            if fc < vals[-1]:
                simplex[-1], vals[-1] = xc, fc
            else:
                for k in range(1, n + 1):
                    simplex[k] = clip([simplex[0][i] + 0.5 * (simplex[k][i] - simplex[0][i])
                                       for i in range(n)])
                    vals[k] = fn(simplex[k])
    best = min(range(n + 1), key=lambda k: vals[k])
    return simplex[best], vals[best]


# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Калибровка модели по журналу наблюдений.")
    ap.add_argument("--file", default=journal.JOURNAL)
    ap.add_argument("--species", nargs="*", default=[],
                    help="виды, для которых подбирать индивидуальные параметры")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(engine.__file__)), "calibration.json"),
        help="куда писать (по умолчанию рядом с ядром)")
    ap.add_argument("--holdout", type=float, default=0.3, help="доля контрольной выборки")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    entries = journal.read(a.file)
    if len(entries) < 20:
        print(f"Записей всего {len(entries)}. Калибровать бессмысленно: "
              f"нужно хотя бы 30, лучше 60+.", file=sys.stderr)
        return 1

    print("Поднимаю архив погоды по точкам журнала:")
    samples = build_samples(entries)
    if len(samples) < 20:
        print("Слишком мало наблюдений с погодой.", file=sys.stderr)
        return 1

    rnd = random.Random(a.seed)
    idx = list(range(len(samples)))
    rnd.shuffle(idx)
    cut = int(len(idx) * (1 - a.holdout))
    train = [samples[i] for i in idx[:cut]]
    test = [samples[i] for i in idx[cut:]]

    species_keys = []
    for k in a.species:
        key = journal.species_key(k)
        if key is None:
            print(f"Неизвестный вид: {k}", file=sys.stderr)
            return 1
        n = sum(1 for s in train if s.entry.key == key)
        if n < MIN_PER_SPECIES:
            print(f"  {engine.SPECIES[key].name}: всего {n} записей в обучающей "
                  f"выборке, индивидуальные параметры не подбираю (нужно {MIN_PER_SPECIES})")
            continue
        species_keys.append(key)

    backup = {k: {"lag_min": sp.lag_min, "lag_max": sp.lag_max, "m_opt": sp.m_opt,
                  "t_opt": sp.t_opt, "m_min": sp.m_min}
              for k, sp in engine.SPECIES.items()}
    saved_globals = {n: getattr(engine, n) for n in GLOBAL_BOUNDS}

    names = list(GLOBAL_BOUNDS)
    x0, steps, bounds = [], [], []
    for n in names:
        lo, hi, st = GLOBAL_BOUNDS[n]
        x0.append(getattr(engine, n))
        steps.append(st)
        bounds.append((lo, hi))
    for key in species_keys:
        sp = engine.SPECIES[key]
        for field, (lo, hi, st) in SPECIES_BOUNDS.items():
            x0.append(0.0 if field == "lag_shift" else getattr(sp, field))
            steps.append(st)
            bounds.append((lo, hi))

    def objective(vec):
        _set_params(vec, names, species_keys, backup)
        return rmse(train)

    base_train, base_test = rmse(train), rmse(test)
    print(f"\nНаблюдений: {len(samples)} (обучение {len(train)}, контроль {len(test)})")
    print(f"Свободных параметров: {len(x0)}")
    print(f"До подгонки:  RMSE обучение {base_train:.1f}, контроль {base_test:.1f}")

    best, val = nelder_mead(objective, x0, steps, bounds)
    _set_params(best, names, species_keys, backup)
    fit_train, fit_test = rmse(train), rmse(test)
    print(f"После:        RMSE обучение {fit_train:.1f}, контроль {fit_test:.1f}")

    result = {
        "global": {n: round(v, 4) for n, v in zip(names, best[:len(names)])},
        "species": {},
        "meta": {"date": date.today().isoformat(), "records": len(samples),
                 "rmse_train": round(fit_train, 1), "rmse_test": round(fit_test, 1),
                 "rmse_test_before": round(base_test, 1),
                 "model_version": engine.VERSION,
                 "generated": datetime.now().isoformat(timespec="seconds")},
    }
    k = len(names)
    for key in species_keys:
        sp = engine.SPECIES[key]
        result["species"][key] = {"t_opt": round(sp.t_opt, 2), "m_min": round(sp.m_min, 3),
                                  "lag_min": sp.lag_min, "lag_max": sp.lag_max}
        k += len(SPECIES_BOUNDS)

    print("\nПодобранные значения:")
    for n, v in result["global"].items():
        print(f"  {n:<14} {saved_globals[n]:>8.3f}  ->{v:>9.3f}")
    for key, over in result["species"].items():
        b = backup[key]
        print(f"  {engine.SPECIES[key].name}: t_opt {b['t_opt']:.1f} -> {over['t_opt']:.1f}, "
              f"лаг {b['lag_min']}–{b['lag_max']} -> {over['lag_min']}–{over['lag_max']}")

    gain = base_test - fit_test
    print()
    if fit_test > base_test + 0.5:
        print("Контрольная выборка стала хуже — это переобучение. "
              "Файл не пишу, наберите больше наблюдений.")
        return 3
    if gain < 1.0:
        print(f"Улучшение на контроле всего {gain:.1f} — в пределах шума. "
              f"Модель и так неплохо описывает ваши данные, либо записей мало.")
    else:
        print(f"Контрольная выборка улучшилась на {gain:.1f} — подгонка осмысленная.")

    if a.dry_run:
        print("Режим --dry-run: файл не записан.")
        return 0
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Записано: {os.path.abspath(a.out)} — ядро подхватит при следующем запуске.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
