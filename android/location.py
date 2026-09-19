# -*- coding: utf-8 -*-
"""
location.py — координаты в самом приложении, без сторонних пакетов.

plyer из сборки исключён: он ломал сборку, а его реализация под Android всё
равно сводится к LocationManager. Здесь тот же вызов напрямую через pyjnius,
который python-for-android кладёт в APK всегда.

Три источника по убыванию предпочтения: LocationManager через jnius, затем
plyer (если вдруг доступен), затем ничего — тогда интерфейс честно сообщает,
что координаты надо задать вручную.

Про разрешения. Начиная с Android 6 доступ к координатам спрашивают в момент
работы, и диалог показывается АСИНХРОННО: request_permissions() возвращает
управление сразу, ещё до того, как человек нажал «Разрешить». Если сразу за
ним вызвать requestLocationUpdates(), система выбросит SecurityException —
и приложение решит, что приёмника нет, хотя разрешение через секунду дадут.
Поэтому здесь есть has_permission() и request_permission(callback), а запуск
приёмника выполняется только после ответа человека.
"""

from __future__ import annotations

# Фильтр по расстоянию отдан приёмнику нулём намеренно. Раньше здесь стояло
# 4 метра, и Android просто не присылал обновлений, пока человек не отойдёт
# на четыре метра: стоящий грибник за полтора часа не получал НИ ОДНОЙ точки,
# приложение показывало «0 метров» и выглядело сломанным, хотя работало.
# Дрожание на месте всё равно отсеивается в track.Walk.add_point (MIN_STEP_M),
# зато теперь видно, что приём жив, и известна текущая точность.
MIN_TIME_MS = 2000
MIN_DIST_M = 0.0


# --------------------------------------------------------------------------- #
#  Разрешения
# --------------------------------------------------------------------------- #

def on_android() -> bool:
    try:
        from jnius import autoclass                              # noqa: F401
        autoclass("org.kivy.android.PythonActivity")
        return True
    except Exception:                                             # noqa: BLE001
        return False


def has_permission() -> bool:
    """Дано ли уже разрешение на координаты. Вне Android — считаем, что да."""
    try:
        from android.permissions import Permission, check_permission
    except ImportError:
        return True
    try:
        return bool(check_permission(Permission.ACCESS_FINE_LOCATION)
                    or check_permission(Permission.ACCESS_COARSE_LOCATION))
    except Exception:                                             # noqa: BLE001
        return True


def request_permission(callback=None) -> bool:
    """Спрашивает разрешение. callback(granted: bool) вызывается после ответа.

    Возвращает False, если спрашивать не у кого (не Android) — в этом случае
    callback вызывается сразу с True.
    """
    try:
        from android.permissions import Permission, request_permissions
    except ImportError:
        if callback:
            callback(True)
        return False
    perms = [Permission.ACCESS_FINE_LOCATION, Permission.ACCESS_COARSE_LOCATION]
    if callback is None:
        request_permissions(perms)
        return True

    def _answer(permissions, results):
        try:
            callback(bool(results) and any(results))
        except Exception:                                         # noqa: BLE001
            pass

    request_permissions(perms, _answer)
    return True


def request_permissions_if_needed():
    """Совместимость со старым кодом: спросить и не ждать ответа."""
    return request_permission(None)


class Locator:
    """Подписка на координаты. on_location(lat, lon, acc) вызывается из главного потока."""

    def __init__(self, on_location):
        self.on_location = on_location
        self.kind = ""            # чем именно получаем: jnius / plyer / нет
        self.providers = []       # какие источники реально подписались
        self.error = ""
        self._lm = None
        self._listener = None
        self._plyer = None

    # --- запуск -------------------------------------------------------------
    def start(self) -> bool:
        if self._start_jnius():
            self.kind = "jnius"
            return True
        if self._start_plyer():
            self.kind = "plyer"
            return True
        self.kind = ""
        return False

    def _start_jnius(self) -> bool:
        try:
            from jnius import PythonJavaClass, autoclass, java_method
        except ImportError:
            self.error = "не Android"
            return False
        if not has_permission():
            self.error = "нет разрешения на доступ к координатам"
            return False
        try:
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            Context = autoclass("android.content.Context")
            LocationManager = autoclass("android.location.LocationManager")
            Looper = autoclass("android.os.Looper")
            lm = activity.getSystemService(Context.LOCATION_SERVICE)

            cb = self.on_location

            # ВНИМАНИЕ: реализовать надо ВСЕ методы интерфейса, включая те,
            # у которых в Java есть реализация по умолчанию.
            #
            # Динамический посредник (java.lang.reflect.Proxy), через который
            # pyjnius связывает Python с Java, перехватывает вызовы всех
            # методов интерфейса без разбора — методы по умолчанию тоже.
            # Реализации из Java при этом не остаётся: посредник её подменил.
            # Если вызванного метода нет на стороне Python, pyjnius печатает
            # «Python/java method missing» и возвращает пустоту.
            #
            # Начиная с Android 12 система отдаёт координаты пачкой — через
            # onLocationChanged(List<Location>), а не поштучно. Пока этого
            # метода здесь не было, происходило вот что: подписка проходила
            # успешно, getLastKnownLocation отдавал точку мгновенно, а живых
            # обновлений не приходило НИ ОДНОГО. Приёмник работал, точность
            # была четыре метра, счётчик показывал ноль точек и «193 с назад».
            class Listener(PythonJavaClass):
                __javainterfaces__ = ["android/location/LocationListener"]

                @java_method("(Landroid/location/Location;)V")
                def onLocationChanged(self, location):
                    cb(location.getLatitude(), location.getLongitude(),
                       location.getAccuracy())

                @java_method("(Ljava/util/List;)V", name="onLocationChanged")
                def onLocationsChanged(self, locations):
                    """Пачка координат, Android 12 и новее."""
                    try:
                        for i in range(locations.size()):
                            loc = locations.get(i)
                            cb(loc.getLatitude(), loc.getLongitude(),
                               loc.getAccuracy())
                    except Exception:                             # noqa: BLE001
                        pass

                @java_method("(I)V")
                def onFlushComplete(self, request_code):
                    pass

                @java_method("(Ljava/lang/String;)V")
                def onProviderEnabled(self, provider):
                    pass

                @java_method("(Ljava/lang/String;)V")
                def onProviderDisabled(self, provider):
                    pass

                @java_method("(Ljava/lang/String;ILandroid/os/Bundle;)V")
                def onStatusChanged(self, provider, status, extras):
                    pass

            listener = Listener()
            got = []
            # Причина отказа по каждому провайдеру запоминается: «выключено в
            # настройках» и «нет разрешения» лечатся по-разному, и человеку
            # нельзя показывать одно вместо другого.
            reasons = []
            for name in self._providers(lm, LocationManager):
                try:
                    if not lm.isProviderEnabled(name):
                        reasons.append(f"{name}: выключен")
                        continue
                    lm.requestLocationUpdates(name, MIN_TIME_MS, MIN_DIST_M,
                                              listener, Looper.getMainLooper())
                    got.append(name)
                except Exception as e:                            # noqa: BLE001
                    reasons.append(f"{name}: {str(e)[:40]}")
                    continue
            if not got:
                self.error = "; ".join(reasons) or "провайдеры недоступны"
                return False
            self.providers = got
            self._lm, self._listener = lm, listener
            return True
        except Exception as e:                                    # noqa: BLE001
            self.error = str(e)[:80]
            return False

    @staticmethod
    def _providers(lm, LocationManager) -> list:
        """Все источники координат, какие есть на аппарате.

        Одного GPS мало. Под крышей и в еловом лесу спутники ловятся
        минутами, а то и не ловятся вовсе; сетевой провайдер на аппаратах
        без сервисов Google может отсутствовать совсем. Пассивный источник
        не тратит батарею вообще: он отдаёт координаты, которые для себя
        запросило любое другое приложение, — этого достаточно, чтобы
        маршрут не был пустым, пока спутники ищутся.
        """
        names = [LocationManager.GPS_PROVIDER,
                 LocationManager.NETWORK_PROVIDER,
                 LocationManager.PASSIVE_PROVIDER]
        # FUSED_PROVIDER появился в Android 12 и обычно самый шустрый.
        fused = getattr(LocationManager, "FUSED_PROVIDER", None)
        if fused:
            names.insert(0, fused)
        out = []
        for n in names:
            if n and n not in out:
                out.append(n)
        return out

    def _start_plyer(self) -> bool:
        try:
            from plyer import gps
        except ImportError:
            return False
        try:
            gps.configure(
                on_location=lambda **kw: self.on_location(
                    float(kw.get("lat")), float(kw.get("lon")),
                    float(kw.get("accuracy") or 0.0)),
                on_status=lambda *a: None)
            gps.start(minTime=MIN_TIME_MS, minDistance=MIN_DIST_M)
            self._plyer = gps
            return True
        except Exception as e:                                    # noqa: BLE001
            self.error = str(e)[:80]
            return False

    # --- остановка ----------------------------------------------------------
    def stop(self):
        if self._lm is not None and self._listener is not None:
            try:
                self._lm.removeUpdates(self._listener)
            except Exception:                                     # noqa: BLE001
                pass
            self._lm = self._listener = None
        if self._plyer is not None:
            try:
                self._plyer.stop()
            except Exception:                                     # noqa: BLE001
                pass
            self._plyer = None

    def poll(self):
        """Свежайшая известная точка: (широта, долгота, точность, время).

        Аварийный путь на случай, когда подписка молчит. Обращение к
        getLastKnownLocation не включает приёмник и не тратит батарею — оно
        лишь читает то, что система уже знает, а знает она ровно потому, что
        подписка выше её об этом попросила. Даже если обратный вызов почему-то
        не доходит до Python, координаты всё равно доедут до маршрута.
        """
        try:
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            Context = autoclass("android.content.Context")
            LocationManager = autoclass("android.location.LocationManager")
            lm = activity.getSystemService(Context.LOCATION_SERVICE)
        except Exception:                                         # noqa: BLE001
            return None
        best = None
        for name in self._providers(lm, LocationManager):
            try:
                loc = lm.getLastKnownLocation(name)
            except Exception:                                     # noqa: BLE001
                continue
            if loc is None:
                continue
            t = loc.getTime() / 1000.0
            if best is None or t > best[3]:
                best = (loc.getLatitude(), loc.getLongitude(),
                        loc.getAccuracy(), t)
        return best

    def last_known(self):
        """Последняя известная точка — чтобы карта не открывалась в пустоте."""
        if not has_permission():
            return None
        try:
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            Context = autoclass("android.content.Context")
            LocationManager = autoclass("android.location.LocationManager")
            lm = activity.getSystemService(Context.LOCATION_SERVICE)
            for name in (LocationManager.GPS_PROVIDER,
                         LocationManager.NETWORK_PROVIDER):
                loc = lm.getLastKnownLocation(name)
                if loc is not None:
                    return loc.getLatitude(), loc.getLongitude(), loc.getAccuracy()
        except Exception:                                         # noqa: BLE001
            pass
        return None
