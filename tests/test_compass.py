# -*- coding: utf-8 -*-
"""Тесты компаса.

Проверяется то, на чём компасы обычно и ломаются: перепутанные оси, потеря
склонения, прыжок стрелки при переходе через север и доверие к показаниям
при сильном наклоне телефона.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

sys.path.insert(0, APP)

import compass  # noqa: E402

# Телефон лежит экраном вверх: сила тяжести направлена вдоль -Z устройства.
FLAT = (0.0, 0.0, -9.8)

# Магнитное поле средней полосы: горизонтальная составляющая около 15 мкТл,
# вертикальная около 48 и направлена вниз.
H, V = 15.0, -48.0


def heading(mx, my, mz, g=FLAT):
    return compass.heading_from_vectors(mx, my, mz, *g)


# --------------------------------------------------------------------------- #
#  Стороны света
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("field,expect", [
    ((0, H, V), 0),        # верх телефона смотрит на север
    ((-H, 0, V), 90),      # на восток
    ((0, -H, V), 180),     # на юг
    ((H, 0, V), 270),      # на запад
])
def test_cardinal_directions(field, expect):
    assert heading(*field) == pytest.approx(expect, abs=1)


def test_diagonal_direction():
    d = H / (2 ** 0.5)
    assert heading(-d, d, V) == pytest.approx(45, abs=1)


# --------------------------------------------------------------------------- #
#  Отказы
# --------------------------------------------------------------------------- #

def test_zero_vectors_give_nothing():
    assert heading(0, 0, 0) is None
    assert compass.heading_from_vectors(0, H, V, 0, 0, 0) is None


def test_vertical_phone_rejected():
    """Телефон подняли как зеркало — горизонтальная проекция вырождается."""
    upright = (0.0, -9.8, 0.0)
    assert heading(0, H, V, upright) is None


def test_moderate_tilt_still_works():
    """Держать телефон под 30° — обычное дело, курс должен считаться."""
    import math
    a = math.radians(30)
    g = (0.0, -9.8 * math.sin(a), -9.8 * math.cos(a))
    m = (0.0, H * math.cos(a) - V * math.sin(a), H * math.sin(a) + V * math.cos(a))
    assert heading(*m, g) == pytest.approx(0, abs=5)


# --------------------------------------------------------------------------- #
#  Склонение и сглаживание
# --------------------------------------------------------------------------- #

def test_declination_applied():
    """Стрелка показывает на магнитный полюс, карта — на географический."""
    assert compass.true_heading(0, 11) == pytest.approx(11)
    assert compass.true_heading(355, 11) == pytest.approx(6)      # через ноль


def test_smoothing_does_not_jump_through_north():
    """359° и 1° — это два градуса разницы, а не 358."""
    assert compass.smooth_angle(359, 1, 0.5) == pytest.approx(0, abs=0.5)
    assert compass.smooth_angle(10, 350, 0.5) == pytest.approx(0, abs=0.5)


def test_smoothing_lags_behind_but_follows():
    v = compass.smooth_angle(0, 90, 0.15)
    assert 5 < v < 20                       # сдвинулось, но не прыгнуло
    for _ in range(40):
        v = compass.smooth_angle(v, 90, 0.15)
    assert v == pytest.approx(90, abs=1)    # догнало


def test_first_reading_taken_as_is():
    assert compass.smooth_angle(None, 137) == pytest.approx(137)


def test_angle_diff_is_shortest():
    assert compass.angle_diff(350, 10) == pytest.approx(20)
    assert compass.angle_diff(10, 350) == pytest.approx(20)
    assert compass.angle_diff(0, 180) == pytest.approx(180)


# --------------------------------------------------------------------------- #
#  Класс
# --------------------------------------------------------------------------- #

def test_compass_without_sensors_is_silent():
    """На компьютере датчиков нет: объект обязан молча выключиться,
    а не уронить приложение."""
    c = compass.Compass()
    assert c.start() is False
    assert c.available is False
    assert c.error
    assert c.read() is None
    assert c.heading() is None
    c.stop()


def test_compass_reads_from_fake_sensors(monkeypatch):
    class FakeSensor:
        field = (0.0, H, V)

        def enable(self):
            pass

        def disable(self):
            pass

    class FakeAccel:
        acceleration = FLAT

        def enable(self):
            pass

        def disable(self):
            pass

    fake = type(sys)("plyer")
    fake.compass = FakeSensor()
    fake.accelerometer = FakeAccel()
    monkeypatch.setitem(sys.modules, "plyer", fake)

    c = compass.Compass(declination=11.0)
    assert c.start() is True
    v = c.read()
    assert v == pytest.approx(11, abs=1)    # ноль магнитный плюс склонение
    assert c.heading() == v
    c.stop()
    assert c.available is False
