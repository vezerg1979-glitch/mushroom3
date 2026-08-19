# -*- coding: utf-8 -*-
"""Резервная копия: что уезжает в архив и что возвращается обратно.

Копия проверяется придирчивее прочего по простой причине: ошибку здесь
человек обнаружит в тот единственный момент, когда исправить её уже нечем —
когда телефон утонул, а архив оказался пустым или не разворачивается.
"""

import json
import os
import sys
import zipfile

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "android")
sys.path.insert(0, ROOT)

import backup  # noqa: E402
import places  # noqa: E402


@pytest.fixture
def data(tmp_path, monkeypatch):
    """Каталог данных с журналом, походом, снимком и мусором."""
    monkeypatch.setattr(places, "_DATA_DIR", str(tmp_path))
    (tmp_path / "tracks").mkdir()
    (tmp_path / "photos").mkdir()
    (tmp_path / "cache").mkdir()
    (tmp_path / "journal.csv").write_text("дата;место\n2026-08-01;Бор\n",
                                          encoding="utf-8")
    (tmp_path / "places.json").write_text("[]", encoding="utf-8")
    (tmp_path / "prefs.json").write_text("{}", encoding="utf-8")
    (tmp_path / "tracks" / "2026-08-01_0900.json").write_text('{"started":1}',
                                                              encoding="utf-8")
    (tmp_path / "photos" / "a.jpg").write_bytes(b"x" * 2048)
    (tmp_path / "photos" / "b.jpg").write_bytes(b"y" * 2048)
    (tmp_path / "cache" / "weather.json").write_text("{}", encoding="utf-8")
    (tmp_path / "service.log").write_text("лог", encoding="utf-8")
    (tmp_path / "track_live.ndjson").write_text("{}", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
#  Что входит в копию
# --------------------------------------------------------------------------- #

def test_counts_records_and_photos_separately(data):
    """Числа нужны до нажатия: записи весят килобайты, снимки — сотни мегабайт."""
    full = backup.contents(with_photos=True)
    light = backup.contents(with_photos=False)
    assert full["photos"] == 2
    assert light["files"] == full["files"] - 2
    assert light["bytes"] < full["bytes"]


def test_cache_and_service_files_stay_out(data):
    """Кэш и лог восстановятся сами, а место в письме занимают."""
    dst = data / "out.zip"
    backup.create(str(dst))
    names = zipfile.ZipFile(dst).namelist()
    assert not any(n.startswith("cache/") for n in names)
    assert "service.log" not in names
    assert "track_live.ndjson" not in names


def test_archive_holds_the_whole_journal(data):
    dst = data / "out.zip"
    backup.create(str(dst))
    names = zipfile.ZipFile(dst).namelist()
    for expected in ("journal.csv", "places.json", "prefs.json",
                     "tracks/2026-08-01_0900.json", "photos/a.jpg"):
        assert expected in names, expected


def test_light_archive_has_no_photos(data):
    dst = data / "light.zip"
    backup.create(str(dst), with_photos=False)
    names = zipfile.ZipFile(dst).namelist()
    assert not any(n.startswith("photos/") for n in names)
    assert "journal.csv" in names


def test_manifest_says_what_this_is(data):
    dst = data / "out.zip"
    backup.create(str(dst))
    man = json.loads(zipfile.ZipFile(dst).read(backup.MANIFEST))
    assert man["app"] == "navigator-gribnika"
    assert man["format"] == backup.FORMAT


def test_archive_name_is_ascii_and_dated():
    """Имя поедет в почту и на компьютер: кириллица там превращается в кракозябры."""
    name = backup.archive_name(1_700_000_000.0)
    assert name.endswith(".zip")
    assert all(ord(c) < 128 for c in name)
    assert "2023" in name


def test_broken_run_leaves_no_half_archive(data, monkeypatch):
    """Обрубок с правильным именем человек примет за копию — и узнает правду поздно."""
    real = zipfile.ZipFile.write
    calls = {"n": 0}

    def boom(self, *a, **kw):
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("кончилось место")
        return real(self, *a, **kw)

    monkeypatch.setattr(zipfile.ZipFile, "write", boom)
    dst = data / "out.zip"
    with pytest.raises(OSError):
        backup.create(str(dst))
    assert not dst.exists()
    assert not (data / "out.zip.part").exists()


# --------------------------------------------------------------------------- #
#  Возвращение обратно
# --------------------------------------------------------------------------- #

def test_restore_brings_everything_back(data, tmp_path):
    dst = data / "out.zip"
    backup.create(str(dst))
    fresh = tmp_path / "новый-телефон"
    fresh.mkdir()
    res = backup.restore(str(dst), root=str(fresh))
    assert res["added"] >= 5
    assert (fresh / "journal.csv").read_text(encoding="utf-8").startswith("дата")
    assert (fresh / "tracks" / "2026-08-01_0900.json").exists()
    assert (fresh / "photos" / "a.jpg").read_bytes() == b"x" * 2048


def test_restore_does_not_overwrite_what_is_already_there(data, tmp_path):
    """Прошлогодняя копия не должна съесть сегодняшний поход."""
    dst = data / "out.zip"
    backup.create(str(dst))
    (data / "journal.csv").write_text("свежий журнал", encoding="utf-8")
    res = backup.restore(str(dst))
    assert (data / "journal.csv").read_text(encoding="utf-8") == "свежий журнал"
    assert res["skipped"] > 0


def test_restore_can_replace_when_asked(data):
    dst = data / "out.zip"
    backup.create(str(dst))
    (data / "journal.csv").write_text("испортили", encoding="utf-8")
    backup.restore(str(dst), replace=True)
    assert "Бор" in (data / "journal.csv").read_text(encoding="utf-8")


def test_alien_archive_is_refused(tmp_path):
    """Архив с отпускными фотографиями не должен разворачиваться в журнал."""
    alien = tmp_path / "alien.zip"
    with zipfile.ZipFile(alien, "w") as z:
        z.writestr("отпуск/море.jpg", b"data")
    with pytest.raises(backup.NotOurs):
        backup.inspect(str(alien))


def test_archive_from_a_newer_version_is_refused(tmp_path):
    newer = tmp_path / "newer.zip"
    with zipfile.ZipFile(newer, "w") as z:
        z.writestr(backup.MANIFEST, json.dumps({"app": "navigator-gribnika",
                                                "format": backup.FORMAT + 1}))
    with pytest.raises(backup.NotOurs):
        backup.inspect(str(newer))


def test_garbage_file_is_refused(tmp_path):
    junk = tmp_path / "junk.zip"
    junk.write_bytes("это не архив".encode("utf-8"))
    with pytest.raises(backup.NotOurs):
        backup.inspect(str(junk))


def test_paths_climbing_out_of_the_archive_are_ignored(data, tmp_path):
    """Классика: zip с путём ../../ раскладывает файлы куда захочет.

    Копия приходит из почты и с чужой флешки, то есть из места, которому
    доверять нельзя, — поэтому проверяется каждое имя, а не только своё.
    """
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr(backup.MANIFEST, json.dumps({"app": "navigator-gribnika",
                                                "format": backup.FORMAT}))
        z.writestr("../../взлом.txt", "нет")
        z.writestr("/etc/passwd", "нет")
        z.writestr("journal.csv", "дата;место\n")
    fresh = tmp_path / "цель"
    fresh.mkdir()
    res = backup.restore(str(evil), root=str(fresh))
    assert res["added"] == 1
    assert (fresh / "journal.csv").exists()
    assert not (tmp_path / "взлом.txt").exists()
    assert not (tmp_path.parent / "взлом.txt").exists()


def test_full_circle(data, tmp_path):
    """Собрали, развернули на пустом месте, собрали снова — то же самое."""
    first = data / "a.zip"
    backup.create(str(first))
    fresh = tmp_path / "чистый"
    fresh.mkdir()
    backup.restore(str(first), root=str(fresh))
    second = tmp_path / "b.zip"
    backup.create(str(second), root=str(fresh))
    a = sorted(n for n in zipfile.ZipFile(first).namelist())
    b = sorted(n for n in zipfile.ZipFile(second).namelist())
    assert a == b


# --------------------------------------------------------------------------- #
#  Честность интерфейса
# --------------------------------------------------------------------------- #

def _visible_strings(path):
    """Строковые литералы модуля, кроме докстрок.

    Тот же разбор, что в test_icons: запрещать упоминание фразы в
    комментарии — значит запретить объяснить, почему её нельзя писать на
    кнопке.
    """
    import ast

    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    docs = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
                and body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            docs.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docs]


def test_screen_does_not_promise_to_send_mail_itself():
    """Кнопка «Отправить на почту» была бы удобной неправдой.

    Приложение не знает ни ящика человека, ни пароля: оно отдаёт файл
    системе, а почтовую программу выбирает человек. Решив, что копия ушла
    сама, он перестанет о ней думать — и это худший исход из возможных.
    """
    shown = " ".join(_visible_strings(os.path.join(ROOT, "backupscreen.py")))
    assert "Отправить на почту" not in shown
    assert "не знает ни вашего ящика" in shown


def test_mail_limit_is_mentioned_before_the_work():
    with open(os.path.join(ROOT, "backupscreen.py"), encoding="utf-8") as f:
        src = f.read()
    assert "MAIL_LIMIT_MB" in src and "fits_mail" in src


def test_vanished_file_does_not_break_the_copy(data, monkeypatch):
    """Снимок, удалённый между подсчётом и записью, — не повод падать."""
    real = zipfile.ZipFile.write

    def sneaky(self, filename, arcname=None, **kw):
        # Порядок обхода каталога не задан, поэтому файл исчезает ровно в
        # тот момент, когда до него дошла очередь: иначе тест зависел бы от
        # того, в каком порядке файловая система вернула имена.
        if arcname == "photos/b.jpg":
            os.remove(filename)
            raise OSError("файл исчез")
        return real(self, filename, arcname, **kw)

    monkeypatch.setattr(zipfile.ZipFile, "write", sneaky)
    dst = data / "out.zip"
    info = backup.create(str(dst))
    assert dst.exists()
    assert info["missing"] == 1
    names = zipfile.ZipFile(dst).namelist()
    assert "journal.csv" in names and "photos/a.jpg" in names
