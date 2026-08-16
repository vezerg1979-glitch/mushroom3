# -*- coding: utf-8 -*-
"""Журнал походов: подписи, сводки и удаление.

Виджеты Kivy без экрана не поднять, поэтому проверяется то, ради чего журнал
и существует: человеческие подписи и то, что удаление действительно уносит
все файлы, а не оставляет мусор.
"""

import os
import sys
import tempfile
import time
from datetime import datetime

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "android")
sys.path.insert(0, ROOT)

import photos  # noqa: E402
import places  # noqa: E402
import track  # noqa: E402
import walkjournal as wj  # noqa: E402


@pytest.fixture
def data_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(places, "_DATA_DIR", tmp)
        yield tmp


def _walk(place="Ельник", when=None, dist=3200.0):
    w = track.Walk(place=place, started=when or time.time() - 7200)
    w.distance = dist
    w.finished = w.started + 5400
    return w


# --------------------------------------------------------------------------- #
#  Подписи
# --------------------------------------------------------------------------- #

def test_duration_is_human():
    assert wj.duration_text(0) == "0 мин"
    assert wj.duration_text(40 * 60) == "40 мин"
    assert wj.duration_text(2 * 3600 + 15 * 60) == "2 ч 15 мин"
    assert wj.duration_text(3600) == "1 ч 00 мин"


def test_duration_survives_a_broken_clock():
    """Отрицательная длительность бывает при переводе часов."""
    assert wj.duration_text(-500) == "0 мин"


def test_distance_rounds_the_way_people_speak():
    assert wj.distance_text(0) == "0 м"
    assert wj.distance_text(347) == "350 м"
    assert wj.distance_text(3200) == "3,2 км"


def test_year_appears_only_when_it_is_not_this_one():
    now = datetime.now()
    fresh = _walk(when=datetime(now.year, 8, 16, 9, 40).timestamp())
    assert "9:40" in wj.when_text(fresh)
    assert str(now.year) not in wj.when_text(fresh)
    old = _walk(when=datetime(now.year - 3, 8, 16, 9, 40).timestamp())
    assert str(now.year - 3) in wj.when_text(old)


# --------------------------------------------------------------------------- #
#  Что нашли — главное в строке
# --------------------------------------------------------------------------- #

def test_species_line_sorts_by_count():
    w = _walk()
    w.add_find(55.9, 38.0, "лисичка", count=12)
    w.add_find(55.9, 38.0, "белый", count=4)
    line = wj.species_line(w)
    assert line.index("лисичка") < line.index("белый")


def test_species_line_sums_repeated_marks():
    """Три отдельные метки одного вида — это один вид, а не три."""
    w = _walk()
    for _ in range(3):
        w.add_find(55.9, 38.0, "белый", count=2)
    assert "6" in wj.species_line(w)


def test_species_line_folds_a_long_tail():
    w = _walk()
    for key, n in (("белый", 9), ("лисичка", 7), ("подберёзовик", 5),
                   ("подосиновик", 3), ("маслёнок", 2), ("сыроежка", 1)):
        w.add_find(55.9, 38.0, key, count=n)
    line = wj.species_line(w)
    assert "и ещё 2" in line


def test_empty_walk_says_so_plainly():
    w = _walk()
    assert wj.species_line(w) == ""
    w.add_find(55.9, 38.0, "")          # просто метка, без вида
    assert wj.species_line(w) == "без находок"


def test_stats_line_mentions_photos_only_when_there_are_any():
    w = _walk()
    assert "снимков" not in wj.stats_line(w)
    w.add_find(55.9, 38.0, "белый", photos=["a.jpg"])
    assert "снимков 1" in wj.stats_line(w)


# --------------------------------------------------------------------------- #
#  Удаление
# --------------------------------------------------------------------------- #

def test_delete_removes_the_file_and_the_photos(data_dir):
    photo = photos.save_bytes(b"\xff\xd8\xff\xe0")
    w = _walk()
    w.add_point(55.96, 38.04, 5.0, t=1000.0)
    w.add_find(55.96, 38.04, "белый", photos=[photo])
    path = track.save(w)
    track.export_gpx(w)

    assert os.path.isfile(path)
    assert track.delete(w) >= 3          # json + gpx + снимок
    assert not os.path.isfile(path)
    assert not photos.exists(photo)
    assert track.load_all() == []


def test_delete_of_a_missing_walk_is_quiet(data_dir):
    assert track.delete(_walk()) == 0


def test_delete_leaves_other_walks_alone(data_dir):
    keep_photo = photos.save_bytes(b"\xff\xd8\xff\xe0")
    keep = _walk(place="Дальний бор", when=time.time() - 200000)
    keep.add_point(55.96, 38.04, 5.0, t=1000.0)
    keep.add_find(55.96, 38.04, "белый", photos=[keep_photo])
    track.save(keep)

    drop_photo = photos.save_bytes(b"\xff\xd8\xff\xe0")
    drop = _walk(place="Ельник")
    drop.add_point(55.97, 38.05, 5.0, t=2000.0)
    drop.add_find(55.97, 38.05, "лисичка", photos=[drop_photo])
    track.save(drop)

    track.delete(drop)
    assert photos.exists(keep_photo)
    assert not photos.exists(drop_photo)
    places_left = [w.place for w in track.load_all()]
    assert places_left == ["Дальний бор"]


def test_path_for_is_stable(data_dir):
    w = _walk()
    assert track.path_for(w) == track.path_for(track.Walk.from_dict(w.as_dict()))


# --------------------------------------------------------------------------- #
#  Кнопка на главном экране
# --------------------------------------------------------------------------- #

def test_main_screen_opens_the_journal():
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        src = f.read()
    assert "show_walk_journal" in src
    assert "import walkjournal" in src
