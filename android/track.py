# -*- coding: utf-8 -*-
"""
track.py — запись маршрута по лесу, отметки находок, пройденное расстояние.

Грибник нажимает «Старт», телефон пишет точки; на карте рисуется траектория,
касанием ставятся метки находок. По окончании считается пройденное расстояние,
время, число находок и находок на километр, а сам поход можно выгрузить в GPX
и записать в журнал наблюдений — тот самый, по которому калибруется модель.

Про расстояние: сырой GPS-трек всегда длиннее реального пути, потому что точки
дрожат на месте. Поэтому точки с плохой точностью отбрасываются, а шаги короче
порога не засчитываются — иначе за час стояния у костра «набегает» километр.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime

import places as places_mod

TRACKS_DIR = "tracks"

MIN_STEP_M = 6.0        # шаги короче не засчитываются: дрожание приёмника
MAX_ACCURACY_M = 50.0   # обычный порог: точки хуже игнорируются

# Аварийный порог. Под пологом ельника приёмник нередко рапортует 60-80 м,
# и строгий фильтр отбрасывал ВСЁ: человек видел свою точку на карте, а трек
# оставался пустым. Лучше грубая линия, чем её отсутствие, поэтому после
# нескольких подряд отброшенных точек фильтр временно ослабляется.
FALLBACK_ACCURACY_M = 150.0
FALLBACK_AFTER = 5      # столько подряд отброшенных — и принимаем как есть
MAX_SPEED_MS = 8.0      # быстрее человек по лесу не идёт — выброс приёмника
EARTH_R = 6371008.8


def haversine(lat1, lon1, lat2, lon2) -> float:
    """Расстояние между точками по поверхности, м."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


@dataclass
class Point:
    lat: float
    lon: float
    t: float                       # время, unix-секунды
    acc: float = 0.0               # заявленная точность, м


@dataclass
class Find:
    """Метка на маршруте: находка, ориентир или просто наблюдение.

    Заметка и снимки — то, ради чего метку вообще стоит ставить. Через месяц
    «крупный, под елью» не восстановит ничего, а фотография восстановит всё,
    включая спорные определения: снял, вечером посмотрел в определитель.

    В photos лежат ИМЕНА файлов, а не пути. Каталог данных на Android
    меняется при переустановке приложения, и сохранённый абсолютный путь
    после неё указывает в никуда.
    """

    lat: float
    lon: float
    t: float
    species: str = ""              # ключ вида из SPECIES
    count: int = 1
    note: str = ""
    photos: list = field(default_factory=list)

    def has_details(self) -> bool:
        return bool(self.note.strip() or self.photos)


@dataclass
class Walk:
    """Один поход: точки маршрута и находки."""

    started: float = field(default_factory=time.time)
    finished: float | None = None
    points: list = field(default_factory=list)
    finds: list = field(default_factory=list)
    place: str = ""
    biotope: str = "смешанный"
    distance: float = 0.0          # накопленное расстояние, м
    skipped: int = 0               # отброшенные точки
    rough: int = 0                 # принятые по аварийному порогу точности
    last_acc: float = 0.0          # точность последней координаты, м
    _weak_streak: int = 0          # сколько точек подряд отбраковано

    # --- запись ------------------------------------------------------------
    def add_point(self, lat, lon, acc=0.0, t=None) -> bool:
        """Добавляет точку. Возвращает True, если она зачтена в маршрут."""
        t = time.time() if t is None else t
        self.last_acc = acc
        limit = (FALLBACK_ACCURACY_M if self._weak_streak >= FALLBACK_AFTER
                 else MAX_ACCURACY_M)
        if acc and acc > limit:
            self.skipped += 1
            self._weak_streak += 1
            return False
        if acc and acc > MAX_ACCURACY_M:
            self.rough += 1            # приняли по аварийному порогу
        self._weak_streak = 0
        if not self.points:
            self.points.append(Point(lat, lon, t, acc))
            return True
        last = self.points[-1]
        d = haversine(last.lat, last.lon, lat, lon)
        dt = max(0.5, t - last.t)
        if d / dt > MAX_SPEED_MS:                 # выброс приёмника
            self.skipped += 1
            return False
        if d < MIN_STEP_M:                        # дрожание на месте
            last.t = t                            # но человек здесь и сейчас:
            return False                          # иначе сломается проверка скорости
        self.points.append(Point(lat, lon, t, acc))
        self.distance += d
        return True

    def signal_state(self) -> str:
        """Что показать человеку про качество приёма: пусто — всё хорошо."""
        if not self.points and self.skipped >= 3:
            return (f"Сигнал слабый (точность {self.last_acc:.0f} м) — "
                    f"жду, пока приёмник соберёт спутники")
        if self.rough and self.rough * 3 >= len(self.points):
            return f"Сигнал неуверенный: линия маршрута будет грубой"
        return ""

    def add_find(self, lat, lon, species="", count=1, note="", photos=None) -> Find:
        f = Find(lat, lon, time.time(), species, count, note,
                 list(photos or []))
        self.finds.append(f)
        return f

    def photo_names(self) -> list:
        """Все снимки похода одним списком — для уборки и для показа."""
        out = []
        for f in self.finds:
            out.extend(f.photos)
        return out

    def undo_find(self):
        return self.finds.pop() if self.finds else None

    def stop(self):
        self.finished = time.time()

    # --- показатели ---------------------------------------------------------
    @property
    def duration(self) -> float:
        """Длительность по самим точкам, если они есть: надёжнее часов запуска."""
        if len(self.points) >= 2:
            return self.points[-1].t - self.points[0].t
        return (self.finished or time.time()) - self.started

    @property
    def km(self) -> float:
        return self.distance / 1000.0

    @property
    def finds_per_km(self) -> float:
        return len(self.finds) / self.km if self.km > 0.2 else 0.0

    def summary(self) -> str:
        h, m = divmod(int(self.duration // 60), 60)
        dur = f"{h} ч {m} мин" if h else f"{m} мин"
        s = f"{self.distance:.0f} м за {dur}"
        if self.finds:
            s += f", находок {len(self.finds)}"
            if self.km > 0.2:
                s += f" ({self.finds_per_km:.1f} на км)"
        return s

    def species_counts(self) -> dict:
        out = {}
        for f in self.finds:
            if f.species:
                out[f.species] = out.get(f.species, 0) + max(1, f.count)
        return out

    # --- хранение -----------------------------------------------------------
    def as_dict(self) -> dict:
        return {
            "version": 1, "started": self.started, "finished": self.finished,
            "place": self.place, "biotope": self.biotope,
            "distance": round(self.distance, 1), "skipped": self.skipped,
            "points": [[round(p.lat, 6), round(p.lon, 6), round(p.t, 1),
                        round(p.acc, 1)] for p in self.points],
            # Снимки — седьмым полем: старые записи из шести элементов
            # читаются как раньше, новые понимает старая версия приложения.
            "finds": [[round(f.lat, 6), round(f.lon, 6), round(f.t, 1),
                       f.species, f.count, f.note, list(f.photos)]
                      for f in self.finds],
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Walk":
        w = cls(started=float(raw.get("started", 0)),
                finished=raw.get("finished"),
                place=raw.get("place", ""),
                biotope=raw.get("biotope", "смешанный"),
                distance=float(raw.get("distance", 0.0)),
                skipped=int(raw.get("skipped", 0)))
        w.points = [Point(p[0], p[1], p[2], p[3] if len(p) > 3 else 0.0)
                    for p in raw.get("points", [])]
        w.finds = [Find(f[0], f[1], f[2], f[3] if len(f) > 3 else "",
                        int(f[4]) if len(f) > 4 else 1,
                        f[5] if len(f) > 5 else "",
                        list(f[6]) if len(f) > 6 and f[6] else [])
                   for f in raw.get("finds", [])]
        return w


# --------------------------------------------------------------------------- #
#  Каталог походов
# --------------------------------------------------------------------------- #

def _dir() -> str:
    d = os.path.join(places_mod.data_dir(), TRACKS_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def save(walk: Walk) -> str:
    name = datetime.fromtimestamp(walk.started).strftime("%Y-%m-%d_%H%M") + ".json"
    path = os.path.join(_dir(), name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(walk.as_dict(), f, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def load_all() -> list[Walk]:
    out = []
    for name in sorted(os.listdir(_dir()), reverse=True):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(_dir(), name), encoding="utf-8") as f:
                out.append(Walk.from_dict(json.load(f)))
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            continue
    return out


def all_photo_names() -> list:
    """Снимки, на которые ссылается хоть один сохранённый поход.

    Нужен для уборки: удалять всё, чего нет в текущем походе, нельзя —
    так пропадут кадры прошлых выездов, а они и есть архив.
    """
    out = []
    for walk in load_all():
        out.extend(walk.photo_names())
    return out


def gpx_escape(text: str) -> str:
    """Экранирование для XML.

    Заметку пишет человек, а не программа, и рано или поздно там окажется
    «просека 3 & 4» или «ёлка < 2 м». Без экранирования такой символ ломает
    весь файл: навигатор отказывается открывать поход целиком из-за одного
    амперсанда в подписи к метке.
    """
    return (str(text or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def to_gpx(walk: Walk) -> str:
    """Выгрузка в GPX: открывается в OsmAnd, Garmin, любом навигаторе."""
    def iso(t):
        return datetime.utcfromtimestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ")

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="mushroom-forecast" '
             'xmlns="http://www.topografix.com/GPX/1/1">',
             f"<metadata><time>{iso(walk.started)}</time></metadata>"]
    for f in walk.finds:
        label = gpx_escape(f.species or "находка")
        wpt = [f'<wpt lat="{f.lat:.6f}" lon="{f.lon:.6f}">',
               f'<time>{iso(f.t)}</time><name>{label}</name>',
               f'<desc>{gpx_escape(f.note)}</desc>']
        # Снимки — ссылками на файлы рядом с треком. OsmAnd и большинство
        # настольных программ показывают их прямо в карточке точки.
        for name in f.photos:
            wpt.append(f'<link href="photos/{gpx_escape(name)}">'
                       f'<text>снимок</text></link>')
        wpt.append("</wpt>")
        parts.append("".join(wpt))
    parts.append(f'<trk><name>Поход {iso(walk.started)}</name><trkseg>')
    for p in walk.points:
        parts.append(f'<trkpt lat="{p.lat:.6f}" lon="{p.lon:.6f}">'
                     f'<time>{iso(p.t)}</time></trkpt>')
    parts.append("</trkseg></trk></gpx>")
    return "\n".join(parts)


def export_gpx(walk: Walk) -> str:
    path = os.path.join(_dir(), datetime.fromtimestamp(walk.started)
                        .strftime("%Y-%m-%d_%H%M") + ".gpx")
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_gpx(walk))
    return path


# --------------------------------------------------------------------------- #
#  Связь с журналом наблюдений
# --------------------------------------------------------------------------- #

# Верхняя граница включительно -> балл обилия:
# 0 — не было, 1-3 — единично, 4-8 — мало, 9-20 — умеренно, 21-50 — обильно,
# больше 50 — массовый слой.
COUNT_TO_SCORE = [(0, 0), (3, 1), (8, 2), (20, 3), (50, 4)]


def count_to_score(n: int) -> int:
    """Число найденных штук -> балл обилия 0-5 для журнала."""
    for limit, score in COUNT_TO_SCORE:
        if n <= limit:
            return score
    return 5


def to_journal(walk: Walk, journal_module, path=None, extra_zero=()) -> int:
    """Записывает находки похода в журнал наблюдений. Возвращает число строк.

    extra_zero — виды, которые искали и не нашли: их полезно записать нулём,
    иначе модель никогда не научится отговаривать от поездки.
    """
    if not walk.points:
        return 0
    lat = sum(p.lat for p in walk.points) / len(walk.points)
    lon = sum(p.lon for p in walk.points) / len(walk.points)
    d = datetime.fromtimestamp(walk.started).date()
    counts = walk.species_counts()
    rows = 0
    target = path or journal_module.JOURNAL
    for key, n in counts.items():
        journal_module.append(target, journal_module.Entry(
            d, walk.place, lat, lon, key, count_to_score(n),
            f"поход {walk.distance:.0f} м, штук {n}", walk.biotope))
        rows += 1
    for key in extra_zero:
        if key in counts:
            continue
        journal_module.append(target, journal_module.Entry(
            d, walk.place, lat, lon, key, 0,
            f"поход {walk.distance:.0f} м, не найдено", walk.biotope))
        rows += 1
    return rows
