# -*- coding: utf-8 -*-
"""Живучесть фоновой записи: разрывы, перерывы и подсказки по производителям.

Проверяется в первую очередь то, что легко сделать неправильно: обвинить
телефон в разрыве, который человек устроил сам, нажав «Пауза». Ложное
обвинение здесь дороже пропущенного: человек пойдёт крутить настройки,
которые ни при чём, и перестанет верить сообщениям вообще.
"""

import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "android")
sys.path.insert(0, ROOT)

import survival  # noqa: E402
import track  # noqa: E402

T0 = 1_700_000_000.0


def _walk(steps):
    """Поход из точек: steps — секунды от начала.

    Координаты берутся так, чтобы шаг был больше MIN_STEP_M и меньше
    предела скорости: иначе точки отсеет сам track, и тест будет мерить
    не то, что заявлено.
    """
    w = track.Walk(started=T0)
    lat, lon = 55.0, 38.0
    for i, t in enumerate(steps):
        w.points.append(track.Point(lat + i * 0.0002, lon, T0 + t, 8.0))
    w.finished = T0 + (steps[-1] if steps else 0)
    return w


# --------------------------------------------------------------------------- #
#  Что считается разрывом
# --------------------------------------------------------------------------- #

def test_steady_recording_has_no_gaps():
    w = _walk([0, 20, 40, 60, 80])
    assert survival.gaps(w) == []
    assert survival.report(w) == ""


def test_long_silence_is_a_gap():
    w = _walk([0, 20, 40, 1900, 1920])
    found = survival.gaps(w)
    assert len(found) == 1
    assert found[0][2] == pytest.approx(1860)


def test_short_silence_is_not_a_gap():
    """Пара минут без точек — это овраг и полог, а не остановка записи."""
    w = _walk([0, 20, 200, 220])
    assert survival.gaps(w) == []


def test_a_pause_the_person_made_is_not_a_gap():
    """Обед на пне выглядит точно так же, как убитый сервис."""
    w = _walk([0, 20, 3600, 3620])
    w.pause(T0 + 30)
    w.resume(T0 + 3590)
    assert survival.gaps(w) == []
    assert survival.report(w) == ""


def test_a_kill_during_a_walk_with_a_pause_is_still_seen():
    """Перерыв не должен становиться прикрытием для всех разрывов подряд."""
    w = _walk([0, 20, 1000, 1020, 4000, 4020])
    w.pause(T0 + 30)
    w.resume(T0 + 990)
    found = survival.gaps(w)
    assert len(found) == 1
    assert found[0][0] == pytest.approx(T0 + 1020)


def test_lost_time_sums_the_gaps():
    w = _walk([0, 1000, 2000, 3000])
    assert survival.lost_time(w) == pytest.approx(3000)


# --------------------------------------------------------------------------- #
#  Кого винить
# --------------------------------------------------------------------------- #

def test_a_short_walk_is_not_blamed_on_the_phone():
    """Двадцать минут — мало для вывода: приёмник мог просто искать спутники.

    Разрыв здесь нарочно длиннее порога «убитого» процесса: проверяется
    именно оговорка про короткий поход, а не то, что разрыв мал.
    """
    w = _walk([0, 1200])
    assert w.duration < 1800
    assert survival.gaps(w)
    assert not survival.looks_killed(w)


def test_a_quarter_hour_of_silence_in_a_long_walk_looks_killed():
    w = _walk([0, 600, 1200, 3600, 7200])
    assert survival.looks_killed(w)
    assert "фоне" in survival.report(w)


def test_moderate_gaps_are_blamed_on_the_sky_not_the_phone():
    """Шесть минут — плохой приём. Обвинять телефон рано."""
    w = _walk([0, 600, 1200, 1600, 2000, 2400, 3000, 3600, 4200])
    assert not survival.looks_killed(w)
    text = survival.report(w)
    assert "спутник" in text


def test_report_counts_repeated_interruptions():
    w = _walk([0, 600, 1200, 2000, 2600, 3400, 4000])
    text = survival.report(w)
    assert "раза" in text


# --------------------------------------------------------------------------- #
#  Куда идти в настройках
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", ["xiaomi", "Xiaomi", "REDMI", "poco",
                                  "honor", "Huawei", "realme", "iqoo",
                                  "samsung", "OnePlus"])
def test_known_vendors_get_their_own_path(name):
    """Общий совет «разрешите работу в фоне» бесполезен: пункта с таким
    названием нет ни в одной оболочке."""
    v = survival.vendor(name)
    assert v is not survival.GENERIC, name
    assert v["steps"]


@pytest.mark.parametrize("name", ["", "неизвестный", "google"])
def test_unknown_vendors_get_a_general_path(name):
    assert survival.vendor(name) is survival.GENERIC
    assert "Автозапуск" in survival.advice(name)


def test_advice_names_the_phone_family():
    assert "MIUI" in survival.advice("xiaomi")
    assert "One UI" in survival.advice("samsung")


def test_every_vendor_entry_is_filled_in():
    for key, v in survival.VENDORS.items():
        assert v["name"] and v["steps"], key
        for step in v["steps"]:
            assert len(step) > 20, (key, step)
        comp = v.get("activity")
        assert comp is None or (len(comp) == 2 and all(comp)), key


def test_aliases_point_at_real_vendors():
    for alias, target in survival.ALIASES.items():
        assert target in survival.VENDORS, alias


def test_off_android_everything_stays_quiet():
    """На компьютере нет ни настроек, ни системы: молчим, а не падаем."""
    assert survival.manufacturer() == ""
    assert survival.is_exempt() is None
    assert survival.open_battery_settings() is False
    assert survival.open_app_settings() is False


def test_play_forbidden_permission_is_not_requested():
    """REQUEST_IGNORE_BATTERY_OPTIMIZATIONS Google Play принимает лишь для
    узкого списка назначений и снимает приложения с публикации за него.

    Поэтому открывается системный СПИСОК оптимизации батареи: на касание
    больше, зато сборку нельзя снять с публикации.
    """
    with open(os.path.join(ROOT, "survival.py"), encoding="utf-8") as f:
        src = f.read()
    assert "ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS" in src
    assert "ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS" not in src
    with open(os.path.join(ROOT, "buildozer.spec"), encoding="utf-8") as f:
        spec = f.read()
    assert "REQUEST_IGNORE_BATTERY_OPTIMIZATIONS" not in spec


def test_walk_summary_tells_about_a_broken_recording():
    """Молчание про оборванную запись человек читает как «приложение врёт»."""
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        src = f.read()
    assert "survival.report(walk)" in src
    assert "survival.advice()" in src


def test_pauses_survive_saving(tmp_path, monkeypatch):
    import places

    monkeypatch.setattr(places, "_DATA_DIR", str(tmp_path))
    w = _walk([0, 20, 3600])
    w.pause(T0 + 30)
    w.resume(T0 + 3590)
    track.save(w)
    back = track.load_all()[0]
    assert back.pauses == w.pauses
    assert survival.gaps(back) == []


def test_stop_closes_an_open_pause():
    """Иначе поход, законченный на паузе, оставляет перерыв без конца."""
    w = _walk([0, 20])
    w.pause(T0 + 30)
    w.stop()
    assert w.pauses[-1][1] > w.pauses[-1][0]
