# -*- coding: utf-8 -*-
"""
heatfetch.py — где взять погоду на все клетки сетки разом.

Про то, что здесь не проверено. Open-Meteo, по моим сведениям, принимает
несколько точек одним запросом — координаты через запятую в тех же
параметрах `latitude`/`longitude`, а ответ приходит списком, по одному
элементу на точку, в том же порядке. Живьём это здесь никогда не
исполнялось: у среды, в которой писался этот код, нет доступа в интернет
за пределами нескольких сервисов пакетов, и проверить пакетный запрос
вживую было нечем. Поэтому код написан так, чтобы ошибиться в этом
предположении было не страшно: `_try_batch` проверяет форму ответа —
список нужной длины, у каждого элемента есть `daily` — и при любом
расхождении просто возвращает False, не трогая клетки. `fetch_grid` в этом
случае молча переходит на запросы по одной точке — то, что в проекте уже
год как проверено и работает. Один раз убедиться на реальном отклике —
и можно со спокойной душой удалить это предупреждение.

Почему это вообще стоит делать. Сетка в 36 точек по одной — это 36-100
запросов подряд (перебор почвенных слоёв на КАЖДОЙ точке при неудаче
множит цифру дальше), с паузами, чтобы не выглядеть как атака на чужой
сервис. Одним запросом — секунды вместо минуты с лишним, и совсем другое
ощущение на телефоне.

Почему перебор слоёв почвы делается один раз, а не на каждую клетку.
Сервис, поддерживающий данные о почве в одной точке области, почти
наверняка поддерживает их и в соседних — это тот же региональный набор
станций и той же модели, не посточечная лотерея. Пробовать 36 раз то, что
можно узнать одним пробным запросом по центру сетки, — трата времени и
трафика без всякой пользы взамен.
"""

from __future__ import annotations

import time

import heatgrid
import mushroom_forecast as engine

#: Пауза между последовательными запросами при отказе от пакетного режима.
#: Без неё десятки запросов подряд выглядят как нагрузочный тест чужого
#: бесплатного сервиса, а не как один человек, смотрящий на карту.
THROTTLE_S = 0.35

#: Пакетный запрос везёт больше данных, чем один — тайм-аут щедрее.
BATCH_TIMEOUT_S = 40


def fetch_grid(grid: heatgrid.Grid, forecast_days: int = 7,
               on_progress=None) -> heatgrid.Grid:
    """Заполняет grid.cells погодой и индексом. Возвращает тот же grid.

    Минимум два обращения к сети даже в лучшем случае: одно — подобрать
    слои почвы по центру сетки, второе — пакетный запрос по всем клеткам
    этими же ключами. Дальше идёт резервный путь, если пакетный не
    получился, и он тоже использует уже подобранные ключи, а не выясняет
    их заново на каждой клетке.

    on_progress(done, total), если передан, вызывается по ходу дела — и в
    пакетном режиме (0 и total, промежуточных чисел там взяться неоткуда:
    один HTTP-запрос либо весь прошёл, либо весь нет), и в резервном, где
    прогресс настоящий, по одной клетке.
    """
    cells = grid.cells
    if not cells:
        return grid
    if on_progress:
        on_progress(0, len(cells))

    center = cells[len(cells) // 2]
    try:
        soil_keys, has_snow, _ = engine.probe_soil_keys(
            center.lat, center.lon, forecast_days)
    except Exception:                                             # noqa: BLE001
        # Не удалось даже для центра — région, судя по всему, без данных о
        # почве вовсе. Резервный путь ниже честно попробует без слоёв, а
        # не станет перебирать их на каждой клетке заново.
        soil_keys, has_snow = None, False

    if len(cells) > 1 and _try_batch(cells, forecast_days, soil_keys,
                                     has_snow, on_progress):
        return grid

    _fetch_sequential(cells, forecast_days, soil_keys, has_snow, on_progress)
    return grid


def _try_batch(cells: list, forecast_days: int, soil_keys, has_snow,
               on_progress) -> bool:
    """Один запрос на все клетки. True — получилось и клетки заполнены."""
    daily = ",".join(engine.DAILY_VARS)
    params = {
        "latitude": ",".join(f"{c.lat:.5f}" for c in cells),
        "longitude": ",".join(f"{c.lon:.5f}" for c in cells),
        "timezone": "auto",
        "past_days": engine.PAST_DAYS,
        "forecast_days": max(3, min(16, forecast_days)),
        "daily": daily,
    }
    if soil_keys:
        extra = f",{engine.SNOW_KEY}" if has_snow else ""
        params["hourly"] = f"{soil_keys[0]},{soil_keys[1]}{extra}"

    try:
        data = engine._get_json(engine.FORECAST_URL, params,
                                timeout=BATCH_TIMEOUT_S)
    except Exception:                                             # noqa: BLE001
        return False

    # Ответ на несколько точек — по нашим сведениям, список той же длины,
    # что и число точек в запросе, по одному элементу на клетку в том же
    # порядке. Если это не так — не подгоняем под свою догадку, а честно
    # отступаем на путь, который уже год как работает.
    if not isinstance(data, list) or len(data) != len(cells):
        return False
    if not all(isinstance(item, dict) and "daily" in item for item in data):
        return False

    for cell, item in zip(cells, data):
        try:
            days = engine._parse_daily_blob(item, soil_keys, has_snow)
        except Exception as e:                                    # noqa: BLE001
            cell.error = f"{type(e).__name__}: {e}"[:120]
            continue
        heatgrid.fill_cell(cell, days)
    if on_progress:
        on_progress(len(cells), len(cells))
    return True


def _fetch_sequential(cells: list, forecast_days: int, soil_keys, has_snow,
                      on_progress) -> None:
    """Резервный путь: по одной точке, с паузой между запросами.

    Использует уже подобранные (или заведомо отсутствующие) слои почвы, а
    не выясняет их заново на каждой клетке — тот же смысл, что и у
    пакетного пути, просто без пакета. Раньше здесь стоял вызов
    engine.fetch_weather(), который внутри сам заново перебирал слои
    почвы на КАЖДОЙ клетке — то есть резервный путь тратил ровно то время,
    которого «перебор один раз для центра» должен был избежать.
    """
    for i, cell in enumerate(cells):
        try:
            days = engine.fetch_weather_with_keys(
                cell.lat, cell.lon, forecast_days, soil_keys, has_snow)
            heatgrid.fill_cell(cell, days)
        except Exception as e:                                    # noqa: BLE001
            cell.error = f"{type(e).__name__}: {e}"[:120]
        if on_progress:
            on_progress(i + 1, len(cells))
        if i + 1 < len(cells):
            time.sleep(THROTTLE_S)
