# -*- coding: utf-8 -*-
"""Проверки того, что сломалось в 2.7 и починено в 2.8.

Оба дефекта проявлялись только на телефоне и не ловились прежними тестами:
первый — из-за того, что тесты компаса подавали вектор «вниз», а датчик
Android отдаёт вектор «вверх»; второй — из-за того, что каталог данных
сервиса никто не сравнивал с каталогом приложения.
"""

import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "android"))

import compass  # noqa: E402

H, V = 15.0, -48.0

# Как показывает акселерометр Android лежащий экраном вверх телефон:
# вектор направлен ВВЕРХ, +9.8 по оси Z. Именно эти числа приходят
# из plyer.accelerometer.acceleration и из TYPE_ACCELEROMETER.
ANDROID_FLAT = (0.0, 0.0, 9.8)


@pytest.mark.parametrize("field,expect", [
    ((0, H, V), 0),        # верх телефона смотрит на север
    ((-H, 0, V), 90),      # на восток
    ((0, -H, V), 180),     # на юг
    ((H, 0, V), 270),      # на запад
])
def test_android_convention_is_not_mirrored(field, expect):
    """Восток должен оставаться востоком.

    До исправления сырые показания акселерометра шли в расчёт как есть,
    и курс получался зеркальным: 90° вместо 270° и наоборот.
    """
    got = compass.heading_from_android_sensors(*field, *ANDROID_FLAT)
    assert got == pytest.approx(expect, abs=1)


def test_android_helper_matches_negated_vectors():
    """Помощник — это ровно инверсия вектора, без иной арифметики."""
    m = (3.0, -7.0, -40.0)
    a = (0.5, 1.2, 9.6)
    assert (compass.heading_from_android_sensors(*m, *a)
            == compass.heading_from_vectors(*m, *(-x for x in a)))


def test_compass_start_is_quiet_off_android():
    """На компьютере компас должен выключаться, а не бросать исключение."""
    c = compass.Compass()
    assert c.start() is False
    assert c.available is False
    assert c.error                      # причина названа
    assert c.read() is None
    c.stop()


# --------------------------------------------------------------------------- #
#  Общий каталог данных приложения и фонового сервиса
# --------------------------------------------------------------------------- #

def test_data_dir_follows_android_private(tmp_path, monkeypatch):
    """Сервис и приложение обязаны смотреть в один каталог.

    p4a выставляет ANDROID_PRIVATE в обоих процессах, и он совпадает
    с App.user_data_dir. Раньше сервис откатывался на ~/.mushroom-forecast
    и писал трек туда, где приложение его не искало.
    """
    monkeypatch.delenv("MUSHROOM_DATA_DIR", raising=False)
    monkeypatch.setenv("ANDROID_PRIVATE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "чужой-дом"))
    places = importlib.reload(importlib.import_module("places"))
    try:
        assert places.data_dir() == str(tmp_path)
    finally:
        monkeypatch.delenv("ANDROID_PRIVATE", raising=False)
        importlib.reload(places)


def test_service_reads_data_dir_from_argument():
    """Каталог передаётся сервису аргументом, а не угадывается."""
    with open(os.path.join(ROOT, "android", "service_tracker.py"),
              encoding="utf-8") as f:
        src = f.read()
    assert "PYTHON_SERVICE_ARGUMENT" in src
    # и приложение этот аргумент действительно кладёт
    with open(os.path.join(ROOT, "android", "service_ctl.py"),
              encoding="utf-8") as f:
        ctl = f.read()
    assert "service.start(activity, places_mod.data_dir())" in ctl


def test_location_permission_helpers_exist():
    """Запись не должна стартовать раньше ответа на диалог разрешений."""
    import location
    assert hasattr(location, "has_permission")
    assert hasattr(location, "request_permission")
    # вне Android разрешение считается данным, обратный вызов срабатывает сразу
    seen = []
    location.request_permission(seen.append)
    assert seen == [True]
