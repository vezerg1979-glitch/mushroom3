# -*- coding: utf-8 -*-
"""
history.py — прошлые походы на карте текущего похода.

Зачем. Грибник ходит по одним и тем же местам годами и держит их в голове:
«за той просекой у трёх ёлок в конце августа берут белые». Голова эти места
теряет — особенно через год и особенно чужой лес. Приложение всё это время
их записывало: маршруты в tracks/, находки с видом, числом и координатой.
Пока они лежали только в журнале, толку от них в лесу не было никакого:
пролистать список записей на ходу нельзя.

Здесь то же самое превращается в подложку карты: блёклые нитки старых
маршрутов и точки находок поверх них. Тогда поход строится не наугад, а по
известным местам — видно, где уже ходил, где брал и куда ещё не заглядывал.

Что модуль делает, кроме чтения файлов:

  прореживание — сырой трек это тысячи точек с шагом в пару метров. Рисовать
    их все на каждый тик GPS нельзя: карта начнёт заикаться, а на экране
    разницы никакой. Дуглас-Пойкер оставляет форму маршрута и выкидывает
    остальное;

  слияние находок — пять меток, поставленных у одной ели за три года, дают
    на карте кляксу вместо места. Близкие находки сливаются в одну точку, и
    её размер говорит, сколько там брали всего.

Kivy модуль не знает: вся арифметика проверяется тестами на компьютере, а
рисует mapview.TileMap.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import track as track_mod

# Прореживание. 12 м — примерно ширина просеки: изгибы крупнее сохраняются,
# мелкое дрожание приёмника уходит.
SIMPLIFY_M = 12.0

# Сколько точек оставлять на маршрут после прореживания. Потолок нужен для
# многочасовых походов: они и после Дугласа-Пойкера бывают в тысячу точек.
MAX_TRAIL_POINTS = 300

# Радиус слияния находок. 30 м — это то расстояние, в пределах которого
# человек скажет «то же самое место»; при этом две соседние куртины лисичек
# в разных концах поляны не склеиваются в одну.
MERGE_M = 30.0

# Сколько последних походов брать. Пятьдесят — это несколько сезонов; больше
# карта всё равно не покажет, а память и время загрузки растут.
MAX_WALKS = 50


# --------------------------------------------------------------------------- #
#  Данные
# --------------------------------------------------------------------------- #

@dataclass
class Trail:
    """Прореженный маршрут одного похода."""

    points: list                    # [(lat, lon), ...]
    started: float = 0.0
    place: str = ""

    @property
    def age_days(self) -> float:
        return max(0.0, (time.time() - self.started) / 86400.0)

    def bbox(self) -> tuple:
        """(min_lat, min_lon, max_lat, max_lon) — для отсечения по экрану."""
        lats = [p[0] for p in self.points]
        lons = [p[1] for p in self.points]
        return min(lats), min(lons), max(lats), max(lons)


@dataclass
class Spot:
    """Место, где брали: одна или несколько слитых находок.

    lat/lon названы именно так не случайно: с этими полями точку принимает
    навигация (walkscreen.navigate_to), и по старой находке можно идти как
    по метке.
    """

    lat: float
    lon: float
    count: int = 0                  # сколько всего штук взято
    visits: int = 0                 # сколько отдельных находок слилось
    last_t: float = 0.0             # когда были здесь в последний раз
    species: str = ""               # преобладающий вид, ключ SPECIES
    kinds: dict = field(default_factory=dict)   # вид -> штук

    @property
    def age_days(self) -> float:
        return max(0.0, (time.time() - self.last_t) / 86400.0)


@dataclass
class History:
    trails: list = field(default_factory=list)
    spots: list = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.trails or self.spots)

    def summary(self) -> str:
        """Строка для подписи под картой."""
        if not self:
            return "Прошлых походов пока нет"
        t, s = len(self.trails), len(self.spots)
        return (f"Прошлые походы: {t} " + _plural(t, "маршрут", "маршрута", "маршрутов")
                + f", {s} " + _plural(s, "место находок", "места находок",
                                      "мест находок"))


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


# --------------------------------------------------------------------------- #
#  Прореживание
# --------------------------------------------------------------------------- #

def _local_xy(points: list) -> list:
    """Широта/долгота -> метры от первой точки.

    Дуглас-Пойкер меряет расстояния, а градус долготы на широте Москвы вдвое
    короче градуса широты. Без пересчёта прореживание съедало бы изгибы по
    одной оси сильнее, чем по другой.
    """
    lat0 = points[0][0]
    k = math.cos(math.radians(lat0))
    m_per_deg = math.pi * track_mod.EARTH_R / 180.0
    return [((lon - points[0][1]) * m_per_deg * k,
             (lat - points[0][0]) * m_per_deg) for lat, lon in points]


def _perp(px, py, ax, ay, bx, by) -> float:
    """Расстояние от точки до отрезка."""
    dx, dy = bx - ax, by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def simplify(points: list, tol_m: float = SIMPLIFY_M) -> list:
    """Дуглас-Пойкер: та же линия меньшим числом точек.

    Цикл, а не рекурсия: на многочасовом треке рекурсивная версия упирается
    в предел вложенности интерпретатора и валит приложение при открытии
    карты — то есть ровно там, где человек его открывает в лесу.
    """
    if len(points) < 3:
        return list(points)
    xy = _local_xy(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        ax, ay = xy[i]
        bx, by = xy[j]
        worst, at = -1.0, -1
        for k in range(i + 1, j):
            d = _perp(xy[k][0], xy[k][1], ax, ay, bx, by)
            if d > worst:
                worst, at = d, k
        if worst > tol_m:
            keep[at] = True
            stack.append((i, at))
            stack.append((at, j))
    return [p for p, k in zip(points, keep) if k]


def thin(points: list, limit: int = MAX_TRAIL_POINTS) -> list:
    """Жёсткий потолок числа точек: берём каждую n-ю, концы сохраняем."""
    if len(points) <= limit or limit < 2:
        return list(points)
    step = len(points) / float(limit - 1)
    out = [points[min(len(points) - 1, int(i * step))] for i in range(limit - 1)]
    out.append(points[-1])
    return out


# --------------------------------------------------------------------------- #
#  Слияние находок
# --------------------------------------------------------------------------- #

def merge(finds: list, radius_m: float = MERGE_M) -> list:
    """Близкие находки -> одна точка места.

    finds — объекты с lat, lon, t, species, count (track.Find или что угодно
    с теми же полями). Порядок результата не зависит от порядка входа:
    точки сортируются по числу взятого, чтобы самые грибные рисовались
    последними и не оказались под соседними.
    """
    spots: list[Spot] = []
    for f in sorted(finds, key=lambda x: getattr(x, "t", 0.0)):
        lat, lon = float(f.lat), float(f.lon)
        n = max(1, int(getattr(f, "count", 1) or 1))
        key = getattr(f, "species", "") or ""
        best, best_d = None, radius_m
        for s in spots:
            d = track_mod.haversine(lat, lon, s.lat, s.lon)
            if d <= best_d:
                best, best_d = s, d
        t = float(getattr(f, "t", 0.0) or 0.0)
        if best is None:
            spots.append(Spot(lat=lat, lon=lon, count=n, visits=1, last_t=t,
                              species=key, kinds={key: n} if key else {}))
            continue
        # Центр места — среднее по находкам: одна неточная координата под
        # пологом не должна утаскивать всю точку в сторону.
        w = best.visits
        best.lat = (best.lat * w + lat) / (w + 1)
        best.lon = (best.lon * w + lon) / (w + 1)
        best.visits += 1
        best.count += n
        best.last_t = max(best.last_t, t)
        if key:
            best.kinds[key] = best.kinds.get(key, 0) + n
    for s in spots:
        if s.kinds:
            s.species = max(s.kinds.items(), key=lambda kv: kv[1])[0]
    spots.sort(key=lambda s: s.count)
    return spots


# --------------------------------------------------------------------------- #
#  Загрузка
# --------------------------------------------------------------------------- #

def load(max_walks: int = MAX_WALKS, skip_started: float | None = None,
         tol_m: float = SIMPLIFY_M, radius_m: float = MERGE_M) -> History:
    """Читает сохранённые походы и готовит слой для карты.

    skip_started — время начала похода, который рисовать не надо (текущий,
    если его уже успели сохранить: иначе поверх живого трека ляжет его же
    блёклая копия и человек решит, что запись раздвоилась).

    Вызывать в отдельном потоке: за несколько сезонов тут набирается сотня
    файлов, и на телефоне это заметная пауза. Окно похода должно открываться
    мгновенно — слой доедет через секунду.
    """
    walks = track_mod.load_all()[:max_walks]
    trails, finds = [], []
    for w in walks:
        if skip_started is not None and abs(w.started - skip_started) < 1.0:
            continue
        finds.extend(w.finds)
        if len(w.points) >= 2:
            pts = thin(simplify([(p.lat, p.lon) for p in w.points], tol_m))
            trails.append(Trail(points=pts, started=w.started, place=w.place))
    return History(trails=trails, spots=merge(finds, radius_m))
