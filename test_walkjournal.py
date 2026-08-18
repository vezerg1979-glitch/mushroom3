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
# Импортируется summary, а не walkjournal: второй тянет за собой Kivy,
# которого на сборочной машине нет, и тогда падает не тест, а весь релиз.
import summary as wj  # noqa: E402


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


# --------------------------------------------------------------------------- #
#  Обещание модели против того, что вышло
# --------------------------------------------------------------------------- #

def _rated_walk(index_value, finds, km=3.0, key="белый"):
    w = _walk(dist=km * 1000.0)
    w.index = {key: float(index_value)} if index_value is not None else {}
    for _ in range(finds):
        w.add_find(55.0, 38.0, key)
    return w


def test_index_line_names_the_species_it_promised():
    w = _rated_walk(61.4, 0)
    line = wj.index_line(w)
    assert "61" in line and "белый гриб" in line


def test_index_line_adds_what_was_actually_found():
    """Обещание проверяется индексом найденного вида, а не общим максимумом."""
    w = _rated_walk(61.4, 0)
    w.index["лисичка"] = 22.0
    w.add_find(55.0, 38.0, "лисичка")
    line = wj.index_line(w)
    assert "лисичка 22" in line


def test_index_line_does_not_repeat_the_same_species_twice():
    w = _rated_walk(61.4, 2)
    assert wj.index_line(w).count("белый гриб") == 1


def test_index_line_is_empty_for_walks_without_a_forecast():
    """Походы, записанные до появления снимка, не должны ничего показывать."""
    assert wj.index_line(_rated_walk(None, 3)) == ""


def test_walk_index_reads_the_best_or_a_named_species():
    w = _rated_walk(61.4, 0)
    w.index["лисичка"] = 22.0
    assert wj.walk_index(w) == 61.4
    assert wj.walk_index(w, "лисичка") == 22.0
    assert wj.walk_index(w, "груздь") is None
    assert wj.walk_index(_rated_walk(None, 0)) is None


def test_personal_scale_stays_silent_on_thin_data():
    """Три точки — совпадение, а не шкала: выдавать их за вывод нечестно."""
    assert wj.personal_scale([]) == ""
    few = [_rated_walk(50, 4) for _ in range(3)]
    text = wj.personal_scale(few)
    assert "появится" in text and str(wj.MIN_WALKS) in text


def test_personal_scale_finds_the_boundary():
    walks = [_rated_walk(v, n) for v, n in
             ((70, 9), (65, 6), (60, 4), (45, 1), (38, 0), (30, 0))]
    text = wj.personal_scale(walks)
    assert "60" in text and "45" in text


def test_personal_scale_admits_when_there_is_no_boundary():
    """Перемешанные данные — повод сказать об этом, а не рисовать порог."""
    walks = [_rated_walk(v, n) for v, n in
             ((70, 9), (40, 6), (60, 0), (45, 1), (38, 0), (30, 5))]
    text = wj.personal_scale(walks)
    assert "границы не видно" in text


def test_personal_scale_ignores_walks_without_distance():
    """Находки на километр без километров не считаются: делить не на что."""
    walks = [_rated_walk(v, n, km=0.05) for v, n in
             ((70, 9), (65, 6), (60, 4), (45, 1), (38, 0), (30, 0))]
    assert wj.personal_scale(walks) == ""


def test_forecast_snapshot_survives_saving(data_dir):
    w = _rated_walk(61.4, 2)
    w.index_stamp = 1_700_000_000.0
    track.save(w)
    back = track.load_all()[0]
    assert back.index == w.index
    assert back.index_stamp == w.index_stamp
    assert wj.index_line(back) == wj.index_line(w)


# --------------------------------------------------------------------------- #
#  Итог сезона
# --------------------------------------------------------------------------- #

def _season_walk(days_ago, finds, place="Ельник", km=4.0, species="белый"):
    import time as _time

    w = _walk(dist=km * 1000.0)
    w.started = _time.time() - days_ago * 86400
    w.finished = w.started + 3600
    w.place = place
    for _ in range(finds):
        w.add_find(56.0, 38.0, species)
    return w


def test_season_line_sums_the_year():
    text = wj.season_line([_season_walk(1, 5), _season_walk(3, 2)])
    assert "походов 2" in text
    assert "находок 7" in text


def test_season_line_names_the_commonest_species():
    walks = [_season_walk(1, 5, species="белый"),
             _season_walk(2, 1, species="лисичка")]
    assert "белый гриб" in wj.season_line(walks)


def test_season_line_remembers_the_best_day():
    walks = [_season_walk(1, 2, place="Просека"),
             _season_walk(5, 9, place="Бор за рекой")]
    text = wj.season_line(walks)
    assert "Бор за рекой" in text and "находок 9" in text


def test_a_thin_day_is_not_called_the_best():
    """«Лучший день: находок 1» звучит как насмешка."""
    text = wj.season_line([_season_walk(1, 1), _season_walk(2, 0)])
    assert "Лучший день" not in text


def test_last_year_walks_are_not_counted():
    """Сезон — календарный год: иначе сравнить с прошлым разом не с чем."""
    assert wj.season_line([_season_walk(500, 8)]) == ""


def test_no_walks_no_line():
    assert wj.season_line([]) == ""


def test_best_day_has_no_clock_time():
    """«18 августа, 18:10» читается как отметка в журнале, а не как день.

    Ищется именно время на часах, а не двоеточие: двоеточие в этой фразе
    законно стоит перед числом находок.
    """
    import re

    text = wj.season_line([_season_walk(1, 7)])
    assert not re.search(r"\d{1,2}:\d{2}", text), text
