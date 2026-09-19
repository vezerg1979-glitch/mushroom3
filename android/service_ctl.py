# -*- coding: utf-8 -*-
"""
service_ctl.py — запуск и остановка фонового сервиса со стороны приложения.

Имя Java-класса сервиса складывается python-for-android из домена, имени пакета
и имени сервиса в buildozer.spec: services = Tracker:service_tracker.py:foreground
даёт класс ru.grezev.mushroomforecast.ServiceTracker.

На компьютере ничего этого нет, поэтому все функции возвращают False,
а приложение переходит на запасной путь — plyer.gps в открытом окне.
"""

from __future__ import annotations

import time

import places as places_mod
import tracklog

SERVICE_CLASS = "ru.grezev.mushroomforecast.ServiceTracker"


def available() -> bool:
    """Есть ли вообще Android под ногами."""
    try:
        from jnius import autoclass          # noqa: F401
        autoclass("org.kivy.android.PythonActivity")
        return True
    except Exception:                                             # noqa: BLE001
        return False


def start() -> bool:
    """Запускает сервис. True — команда отдана, но проверять надо по статусу."""
    if not available():
        return False
    try:
        from jnius import autoclass
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        service = autoclass(SERVICE_CLASS)
        tracklog.set_status(running=False, stop=False, source="сервис")
        # Аргумент сервиса — каталог данных. Сервис живёт в отдельном
        # процессе и сам вычислить его не может: HOME там не выставлен.
        # p4a кладёт эту строку в переменную PYTHON_SERVICE_ARGUMENT.
        service.start(activity, places_mod.data_dir())
        tracklog.log("команда запуска сервиса отдана")
        return True
    except Exception as e:                                        # noqa: BLE001
        tracklog.log(f"не удалось запустить сервис: {e}")
        return False


def stop(wait: float = 1.0) -> bool:
    """Останавливает сервис: сначала мягко через файл-команду, затем принудительно.

    wait — сколько секунд ждать мягкой остановки. Вызывается из главного
    потока Kivy, поэтому ожидание короткое: длинный sleep подвешивает окно.
    """
    tracklog.set_status(stop=True)
    if not available():
        return False
    deadline = time.time() + max(0.0, wait)
    while time.time() < deadline:
        if not tracklog.get_status().get("running"):
            break
        time.sleep(0.2)
    try:
        from jnius import autoclass
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        autoclass(SERVICE_CLASS).stop(activity)
        tracklog.log("команда остановки сервиса отдана")
        return True
    except Exception as e:                                        # noqa: BLE001
        tracklog.log(f"не удалось остановить сервис: {e}")
        return False


def wait_alive(timeout: float = 8.0) -> bool:
    """Дожидается первого признака жизни: сервис поднимается не мгновенно."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if tracklog.service_alive():
            return True
        time.sleep(0.4)
    return False
