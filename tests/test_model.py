#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Регрессионные тесты mushroom-forecast.

Запуск из каталога desktop:
    python -m unittest discover -s tests -v
    python tests/test_model.py

Сторонних библиотек не требуется. Сеть не используется: все ответы API
подменяются заглушками, погода строится синтетически.
"""

from __future__ import annotations

import math
import os
import sys
import unittest
import urllib.error
from datetime import date, datetime, timedelta

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_root, "desktop"), _root):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import mushroom_forecast as engine  # noqa: E402


# --------------------------------------------------------------------------- #
#  Вспомогательное
# --------------------------------------------------------------------------- #

def make_days(n, precip, tmean, start=date(2026, 6, 1), soil_t=None, soil_w=None):
    """Синтетический ряд: precip и tmean — функции от номера суток."""
    out = []
    for i in range(n):
        t = tmean(i)
        p = precip(i)
        out.append(engine.Day(
            start + timedelta(days=i), t + 5, t - 5, t, p,
            max(0.6, 3.4 - 0.12 * p - 0.05 * (20 - t)), None,
            None if soil_t is None else soil_t(i),
            None if soil_w is None else soil_w(i)))
    return out


def index_of(days, key, at=-1):
    m = engine.water_balance(days)
    ts = engine.soil_temperature(days)
    v = engine.species_index(engine.SPECIES[key], days, m, ts)
    return v[at]


class ResetConstants(unittest.TestCase):
    """Константы модели глобальные — восстанавливаем их после каждого теста."""

    def setUp(self):
        self._saved = {n: getattr(engine, n) for n in
                       ("GAIN", "BASE", "CAPACITY_MM", "CANOPY", "THETA_WILT", "THETA_FC")}
        self._species = {k: (sp.t_opt, sp.m_min, sp.m_opt, sp.lag_min, sp.lag_max)
                         for k, sp in engine.SPECIES.items()}
        self._get_json = engine._get_json
        self._biotope = engine.CURRENT_BIOTOPE.key

    def tearDown(self):
        for n, v in self._saved.items():
            setattr(engine, n, v)
        for k, vals in self._species.items():
            sp = engine.SPECIES[k]
            sp.t_opt, sp.m_min, sp.m_opt, sp.lag_min, sp.lag_max = vals
        engine._get_json = self._get_json
        engine.set_biotope(self._biotope)
        for n, v in self._saved.items():
            setattr(engine, n, v)
        engine.CALIBRATION = None


# --------------------------------------------------------------------------- #
#  Поведение модели на характерных сценариях
# --------------------------------------------------------------------------- #

class TestScenarios(ResetConstants):

    def test_drought_gives_zero(self):
        days = make_days(45, lambda i: 0.0, lambda i: 24.0)
        self.assertEqual(index_of(days, "белый"), 0.0,
                         "месяц без осадков должен давать ноль")

    def test_downpour_then_lag_gives_wave(self):
        days = make_days(45, lambda i: 35.0 if i == 35 else 0.0, lambda i: 18.0)
        v = index_of(days, "белый")            # ливень + 9 суток = попадание в лаг
        self.assertGreater(v, 40, "через 9 суток после ливня должен быть слой")
        self.assertLess(v, 95, "единичный ливень не должен давать максимум шкалы")

    def test_rain_too_recent(self):
        """Дождь вчера — грибы вырасти не успели."""
        days = make_days(45, lambda i: 30.0 if i == 43 else 0.0, lambda i: 18.0)
        self.assertLess(index_of(days, "белый"), 25)

    def test_heat_suppresses(self):
        """Сырость при +30 не даёт слоя: температура почвы вне окна вида."""
        days = make_days(45, lambda i: 6.0 if i % 3 == 0 else 0.0, lambda i: 29.0)
        self.assertLess(index_of(days, "белый"), 15)

    def test_steady_drizzle_moderate(self):
        """Ровная морось — умеренный фон, но не массовый слой."""
        days = make_days(45, lambda i: 3.0, lambda i: 18.0)
        v = index_of(days, "белый")
        self.assertGreater(v, 30)
        self.assertLess(v, 85)

    def test_wave_beats_drizzle(self):
        """Импульсный отклик: та же сумма осадков залпом даёт больше, чем размазанная."""
        total = 45.0
        burst = make_days(45, lambda i: total / 3 if 33 <= i <= 35 else 0.0, lambda i: 17.0)
        spread = make_days(45, lambda i: total / 45, lambda i: 17.0)
        self.assertGreater(index_of(burst, "белый"), index_of(spread, "белый"))

    def test_frost_kills_harvest(self):
        """Заморозок губит уже выросшие плодовые тела."""
        rain = lambda i: 15.0 if i in (36, 37, 38) else 0.0
        warm = make_days(45, rain, lambda i: 14.0)
        cold = make_days(45, rain, lambda i: 14.0 if i < 43 else -8.0)
        v_warm, v_cold = index_of(warm, "подберёзовик"), index_of(cold, "подберёзовик")
        self.assertGreater(v_warm, 40, "контрольный вариант без заморозка должен идти")
        self.assertLess(v_cold, v_warm * 0.4, "заморозок должен резко срезать индекс")

    def test_autumn_honey_fungus_wave(self):
        """Опёнок: волна после осеннего похолодания, пик через 2-4 недели."""
        days = make_days(60, lambda i: 8.0 if i in (20, 21, 30, 31) else
                         (2.0 if i % 4 == 0 else 0.0),
                         lambda i: 20.0 if i < 22 else 11.0, start=date(2026, 8, 20))
        m = engine.water_balance(days)
        ts = engine.soil_temperature(days)
        idx = engine.species_index(engine.SPECIES["опёнок"], days, m, ts)
        peak = max(range(30, len(idx)), key=lambda i: idx[i])
        self.assertGreater(idx[peak], 45, "волна опят должна доходить до заметных значений")
        self.assertIn(days[peak].d.month, (9, 10))
        # спад плавный: без скачков более чем вдвое между соседними днями
        for i in range(peak, len(idx) - 1):
            if idx[i] > 20:
                self.assertGreater(idx[i + 1], idx[i] * 0.45,
                                   f"разрыв в кривой около {days[i].d}")

    def test_honey_fungus_needs_cooling(self):
        """Без похолодания опёнок не идёт даже по сырой погоде."""
        wet_warm = make_days(60, lambda i: 6.0 if i % 3 == 0 else 0.0, lambda i: 19.0,
                             start=date(2026, 8, 20))
        self.assertLess(index_of(wet_warm, "опёнок"), 35)

    def test_out_of_season_is_zero(self):
        """Сезонный вес: летний вид в январе даёт ноль."""
        days = make_days(45, lambda i: 5.0, lambda i: 15.0, start=date(2026, 1, 1))
        self.assertEqual(index_of(days, "лисичка"), 0.0)


# --------------------------------------------------------------------------- #
#  Свойства расчёта
# --------------------------------------------------------------------------- #

class TestProperties(ResetConstants):

    def setUp(self):
        super().setUp()
        self.days = make_days(50, lambda i: 12.0 if i in (20, 21, 34) else 0.0,
                              lambda i: 16.0)
        self.m = engine.water_balance(self.days)
        self.ts = engine.soil_temperature(self.days)

    def test_index_within_bounds(self):
        for key, sp in engine.SPECIES.items():
            for v in engine.species_index(sp, self.days, self.m, self.ts):
                if v == v:
                    self.assertGreaterEqual(v, 0.0)
                    self.assertLessEqual(v, 100.0, f"{key} превысил шкалу")

    def test_nan_only_at_start(self):
        """Пропуски допустимы только пока не набралась история под лаг."""
        for key, sp in engine.SPECIES.items():
            idx = engine.species_index(sp, self.days, self.m, self.ts)
            for i, v in enumerate(idx):
                if v != v:
                    self.assertLess(i, sp.lag_max, f"{key}: пропуск в середине ряда")

    def test_kernel_normalised(self):
        for key, sp in engine.SPECIES.items():
            self.assertAlmostEqual(sum(engine.lag_kernel(sp)), 1.0, places=9,
                                   msg=f"ядро лага {key} не нормировано")

    def test_moisture_monotonic(self):
        """Больше осадков — не меньше индекса, при прочих равных."""
        prev = -1.0
        for mm in (0.0, 5.0, 12.0, 25.0, 40.0):
            days = make_days(45, lambda i, mm=mm: mm if i == 35 else 0.0, lambda i: 17.0)
            v = index_of(days, "белый")
            self.assertGreaterEqual(v + 1e-9, prev, f"немонотонность на {mm} мм")
            prev = v

    def test_explain_factors_bounded(self):
        for key, sp in engine.SPECIES.items():
            for name, val, why in engine.explain(sp, 40, self.days, self.m, self.ts):
                self.assertGreaterEqual(val, 0.0, f"{key}/{name}")
                self.assertLessEqual(val, 1.0, f"{key}/{name}")
                self.assertTrue(why.strip(), f"{key}/{name}: пустое пояснение")

    def test_limiting_factor_matches_weakest(self):
        """Диагностика должна указывать на слабейший сомножитель, а не на случайный."""
        dry = make_days(45, lambda i: 0.0, lambda i: 17.0)
        m, ts = engine.water_balance(dry), engine.soil_temperature(dry)
        txt = engine.limiting_factor(engine.SPECIES["белый"], 44, dry, m, ts)
        self.assertIn("влаг", txt.lower())

    def test_plain_summary_mentions_species(self):
        txt = engine.plain_summary(engine.SPECIES["белый"], 40, self.days,
                                   self.m, self.ts, 70.0)
        self.assertIn("Белый гриб", txt)
        self.assertGreater(len(txt), 40)

    def test_level_thresholds_ordered(self):
        vals = [engine.level(v) for v in (0, 10, 20, 40, 55, 75, 95)]
        self.assertEqual(len(set(vals)), 7, "уровни шкалы должны различаться")


# --------------------------------------------------------------------------- #
#  Данные почвы и резервные формулы
# --------------------------------------------------------------------------- #

class TestSoilData(ResetConstants):

    def test_model_soil_preferred(self):
        """При наличии полей почвы берутся они, а не приближения."""
        days = make_days(30, lambda i: 0.0, lambda i: 25.0,
                         soil_t=lambda i: 12.0, soil_w=lambda i: 0.23)
        self.assertEqual(engine.soil_temperature(days)[0], 12.0)
        expected = (0.23 - engine.THETA_WILT) / (engine.THETA_FC - engine.THETA_WILT)
        self.assertAlmostEqual(engine.water_balance(days)[0], expected, places=6)
        self.assertIn("модель почвы", engine.sources(days)[0])

    def test_fallback_without_soil(self):
        days = make_days(30, lambda i: 4.0, lambda i: 18.0)
        self.assertIn("оценка", engine.sources(days)[0])
        self.assertIn("оценка", engine.sources(days)[1])
        self.assertTrue(all(0.0 <= v <= 1.0 for v in engine.water_balance(days)))

    def test_gaps_interpolated(self):
        """Единичные пропуски заполняются, ряд остаётся из модели."""
        days = make_days(30, lambda i: 0.0, lambda i: 20.0,
                         soil_t=lambda i: None if i == 10 else 10.0 + i * 0.1,
                         soil_w=lambda i: 0.25)
        ts = engine.soil_temperature(days)
        self.assertAlmostEqual(ts[10], 11.0, places=6)
        self.assertIn("модель почвы", engine.sources(days)[1])

    def test_too_many_gaps_falls_back(self):
        days = make_days(30, lambda i: 3.0, lambda i: 18.0,
                         soil_t=lambda i: 10.0 if i % 4 == 0 else None,
                         soil_w=lambda i: None)
        self.assertIn("оценка", engine.sources(days)[1])

    def test_soil_candidates_probed_in_order(self):
        """Неподдержанный набор слоёв не должен ронять загрузку целиком."""
        calls = []
        n = engine.PAST_DAYS + 5
        times = [(date(2026, 7, 1) + timedelta(days=i)).isoformat() for i in range(n)]

        def fake(url, params):
            calls.append(params.get("hourly"))
            if params.get("hourly") and len(calls) < 3:
                raise urllib.error.HTTPError(url, 400, "unsupported", None, None)
            body = {"daily": {"time": times,
                              "temperature_2m_max": [20.0] * n,
                              "temperature_2m_min": [10.0] * n,
                              "temperature_2m_mean": [15.0] * n,
                              "precipitation_sum": [1.0] * n,
                              "et0_fao_evapotranspiration": [3.0] * n}}
            if params.get("hourly"):
                keys = params["hourly"].split(",")
                h = {"time": [], keys[0]: [], keys[1]: []}
                for t in times:
                    for hh in range(24):
                        h["time"].append(f"{t}T{hh:02d}:00")
                        h[keys[0]].append(14.0)
                        h[keys[1]].append(0.25)
                body["hourly"] = h
            return body

        engine._get_json = fake
        days = engine.fetch_weather(engine.Place("t", 56.0, 38.0), 5)
        self.assertEqual(len(calls), 3, "должен был перебрать наборы слоёв")
        self.assertEqual(len(days), n)
        self.assertIsNotNone(days[0].soil_t)


# --------------------------------------------------------------------------- #
#  Весенние виды
# --------------------------------------------------------------------------- #

class TestSpring(ResetConstants):

    def _spring(self, dry=False, melt_day=24, n=90):
        """Весна: снег сходит на melt_day сутки, дальше прогрев."""
        start = date(2026, 3, 1)
        days = []
        for i in range(n):
            t = -4.0 + 0.28 * i
            snow = max(0.0, 0.35 - 0.35 * i / melt_day)
            sw = 0.13 if dry else 0.32
            days.append(engine.Day(start + timedelta(days=i), t + 5, t - 5, t,
                                   0.0 if dry else (3.0 if i % 4 == 0 else 0.0),
                                   max(0.4, 2.0 + 0.05 * t), None,
                                   max(-1.0, t - 2), sw, snow))
        return days

    def _peak(self, days, key):
        m, ts = engine.water_balance(days), engine.soil_temperature(days)
        idx = engine.species_index(engine.SPECIES[key], days, m, ts)
        i = max(range(len(idx)), key=lambda k: idx[k] if idx[k] == idx[k] else -1)
        return days[i].d, idx[i]

    def test_snowmelt_detected_from_depth(self):
        days = self._spring(melt_day=24)
        ts = engine.soil_temperature(days)
        gdd, melt = engine.snowmelt_gdd(days, ts)
        self.assertIsNotNone(melt)
        self.assertEqual(melt.month, 3)
        self.assertTrue(23 <= melt.day <= 26, f"сход снега определён как {melt}")

    def test_snowmelt_fallback_without_snow_data(self):
        """Нет данных о снеге — дата берётся по переходу температуры почвы через нуль."""
        days = [engine.Day(d.d, d.tmax, d.tmin, d.tmean, d.precip, d.et0,
                           None, d.soil_t, d.soil_w, None)
                for d in self._spring()]
        ts = engine.soil_temperature(days)
        gdd, melt = engine.snowmelt_gdd(days, ts)
        self.assertIsNotNone(melt)
        self.assertEqual(melt.year, 2026)

    def test_gdd_non_decreasing(self):
        days = self._spring()
        ts = engine.soil_temperature(days)
        gdd, _ = engine.snowmelt_gdd(days, ts)
        for a, b in zip(gdd, gdd[1:]):
            self.assertLessEqual(a, b + 1e-9, "накопленное тепло не может убывать")

    def test_gyromitra_before_morchella(self):
        """Строчок идёт раньше сморчка — на меньшем накопленном тепле."""
        days = self._spring()
        d_gyro, v_gyro = self._peak(days, "строчок")
        d_morch, v_morch = self._peak(days, "сморчок")
        self.assertLess(d_gyro, d_morch, "строчок должен опережать сморчка")
        self.assertGreater(v_gyro, 45)
        self.assertGreater(v_morch, 45)

    def test_dry_spring_gives_nothing(self):
        days = self._spring(dry=True)
        for key in ("строчок", "сморчок"):
            self.assertLess(self._peak(days, key)[1], 10, key)

    def test_spring_species_before_summer_start(self):
        """В апреле летние виды молчат, весенние работают."""
        days = self._spring()
        m, ts = engine.water_balance(days), engine.soil_temperature(days)
        i = next(k for k, d in enumerate(days) if d.d == date(2026, 4, 30))
        self.assertGreater(engine.species_index(engine.SPECIES["строчок"],
                                                days, m, ts)[i], 40)
        self.assertEqual(engine.species_index(engine.SPECIES["белый"],
                                              days, m, ts)[i], 0.0)

    def test_spring_factor_in_explain(self):
        days = self._spring()
        m, ts = engine.water_balance(days), engine.soil_temperature(days)
        i = next(k for k, d in enumerate(days) if d.d == date(2026, 5, 5))
        names = [n for n, v, w in engine.explain(engine.SPECIES["сморчок"],
                                                 i, days, m, ts)]
        self.assertTrue(any("снег" in n.lower() for n in names))

    def test_summer_species_unaffected(self):
        """Весенний блок не должен влиять на летние виды."""
        days = make_days(45, lambda i: 14.0 if i in (35, 36) else 0.0, lambda i: 16.0)
        m, ts = engine.water_balance(days), engine.soil_temperature(days)
        for key in ("белый", "подберёзовик", "опёнок"):
            self.assertFalse(engine.SPECIES[key].spring)
            v = engine.species_index(engine.SPECIES[key], days, m, ts)[-1]
            self.assertEqual(v, v)          # не nan


# --------------------------------------------------------------------------- #
#  Тип леса
# --------------------------------------------------------------------------- #

class TestBiotopes(ResetConstants):

    def test_set_biotope_changes_constants(self):
        engine.set_biotope("сосняк")
        self.assertLess(engine.THETA_FC, 0.30, "песок держит меньше воды")
        self.assertLess(engine.CAPACITY_MM, 45)
        engine.set_biotope("низина")
        self.assertGreater(engine.THETA_FC, 0.40)

    def test_unknown_biotope_raises(self):
        with self.assertRaises(LookupError):
            engine.set_biotope("тундра")

    def test_species_ordering_by_biotope(self):
        """Каждый вид должен быть сильнее всего в своём типе леса."""
        days = make_days(45, lambda i: 5.0, lambda i: 16.0)
        best = {}
        for key in ("сосняк", "березняк", "ельник", "низина", "смешанный"):
            engine.set_biotope(key)
            for sp_key in ("маслёнок", "подберёзовик", "груздь"):
                v = index_of(days, sp_key)
                if v > best.get(sp_key, (-1, ""))[0]:
                    best[sp_key] = (v, key)
        self.assertEqual(best["маслёнок"][1], "сосняк")
        self.assertEqual(best["подберёзовик"][1], "березняк")
        self.assertEqual(best["груздь"][1], "низина")

    def test_soil_temperature_offset(self):
        """В ельнике почва холоднее, в сосняке теплее."""
        days = make_days(30, lambda i: 2.0, lambda i: 15.0)
        engine.set_biotope("смешанный")
        base = engine.soil_temperature(days)[-1]
        engine.set_biotope("ельник")
        self.assertLess(engine.soil_temperature(days)[-1], base)
        engine.set_biotope("сосняк")
        self.assertGreater(engine.soil_temperature(days)[-1], base)

    def test_weight_appears_in_explain(self):
        days = make_days(45, lambda i: 5.0, lambda i: 16.0)
        m, ts = engine.water_balance(days), engine.soil_temperature(days)
        engine.set_biotope("сосняк")
        names = [n for n, v, w in engine.explain(engine.SPECIES["подберёзовик"],
                                                 44, days, m, ts)]
        self.assertTrue(any("сосняк" in n.lower() for n in names))

    def test_all_biotopes_have_valid_profiles(self):
        for key, b in engine.BIOTOPES.items():
            self.assertEqual(key, b.key)
            self.assertLess(b.theta_wilt, b.theta_fc, f"{key}: θ завядания ≥ ПВ")
            self.assertGreater(b.capacity, 10)
            self.assertTrue(0.3 <= b.canopy <= 1.0, f"{key}: затенение вне диапазона")
            for sp_key, w in b.weight.items():
                self.assertIn(sp_key, engine.SPECIES, f"{key}: неизвестный вид {sp_key}")
                self.assertTrue(0.1 <= w <= 2.0, f"{key}/{sp_key}: множитель {w}")


# --------------------------------------------------------------------------- #
#  Геокодирование
# --------------------------------------------------------------------------- #

class TestGeocode(ResetConstants):

    def test_translit(self):
        self.assertEqual(engine.translit("Душоново"), "Dushonovo")
        self.assertEqual(engine.translit("Щёлково"), "Shchelkovo")
        self.assertEqual(engine.translit("Фрязино"), "Fryazino")

    def test_variants_tried(self):
        seen = []

        def fake(url, params):
            seen.append(params["name"])
            if params["name"] == "Dushonovo":
                return {"results": [{"name": "Dushonovo", "admin1": "MO",
                                     "country": "RU", "latitude": 56.05,
                                     "longitude": 38.31}]}
            return {"results": []}

        engine._get_json = fake
        place = engine.geocode("село Душоново")
        self.assertEqual(seen, ["село Душоново", "Душоново", "Dushonovo"])
        self.assertAlmostEqual(place.lat, 56.05)

    def test_not_found_raises_lookup_error(self):
        """Не SystemExit: он не ловится через except Exception и вешает поток."""
        engine._get_json = lambda url, params: {"results": []}
        with self.assertRaises(LookupError):
            engine.geocode("Абракадабра")


# --------------------------------------------------------------------------- #
#  Калибровка и журнал
# --------------------------------------------------------------------------- #

class TestCalibration(ResetConstants):

    def test_apply_changes_constants(self):
        engine.apply_calibration({"global": {"GAIN": 0.9, "BASE": 0.2},
                                  "species": {"белый": {"t_opt": 18.0}},
                                  "meta": {"date": "2026-08-14", "records": 50,
                                           "rmse_test": 12.0}})
        self.assertAlmostEqual(engine.GAIN, 0.9)
        self.assertAlmostEqual(engine.SPECIES["белый"].t_opt, 18.0)
        self.assertIn("50", engine.calibration_info())

    def test_gain_scales_index(self):
        days = make_days(45, lambda i: 20.0 if i == 35 else 0.0, lambda i: 17.0)
        engine.apply_calibration({"global": {"GAIN": 0.6}})
        low = index_of(days, "белый")
        engine.apply_calibration({"global": {"GAIN": 1.6}})
        high = index_of(days, "белый")
        self.assertGreater(high, low)

    def test_nelder_mead_finds_minimum(self):
        import calibrate
        fn = lambda v: (v[0] - 3.0) ** 2 + (v[1] + 1.5) ** 2 + 1.0
        best, val = calibrate.nelder_mead(fn, [0.0, 0.0], [1.0, 1.0],
                                          [(-10, 10), (-10, 10)])
        self.assertAlmostEqual(best[0], 3.0, places=1)
        self.assertAlmostEqual(best[1], -1.5, places=1)
        self.assertAlmostEqual(val, 1.0, places=2)

    def test_journal_roundtrip(self):
        import journal
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "j.csv")
            journal.write_header(path, example=False)
            journal.append(path, journal.Entry(date(2026, 8, 14), "Бор", 55.96, 38.05,
                                               "белый", 3, "у просеки", "березняк"))
            journal.append(path, journal.Entry(date(2026, 8, 15), "Бор", 55.96, 38.05,
                                               "опёнок", 0, ""))
            rows = journal.read(path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].key, "белый")
        self.assertEqual(rows[0].biotope, "березняк")
        self.assertEqual(rows[1].biotope, "смешанный")
        self.assertEqual(rows[1].score, 0)
        self.assertAlmostEqual(rows[0].target, journal.SCORE_TO_INDEX[3])

    def test_journal_species_aliases(self):
        import journal
        self.assertEqual(journal.species_key("Белый гриб"), "белый")
        self.assertEqual(journal.species_key("ОПЁНОК"), "опёнок")
        self.assertIsNone(journal.species_key("мухомор"))

    def test_journal_rejects_bad_rows(self):
        import contextlib
        import io
        import journal
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "j.csv")
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write("дата;место;широта;долгота;биотоп;вид;обилие;заметка\n")
                f.write("2026-08-14;Бор;55.96;38.05;березняк;белый;9;большая оценка\n")
                f.write("не-дата;Бор;55.96;38.05;березняк;белый;3;\n")
                f.write("2026-08-16;Бор;55.96;38.05;березняк;белый;2;норм\n")
            with contextlib.redirect_stderr(io.StringIO()):
                rows = journal.read(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].score, 2)


# --------------------------------------------------------------------------- #
#  Ансамбль
# --------------------------------------------------------------------------- #

class TestEnsemble(ResetConstants):

    N_MEMBERS, PAST, FUT = 12, 20, 12

    def _fake_api(self, seed=1):
        import random as rnd_mod
        start = date.today() - timedelta(days=self.PAST)
        n = self.PAST + self.FUT

        def fake(url, params):
            h = {"time": []}
            for i in range(n):
                d = start + timedelta(days=i)
                for hh in range(24):
                    h["time"].append(f"{d.isoformat()}T{hh:02d}:00")
            for mem in range(self.N_MEMBERS):
                r = rnd_mod.Random(seed * 100 + mem)
                wet = r.random() < 0.5
                tt, pp = [], []
                for i in range(n):
                    future = (start + timedelta(days=i)) >= date.today()
                    for _ in range(24):
                        tt.append(16.0 + (r.uniform(-3, 3) if future else 0.0))
                        pp.append(r.uniform(0.3, 1.2)
                                  if (wet and future and i % 3 == 0) else 0.0)
                h[f"temperature_2m_member{mem:02d}"] = tt
                h[f"precipitation_member{mem:02d}"] = pp
            return {"hourly": h}
        return fake, start

    def _base(self, start):
        return make_days(self.PAST + self.FUT,
                         lambda i: 14.0 if i in (12, 13) else 0.0,
                         lambda i: 16.0, start=start)

    def test_members_parsed(self):
        import ensemble
        fake, _ = self._fake_api()
        engine._get_json = fake
        members = ensemble.fetch_members(engine.Place("t", 56.0, 38.0),
                                         self.FUT, self.PAST)
        self.assertEqual(len(members), self.N_MEMBERS)
        for m in members:
            self.assertGreaterEqual(len(m), self.PAST)
            for tmean, precip in m.values():
                self.assertTrue(-60 < tmean < 60)
                self.assertGreaterEqual(precip, 0.0)

    def test_model_fallback_on_error(self):
        """Первая модель ансамбля не отдала — пробуем следующую."""
        import ensemble
        fake, _ = self._fake_api()
        calls = []

        def flaky(url, params):
            calls.append(params.get("models"))
            if len(calls) == 1:
                raise urllib.error.HTTPError(url, 400, "no model", None, None)
            return fake(url, params)

        engine._get_json = flaky
        members = ensemble.fetch_members(engine.Place("t", 56.0, 38.0),
                                         self.FUT, self.PAST)
        self.assertEqual(len(calls), 2)
        self.assertTrue(members)

    def test_no_data_returns_empty(self):
        import ensemble
        engine._get_json = lambda url, params: {}
        self.assertEqual(ensemble.fetch_members(engine.Place("t", 56.0, 38.0), 7), [])
        self.assertEqual(ensemble.band([], [], engine.SPECIES["белый"]), {})

    def test_quantiles_ordered_and_bounded(self):
        import ensemble
        fake, start = self._fake_api()
        engine._get_json = fake
        members = ensemble.fetch_members(engine.Place("t", 56.0, 38.0),
                                         self.FUT, self.PAST)
        bnd = ensemble.band(self._base(start), members, engine.SPECIES["белый"])
        self.assertTrue(bnd)
        for d, (lo, mid, hi) in bnd.items():
            self.assertLessEqual(lo, mid + 1e-9, f"P10 > P50 на {d}")
            self.assertLessEqual(mid, hi + 1e-9, f"P50 > P90 на {d}")
            self.assertGreaterEqual(lo, 0.0)
            self.assertLessEqual(hi, 100.0)

    def test_spread_grows_with_horizon(self):
        """Ближние дни определены прошлым дождём, дальние — разбегаются."""
        import ensemble
        fake, start = self._fake_api()
        engine._get_json = fake
        members = ensemble.fetch_members(engine.Place("t", 56.0, 38.0),
                                         self.FUT, self.PAST)
        base = self._base(start)
        bnd = ensemble.band(base, members, engine.SPECIES["белый"])
        ti = next(i for i, d in enumerate(base) if d.d >= date.today())
        near = [bnd[base[i].d][2] - bnd[base[i].d][0]
                for i in range(ti, ti + 3) if base[i].d in bnd]
        far = [bnd[base[i].d][2] - bnd[base[i].d][0]
               for i in range(len(base) - 3, len(base)) if base[i].d in bnd]
        self.assertLessEqual(sum(near) / len(near), sum(far) / len(far) + 1e-9)

    def test_history_identical_across_members(self):
        """Прошлое у всех сценариев общее: разброса до сегодня быть не должно."""
        import ensemble
        fake, start = self._fake_api()
        engine._get_json = fake
        members = ensemble.fetch_members(engine.Place("t", 56.0, 38.0),
                                         self.FUT, self.PAST)
        base = self._base(start)
        bnd = ensemble.band(base, members, engine.SPECIES["белый"])
        for d, (lo, mid, hi) in bnd.items():
            if d < date.today():
                self.assertLess(hi - lo, 1e-6, f"разброс в прошлом на {d}")

    def test_quantile_helper(self):
        import ensemble
        self.assertAlmostEqual(ensemble._quantile([1.0, 2.0, 3.0], 0.5), 2.0)
        self.assertAlmostEqual(ensemble._quantile([1.0, 2.0, 3.0, 4.0], 0.0), 1.0)
        self.assertAlmostEqual(ensemble._quantile([1.0, 2.0, 3.0, 4.0], 1.0), 4.0)
        self.assertAlmostEqual(ensemble._quantile([5.0], 0.9), 5.0)
        self.assertTrue(math.isnan(ensemble._quantile([], 0.5)))

    def test_texts_generated(self):
        import ensemble
        d = date.today()
        self.assertIn("сходятся", ensemble.spread_text({d: (50.0, 52.0, 56.0)}, d))
        self.assertIn("умеренный", ensemble.spread_text({d: (30.0, 45.0, 55.0)}, d))
        self.assertIn("расходятся", ensemble.spread_text({d: (10.0, 40.0, 80.0)}, d))
        self.assertEqual(ensemble.spread_text({}, d), "")

    def test_reliability_horizon(self):
        import ensemble
        days = make_days(10, lambda i: 0.0, lambda i: 16.0, start=date.today())
        tight = {d.d: (40.0, 45.0, 50.0) for d in days}
        self.assertIn("на всём горизонте", ensemble.reliability(tight, days, 0))
        wide = dict(tight)
        wide[days[4].d] = (5.0, 40.0, 90.0)
        self.assertIn("4 суток", ensemble.reliability(wide, days, 0))


# --------------------------------------------------------------------------- #
#  Места и офлайн-кэш
# --------------------------------------------------------------------------- #

class TestPlaces(ResetConstants):

    def setUp(self):
        super().setUp()
        import tempfile
        import places
        self._tmp = tempfile.TemporaryDirectory()
        places.set_data_dir(self._tmp.name)
        self.places = places

    def tearDown(self):
        super().tearDown()
        import places
        places._DATA_DIR = None
        self._tmp.cleanup()

    def test_save_and_load(self):
        P = self.places
        P.add(P.Spot("Дальний бор", 55.9606, 38.0456, "сосняк"))
        P.add(P.Spot("Низина", 55.90, 38.00, "низина", "за мостом"))
        spots = P.load()
        self.assertEqual([s.name for s in spots], ["Дальний бор", "Низина"])
        self.assertEqual(spots[0].biotope, "сосняк")
        self.assertEqual(spots[1].note, "за мостом")

    def test_same_name_updates(self):
        P = self.places
        P.add(P.Spot("Бор", 55.9, 38.0, "сосняк"))
        P.add(P.Spot("Бор", 55.9, 38.0, "ельник"))
        self.assertEqual(len(P.load()), 1)
        self.assertEqual(P.load()[0].biotope, "ельник")

    def test_same_point_updates(self):
        P = self.places
        P.add(P.Spot("Бор", 55.90000, 38.00000))
        P.add(P.Spot("Тот же бор", 55.90005, 38.00005))
        self.assertEqual(len(P.load()), 1)

    def test_remove(self):
        P = self.places
        P.add(P.Spot("Бор", 55.9, 38.0))
        P.add(P.Spot("Низина", 55.8, 38.1))
        P.remove("бор")
        self.assertEqual([s.name for s in P.load()], ["Низина"])

    def test_bad_file_does_not_crash(self):
        P = self.places
        with open(os.path.join(self._tmp.name, P.PLACES_FILE), "w", encoding="utf-8") as f:
            f.write("{это не json")
        self.assertEqual(P.load(), [])

    def test_cache_roundtrip(self):
        P = self.places
        spot = P.Spot("Бор", 55.9, 38.0, "сосняк")
        days = make_days(30, lambda i: 4.0, lambda i: 15.0,
                         soil_t=lambda i: 12.0, soil_w=lambda i: 0.25)
        P.cache_forecast(spot, days)
        got = P.cached_forecast(spot)
        self.assertIsNotNone(got)
        back, stamp = got
        self.assertEqual(len(back), len(days))
        self.assertEqual(back[7].d, days[7].d)
        self.assertAlmostEqual(back[7].precip, days[7].precip)
        self.assertAlmostEqual(back[7].soil_w, 0.25)
        self.assertLess((datetime.now() - stamp).total_seconds(), 60)

    def test_stale_cache_rejected(self):
        P = self.places
        spot = P.Spot("Бор", 55.9, 38.0)
        P.cache_forecast(spot, make_days(10, lambda i: 0.0, lambda i: 15.0))
        self.assertIsNone(P.cached_forecast(spot, max_hours=0))

    def test_forecast_falls_back_to_cache(self):
        """Нет сети — берём кэш, а не падаем."""
        P = self.places
        spot = P.Spot("Бор", 55.9, 38.0, "сосняк")
        days = make_days(40, lambda i: 6.0 if i % 5 == 0 else 0.0, lambda i: 16.0,
                         start=date.today() - timedelta(days=34))
        P.cache_forecast(spot, days)
        engine._get_json = lambda url, params: (_ for _ in ()).throw(OSError("нет сети"))
        f = P.forecast_spot(spot, 7)
        self.assertEqual(f.error, "")
        self.assertIsNotNone(f.stale)
        self.assertTrue(f.idx)

    def test_forecast_reports_error_without_cache(self):
        P = self.places
        engine._get_json = lambda url, params: (_ for _ in ()).throw(OSError("нет сети"))
        f = P.forecast_spot(P.Spot("Пустое", 10.0, 10.0), 7)
        self.assertIn("нет сети", f.error)
        self.assertFalse(f.days)

    def test_biotope_restored_after_forecast(self):
        """Расчёт по месту не должен менять текущий профиль глобально."""
        P = self.places
        engine.set_biotope("ельник")
        engine._get_json = lambda url, params: (_ for _ in ()).throw(OSError("нет сети"))
        P.forecast_spot(P.Spot("Бор", 55.9, 38.0, "сосняк"), 7)
        self.assertEqual(engine.CURRENT_BIOTOPE.key, "ельник")

    def test_recommend_text(self):
        P = self.places
        spot = P.Spot("Бор", 55.9, 38.0, "березняк")
        days = make_days(40, lambda i: 14.0 if i in (28, 29) else 0.0, lambda i: 16.0,
                         start=date.today() - timedelta(days=34))
        P.cache_forecast(spot, days)
        engine._get_json = lambda url, params: (_ for _ in ()).throw(OSError("x"))
        txt = P.recommend([P.forecast_spot(spot, 7)])
        self.assertTrue(txt)
        self.assertIn("Бор", txt + "нет данных")


# --------------------------------------------------------------------------- #
#  Поход: трек, находки, расстояние
# --------------------------------------------------------------------------- #

class TestTrack(ResetConstants):

    def setUp(self):
        super().setUp()
        import tempfile
        sys.path.insert(0, os.path.join(_root, "android"))
        import places
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MUSHROOM_DATA_DIR"] = self._tmp.name
        places._DATA_DIR = None
        places.data_dir()
        import track
        self.T = track

    def tearDown(self):
        super().tearDown()
        import places
        os.environ.pop("MUSHROOM_DATA_DIR", None)
        places._DATA_DIR = None
        self._tmp.cleanup()

    def _straight_walk(self, n=50, step_m=10.0, t0=1000000.0):
        """Прямой отрезок с дрожанием приёмника."""
        w = self.T.Walk(place="Бор", biotope="сосняк")
        lat, lon, t = 55.9606, 38.0456, t0
        d = step_m / 111320.0
        for i in range(n):
            t += 20
            lat += d
            w.add_point(lat + (2e-6 if i % 2 else -2e-6), lon, acc=8.0, t=t)
        return w, lat, lon, t

    def test_haversine_known_distance(self):
        """Один градус широты — примерно 111 км."""
        d = self.T.haversine(55.0, 38.0, 56.0, 38.0)
        self.assertAlmostEqual(d, 111195, delta=300)
        self.assertAlmostEqual(self.T.haversine(55.0, 38.0, 55.0, 38.0), 0.0, places=6)

    def test_straight_distance(self):
        w, *_ = self._straight_walk(n=50, step_m=10.0)
        self.assertAlmostEqual(w.distance, 490, delta=25)

    def test_jitter_adds_nothing(self):
        """Стояние на месте не должно накручивать метры."""
        w, lat, lon, t = self._straight_walk()
        before = w.distance
        for i in range(60):
            t += 20
            w.add_point(lat + (1e-5 if i % 2 else -1e-5), lon, acc=8.0, t=t)
        self.assertEqual(w.distance, before)

    def test_speed_outlier_rejected_after_pause(self):
        """Выброс приёмника после долгой стоянки — тоже выброс."""
        w, lat, lon, t = self._straight_walk()
        for i in range(60):
            t += 20
            w.add_point(lat + (1e-5 if i % 2 else -1e-5), lon, acc=8.0, t=t)
        before, skipped = w.distance, w.skipped
        self.assertFalse(w.add_point(lat + 0.01, lon, acc=8.0, t=t + 20))
        self.assertEqual(w.distance, before)
        self.assertEqual(w.skipped, skipped + 1)

    def test_bad_accuracy_rejected(self):
        w = self.T.Walk()
        self.assertTrue(w.add_point(55.0, 38.0, acc=10.0, t=1000.0))
        self.assertFalse(w.add_point(55.001, 38.0, acc=120.0, t=1020.0))
        self.assertEqual(len(w.points), 1)

    def test_duration_from_points(self):
        w, *_ = self._straight_walk(n=10)
        self.assertAlmostEqual(w.duration, 9 * 20, delta=1)

    def test_finds_and_undo(self):
        w = self.T.Walk()
        w.add_point(55.0, 38.0, t=1000.0)
        w.add_find(55.0, 38.0, "белый", 3)
        w.add_find(55.0, 38.0, "белый", 2)
        w.add_find(55.0, 38.0, "подберёзовик", 7)
        self.assertEqual(w.species_counts(), {"белый": 5, "подберёзовик": 7})
        w.undo_find()
        self.assertEqual(w.species_counts(), {"белый": 5})
        self.assertEqual(len(w.finds), 2)

    def test_save_load_roundtrip(self):
        w, lat, lon, t = self._straight_walk(n=20)
        w.add_find(lat, lon, "белый", 2, "у пня")
        w.stop()
        self.T.save(w)
        back = self.T.load_all()
        self.assertEqual(len(back), 1)
        self.assertEqual(len(back[0].points), len(w.points))
        self.assertAlmostEqual(back[0].distance, w.distance, places=1)
        self.assertEqual(back[0].finds[0].species, "белый")
        self.assertEqual(back[0].finds[0].note, "у пня")
        self.assertEqual(back[0].biotope, "сосняк")

    def test_gpx_structure(self):
        w, lat, lon, t = self._straight_walk(n=12)
        w.add_find(lat, lon, "лисичка")
        gpx = self.T.to_gpx(w)
        self.assertTrue(gpx.startswith("<?xml"))
        self.assertEqual(gpx.count("<trkpt"), len(w.points))
        self.assertEqual(gpx.count("<wpt"), 1)
        self.assertIn("</gpx>", gpx)

    def test_count_to_score(self):
        pairs = [(0, 0), (1, 1), (3, 1), (4, 2), (8, 2), (9, 3), (20, 3),
                 (21, 4), (50, 4), (200, 5)]
        for n, expected in pairs:
            self.assertEqual(self.T.count_to_score(n), expected, f"{n} штук")

    def test_to_journal(self):
        """Находки похода должны ложиться в журнал — он питает калибровку."""
        import journal
        w, lat, lon, t = self._straight_walk(n=15)
        w.place = "Дальний бор"
        for _ in range(5):
            w.add_find(lat, lon, "белый")
        w.add_find(lat, lon, "лисичка")
        path = os.path.join(self._tmp.name, "j.csv")
        journal.write_header(path, example=False)
        n = self.T.to_journal(w, journal, path=path, extra_zero=("опёнок",))
        self.assertEqual(n, 3)
        rows = journal.read(path)
        by_key = {r.key: r for r in rows}
        self.assertEqual(by_key["белый"].score, 2)          # 5 штук -> «мало»
        self.assertEqual(by_key["лисичка"].score, 1)
        self.assertEqual(by_key["опёнок"].score, 0)         # искали, не нашли
        self.assertEqual(by_key["белый"].biotope, "сосняк")
        self.assertEqual(by_key["белый"].place, "Дальний бор")

    def test_empty_walk_writes_nothing(self):
        import journal
        w = self.T.Walk()
        path = os.path.join(self._tmp.name, "j2.csv")
        journal.write_header(path, example=False)
        self.assertEqual(self.T.to_journal(w, journal, path=path), 0)


# --------------------------------------------------------------------------- #
#  Фоновая запись маршрута
# --------------------------------------------------------------------------- #

class TestTrackLog(ResetConstants):

    def setUp(self):
        super().setUp()
        import tempfile
        sys.path.insert(0, os.path.join(_root, "android"))
        import places
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MUSHROOM_DATA_DIR"] = self._tmp.name
        places._DATA_DIR = None
        places.data_dir()
        import tracklog
        self.L = tracklog

    def tearDown(self):
        super().tearDown()
        import places
        os.environ.pop("MUSHROOM_DATA_DIR", None)
        places._DATA_DIR = None
        self._tmp.cleanup()

    def test_append_and_read(self):
        for i in range(5):
            self.L.append_point(55.0 + i * 1e-4, 38.0, 7.0, 1000.0 + i * 20)
        pts = self.L.LiveReader().read_new()
        self.assertEqual(len(pts), 5)
        self.assertAlmostEqual(pts[0][0], 55.0)
        self.assertAlmostEqual(pts[4][3], 1080.0)

    def test_incremental_reading(self):
        """Приложение просыпается редко и не должно терять или дублировать точки."""
        reader = self.L.LiveReader()
        seen = 0
        for batch in range(4):
            for i in range(3):
                self.L.append_point(55.0 + batch * 1e-3 + i * 1e-4, 38.0, 7.0,
                                    1000.0 + batch * 100 + i)
            new = reader.read_new()
            self.assertEqual(len(new), 3, f"партия {batch}")
            seen += len(new)
        self.assertEqual(seen, 12)
        self.assertEqual(reader.read_new(), [])

    def test_partial_line_ignored(self):
        """Строку, которую сервис ещё дописывает, читать нельзя."""
        self.L.append_point(55.0, 38.0, 7.0, 1000.0)
        path = os.path.join(self._tmp.name, self.L.LIVE_FILE)
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"lat":55.1,"lon":38.0')
        reader = self.L.LiveReader()
        self.assertEqual(len(reader.read_new()), 1)
        # дописали строку — теперь она читается
        with open(path, "a", encoding="utf-8") as f:
            f.write(',"t":1020.0,"acc":7.0}\n')
        self.assertEqual(len(reader.read_new()), 1)

    def test_broken_line_skipped(self):
        self.L.append_point(55.0, 38.0, 7.0, 1000.0)
        path = os.path.join(self._tmp.name, self.L.LIVE_FILE)
        with open(path, "a", encoding="utf-8") as f:
            f.write("совсем не json\n")
        self.L.append_point(55.1, 38.0, 7.0, 1040.0)
        self.assertEqual(len(self.L.LiveReader().read_new()), 2)

    def test_file_restart_resets_offset(self):
        for i in range(5):
            self.L.append_point(55.0, 38.0, 7.0, 1000.0 + i)
        reader = self.L.LiveReader()
        reader.read_new()
        self.L.clear_live()
        self.L.append_point(56.0, 39.0, 7.0, 2000.0)
        pts = reader.read_new()
        self.assertEqual(len(pts), 1)
        self.assertAlmostEqual(pts[0][0], 56.0)

    def test_status_and_alive(self):
        self.assertFalse(self.L.service_alive())
        self.L.set_status(running=True, points=3, source="сервис")
        self.assertTrue(self.L.service_alive())
        self.assertEqual(self.L.get_status()["points"], 3)
        self.L.set_status(running=False)
        self.assertFalse(self.L.service_alive())

    def test_stale_status_not_alive(self):
        """Сервис молчит дольше положенного — считаем, что его нет."""
        self.L.set_status(running=True)
        self.assertFalse(self.L.service_alive(max_silence=0.0))

    def test_unfinished_walk_detected(self):
        self.assertFalse(self.L.has_unfinished())
        for i in range(6):
            self.L.append_point(55.0 + i * 1e-4, 38.0, 7.0, 1000.0 + i)
        self.assertTrue(self.L.has_unfinished())
        self.L.clear_live()
        self.assertFalse(self.L.has_unfinished())

    def test_stream_feeds_walk(self):
        """Сквозная проверка: поток сервиса даёт то же расстояние, что и прямой ввод."""
        import track
        lat, lon, t = 55.9606, 38.0456, 1000.0
        step = 10.0 / 111320.0
        direct = track.Walk()
        for i in range(40):
            t += 20
            lat += step
            self.L.append_point(lat, lon, 7.0, t)
            direct.add_point(lat, lon, 7.0, t)
        via_log = track.Walk()
        for la, lo, ac, tt in self.L.LiveReader().read_new():
            via_log.add_point(la, lo, ac, tt)
        self.assertEqual(len(via_log.points), len(direct.points))
        # координаты в файле округляются до шести знаков (примерно 11 см),
        # поэтому сходимость проверяется с запасом, а не до последнего бита
        self.assertAlmostEqual(via_log.distance, direct.distance, delta=1.0)

    def test_service_control_safe_off_android(self):
        """На компьютере управление сервисом не должно падать."""
        import service_ctl
        self.assertFalse(service_ctl.available())
        self.assertFalse(service_ctl.start())
        service_ctl.stop()

    def test_locator_reports_absence(self):
        import location
        loc = location.Locator(lambda *a: None)
        self.assertFalse(loc.start())
        self.assertEqual(loc.kind, "")
        loc.stop()


# --------------------------------------------------------------------------- #
#  Карта и прогон по архиву
# --------------------------------------------------------------------------- #

class TestGeometryAndReports(unittest.TestCase):

    def test_mobile_projection_matches_desktop(self):
        """Математика карты в мобильной версии должна совпадать с десктопной."""
        sys.path.insert(0, os.path.join(_root, "android"))
        try:
            import mapview
        except ImportError:
            self.skipTest("Kivy не установлен")
        try:
            from map_picker import deg2num as d2n_desk
        except ImportError:
            d2n_desk = None
        for lat, lon in ((55.96, 38.05), (0.0, 0.0), (-33.87, 151.21), (71.0, -8.0)):
            for z in (5, 11, 17):
                x, y = mapview.deg2num(lat, lon, z)
                la, lo = mapview.num2deg(x, y, z)
                self.assertAlmostEqual(la, lat, places=6)
                self.assertAlmostEqual(lo, lon, places=6)
                if d2n_desk:
                    xd, yd = d2n_desk(lat, lon, z)
                    self.assertAlmostEqual(x, xd, places=9)
                    self.assertAlmostEqual(y, yd, places=9)

    def test_projection_roundtrip(self):
        try:
            from map_picker import deg2num, num2deg
        except ImportError:
            self.skipTest("PySide6 не установлен")
        for lat, lon in ((55.96, 38.05), (0.0, 0.0), (-33.87, 151.21), (71.0, -8.0)):
            for z in (5, 11, 17):
                x, y = deg2num(lat, lon, z)
                la, lo = num2deg(x, y, z)
                self.assertAlmostEqual(la, lat, places=6)
                self.assertAlmostEqual(lo, lon, places=6)

    def test_wave_counting(self):
        import backtest
        dates = [date(2026, 8, 1) + timedelta(days=i) for i in range(60)]
        idx = [0.0] * 60
        for i in range(10, 16):
            idx[i] = 70.0                    # первая волна
        for i in range(40, 46):
            idx[i] = 70.0                    # вторая, после долгого провала
        self.assertEqual(backtest._count_waves(idx, dates), 2)
        self.assertEqual(backtest._count_waves([0.0] * 60, dates), 0)

    def test_heatmap_svg_generated(self):
        import backtest
        days = make_days(120, lambda i: 6.0 if i % 7 == 0 else 0.0, lambda i: 15.0,
                         start=date(2025, 5, 1))
        m, ts = engine.water_balance(days), engine.soil_temperature(days)
        idx = engine.species_index(engine.SPECIES["белый"], days, m, ts)
        stats = backtest.SeasonStats(2025, days, idx, m, ts, 20)
        svg = backtest.heatmap_svg([stats], "тест")
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("</svg>", svg)
        self.assertGreater(svg.count("<rect"), 50)


if __name__ == "__main__":
    unittest.main(verbosity=2)
