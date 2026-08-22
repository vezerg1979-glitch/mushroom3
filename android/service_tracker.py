# -*- coding: utf-8 -*-
"""
service_tracker.py — фоновый сервис записи маршрута.

Запускается из приложения и продолжает писать координаты, когда экран погашен
и телефон лежит в кармане. Это отдельный процесс Python со своим интерпретатором;
общение с приложением идёт через файлы (см. tracklog.py).

Почему не plyer.gps: его реализация под Android завязана на Activity, а в сервисе
Activity нет. Поэтому LocationManager вызывается напрямую через jnius, а слушатель
вешается на главный Looper — иначе на своём потоке пришлось бы поднимать Looper
вручную, что даёт лишний источник отказов.

Всё обёрнуто в перехват: сервис, который падает молча, хуже отсутствующего.
"""

from __future__ import annotations

import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Каталог данных задаётся ДО первого обращения к tracklog. Сервис — отдельный
# процесс: App.user_data_dir здесь недоступен, а HOME python-for-android не
# выставляет, поэтому по умолчанию каталог получался не тот, куда смотрит
# приложение, и трек уходил в никуда. Приложение передаёт правильный путь
# аргументом сервиса (см. service_ctl.start), он приходит в переменной
# PYTHON_SERVICE_ARGUMENT; ANDROID_PRIVATE — запасной, тоже общий для обоих
# процессов.
import places as places_mod

for _candidate in (os.environ.get("PYTHON_SERVICE_ARGUMENT"),
                   os.environ.get("ANDROID_PRIVATE"),
                   os.path.join(os.path.expanduser("~"), ".mushroom-forecast")):
    if not _candidate:
        continue
    try:
        places_mod.set_data_dir(_candidate)
        break
    except OSError:                   # каталог не создать — пробуем следующий
        continue

import tracklog

POLL_SECONDS = 5.0
# Фильтр по расстоянию отдан приёмнику нулём намеренно. Раньше здесь стояло
# 4 метра, и Android просто не присылал обновлений, пока человек не отойдёт
# на четыре метра: стоящий грибник за полтора часа не получал НИ ОДНОЙ точки,
# приложение показывало «0 метров» и выглядело сломанным, хотя работало.
# Дрожание на месте всё равно отсеивается в track.Walk.add_point (MIN_STEP_M),
# зато теперь видно, что приём жив, и известна текущая точность.
MIN_TIME_MS = 3000
MIN_DIST_M = 0.0
IDLE_TIMEOUT = 12 * 3600          # страховка: сутки в лесу — предел


def _run():
    from jnius import autoclass, PythonJavaClass, java_method

    PythonService = autoclass("org.kivy.android.PythonService")
    service = PythonService.mService
    Context = autoclass("android.content.Context")
    LocationManager = autoclass("android.location.LocationManager")
    Looper = autoclass("android.os.Looper")

    lm = service.getSystemService(Context.LOCATION_SERVICE)
    tracklog.log(f"сервис запущен, каталог данных {places_mod.data_dir()}")

    state = {"last": 0.0, "count": 0}

    def take(location):
        """Одна координата от системы."""
        try:
            tracklog.append_point(location.getLatitude(), location.getLongitude(),
                                  location.getAccuracy())
            state["last"] = time.time()
            state["count"] += 1
            tracklog.set_status(running=True, points=state["count"],
                                source="сервис")
        except Exception as e:                                    # noqa: BLE001
            tracklog.log(f"ошибка записи точки: {e}")

    # Реализованы ВСЕ методы интерфейса, включая методы по умолчанию:
    # динамический посредник pyjnius перехватывает их наравне с остальными,
    # и нереализованный метод означает молча потерянные координаты. Начиная
    # с Android 12 система отдаёт координаты именно пачкой, через
    # onLocationChanged(List<Location>) — см. подробности в location.py.
    class Listener(PythonJavaClass):
        __javainterfaces__ = ["android/location/LocationListener"]

        @java_method("(Landroid/location/Location;)V")
        def onLocationChanged(self, location):
            take(location)

        @java_method("(Ljava/util/List;)V", name="onLocationChanged")
        def onLocationsChanged(self, locations):
            try:
                for i in range(locations.size()):
                    take(locations.get(i))
            except Exception as e:                                # noqa: BLE001
                tracklog.log(f"ошибка разбора пачки координат: {e}")

        @java_method("(I)V")
        def onFlushComplete(self, request_code):
            pass

        @java_method("(Ljava/lang/String;)V")
        def onProviderEnabled(self, provider):
            tracklog.log(f"провайдер включён: {provider}")

        @java_method("(Ljava/lang/String;)V")
        def onProviderDisabled(self, provider):
            tracklog.log(f"провайдер выключен: {provider}")

        @java_method("(Ljava/lang/String;ILandroid/os/Bundle;)V")
        def onStatusChanged(self, provider, status, extras):
            pass

    listener = Listener()
    providers = []
    for name in (LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER):
        try:
            if lm.isProviderEnabled(name):
                lm.requestLocationUpdates(name, MIN_TIME_MS, MIN_DIST_M,
                                          listener, Looper.getMainLooper())
                providers.append(name)
        except Exception as e:                                    # noqa: BLE001
            tracklog.log(f"не удалось подписаться на {name}: {e}")

    if not providers:
        # Самая частая причина — не разрешение, а его отсутствие: диалог
        # показывается асинхронно, и сервис успевает стартовать раньше, чем
        # человек нажал «Разрешить». Сервис спросить разрешение не может,
        # это делает приложение перед его запуском.
        tracklog.log("ни один провайдер координат недоступен")
        tracklog.set_status(running=False,
                            error="нет разрешения или отключена геолокация")
        return

    # Последняя известная точка: чтобы карта не ждала первого спутника.
    try:
        for name in providers:
            loc = lm.getLastKnownLocation(name)
            if loc is not None:
                tracklog.append_point(loc.getLatitude(), loc.getLongitude(),
                                      loc.getAccuracy())
                break
    except Exception as e:                                        # noqa: BLE001
        tracklog.log(f"последняя известная точка недоступна: {e}")

    tracklog.log(f"подписка оформлена: {', '.join(providers)}")
    tracklog.set_status(running=True, points=0, source="сервис",
                        providers=",".join(providers))

    started = time.time()
    while True:
        time.sleep(POLL_SECONDS)
        st = tracklog.get_status()
        if st.get("stop"):
            tracklog.log("получена команда остановки")
            break
        if time.time() - started > IDLE_TIMEOUT:
            tracklog.log("превышен предельный срок записи")
            break
        # поддерживаем отметку живости, даже когда точек нет
        tracklog.set_status(running=True, points=state["count"], source="сервис")
        if state["last"] and time.time() - state["last"] > 300:
            tracklog.log("координат нет более пяти минут")

    try:
        lm.removeUpdates(listener)
    except Exception:                                             # noqa: BLE001
        pass
    tracklog.set_status(running=False, stop=False)
    tracklog.log("сервис остановлен")


if __name__ == "__main__":
    try:
        _run()
    except Exception:                                             # noqa: BLE001
        tracklog.log("СБОЙ СЕРВИСА:\n" + traceback.format_exc())
        tracklog.set_status(running=False, error="сбой сервиса")
