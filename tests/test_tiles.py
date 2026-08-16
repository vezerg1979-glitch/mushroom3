# -*- coding: utf-8 -*-
"""Тесты предзагрузки карты. Сеть не нужна: загрузка подменяется."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "android"))

import tiles  # noqa: E402

LAT, LON = 55.9606, 38.0456


def test_tile_of_known_point():
    """Фрязино на 15-м масштабе: значение сверено с рабочей картой mapview."""
    assert tiles.deg2num(LAT, LON, 15) == (19846, 10210)


def test_matches_mapview_formula():
    """Кэш общий с картой, значит и нумерация тайлов должна совпадать."""
    import importlib.util
    spec = importlib.util.find_spec("mapview")
    if spec is None:                      # на CI без Kivy проверять нечего
        return
    try:
        import mapview
    except Exception:                     # noqa: BLE001 — Kivy без экрана
        return
    for z in (13, 15, 16):
        mine = tiles.deg2num(LAT, LON, z)
        theirs = tuple(int(v) for v in mapview.deg2num(LAT, LON, z))
        assert mine == theirs


def test_tile_span_shrinks_with_zoom():
    a = tiles.tile_span(LAT, 13)
    b = tiles.tile_span(LAT, 15)
    assert a / b == pytest.approx(4, abs=0.01)


def test_range_covers_radius():
    x0, x1, y0, y1 = tiles.tile_range(LAT, LON, 2000, 15)
    span = tiles.tile_span(LAT, 15)
    assert (x1 - x0 + 1) * span >= 2 * 2000       # круг влезает по ширине
    assert (y1 - y0 + 1) * span >= 2 * 2000


def test_plan_grows_with_radius():
    small = len(tiles.plan(LAT, LON, 1.0))
    big = len(tiles.plan(LAT, LON, 3.0))
    assert big > small * 3


def test_radius_is_capped():
    """Просьба скачать пол-области молча урезается до предела."""
    huge = len(tiles.plan(LAT, LON, 50.0))
    limit = len(tiles.plan(LAT, LON, tiles.MAX_RADIUS_KM))
    assert huge == limit


def test_estimate_flags_too_many():
    assert not tiles.estimate(LAT, LON, 1.0)["too_many"]
    assert tiles.estimate(LAT, LON, 5.0)["too_many"]


def test_describe_is_human_readable():
    text = tiles.describe(LAT, LON, 1.0)
    assert "клеток" in text and "МБ" in text
    assert "Слишком большая" in tiles.describe(LAT, LON, 5.0)


def test_download_skips_existing_and_counts(tmp_path, monkeypatch):
    items = [(15, 100, 200), (15, 100, 201), (15, 100, 202)]
    d = str(tmp_path)
    # один тайл уже в кэше
    open(os.path.join(d, "15_100_200.png"), "wb").write(b"x")

    calls = []

    class FakeResponse:
        def read(self):
            return b"PNG"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        return FakeResponse()

    monkeypatch.setattr(tiles.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(tiles.time, "sleep", lambda *_: None)

    seen = []
    res = tiles.download(items, d, on_progress=lambda i, n: seen.append((i, n)))

    assert res == {"downloaded": 2, "skipped": 1, "failed": 0, "total": 3}
    assert len(calls) == 2                     # существующий не перекачивался
    assert seen[-1] == (3, 3)
    assert os.path.exists(os.path.join(d, "15_100_202.png"))


def test_download_can_be_stopped(tmp_path, monkeypatch):
    items = [(15, 1, i) for i in range(10)]
    monkeypatch.setattr(tiles.time, "sleep", lambda *_: None)
    monkeypatch.setattr(tiles.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("нет сети")))

    stop = {"n": 0}

    def should_stop():
        stop["n"] += 1
        return stop["n"] > 3

    res = tiles.download(items, str(tmp_path), should_stop=should_stop)
    assert res["total"] == 10
    assert res["failed"] < 10                  # прервались, не дойдя до конца


def test_network_failure_is_counted_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(tiles.time, "sleep", lambda *_: None)
    monkeypatch.setattr(tiles.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("нет сети")))
    res = tiles.download([(15, 1, 1)], str(tmp_path))
    assert res["failed"] == 1
    assert not os.listdir(tmp_path)            # обрывков в кэше не остаётся


def test_cache_size(tmp_path):
    assert tiles.cache_size_mb(str(tmp_path)) == 0.0
    open(os.path.join(str(tmp_path), "a.png"), "wb").write(b"x" * 1024 * 512)
    assert tiles.cache_size_mb(str(tmp_path)) == pytest.approx(0.5, abs=0.01)
    assert tiles.cache_size_mb("/nonexistent") == 0.0
