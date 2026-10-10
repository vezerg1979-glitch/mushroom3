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

Про правила. Общие серверы OpenStreetMap прямо запрещают скачивание карты
впрок: они живут на пожертвования, а нарушителей блокируют без предупреждения
и по User-Agent — то есть карта отвалилась бы у всех, кто поставил приложение.
Поэтому download() отказывается работать, пока источником подложки стоит OSM,
и требует источника, владелец которого офлайн разрешает (см. tilesource.py).
Радиус и число тайлов ограничены сверх того: даже на своём сервере скачать
пол-области по ошибке легко, а заметить это в лесу — поздно.
"""

from __future__ import annotations

import math
import os
import time
import urllib.error
import urllib.request

UA = "mushroom-forecast/2.8 (personal offline use)"


def tile_url() -> str:
    """Шаблон адреса тайлов из настроек. Отдельной функцией, чтобы смена
    источника подхватывалась без перезапуска приложения."""
    import tilesource
    return tilesource.url()

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
                f"Уменьшите радиус — столько и качать долго, "
                f"и место на карточке занимает.")
    return (f"{e['tiles']} клеток, примерно {e['megabytes']:.0f} МБ "
            f"и {max(1, round(e['minutes']))} мин загрузки")


def cached(items, cache_dir: str) -> int:
    """Сколько из списка уже лежит на диске."""
    return sum(1 for z, x, y in items
               if os.path.exists(os.path.join(cache_dir, f"{z}_{x}_{y}.png")))


class NotAllowed(RuntimeError):
    """Источник подложки не разрешает скачивание впрок."""


def check_allowed():
    """Бросает NotAllowed, если качать с текущего источника нельзя.

    Проверка живёт здесь, а не только в окне: скачивание впрок — это про
    чужие серверы и чужие правила, и оно должно быть невозможно любым
    путём, а не только мимо кнопки.
    """
    import tilesource
    if not tilesource.allows_offline():
        raise NotAllowed(
            f"{tilesource.name()} не разрешает скачивание карты впрок. "
            f"Укажите свой сервер тайлов или поставщика, который офлайн "
            f"разрешает.")


def download(items, cache_dir: str, on_progress=None, should_stop=None) -> dict:
    """Качает тайлы в кэш. Возвращает счётчики: сделано, пропущено, ошибок.

    Функция блокирующая — вызывать из отдельного потока, иначе интерфейс
    замрёт на несколько минут. on_progress(done, total) зовётся после каждой
    клетки, should_stop() позволяет прервать по кнопке «Отмена».

    Бросает NotAllowed, если источник подложки офлайн не разрешает.
    """
    check_allowed()
    url_template = tile_url()
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
                req = urllib.request.Request(
                    url_template.format(z=z, x=x, y=y),
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


def clear_cache(cache_dir: str = None) -> int:
    """Стирает скачанные тайлы. Возвращает число удалённых файлов.

    Кэш растёт молча и незаметно, а места на телефоне всегда мало. Карта
    после очистки не ломается: клетки просто подгрузятся заново при сети.
    """
    directory = cache_dir or globals()["cache_dir"]()
    gone = 0
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    for name in names:
        if not name.endswith(".png"):
            continue
        try:
            os.remove(os.path.join(directory, name))
            gone += 1
        except OSError:
            continue
    return gone


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
