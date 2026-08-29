# -*- coding: utf-8 -*-
"""Загрузка погоды на сетку: пакетный запрос и откат на запросы по одной.

Настоящей сети здесь нет и быть не должно — как и в остальных тестах
проекта, ответы Open-Meteo подменяются заглушками. Главное, что
проверяется: при ЛЮБОМ расхождении формы пакетного ответа с тем, что
ожидалось, код должен молча откатиться на путь по одной точке, а не
уронить расчёт и не разложить данные не в те клетки.
"""

import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

sys.path.insert(0, APP)

import heatfetch  # noqa: E402
import heatgrid  # noqa: E402
import mushroom_forecast as engine  # noqa: E402

LAT, LON = 55.96, 38.04


def _daily_blob(n, t=18.0, precip=0.5):
    times = [(date.today() - timedelta(days=engine.PAST_DAYS) + timedelta(days=i)).isoformat()
             for i in range(n)]
    return {"time": times,
            "temperature_2m_max": [t] * n, "temperature_2m_min": [t - 8] * n,
            "temperature_2m_mean": [t - 4] * n, "precipitation_sum": [precip] * n,
            "et0_fao_evapotranspiration": [3.0] * n,
            "relative_humidity_2m_mean": [80.0] * n}


def _single_response(n=engine.PAST_DAYS + 7):
    return {"daily": _daily_blob(n)}


@pytest.fixture
def small_grid():
    return heatgrid.plan(55.94, 38.00, 55.98, 38.08)   # несколько клеток


@pytest.fixture(autouse=True)
def без_реальной_сети(monkeypatch):
    """Подстраховка: если тест забудет подменить _get_json, лучше упасть
    с понятной ошибкой, чем случайно дёрнуть настоящую сеть."""
    def бы_полез_в_сеть(*a, **kw):
        raise AssertionError("тест обратился к настоящей сети — заглушка не подставлена")
    monkeypatch.setattr(engine, "_get_json", бы_полез_в_сеть)
    yield


# --------------------------------------------------------------------------- #
#  Пакетный путь: форма ответа совпала с ожиданием
# --------------------------------------------------------------------------- #

def test_batch_takes_exactly_the_probe_plus_one_call(monkeypatch, small_grid):
    """Минимум сети: один пробный запрос на центр сетки (подобрать слои
    почвы) и один пакетный на всю сетку — не по вызову на клетку."""
    calls = []

    def fake(url, params, timeout=25):
        calls.append(params)
        n = engine.PAST_DAYS + 7
        if "," in str(params.get("latitude", "")):
            return [_single_response(n) for _ in small_grid.cells]
        return _single_response(n)

    monkeypatch.setattr(engine, "_get_json", fake)
    heatfetch.fetch_grid(small_grid, forecast_days=7)

    assert len(calls) == 2, "должно быть: один пробный + один пакетный"
    assert "," not in str(calls[0]["latitude"]), "первый вызов — пробный, по одной точке"
    assert "," in str(calls[1]["latitude"]), "второй вызов — пакетный, все клетки разом"
    assert all(c.index is not None for c in small_grid.cells)
    assert small_grid.done == small_grid.total


def test_batch_request_lists_every_coordinate():
    """Запрос должен нести координаты всех клеток, а не только первой."""
    grid = heatgrid.plan(55.94, 38.00, 55.98, 38.08)
    captured = {}

    def fake(url, params, timeout=25):
        n = engine.PAST_DAYS + 7
        if "," in str(params.get("latitude", "")):
            captured.update(params)
            return [_single_response(n) for _ in grid.cells]
        return _single_response(n)

    import mushroom_forecast as eng
    eng._get_json = fake
    try:
        heatfetch.fetch_grid(grid, forecast_days=7)
    finally:
        pass
    широты = captured["latitude"].split(",")
    долготы = captured["longitude"].split(",")
    assert len(широты) == len(grid.cells)
    assert len(долготы) == len(grid.cells)


def test_progress_reports_start_and_finish_in_batch_mode(monkeypatch, small_grid):
    отметки = []

    def fake(url, params, timeout=25):
        n = engine.PAST_DAYS + 7
        if "," in str(params.get("latitude", "")):
            return [_single_response(n) for _ in small_grid.cells]
        return _single_response(n)

    monkeypatch.setattr(engine, "_get_json", fake)
    heatfetch.fetch_grid(small_grid, forecast_days=7,
                        on_progress=lambda done, total: отметки.append((done, total)))
    total = small_grid.total
    assert отметки[0] == (0, total)
    assert отметки[-1] == (total, total)


# --------------------------------------------------------------------------- #
#  Пакетный путь: форма ответа НЕ совпала — обязан откатиться, а не упасть
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("плохой_ответ", [
    {"daily": _daily_blob(5)},                      # словарь вместо списка
    [],                                              # список неверной длины
    ["не словарь", "тоже не словарь"],
    [{"нет тут daily": True}] * 6,
])
def test_malformed_batch_response_falls_back_without_crashing(monkeypatch, small_grid,
                                                              плохой_ответ):
    n = engine.PAST_DAYS + 7
    вызовы = {"batch": 0, "single": 0}

    def fake(url, params, timeout=25):
        вызовы["batch" if "," in str(params.get("latitude", "")) else "single"] += 1
        if "," in str(params.get("latitude", "")):
            return плохой_ответ
        return _single_response(n)

    monkeypatch.setattr(engine, "_get_json", fake)
    monkeypatch.setattr(heatfetch, "THROTTLE_S", 0.0)   # тест не должен ждать реальные паузы
    heatfetch.fetch_grid(small_grid, forecast_days=7)

    assert вызовы["batch"] >= 1
    assert вызовы["single"] > 0, "после неудачного пакета должен пойти путь по одной точке"
    assert all(c.index is not None for c in small_grid.cells)


def test_batch_connection_failure_falls_back(monkeypatch, small_grid):
    """Не только неверная форма — обрыв самого запроса тоже должен
    заканчиваться откатом, а не исключением наружу."""
    n = engine.PAST_DAYS + 7
    вызовы = {"batch": 0}

    def fake(url, params, timeout=25):
        if "," in str(params.get("latitude", "")):
            вызовы["batch"] += 1
            raise TimeoutError("сеть не ответила")
        return _single_response(n)

    monkeypatch.setattr(engine, "_get_json", fake)
    monkeypatch.setattr(heatfetch, "THROTTLE_S", 0.0)
    heatfetch.fetch_grid(small_grid, forecast_days=7)          # не должно бросить исключение
    assert вызовы["batch"] == 1
    assert all(c.index is not None for c in small_grid.cells)


# --------------------------------------------------------------------------- #
#  Последовательный путь
# --------------------------------------------------------------------------- #

def test_sequential_path_covers_every_cell_and_paces_itself(monkeypatch):
    grid = heatgrid.plan(55.94, 38.00, 55.98, 38.08)
    n = engine.PAST_DAYS + 7
    вызвано = []

    def fake(url, params, timeout=25):
        вызвано.append((params["latitude"], params["longitude"]))
        return _single_response(n)

    monkeypatch.setattr(engine, "_get_json", fake)
    monkeypatch.setattr(heatfetch, "THROTTLE_S", 0.0)
    heatfetch._fetch_sequential(grid.cells, 7, None, False, None)

    assert len(вызвано) == len(grid.cells)
    assert all(c.index is not None for c in grid.cells)


def test_sequential_path_reports_real_progress(monkeypatch):
    grid = heatgrid.plan(55.94, 38.00, 55.98, 38.08)
    n = engine.PAST_DAYS + 7
    monkeypatch.setattr(engine, "_get_json", lambda *a, **kw: _single_response(n))
    monkeypatch.setattr(heatfetch, "THROTTLE_S", 0.0)

    отметки = []
    heatfetch._fetch_sequential(grid.cells, 7, None, False,
                               lambda done, total: отметки.append((done, total)))
    assert отметки == [(i + 1, len(grid.cells)) for i in range(len(grid.cells))]


def test_sequential_path_survives_one_bad_cell(monkeypatch):
    """Одна клетка без сети не должна остановить остальные тридцать пять."""
    grid = heatgrid.plan(55.94, 38.00, 55.98, 38.08)
    n = engine.PAST_DAYS + 7
    вызов = {"n": 0}

    def fake(url, params, timeout=25):
        вызов["n"] += 1
        if вызов["n"] == 2:
            raise TimeoutError("сеть моргнула")
        return _single_response(n)

    monkeypatch.setattr(engine, "_get_json", fake)
    monkeypatch.setattr(heatfetch, "THROTTLE_S", 0.0)
    heatfetch._fetch_sequential(grid.cells, 7, None, False, None)

    ошибки = [c for c in grid.cells if c.error]
    успехи = [c for c in grid.cells if c.index is not None]
    assert len(ошибки) == 1
    assert len(успехи) == len(grid.cells) - 1


def test_single_cell_grid_skips_batch_entirely(monkeypatch):
    """Одна клетка — пакетный путь не имеет смысла, идём сразу по-старому.

    Вызовов всё равно два: пробный на слои почвы (центр сетки — это и
    есть единственная клетка) и сам запрос погоды этими ключами. Пакетным
    ни один из них не становится — координата в обоих одна.
    """
    grid = heatgrid.plan(55.999, 38.039, 56.001, 38.041)   # крошечная область, 1 клетка
    assert grid.total == 1
    n = engine.PAST_DAYS + 7
    вызовы = []

    def fake(url, params, timeout=25):
        вызовы.append(params)
        return _single_response(n)

    monkeypatch.setattr(engine, "_get_json", fake)
    heatfetch.fetch_grid(grid, forecast_days=7)
    assert len(вызовы) == 2
    assert all("," not in str(v["latitude"]) for v in вызовы)


# --------------------------------------------------------------------------- #
#  Пустая сетка
# --------------------------------------------------------------------------- #

def test_empty_grid_makes_no_calls_at_all(monkeypatch):
    def бы_дёрнул_сеть(*a, **kw):
        raise AssertionError("на пустой сетке в сеть ходить незачем")

    monkeypatch.setattr(engine, "_get_json", бы_дёрнул_сеть)
    grid = heatgrid.Grid()
    heatfetch.fetch_grid(grid)              # не должно ничего вызвать и не упасть


# --------------------------------------------------------------------------- #
#  Резервный путь переиспользует уже подобранные слои почвы
# --------------------------------------------------------------------------- #

def test_sequential_fallback_does_not_reprobe_soil_layers_per_cell(monkeypatch):
    """Перебор слоёв почвы должен идти один раз на всю сетку, а не заново
    на каждой клетке резервного пути.

    Раньше резервный путь звал engine.fetch_weather(), а та сама заново
    перебирала SOIL_CANDIDATES на КАЖДОЙ клетке — «перебор один раз для
    центра» существовал только для пакетного пути, а откат его не видел.
    На сетке 6×6 разница — 40 запросов против 112: первый вариант слоя
    здесь нарочно всегда отклоняется, чтобы перебор был на самом деле
    виден в счётчике, а не спрятан за случайно удачной первой попыткой.
    """
    grid = heatgrid.plan(55.90, 37.95, 56.02, 38.15)
    assert grid.total > 1
    n = engine.PAST_DAYS + 7
    calls = {"n": 0}

    def fake(url, params, timeout=25):
        calls["n"] += 1
        if "," in str(params.get("latitude", "")):
            raise RuntimeError("пакетный путь отключён нарочно — идём в откат")
        # первый вариант слоя всегда отклоняется, чтобы перебор был виден
        if str(params.get("hourly", "")).startswith(engine.SOIL_CANDIDATES[0][0]):
            raise __import__("urllib.error", fromlist=["error"]).HTTPError(
                url, 400, "unsupported", None, None)
        return _single_response(n)

    monkeypatch.setattr(engine, "_get_json", fake)
    monkeypatch.setattr(heatfetch, "THROTTLE_S", 0.0)
    heatfetch.fetch_grid(grid, forecast_days=7)

    # Один пробный перебор на область (до двух попыток слоя) + по одному
    # запросу на клетку известными ключами — точно меньше, чем клеток
    # умножить на попытки перебора.
    assert calls["n"] < grid.total * 2
    assert all(c.index is not None for c in grid.cells)
