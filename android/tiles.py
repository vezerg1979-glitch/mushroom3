# -*- coding: utf-8 -*-
"""
tiles.py — скачивание квадрата карты впрок, чтобы она работала в лесу.

TileMap кэширует на диск то, что человек уже открывал. Проблема в том, что
открывает он карту дома по вайфаю на одном масштабе, а в лесу двигает и
приближает — и упирается в пустые клетки. Поэтому район вокруг точки нужно
залить заранее, целиком и на нескольких масштабах.

Арифметика вынесена сюда отдельно от загрузки: сколько тайлов получится и
сколько это мегабайт, надо знать ДО того, как человек нажмёт кнопку. Скачать
пол-области по ошибке легко, а вот заметить это в лесу — поздно.

Правила OSM: тайлы отдаются бесплатно, но с оговорками — обязательный
User-Agent, никакой массовой выкачки. Радиус ограничен намеренно: 5 км на трёх
масштабах — это сотни тайлов, что для личного пользования нормально, а
скачивание области размером с губернию сервер вправе заблокировать.
"""

from __future__ import annotations

import math
import os
import time
import urllib.error
import urllib.request

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
UA = "mushroom-forecast/2.2 (personal offline use)"

# Масштабы: 13 — обзор района, 15 — просеки и поляны, 16 — тропинки.
# Больше 16 не берём: объём растёт вчетверо на шаг, а толку в лесу мало.
ZOOMS = (13, 15, 16)

MAX_RADIUS_KM = 5.0
MAX_TILES = 1200                  # предохранитель от случайной выкачки
AVG_TILE_BYTES = 14000            # средний лесной тайл: зелень жмётся хорошо
PAUSE = 0.12                      # пауза между запросами, щадящая к серверу


def deg2num(lat: float, lon: float, z: int) -> tuple[int, int]:
    """Координаты тайла, в котором лежит точка."""
    lat_r = math.radians(lat)
    n = 2.0 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def tile_span(lat: float, z: int) -> float:
    """Ширина тайла на местности, м. Нужна, чтобы перевести радиус в клетки."""
    return 40075016.686 * math.cos(math.radians(lat)) / (2.0 ** z)


def tile_range(lat: float, lon: float, radius_m: float, z: int):
    """Диапазон тайлов, покрывающих круг радиусом radius_m: (x0, x1, y0, y1)."""
    span = tile_span(lat, z)
    k = max(0, int(math.ceil(radius_m / span)))
    x, y = deg2num(lat, lon, z)
    n = int(2.0 ** z)
    return (max(0, x - k), min(n - 1, x + k),
            max(0, y - k), min(n - 1, y + k))


def plan(lat: float, lon: float, radius_km: float = 2.0, zooms=ZOOMS) -> list:
    """Список тайлов к скачиванию: [(z, x, y), ...]."""
    radius_m = min(radius_km, MAX_RADIUS_KM) * 1000.0
    out = []
    for z in zooms:
        x0, x1, y0, y1 = tile_range(lat, lon, radius_m, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                out.append((z, x, y))
    return out


def estimate(lat: float, lon: float, radius_km: float = 2.0, zooms=ZOOMS) -> dict:
    """Что получится, если нажать «скачать»: клеток, мегабайт, минут."""
    items = plan(lat, lon, radius_km, zooms)
    n = len(items)
    return {
        "tiles": n,
        "megabytes": n * AVG_TILE_BYTES / 1024.0 / 1024.0,
        "minutes": n * (PAUSE + 0.25) / 60.0,
        "too_many": n > MAX_TILES,
    }


def describe(lat: float, lon: float, radius_km: float = 2.0, zooms=ZOOMS) -> str:
    """Человеческая формулировка для диалога подтверждения."""
    e = estimate(lat, lon, radius_km, zooms)
    if e["too_many"]:
        return (f"Слишком большая область: {e['tiles']} клеток. "
                f"Уменьшите радиус — сервер OSM не любит массовую выкачку.")
    return (f"{e['tiles']} клеток, примерно {e['megabytes']:.0f} МБ "
            f"и {max(1, round(e['minutes']))} мин загрузки")


def cached(items, cache_dir: str) -> int:
    """Сколько из списка уже лежит на диске."""
    return sum(1 for z, x, y in items
               if os.path.exists(os.path.join(cache_dir, f"{z}_{x}_{y}.png")))


def download(items, cache_dir: str, on_progress=None, should_stop=None) -> dict:
    """Качает тайлы в кэш. Возвращает счётчики: сделано, пропущено, ошибок.

    Функция блокирующая — вызывать из отдельного потока, иначе интерфейс
    замрёт на несколько минут. on_progress(done, total) зовётся после каждой
    клетки, should_stop() позволяет прервать по кнопке «Отмена».
    """
    os.makedirs(cache_dir, exist_ok=True)
    total = len(items)
    done = skipped = failed = 0

    for i, (z, x, y) in enumerate(items, 1):
        if should_stop and should_stop():
            break
        path = os.path.join(cache_dir, f"{z}_{x}_{y}.png")
        if os.path.exists(path):
            skipped += 1
        else:
            try:
                req = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y),
                                             headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
                tmp = path + ".part"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)       # чтобы в кэш не попал обрывок
                done += 1
                time.sleep(PAUSE)
            except (urllib.error.URLError, TimeoutError, OSError):
                failed += 1
        if on_progress:
            on_progress(i, total)

    return {"downloaded": done, "skipped": skipped, "failed": failed,
            "total": total}


def cache_dir() -> str:
    """Тот же каталог, что использует TileMap: кэш общий, качаем ему.

    Импорт places внутри функции намеренно: tiles.py должен оставаться
    пригодным для тестов на компьютере, где Kivy может быть не установлен,
    а places тянет за собой ядро прогноза.
    """
    import places as places_mod
    d = os.path.join(places_mod.data_dir(), "tiles")
    os.makedirs(d, exist_ok=True)
    return d


def cache_size_mb(cache_dir: str) -> float:
    """Сколько места занял офлайн-кэш карты."""
    if not os.path.isdir(cache_dir):
        return 0.0
    total = 0
    for name in os.listdir(cache_dir):
        try:
            total += os.path.getsize(os.path.join(cache_dir, name))
        except OSError:
            pass
    return total / 1024.0 / 1024.0
