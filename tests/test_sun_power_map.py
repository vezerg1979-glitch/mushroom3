# -*- coding: utf-8 -*-
"""Закат, заряд, «весь поход» на экране и память последнего места.

Общее у этих четырёх вещей то, что все они отвечают на вопросы, которые
задают, стоя в лесу: сколько осталось светлого времени, хватит ли телефона,
где я относительно машины и почему приложение опять открылось не там.
Виджеты Kivy без экрана не поднять, поэтому проверяется арифметика и разбор
исходников.
"""

import datetime as dt
import os
import sys
import tempfile
import time

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "android")
sys.path.insert(0, ROOT)

import places  # noqa: E402
import power  # noqa: E402
import prefs  # noqa: E402
import sun  # noqa: E402


@pytest.fixture
def data_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(places, "_DATA_DIR", tmp)
        yield tmp


def _src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def _utc(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%H:%M")


# --------------------------------------------------------------------------- #
#  Солнце
# --------------------------------------------------------------------------- #
#
# Опорные значения сверены с библиотекой astral (её в зависимостях нет —
# тащить пакет в APK ради одной формулы незачем). Допуск 4 минуты: в лесу
# сумерки начинаются на полчаса раньше заката, и минута туда-сюда ничего
# не меняет, а вот ошибка в час означала бы неверную формулу.

CASES = [
    # дата, широта, долгота, восход UTC, закат UTC
    (dt.date(2026, 8, 16), 55.75, 37.62, "02:03", "17:03"),      # Москва, лето
    (dt.date(2026, 12, 21), 55.75, 37.62, "05:57", "12:57"),     # Москва, зима
    (dt.date(2026, 6, 21), 55.75, 37.62, "00:45", "18:17"),      # солнцестояние
    (dt.date(2026, 3, 20), 0.0, 0.0, "06:04", "18:10"),          # экватор
    (dt.date(2026, 8, 16), -33.87, 151.21, "20:32", "07:25"),    # южное полушарие
    (dt.date(2026, 10, 3), 56.02, 38.28, "03:33", "14:56"),      # Фрязино
]


@pytest.mark.parametrize("d,lat,lon,rise,set_", CASES)
def test_sunrise_and_sunset_match_the_reference(d, lat, lon, rise, set_):
    def minutes(hhmm):
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    for got, want in ((sun.sunrise(d, lat, lon), rise),
                      (sun.sunset(d, lat, lon), set_)):
        assert got is not None
        diff = abs(minutes(_utc(got)) - minutes(want))
        assert min(diff, 1440 - diff) <= 4, f"{_utc(got)} вместо {want}"


def test_polar_day_has_no_sunset():
    """Шпицберген в июне: солнце не заходит, и «время заката» не существует.

    Ноль здесь был бы враньём: человек прочитал бы его как «пора выходить».
    """
    assert sun.sunset(dt.date(2026, 6, 21), 78.0, 15.0) is None
    assert sun.sunrise(dt.date(2026, 12, 21), 78.0, 15.0) is None


def test_impossible_latitude_is_loud():
    with pytest.raises(ValueError):
        sun.sunset(dt.date(2026, 8, 16), 120.0, 37.0)


def test_seconds_to_sunset_is_positive_at_noon():
    noon = dt.datetime(2026, 8, 16, 9, 0, tzinfo=dt.timezone.utc).timestamp()
    left = sun.seconds_to_sunset(55.75, 37.62, now=noon)
    assert left is not None
    assert 7 * 3600 < left < 9 * 3600


def test_seconds_to_sunset_is_negative_right_after_dark():
    """Полчаса после заката — «стемнело», а не «до заката 23 часа»."""
    later = dt.datetime(2026, 8, 16, 17, 40, tzinfo=dt.timezone.utc).timestamp()
    left = sun.seconds_to_sunset(55.75, 37.62, now=later)
    assert left is not None and -3600 < left < 0


def test_deep_night_rolls_over_to_the_next_sunset():
    """В три часа ночи «до заката» — это сегодняшний вечер, а не вчерашний."""
    night = dt.datetime(2026, 8, 17, 0, 30, tzinfo=dt.timezone.utc).timestamp()
    left = sun.seconds_to_sunset(55.75, 37.62, now=night)
    assert left is not None
    assert 15 * 3600 < left < 18 * 3600


def test_polar_day_says_nothing_rather_than_zero():
    summer = dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.timezone.utc).timestamp()
    assert sun.seconds_to_sunset(78.0, 15.0, now=summer) is None


def test_sun_text_is_short_enough_for_a_counter():
    assert sun.text(None) == "—"
    assert sun.text(-60) == "стемнело"
    assert sun.text(35 * 60) == "35 мин"
    assert sun.text(2 * 3600 + 5 * 60) == "2 ч 05"


def test_dusk_warning_fires_once():
    src = _src("walkscreen.py")
    assert "self._dusk_warned = True" in src
    i = src.index("def _refresh_dusk")
    assert "sun.WARN_S" in src[i:i + 900]


# --------------------------------------------------------------------------- #
#  Заряд
# --------------------------------------------------------------------------- #

def test_warning_appears_once_per_threshold():
    text, level = power.warning(12, already=0)
    assert "Погасите экран" in text and level == power.LOW
    assert power.warning(11, already=level) == ("", level)


def test_critical_speaks_even_after_the_first_warning():
    """Пятнадцать процентов и пять — разные разговоры."""
    text, level = power.warning(4, already=power.LOW)
    assert "сейчас" in text and level == power.CRITICAL
    assert power.warning(3, already=power.CRITICAL) == ("", power.CRITICAL)


def test_full_battery_says_nothing():
    assert power.warning(80, already=0) == ("", 0)


def test_unknown_level_says_nothing():
    """Выдуманные проценты хуже молчания: на них человек останется в лесу."""
    assert power.warning(None, already=0) == ("", 0)


def test_level_falls_through_broken_sources(monkeypatch):
    power.reset()
    monkeypatch.setattr(power, "SOURCES", (
        lambda: (_ for _ in ()).throw(RuntimeError("нет jnius")),
        lambda: None,
        lambda: 42,
    ))
    assert power.level() == 42


def test_level_is_cached(monkeypatch):
    """Опрос через jnius не бесплатный, а заряд не меняется за секунду."""
    power.reset()
    calls = []
    monkeypatch.setattr(power, "SOURCES", (lambda: calls.append(1) or 50,))
    now = time.time()
    assert power.level(now) == 50
    assert power.level(now + 1) == 50
    assert len(calls) == 1
    assert power.level(now + power.PERIOD + 1) == 50
    assert len(calls) == 2
    power.reset()


def test_no_source_gives_none(monkeypatch):
    power.reset()
    monkeypatch.setattr(power, "SOURCES", (lambda: None,))
    assert power.level() is None
    power.reset()


def test_battery_is_only_checked_while_recording():
    """До «Старта» человек у машины, где есть зарядка."""
    src = _src("walkscreen.py")
    i = src.index("def _check_battery")
    assert "if not self.running:" in src[i:i + 400]


# --------------------------------------------------------------------------- #
#  «Весь поход»
# --------------------------------------------------------------------------- #

class _Map:
    """Кусок TileMap, достаточный для проверки арифметики вписывания."""

    def __init__(self, width=1000, height=1400):
        import mapview

        self.width, self.height = width, height
        self.zoom = 15
        self.cx = self.cy = 0.0
        self.redrawn = 0
        self._m = mapview

    def redraw(self):
        self.redrawn += 1


def _fit(points, width=1000, height=1400):
    import mapview

    m = _Map(width, height)
    ok = mapview.TileMap.fit(m, points)
    return ok, m


def test_fit_zooms_out_until_everything_is_on_screen():
    import mapview

    pts = [(55.900, 38.000), (55.960, 38.090)]
    ok, m = _fit(pts)
    assert ok
    for lat, lon in pts:
        x, y = mapview.deg2num(lat, lon, m.zoom)
        px = (x - m.cx) * mapview.TILE
        py = (y - m.cy) * mapview.TILE
        assert abs(px) <= m.width / 2
        assert abs(py) <= m.height / 2


def test_fit_keeps_a_margin_around_the_track():
    """Точка вплотную к рамке наполовину срезается собственным значком."""
    import mapview

    pts = [(55.900, 38.000), (55.930, 38.050)]
    ok, m = _fit(pts)
    assert ok
    xs, ys = [], []
    for lat, lon in pts:
        x, y = mapview.deg2num(lat, lon, m.zoom)
        xs.append((x - m.cx) * mapview.TILE)
        ys.append((y - m.cy) * mapview.TILE)
    assert max(xs) - min(xs) <= m.width * 0.85
    assert max(ys) - min(ys) <= m.height * 0.85


def test_fit_centres_in_projection_not_in_degrees():
    """У Меркатора градус широты по высоте не постоянен.

    Среднее арифметическое широт увело бы вытянутый с севера на юг трек
    вниз экрана — тем сильнее, чем он длиннее.
    """
    import mapview

    pts = [(50.0, 38.0), (60.0, 38.0)]
    ok, m = _fit(pts)
    assert ok
    y0 = mapview.deg2num(60.0, 38.0, m.zoom)[1]
    y1 = mapview.deg2num(50.0, 38.0, m.zoom)[1]
    assert m.cy == pytest.approx((y0 + y1) / 2)
    assert m.cy != pytest.approx(mapview.deg2num(55.0, 38.0, m.zoom)[1], abs=1e-6)


def test_fit_of_a_single_point_stays_close():
    ok, m = _fit([(55.9606, 38.0456)])
    assert ok
    assert m.zoom == 17                      # максимум: приближать некуда


def test_fit_without_points_does_nothing():
    ok, m = _fit([])
    assert ok is False
    assert m.redrawn == 0


def test_fit_switches_following_off():
    """Иначе первая же координата вернёт карту, и посмотреть не успеешь."""
    src = _src("walkscreen.py")
    i = src.index("def fit_walk")
    body = src[i:i + 900]
    assert "self.map.follow = False" in body
    assert "self.map.fit(" in body


# --------------------------------------------------------------------------- #
#  Последнее место
# --------------------------------------------------------------------------- #

def test_last_place_is_saved_and_restored():
    src = _src("main.py")
    assert "_remember_place" in src
    assert "prefs.save(lat=" in src


def test_place_is_remembered_after_every_way_of_changing_it():
    """Карта, сохранённое место и GPS — три разные двери в одну комнату."""
    src = _src("main.py")
    for method in ("def _place_chosen", "def _use_spot", "def _on_gps"):
        i = src.index(method)
        assert "_remember_place" in src[i:i + 700], method


def test_broken_coordinates_fall_back_to_the_default(data_dir):
    """Испорченный файл не должен унести человека в Атлантику."""
    prefs.save(lat="север", lon=38.0)
    saved = prefs.load()
    assert saved["lat"] == "север"
    src = _src("main.py")
    assert "-85.0 <= lat <= 85.0" in src
    assert "HOME = (55.9606, 38.0456" in src


def test_sun_text_survives_a_broken_number():
    """NaN в счётчик попасть не должен, но падать из-за него — тем более."""
    assert sun.text(float("nan")) == "—"
    assert sun.text(float("inf")) == "—"
