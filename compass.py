# -*- coding: utf-8 -*-
"""
compass.py — куда повёрнут телефон.

Зачем нужен, если есть курс по треку. Курс движения (`nav.course_over_ground`)
точен, но существует только пока человек идёт. Стоящему грибнику он ничего не
даёт: остановился посмотреть под ёлку — стрелка «замёрзла». Компас работает
и на месте, поэтому один дополняет другой.

Почему нельзя брать магнитометр напрямую. Датчик меряет вектор магнитного
поля в системе координат телефона. Пока телефон лежит горизонтально, курс —
это просто арктангенс двух горизонтальных составляющих. Но человек держит его
наклонно, и без учёта наклона ошибка достигает десятков градусов. Поэтому
нужна вторая тройка чисел — вектор силы тяжести с акселерометра, по которому
поле проецируется на горизонтальную плоскость.

ВАЖНО про знак акселерометра. Android отдаёт не силу тяжести, а реакцию
опоры: телефон, спокойно лежащий экраном вверх, показывает +9.8 по оси Z,
то есть вектор смотрит ВВЕРХ. Функция heading_from_vectors ждёт вектор
«вниз». Если подать показания как есть, восток и запад меняются местами:
курс получается зеркальным (90° вместо 270°). Поэтому показания
акселерометра перед расчётом инвертируются — этим занимается
heading_from_android_sensors.

Отдельная беда — магнитное склонение: стрелка показывает на магнитный полюс,
а карта нарисована относительно географического. Для Подмосковья расхождение
около +11°, и на километровом маршруте это сотни метров вбок.

Вся арифметика собрана здесь и проверяется тестами на компьютере; чтение
датчиков вынесено в отдельный класс и падает мягко, если их нет.
"""

from __future__ import annotations

import math

# Магнитное склонение по умолчанию, градусы. Положительное — стрелка
# отклоняется к востоку от истинного севера. Для средней полосы России
# около +11°, для Урала +15°, для Дальнего Востока может быть отрицательным.
DECLINATION = 11.0

# Сглаживание: показания магнитометра дрожат на 5-10° даже в покое.
# 0.15 — компромисс между дрожью и запаздыванием примерно в полсекунды.
SMOOTH = 0.15

# Порог наклона: если телефон почти вертикально (смотрят как в зеркало),
# горизонтальная проекция вырождается и курсу верить нельзя.
MAX_TILT_DEG = 65.0


def heading_from_vectors(mx: float, my: float, mz: float,
                         gx: float, gy: float, gz: float) -> float | None:
    """Курс телефона по магнитометру и акселерометру, 0..360 от севера.

    gx, gy, gz — вектор, направленный ВНИЗ (к центру Земли). Показания
    акселерометра Android направлены вверх, их надо подавать со знаком минус
    либо пользоваться heading_from_android_sensors.

    Возвращает None, если данные бессмысленные: нулевые векторы или телефон
    поднят почти вертикально.

    Алгоритм стандартный: сила тяжести задаёт вертикаль, магнитное поле
    проецируется на перпендикулярную ей плоскость, курс — угол проекции.
    """
    gn = math.sqrt(gx * gx + gy * gy + gz * gz)
    mn = math.sqrt(mx * mx + my * my + mz * mz)
    if gn < 1e-6 or mn < 1e-6:
        return None

    # единичный вектор «вниз»
    gx, gy, gz = gx / gn, gy / gn, gz / gn

    # наклон экрана от горизонтали
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, abs(gz)))))
    if tilt > MAX_TILT_DEG:
        return None

    # восток = гравитация × поле, север = восток × гравитация
    ex = gy * mz - gz * my
    ey = gz * mx - gx * mz
    ez = gx * my - gy * mx
    en = math.sqrt(ex * ex + ey * ey + ez * ez)
    if en < 1e-6:                      # поле параллельно вертикали
        return None
    ex, ey, ez = ex / en, ey / en, ez / en

    ny = ez * gx - ex * gz

    # Курс — направление верхней кромки телефона (ось Y устройства).
    # Берутся её составляющие вдоль востока и севера: atan2(восток, север)
    # даёт угол по часовой стрелке от севера, как и принято в навигации.
    return (math.degrees(math.atan2(ey, ny)) + 360.0) % 360.0


def heading_from_android_sensors(mx: float, my: float, mz: float,
                                 ax: float, ay: float, az: float) -> float | None:
    """То же, но на вход подаются СЫРЫЕ показания датчиков Android.

    Акселерометр Android (TYPE_ACCELEROMETER, он же plyer.accelerometer)
    в покое показывает вектор, направленный вверх: лежащий экраном вверх
    телефон даёт (0, 0, +9.8). Инвертируем и получаем «вниз».
    """
    return heading_from_vectors(mx, my, mz, -ax, -ay, -az)


def true_heading(magnetic: float, declination: float = DECLINATION) -> float:
    """Истинный курс из магнитного: прибавляем склонение."""
    return (magnetic + declination) % 360.0


def smooth_angle(prev: float | None, new: float, k: float = SMOOTH) -> float:
    """Сглаживание углов с учётом перехода через ноль.

    Наивное усреднение 359° и 1° даёт 180° — стрелка прыгает в другую
    сторону. Поэтому усредняются не углы, а векторы.
    """
    if prev is None:
        return new % 360.0
    pr, nr = math.radians(prev), math.radians(new)
    x = (1 - k) * math.cos(pr) + k * math.cos(nr)
    y = (1 - k) * math.sin(pr) + k * math.sin(nr)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_diff(a: float, b: float) -> float:
    """Кратчайший угол между направлениями, 0..180."""
    return abs((a - b + 540.0) % 360.0 - 180.0)


# --------------------------------------------------------------------------- #
#  Чтение датчиков напрямую через jnius
# --------------------------------------------------------------------------- #
#
# Почему не plyer. Его compass.enable() поднимает СРАЗУ два слушателя:
# TYPE_MAGNETIC_FIELD и TYPE_MAGNETIC_FIELD_UNCALIBRATED. Второго датчика на
# многих аппаратах просто нет, getDefaultSensor возвращает null, а
# SensorManager.registerListener(listener, null, delay) бросает
# IllegalArgumentException. В результате падает включение всего компаса,
# хотя обычный магнитометр в телефоне есть. Здесь берутся ровно те два
# датчика, которые нужны, и каждый — по отдельности.

class AndroidSensors:
    """Магнитометр и акселерометр напрямую. Слушатели держатся ссылкой:
    если их отдать сборщику мусора, приложение упадёт в нативном коде."""

    DELAY = 2                          # SensorManager.SENSOR_DELAY_UI

    def __init__(self):
        self.mag = [None, None, None]
        self.acc = [None, None, None]
        self._sm = None
        self._pairs = []               # [(listener, sensor), ...]
        self.error = ""

    def start(self) -> bool:
        try:
            from jnius import PythonJavaClass, autoclass, cast, java_method
        except ImportError:
            self.error = "не Android"
            return False
        try:
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            Context = autoclass("android.content.Context")
            Sensor = autoclass("android.hardware.Sensor")
            sm = cast("android.hardware.SensorManager",
                      activity.getSystemService(Context.SENSOR_SERVICE))

            class SensorListener(PythonJavaClass):
                __javainterfaces__ = ["android/hardware/SensorEventListener"]

                def __init__(self, target):
                    self.target = target      # список из трёх чисел
                    super().__init__()

                @java_method("(Landroid/hardware/SensorEvent;)V")
                def onSensorChanged(self, event):
                    try:
                        v = event.values
                        self.target[0] = v[0]
                        self.target[1] = v[1]
                        self.target[2] = v[2]
                    except Exception:                             # noqa: BLE001
                        pass

                @java_method("(Landroid/hardware/Sensor;I)V")
                def onAccuracyChanged(self, sensor, accuracy):
                    pass

            wanted = ((Sensor.TYPE_MAGNETIC_FIELD, self.mag, "магнитометра"),
                      (Sensor.TYPE_ACCELEROMETER, self.acc, "акселерометра"))
            for kind, target, title in wanted:
                sensor = sm.getDefaultSensor(kind)
                if sensor is None:
                    self.error = f"в телефоне нет {title}"
                    self.stop()
                    return False
                listener = SensorListener(target)
                sm.registerListener(listener, sensor, self.DELAY)
                self._pairs.append((listener, sensor))
            self._sm = sm
            return True
        except Exception as e:                                    # noqa: BLE001
            self.error = str(e)[:80]
            self.stop()
            return False

    def stop(self):
        for listener, sensor in self._pairs:
            try:
                if self._sm is not None:
                    self._sm.unregisterListener(listener, sensor)
            except Exception:                                     # noqa: BLE001
                pass
        self._pairs = []
        self._sm = None

    def read(self):
        """(поле, ускорение) или None, если данные ещё не пришли."""
        if self.mag[0] is None or self.acc[0] is None:
            return None
        return tuple(self.mag), tuple(self.acc)


class _PlyerSensors:
    """Запасной путь: те же два датчика, но через plyer."""

    def __init__(self):
        self._compass = None
        self._accel = None
        self.error = ""

    def start(self) -> bool:
        try:
            from plyer import accelerometer, compass as sensor
        except Exception as e:                                    # noqa: BLE001
            self.error = f"нет модуля датчиков: {e}"
            return False
        try:
            sensor.enable()
            accelerometer.enable()
        except Exception as e:                                    # noqa: BLE001
            self.error = f"датчики недоступны: {e}"
            return False
        self._compass, self._accel = sensor, accelerometer
        return True

    def stop(self):
        for s in (self._compass, self._accel):
            try:
                if s:
                    s.disable()
            except Exception:                                     # noqa: BLE001
                pass
        self._compass = self._accel = None

    def read(self):
        if self._compass is None:
            return None
        try:
            m = self._compass.field
            a = self._accel.acceleration
        except Exception:                                         # noqa: BLE001
            return None
        if not m or not a or m[0] is None or a[0] is None:
            return None
        return (m[0], m[1], m[2]), (a[0], a[1], a[2])


class Compass:
    """Чтение датчиков телефона. Без Android молча выключается.

    Использование:
        c = Compass()
        c.start()
        ...
        c.read()         # свежий курс, градусы или None
        c.heading()      # последний известный курс без обращения к датчикам
        c.stop()
    """

    def __init__(self, declination: float = DECLINATION):
        self.declination = declination
        self._src = None
        self._value = None
        self.available = False
        self.kind = ""
        self.error = ""

    def start(self) -> bool:
        errors = []
        for name, cls in (("jnius", AndroidSensors), ("plyer", _PlyerSensors)):
            src = cls()
            if src.start():
                self._src = src
                self.kind = name
                self.available = True
                self.error = ""
                return True
            errors.append(f"{name}: {src.error}")
        self.error = "; ".join(errors)
        return False

    def stop(self):
        if self._src is not None:
            self._src.stop()
        self._src = None
        self.available = False

    def read(self) -> float | None:
        """Свежий курс с учётом склонения и сглаживания."""
        if not self.available or self._src is None:
            return None
        data = self._src.read()
        if data is None:
            return None
        (mx, my, mz), (ax, ay, az) = data
        raw = heading_from_android_sensors(mx, my, mz, ax, ay, az)
        if raw is None:
            return None
        self._value = smooth_angle(self._value,
                                   true_heading(raw, self.declination))
        return self._value

    def heading(self) -> float | None:
        """Последний известный курс без обращения к датчикам."""
        return self._value
