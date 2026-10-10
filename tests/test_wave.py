# -*- coding: utf-8 -*-
"""Начало слоя: когда об этом стоит сказать, а когда лучше промолчать.

Молчание здесь ценнее сообщения. Уведомление, пришедшее не к месту или
третий день подряд, человек отключает — и второй раз его не включит уже
никогда, вместе со всеми полезными. Поэтому большая часть тестов проверяет
именно те случаи, когда программа обязана смолчать.
"""

import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

ROOT = APP
sys.path.insert(0, ROOT)

import mushroom_forecast as engine  # noqa: E402
import notify  # noqa: E402
import places  # noqa: E402
import wave  # noqa: E402


class FakeDay:
    def __init__(self, d):
        self.d = d


def days_from(start=date(2026, 9, 1), n=12):
    return [FakeDay(start + timedelta(days=i)) for i in range(n)]


def rising(low=30.0, high=65.0, at=3, n=12):
    """Индекс, который поднимается через `at` дней."""
    return [low] * at + [high] * (n - at)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(places, "_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MUSHROOM_DATA_DIR", raising=False)
    return tmp_path


# --------------------------------------------------------------------------- #
#  Когда говорить
# --------------------------------------------------------------------------- #

def test_a_rise_over_the_threshold_is_a_wave():
    found = wave.find(days_from(), {"белый": rising()})
    assert len(found) == 1
    assert found[0]["key"] == "белый"
    assert found[0]["day"] == 3
    assert found[0]["value"] == pytest.approx(65.0)


def test_the_earliest_wave_goes_first():
    found = wave.find(days_from(), {"белый": rising(at=4),
                                    "опёнок": rising(at=2, high=60.0)})
    assert [r["key"] for r in found] == ["опёнок", "белый"]


def test_message_names_the_species_and_the_day():
    found = wave.find(days_from(), {"белый": rising(at=2)})
    title, text = wave.message(found)
    assert "Белый гриб" in title and "послезавтра" in title
    assert "65" in text


def test_message_does_not_list_everything():
    """Пять названий на шторке обрежутся на середине — читать нечего."""
    idx = {"белый": rising(at=2), "опёнок": rising(at=2),
           "лисичка": rising(at=2), "маслёнок": rising(at=2)}
    _, text = wave.message(wave.find(days_from(), idx))
    named = sum(1 for sp in engine.SPECIES.values()
                if sp.name.lower() in text.lower())
    assert named <= 1                       # первый вид уже назван в заголовке
    assert "ещё" in text


# --------------------------------------------------------------------------- #
#  Когда молчать
# --------------------------------------------------------------------------- #

def test_a_wave_already_going_is_not_news():
    """Человек увидит это, открыв приложение. Будить его незачем."""
    assert wave.find(days_from(), {"белый": [70.0] * 12}) == []


def test_a_small_rise_is_not_a_wave():
    """Колебание третьего знака — не событие."""
    assert wave.find(days_from(), {"белый": [48.0] * 2 + [52.0] * 10}) == []


def test_a_rise_that_stays_low_is_not_a_wave():
    assert wave.find(days_from(), {"белый": [10.0] * 2 + [45.0] * 10}) == []


def test_a_wave_beyond_the_horizon_waits():
    """За неделю прогноз погоды и сам ненадёжен."""
    assert wave.find(days_from(), {"белый": rising(at=8)}) == []


def test_out_of_season_species_are_ignored():
    """Модель может дать высокий индекс по погоде и в ноябре.

    Лисичек в ноябре нет физически, и сообщение о них — не ошибка расчёта,
    а потеря доверия ко всем остальным сообщениям.
    """
    november = days_from(date(2026, 11, 1))
    assert engine.SPECIES["лисичка"].months.get(11, 0) == 0
    assert wave.find(november, {"лисичка": rising()}) == []


def test_unknown_species_are_skipped():
    assert wave.find(days_from(), {"мухомор": rising()}) == []


def test_broken_numbers_do_not_crash_the_check():
    """NaN в прогнозе — обычное дело на краю данных."""
    bad = [float("nan")] * 3 + [70.0] * 9
    wave.find(days_from(), {"белый": bad})          # не должно бросать
    assert wave.find(days_from(), {"белый": []}) == []


def test_empty_list_gives_empty_text():
    assert wave.message([]) == ("", "")
    assert wave.line([]) == ""


# --------------------------------------------------------------------------- #
#  Не повторяться
# --------------------------------------------------------------------------- #

def test_the_same_wave_is_announced_once(data_dir):
    found = wave.find(days_from(), {"белый": rising()})
    assert wave.fresh(found, "Ельник")
    wave.remember(found, "Ельник")
    assert wave.fresh(found, "Ельник") == []


def test_another_place_is_another_wave(data_dir):
    found = wave.find(days_from(), {"белый": rising()})
    wave.remember(found, "Ельник")
    assert wave.fresh(found, "Бор за рекой")


def test_after_a_week_the_reminder_returns(data_dir):
    found = wave.find(days_from(), {"белый": rising()})
    wave.remember(found, "Ельник", now=1_700_000_000.0)
    later = 1_700_000_000.0 + wave.COOLDOWN_S + 60
    assert wave.fresh(found, "Ельник", now=later)


def test_memory_survives_a_broken_file(data_dir):
    (data_dir / wave.STATE_FILE).write_text("{это не json", encoding="utf-8")
    found = wave.find(days_from(), {"белый": rising()})
    assert wave.fresh(found, "Ельник")          # молча начинаем заново


def test_forget_all_clears_the_memory(data_dir):
    found = wave.find(days_from(), {"белый": rising()})
    wave.remember(found, "Ельник")
    wave.forget_all()
    assert wave.fresh(found, "Ельник")


# --------------------------------------------------------------------------- #
#  Уведомление
# --------------------------------------------------------------------------- #

def test_off_android_notification_is_silent_not_broken():
    assert notify.available() is False
    assert notify.post("Заголовок", "Текст") is False
    assert notify.allowed() is False


def test_empty_title_is_never_posted():
    assert notify.post("", "текст") is False


def test_notification_permission_is_declared():
    """Без POST_NOTIFICATIONS на Android 13+ сообщение не покажется."""
    with open(os.path.join(ROOT, "buildozer.spec"), encoding="utf-8") as f:
        spec = f.read()
    assert "POST_NOTIFICATIONS" in spec


def test_main_screen_checks_for_a_wave_after_each_forecast():
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        src = f.read()
    assert "_check_wave" in src
    assert "wave.remember" in src, "иначе одно и то же сообщение придёт снова"
    assert "wave.fresh" in src
