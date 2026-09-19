# -*- coding: utf-8 -*-
"""Тесты хранилища снимков и заметок к меткам.

Съёмку проверить на компьютере нельзя — она вся в системных вызовах Android.
Зато можно проверить всё остальное: имена файлов, уборку, совместимость
старых записей и то, что заметка человека доходит до журнала.
"""

import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

ROOT = APP
sys.path.insert(0, ROOT)

import journal  # noqa: E402
import photos  # noqa: E402
import places  # noqa: E402
import track  # noqa: E402
import walk2journal  # noqa: E402


@pytest.fixture
def data_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(places, "_DATA_DIR", tmp)
        yield tmp


def _make(name_dir, content=b"\xff\xd8\xff\xe0jpeg"):
    return photos.save_bytes(content)


# --------------------------------------------------------------------------- #
#  Имена и хранение
# --------------------------------------------------------------------------- #

def test_name_carries_the_time(data_dir):
    when = time.mktime((2026, 8, 16, 14, 23, 5, 0, 0, -1))
    name = photos.new_name(when)
    assert name.startswith("2026-08-16_142305_")
    assert name.endswith(".jpg")


def test_names_do_not_collide_within_a_second(data_dir):
    when = time.time()
    names = {photos.new_name(when) for _ in range(200)}
    assert len(names) == 200, "два снимка в одну секунду затрут друг друга"


def test_save_and_read_back(data_dir):
    name = _make(data_dir)
    assert photos.exists(name)
    assert photos.path_for(name).startswith(data_dir)
    with open(photos.path_for(name), "rb") as f:
        assert f.read().startswith(b"\xff\xd8")


def test_only_the_file_name_is_stored(data_dir):
    """В походе хранится имя, а не путь: каталог меняется при переустановке."""
    name = _make(data_dir)
    assert os.sep not in name
    assert photos.path_for("/чужой/путь/" + name) == photos.path_for(name)


def test_remove_is_quiet_about_missing_files(data_dir):
    assert photos.remove("нет-такого.jpg") is False


def test_size_text_is_human(data_dir):
    assert photos.size_text(2048).endswith("КБ")
    assert photos.size_text(5 * 1024 * 1024).endswith("МБ")


# --------------------------------------------------------------------------- #
#  Уборка
# --------------------------------------------------------------------------- #

def test_cleanup_removes_only_orphans(data_dir):
    keep = _make(data_dir)
    orphan = _make(data_dir)
    assert photos.cleanup([keep]) == 1
    assert photos.exists(keep)
    assert not photos.exists(orphan)


def test_cleanup_of_empty_list_wipes_everything(data_dir):
    _make(data_dir)
    _make(data_dir)
    assert photos.cleanup([]) == 2


def test_archive_is_protected_from_cleanup(data_dir):
    """Уборка обязана видеть снимки прошлых походов.

    Иначе завершение сегодняшнего выхода стирает весь архив: снимки старых
    меток не упоминаются в текущем походе и выглядят ничейными.
    """
    old_photo = _make(data_dir)
    old = track.Walk(place="Дальний бор")
    old.add_point(55.96, 38.04, 5.0, t=1000.0)
    old.add_find(55.96, 38.04, "белый", photos=[old_photo])
    track.save(old)

    today_photo = _make(data_dir)
    today = track.Walk()
    today.add_find(55.97, 38.05, "лисичка", photos=[today_photo])

    keep = set(track.all_photo_names()) | set(today.photo_names())
    photos.cleanup(keep)
    assert photos.exists(old_photo), "снимок прошлого похода не должен пропасть"
    assert photos.exists(today_photo)


# --------------------------------------------------------------------------- #
#  Метка: заметка и снимки
# --------------------------------------------------------------------------- #

def test_find_keeps_note_and_photos_through_saving(data_dir):
    w = track.Walk(place="Ельник")
    w.add_point(55.96, 38.04, 5.0, t=1000.0)
    w.add_find(55.96, 38.04, "белый", count=3, note="под елью, ножка сетчатая",
               photos=["a.jpg", "b.jpg"])
    back = track.Walk.from_dict(w.as_dict())
    f = back.finds[0]
    assert f.note == "под елью, ножка сетчатая"
    assert f.photos == ["a.jpg", "b.jpg"]
    assert f.count == 3


def test_old_walks_without_photos_still_load():
    """Записи прошлых версий — шесть полей, седьмого нет."""
    raw = {"started": 1000.0, "points": [], "finds": [
        [55.96, 38.04, 1001.0, "белый", 2, "старая заметка"]]}
    w = track.Walk.from_dict(raw)
    assert w.finds[0].note == "старая заметка"
    assert w.finds[0].photos == []


def test_finds_without_details_are_recognised():
    w = track.Walk()
    bare = w.add_find(55.96, 38.04, "белый")
    rich = w.add_find(55.96, 38.04, "белый", note="у пня")
    assert not bare.has_details()
    assert rich.has_details()


def test_photo_names_gathers_every_find():
    w = track.Walk()
    w.add_find(55.96, 38.04, "белый", photos=["a.jpg"])
    w.add_find(55.97, 38.05, "лисичка", photos=["b.jpg", "c.jpg"])
    assert w.photo_names() == ["a.jpg", "b.jpg", "c.jpg"]


# --------------------------------------------------------------------------- #
#  GPX
# --------------------------------------------------------------------------- #

def test_gpx_escapes_user_text():
    """Амперсанд в заметке ломал весь файл, а не одну точку."""
    w = track.Walk()
    w.add_point(55.96, 38.04, 5.0, t=1000.0)
    w.add_find(55.96, 38.04, "белый", note='просека 3 & 4, ёлка < 2 м')
    gpx = track.to_gpx(w)
    assert "&amp;" in gpx and "&lt;" in gpx
    assert "3 & 4" not in gpx
    import xml.etree.ElementTree as ET
    ET.fromstring(gpx)          # разбирается как валидный XML


def test_gpx_links_photos():
    w = track.Walk()
    w.add_point(55.96, 38.04, 5.0, t=1000.0)
    w.add_find(55.96, 38.04, "белый", photos=["2026-08-16_142305_ab12.jpg"])
    gpx = track.to_gpx(w)
    assert 'href="photos/2026-08-16_142305_ab12.jpg"' in gpx


# --------------------------------------------------------------------------- #
#  Заметка доходит до журнала
# --------------------------------------------------------------------------- #

def test_journal_note_starts_with_the_persons_words():
    w = track.Walk(place="Ельник")
    for i in range(6):
        w.add_point(55.96 + i * 0.002, 38.04, 5.0, t=1000.0 + i * 60)
    w.add_find(55.96, 38.04, "белый", count=4, note="все червивые",
               photos=["a.jpg"])
    entries = walk2journal.entries_from_walk(w)
    note = entries[0].note
    assert note.startswith("все червивые")
    assert "4 шт." in note and "снимков 1" in note


def test_journal_note_is_trimmed():
    w = track.Walk(place="Ельник")
    for i in range(6):
        w.add_point(55.96 + i * 0.002, 38.04, 5.0, t=1000.0 + i * 60)
    w.add_find(55.96, 38.04, "белый", note="ё" * 400)
    note = walk2journal.entries_from_walk(w)[0].note
    assert len(note) < 200, "колонка на пол-экрана делает журнал нечитаемым"
    assert "…" in note


def test_journal_note_survives_without_any_words():
    w = track.Walk(place="Ельник")
    for i in range(6):
        w.add_point(55.96 + i * 0.002, 38.04, 5.0, t=1000.0 + i * 60)
    w.add_find(55.96, 38.04, "белый", count=2)
    note = walk2journal.entries_from_walk(w)[0].note
    assert "2 шт." in note and "снимков" not in note


def test_journal_entry_accepts_the_note():
    e = journal.Entry(__import__("datetime").date(2026, 8, 16), "Ельник",
                      55.96, 38.04, "белый", 3, "все червивые, 4 шт.")
    assert "червивые" in e.note


# --------------------------------------------------------------------------- #
#  Пережатие
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("w,h,expect", [
    (1600, 1200, 1),        # уже помещается
    (3200, 2400, 2),
    (6400, 4800, 4),
    (4000, 3000, 2),        # 2000 точек: чуть больше цели, но не меньше
    (12000, 9000, 4),       # 3000 точек по той же причине
])
def test_sample_size_is_a_power_of_two(w, h, expect):
    """Прореживание кратно только 2, 4, 8: так устроен BitmapFactory."""
    assert photos._sample_size(w, h, photos.MAX_SIDE) == expect


@pytest.mark.parametrize("side", [1700, 2500, 3300, 5000, 9000, 12000])
def test_sample_size_never_shrinks_below_the_target(side):
    """Лучше отдать больше нужного, чем потерять детали для определения вида."""
    s = photos._sample_size(side, side, photos.MAX_SIDE)
    assert side // s >= photos.MAX_SIDE


def test_downscale_is_quiet_off_android(data_dir, tmp_path):
    src = tmp_path / "in.jpg"
    src.write_bytes(b"\xff\xd8\xff")
    assert photos.downscale(str(src), str(tmp_path / "out.jpg")) is False


def test_import_path_falls_back_to_copying(data_dir, tmp_path):
    """Без Android пережать нечем — снимок должен просто скопироваться."""
    src = tmp_path / "in.jpg"
    src.write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)
    name = photos.import_path(str(src))
    assert photos.exists(name)
    assert os.path.getsize(photos.path_for(name)) == os.path.getsize(src)


def test_import_path_complains_about_missing_file(data_dir):
    with pytest.raises(OSError):
        photos.import_path("/нет/такого.jpg")


# --------------------------------------------------------------------------- #
#  Съёмка вне Android
# --------------------------------------------------------------------------- #

def test_camera_answers_politely_on_a_desktop(data_dir):
    seen = []
    p = photos.Photographer()
    assert p.capture(lambda name, err: seen.append((name, err))) is False
    assert seen and seen[0][0] is None and seen[0][1]


def test_gallery_answers_politely_on_a_desktop(data_dir):
    seen = []
    p = photos.Photographer()
    assert p.pick(lambda name, err: seen.append((name, err))) is False
    assert seen and seen[0][0] is None


def test_camera_permission_only_matters_on_old_android():
    """До Android 10 нужна запись в память, начиная с Android 10 — нет."""
    assert photos.Photographer.needs_storage_permission() is False
