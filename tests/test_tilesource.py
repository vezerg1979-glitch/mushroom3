# -*- coding: utf-8 -*-
"""Источник подложки и разрешение качать карту впрок.

Общие серверы OpenStreetMap живут на пожертвования и прямо запрещают
скачивание области впрок; нарушителей блокируют без предупреждения и по
User-Agent — то есть карта отвалилась бы у всех, кто поставил приложение,
а не у того, кто нажал кнопку. Поэтому запрет проверяется тестами.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

ROOT = APP
sys.path.insert(0, ROOT)

import places  # noqa: E402
import tiles  # noqa: E402
import tilesource  # noqa: E402


@pytest.fixture
def data_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(places, "_DATA_DIR", tmp)
        tilesource.reset()
        yield tmp
        tilesource.reset()


# --------------------------------------------------------------------------- #
#  Разрешение
# --------------------------------------------------------------------------- #

def test_osm_is_the_default_and_forbids_offline(data_dir):
    assert tilesource.name() == "OpenStreetMap"
    assert tilesource.allows_offline() is False


def test_download_refuses_on_osm(data_dir):
    with pytest.raises(tiles.NotAllowed):
        tiles.download([(13, 1, 1)], data_dir)


def test_custom_source_allows_offline(data_dir):
    tilesource.save("custom", "https://tiles.example.test/{z}/{x}/{y}.png")
    assert tilesource.allows_offline() is True
    tiles.check_allowed()          # не бросает


def test_switching_back_restores_the_ban(data_dir):
    tilesource.save("custom", "https://tiles.example.test/{z}/{x}/{y}.png")
    tilesource.save("osm")
    assert tilesource.allows_offline() is False


# --------------------------------------------------------------------------- #
#  Адрес шаблона
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("url", [
    "https://tiles.example.test/{z}/{x}/{y}.png",
    "https://tile.example.test/v1/{z}/{x}/{y}@2x.png?key=abc123",
])
def test_good_urls_accepted(url):
    assert tilesource.valid_url(url)


@pytest.mark.parametrize("url", [
    "",
    "http://tiles.example.test/{z}/{x}/{y}.png",       # без шифрования
    "https://tiles.example.test/{z}/{x}.png",          # потеряна скобка {y}
    "https://tiles.example.test/tiles.png",            # шаблона нет вовсе
    "tiles.example.test/{z}/{x}/{y}.png",
])
def test_bad_urls_rejected(url):
    """Потерянная скобка превращает карту в пустые клетки молча."""
    assert not tilesource.valid_url(url)


def test_bad_url_is_not_saved(data_dir):
    with pytest.raises(ValueError):
        tilesource.save("custom", "https://tiles.example.test/tiles.png")
    assert tilesource.name() == "OpenStreetMap"


# --------------------------------------------------------------------------- #
#  Устойчивость
# --------------------------------------------------------------------------- #

def test_broken_settings_fall_back_to_osm(data_dir):
    with open(os.path.join(data_dir, tilesource.FILE), "w", encoding="utf-8") as f:
        f.write("{это не json")
    tilesource.reset()
    assert tilesource.name() == "OpenStreetMap"
    assert tilesource.allows_offline() is False


def test_custom_without_url_falls_back_to_osm(data_dir):
    import json
    with open(os.path.join(data_dir, tilesource.FILE), "w", encoding="utf-8") as f:
        json.dump({"key": "custom", "url": ""}, f)
    tilesource.reset()
    assert tilesource.allows_offline() is False


def test_choice_survives_a_restart(data_dir):
    url = "https://tiles.example.test/{z}/{x}/{y}.png"
    tilesource.save("custom", url)
    tilesource.reset()             # как будто приложение перезапустили
    assert tilesource.url() == url


def test_attribution_is_never_empty(data_dir):
    assert tilesource.attribution()
    tilesource.save("custom", "https://tiles.example.test/{z}/{x}/{y}.png")
    assert "OpenStreetMap" in tilesource.attribution()


# --------------------------------------------------------------------------- #
#  Кэш
# --------------------------------------------------------------------------- #

def test_clear_cache_removes_only_tiles(data_dir):
    cache = tiles.cache_dir()
    for name in ("13_1_1.png", "15_2_2.png"):
        with open(os.path.join(cache, name), "wb") as f:
            f.write(b"\x89PNG")
    with open(os.path.join(cache, "не-тайл.txt"), "w", encoding="utf-8") as f:
        f.write("оставить")
    assert tiles.clear_cache(cache) == 2
    assert os.path.isfile(os.path.join(cache, "не-тайл.txt"))


def test_clear_cache_of_a_missing_dir_is_quiet(tmp_path):
    assert tiles.clear_cache(str(tmp_path / "нет-такого")) == 0


def test_map_uses_the_configured_source(data_dir):
    with open(os.path.join(ROOT, "mapview.py"), encoding="utf-8") as f:
        src = f.read()
    assert "tilesource.url()" in src
    assert "tilesource.attribution()" in src
    assert "https://tile.openstreetmap.org" not in src, "адрес зашит в код"
