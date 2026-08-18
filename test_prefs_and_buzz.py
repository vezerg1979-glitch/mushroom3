# -*- coding: utf-8 -*-
"""Мелкие настройки и виброотклик.

Обе вещи объединяет одно свойство: они не должны мешать приложению открыться.
Настройки можно потерять без последствий, вибромотор может отсутствовать —
и в том, и в другом случае человек должен получить работающую программу,
а не сообщение об ошибке посреди леса.
"""

import os
import sys
import tempfile

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "android")
sys.path.insert(0, ROOT)

import buzz  # noqa: E402
import places  # noqa: E402
import prefs  # noqa: E402


@pytest.fixture
def data_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(places, "_DATA_DIR", tmp)
        yield tmp


# --------------------------------------------------------------------------- #
#  Настройки
# --------------------------------------------------------------------------- #

def test_saved_value_comes_back(data_dir):
    assert prefs.save(kind="Белый гриб")
    assert prefs.get("kind") == "Белый гриб"


def test_saving_one_key_keeps_the_others(data_dir):
    """Вид и тип леса пишутся по отдельности, из разных обработчиков."""
    prefs.save(kind="Лисичка")
    prefs.save(biotope="сосняк")
    assert prefs.load() == {"kind": "Лисичка", "biotope": "сосняк"}


def test_missing_file_is_not_an_error(data_dir):
    assert prefs.load() == {}
    assert prefs.get("kind", "Все виды сезона") == "Все виды сезона"


def test_broken_file_falls_back_to_defaults(data_dir):
    """Телефон выключается в кармане; недописанный файл не повод падать."""
    with open(os.path.join(data_dir, prefs.FILE), "w", encoding="utf-8") as f:
        f.write('{"kind": "Белый')
    assert prefs.load() == {}
    assert prefs.get("kind") is None


def test_file_of_the_wrong_shape_is_ignored(data_dir):
    """Не словарь — значит, файл не наш."""
    with open(os.path.join(data_dir, prefs.FILE), "w", encoding="utf-8") as f:
        f.write("[1, 2, 3]")
    assert prefs.load() == {}


def test_broken_file_is_repaired_by_the_next_save(data_dir):
    with open(os.path.join(data_dir, prefs.FILE), "w", encoding="utf-8") as f:
        f.write("не json")
    assert prefs.save(kind="Груздь настоящий")
    assert prefs.get("kind") == "Груздь настоящий"


def test_save_leaves_no_temporary_file(data_dir):
    prefs.save(kind="Опёнок осенний")
    assert os.listdir(data_dir) == [prefs.FILE]


# --------------------------------------------------------------------------- #
#  Восстановление выбора на главном экране
# --------------------------------------------------------------------------- #

def _src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_choices_are_saved_and_restored():
    src = _src("main.py")
    assert "prefs.save(kind=" in src
    assert "prefs.save(biotope=" in src
    assert "_saved_kind" in src and "_saved_biotope" in src


def test_unknown_saved_choice_falls_back_to_the_reference_book():
    """Вид могли переименовать между версиями.

    Подставленная вслепую строка оставила бы в списке подпись, которой ни
    в одном профиле нет, и прогноз считался бы неизвестно по чему.
    """
    import mushroom_forecast as engine

    src = _src("main.py")
    assert "engine.BIOTOPES.get" in src
    assert "any(sp.name == name for sp in engine.SPECIES.values())" in src
    # Заодно убеждаемся, что значение по умолчанию в справочнике есть.
    assert "смешанный" in engine.BIOTOPES


# --------------------------------------------------------------------------- #
#  Вибро
# --------------------------------------------------------------------------- #

def test_no_vibrator_is_not_a_crash(monkeypatch):
    """На компьютере и на телефоне без мотора plyer просто не поднимется."""
    buzz.reset()
    assert buzz.tap() is False
    assert buzz.long() is False


def test_broken_motor_is_asked_only_once(monkeypatch):
    """Иначе каждое нажатие уходит в исключение — заметная задержка."""
    buzz.reset()
    calls = []

    class Boom:
        def vibrate(self, seconds):
            calls.append(seconds)
            raise RuntimeError("нет мотора")

    monkeypatch.setitem(sys.modules, "plyer", type("M", (), {"vibrator": Boom()}))
    assert buzz.tap() is False
    assert buzz.tap() is False
    assert len(calls) == 1
    buzz.reset()


def test_working_motor_gets_the_durations(monkeypatch):
    buzz.reset()
    calls = []

    class Ok:
        def vibrate(self, seconds):
            calls.append(seconds)

    monkeypatch.setitem(sys.modules, "plyer", type("M", (), {"vibrator": Ok()}))
    assert buzz.tap() is True
    assert buzz.long() is True
    assert calls == [buzz.TAP, buzz.LONG]
    assert buzz.TAP < buzz.LONG        # на ощупь это разные события
    buzz.reset()


def test_marking_a_find_buzzes():
    src = _src("walkscreen.py")
    i = src.index("def _add_find")
    assert "buzz.tap()" in src[i:i + 800]


def test_vibrate_permission_is_declared():
    """Без строки в манифесте вызов молча ничего не делает."""
    with open(os.path.join(ROOT, "buildozer.spec"), encoding="utf-8") as f:
        assert "android.permission.VIBRATE" in f.read()
