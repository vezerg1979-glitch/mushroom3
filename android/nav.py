# -*- coding: utf-8 -*-
"""
nav.py — навигация для грибника: куда идти и сколько осталось.

Модуль намеренно не знает ни про Kivy, ни про Android: только числа и строки.
Благодаря этому он целиком проверяется тестами на компьютере, а на телефоне
остаётся ровно та часть, которая читает координаты.

Задача, ради которой всё затевалось: человек ушёл в лес по кривой траектории,
через три часа хочет вернуться к машине. Прямой азимут ему полезнее карты —
в ельнике карту разглядывать некогда, а «на северо-восток, 740 м» понятно сразу.

Как определяется, куда повёрнут человек. Компас в телефоне врёт под пологом
и рядом с ножом в кармане, поэтому основной источник — курс движения,
посчитанный по последним точкам трека: если человек идёт, направление известно
точно. Компас (если он есть) берётся запасным вариантом на случай остановки.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_R = 6371000.0

# Минимальный сдвиг, по которому имеет смысл считать курс движения.
# Меньше — это дрожание приёмника, а не поворот человека.
COURSE_MIN_M = 12.0

# Сколько последних точек усредняется в курс: одна пара слишком дёргается.
COURSE_SPAN = 4

# Ближе этого расстояния направление теряет смысл: цель уже вот она.
ARRIVED_M = 15.0

RUMBS = ["север", "северо-восток", "восток", "юго-восток",
         "юг", "юго-запад", "запад", "северо-запад"]

RUMBS_SHORT = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]

# Восемь направлений относительно движения: куда повернуть.
#
# Словами, без стрелок: в шрифте, который Kivy кладёт в APK, знаков ← ↑ → ↓
# нет вовсе, и на телефоне вместо стрелки выходил пустой квадрат. Направление
# и без них показано — крупной рисованной стрелкой над этой подписью
# (navwidget.py), так что подпись только называет поворот словом.
CLOCK = ["прямо", "вправо-вперёд", "направо", "вправо-назад",
         "назад", "влево-назад", "налево", "влево-вперёд"]


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние по земной поверхности, м."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Азимут из точки 1 на точку 2: градусы от севера по часовой, 0..360."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def rumb(deg: float, short: bool = False) -> str:
    """Румб по азимуту: «северо-восток» или «СВ»."""
    i = int((deg % 360.0 + 22.5) // 45) % 8
    return RUMBS_SHORT[i] if short else RUMBS[i]


def relative(target_deg: float, course_deg: float) -> float:
    """Куда поворачивать относительно движения: -180..180, плюс — вправо."""
    d = (target_deg - course_deg + 540.0) % 360.0 - 180.0
    return d


def turn_hint(target_deg: float, course_deg: float) -> str:
    """Словесная команда: «прямо», «направо» и так далее."""
    i = int((relative(target_deg, course_deg) % 360.0 + 22.5) // 45) % 8
    return CLOCK[i]


def course_over_ground(points, span: int = COURSE_SPAN):
    """Курс движения по хвосту трека, градусы, или None если человек стоит.

    Точки — любые объекты с полями lat и lon (Point из track.py подходит).
    Берётся не последняя пара, а отрезок от точки span назад: пара точек
    даёт скачущее на десятки градусов направление даже при ровной ходьбе.
    """
    if not points or len(points) < 2:
        return None
    tail = points[-span:] if len(points) >= span else points[:]
    a, b = tail[0], tail[-1]
    if haversine(a.lat, a.lon, b.lat, b.lon) < COURSE_MIN_M:
        return None
    return bearing(a.lat, a.lon, b.lat, b.lon)


def fmt_distance(m: float) -> str:
    """Расстояние человеческими словами: 340 м, 1.2 км."""
    if m < 1000:
        return f"{int(round(m / 10.0)) * 10} м"
    return f"{m / 1000.0:.1f} км".replace(".", ",")


def walk_minutes(m: float, speed_kmh: float = 2.5) -> int:
    """Сколько идти пешком по лесу. 2.5 км/ч — скорость с корзиной и буреломом."""
    return max(1, int(round(m / (speed_kmh * 1000.0 / 60.0))))


@dataclass
class Fix:
    """Ответ навигатора на вопрос «где цель и куда идти»."""
    distance: float                  # метров до цели
    bearing: float                   # азимут на цель, градусы от севера
    course: float | None             # курс движения или None, если стоим
    arrived: bool                    # дошли, дальше вести некуда

    @property
    def text(self) -> str:
        """Строка для крупной надписи на экране."""
        if self.arrived:
            return "вы на месте"
        where = (turn_hint(self.bearing, self.course) if self.course is not None
                 else f"на {rumb(self.bearing)}")
        return f"{where} · {fmt_distance(self.distance)}"

    @property
    def detail(self) -> str:
        """Вторая строка помельче: азимут и время хода."""
        if self.arrived:
            return ""
        head = f"азимут {self.bearing:.0f}° ({rumb(self.bearing, short=True)})"
        if self.course is None:
            head += " · стойте и идите — курс появится через десяток шагов"
        return f"{head} · ~{walk_minutes(self.distance)} мин"

    @property
    def arrow_deg(self) -> float:
        """Поворот стрелки на экране: 0 — вверх, по часовой стрелке.

        Когда курс известен, стрелка показывает относительно движения:
        человек держит телефон перед собой и идёт туда, куда она смотрит.
        Когда стоим — стрелка показывает абсолютный азимут, и её нужно
        совмещать с севером по солнцу или компасу.
        """
        return self.bearing if self.course is None else relative(self.bearing,
                                                                 self.course) % 360.0


def guide(lat: float, lon: float, target_lat: float, target_lon: float,
          points=None) -> Fix:
    """Главная функция: где цель относительно текущего положения."""
    d = haversine(lat, lon, target_lat, target_lon)
    return Fix(distance=d,
               bearing=bearing(lat, lon, target_lat, target_lon),
               course=course_over_ground(points) if points else None,
               arrived=d <= ARRIVED_M)


def guide_to_start(walk) -> Fix | None:
    """Навигация обратно к машине.

    Цель берётся у самого похода (walk.home_point): это отмеченная машина,
    а если её не отмечали — первая точка маршрута. Раньше здесь всегда
    стояла первая точка, и стрелка вела к месту, где человек нажал «Старт»:
    к дому, к повороту с шоссе, к чему угодно.
    """
    pts = getattr(walk, "points", None)
    if not pts:
        return None
    home = walk.home_point() if hasattr(walk, "home_point") else pts[0]
    if home is None:
        return None
    now = pts[-1]
    return guide(now.lat, now.lon, home.lat, home.lon, pts)


def nearest(lat: float, lon: float, targets) -> tuple:
    """Ближайшая цель из списка: (объект, расстояние) или (None, inf).

    Годится и для «моих мест» (Spot), и для находок (Find) — нужны только
    поля lat и lon.
    """
    best, best_d = None, float("inf")
    for t in targets or ():
        d = haversine(lat, lon, t.lat, t.lon)
        if d < best_d:
            best, best_d = t, d
    return best, best_d


def spread(points) -> float:
    """Насколько человек удалялся от старта, м. Для оценки «как далеко зашёл»."""
    if not points or len(points) < 2:
        return 0.0
    s = points[0]
    return max(haversine(s.lat, s.lon, p.lat, p.lon) for p in points)
