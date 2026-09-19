# -*- coding: utf-8 -*-
"""
proximity.py — короткая вибрация рядом с прошлогодней находкой.

Грибница живёт годами и плодоносит на том же месте. Человек это знает и
именно поэтому ведёт журнал, — но в лесу, глядя под ноги, он проходит
мимо своей же прошлогодней точки в двадцати метрах и не вспоминает о ней:
на карту он смотрит, когда заблудился, а не когда ищет.

Отсюда задача: не показать, а тронуть. Телефон в кармане коротко дёргается,
и человек уже сам решает, доставать его или нет. Ничего не открывается,
экран не включается, идти никуда не заставляют.

Всё, что здесь есть, — правила молчания. Их больше, чем правил срабатывания,
и это не случайно: вибрация, которая срабатывает не вовремя или слишком
часто, раздражает сильнее, чем радует, и её выключат вместе с полезной.

  * Одно место — один раз за поход. Человек ходит вокруг куста, то входя в
    круг, то выходя; без этого правила телефон дёргался бы каждые полминуты.
  * Пауза между любыми срабатываниями. Места находок кучные: пройдя по
    старой делянке, можно собрать пять подряд.
  * Молчание в начале похода. Машину ставят там же, где ставили в прошлый
    раз, а прошлогодние находки часто у самой опушки: первое, что получил
    бы человек, нажав «Старт», — вибрацию про место, на котором он стоит.
  * Молчание при плохом приёме. Когда точность хуже радиуса, «в двадцати
    метрах» — выдумка, и проверить её человек не сможет.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import mushroom_forecast as engine
from track import haversine

#: На таком расстоянии гриб ещё имеет смысл искать глазами.
RADIUS_M = 30.0

#: Хуже этой точности координат срабатывание — обман: приёмник сам не
#: знает, где стоит человек.
MAX_ACC_M = 25.0

#: Пауза между любыми срабатываниями.
QUIET_S = 180.0

#: Молчание в начале похода: у машины, где всё и начинается.
GRACE_S = 120.0

#: Место, куда за все годы ходили один раз и взяли один гриб, вибрации не
#: стоит: случайная находка не означает грибницу.
MIN_COUNT = 2


@dataclass
class Hit:
    """Сработка: место, расстояние до него и готовая подпись."""

    spot: object
    distance: float
    text: str


@dataclass
class Watcher:
    """Следит за приближением к старым местам в течение одного похода.

    Состояние (что уже сработало и когда) живёт здесь, а не в экране:
    правила молчания — это и есть вся суть, и проверять их надо там, где их
    видно, а не по всему коду похода.
    """

    spots: list = field(default_factory=list)
    started: float = 0.0
    radius: float = RADIUS_M
    quiet: float = QUIET_S
    grace: float = GRACE_S
    _fired: set = field(default_factory=set)
    _last: float = 0.0

    def check(self, lat: float, lon: float, acc: float = 0.0,
              t: float = None) -> Hit | None:
        """Проверяет текущее место. None — молчим (и это обычный случай)."""
        t = time.time() if t is None else t
        if not self.spots:
            return None
        if self.started and t - self.started < self.grace:
            return None
        if acc and acc > MAX_ACC_M:
            return None
        if self._last and t - self._last < self.quiet:
            return None

        best, best_d = None, self.radius
        for i, spot in enumerate(self.spots):
            if i in self._fired or spot.count < MIN_COUNT:
                continue
            d = haversine(lat, lon, spot.lat, spot.lon)
            if d < best_d:
                best, best_d = i, d
        if best is None:
            return None

        self._fired.add(best)
        self._last = t
        spot = self.spots[best]
        return Hit(spot=spot, distance=best_d, text=text(spot, best_d))

    def reset(self):
        self._fired.clear()
        self._last = 0.0


def text(spot, distance: float) -> str:
    """Подпись под картой: что здесь было и когда.

    Без побуждений. «Поищите вокруг» превращает подсказку в указание, а
    человек и так знает, что делать: он за этим сюда и пришёл.
    """
    name = (engine.SPECIES[spot.species].name.lower()
            if spot.species in engine.SPECIES else "грибы")
    bits = [f"{round(distance / 5) * 5:.0f} м: здесь брали {name}"]
    if spot.count > 1:
        bits.append(f"{spot.count} шт")
    bits.append(_ago(spot.age_days))
    return ", ".join(bits)


def _ago(days: float) -> str:
    """«в прошлом сезоне», «три недели назад» — без точных дат.

    Точная дата тут лишняя: важно, свежая это находка или прошлогодняя, а
    «14 сентября 2024» человек всё равно переведёт в «в позапрошлом году».
    """
    if days < 10:
        return "на днях"
    if days < 40:
        return f"{int(round(days / 7))} недели назад"
    if days < 200:
        return f"{int(round(days / 30))} месяца назад"
    years = max(1, int(round(days / 365)))
    if years == 1:
        return "в прошлом сезоне"
    if years == 2:
        return "два сезона назад"
    return f"{years} сезона назад"
