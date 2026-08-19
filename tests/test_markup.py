# -*- coding: utf-8 -*-
"""Экранирование чужого текста в подписях Kivy.

Kivy разбирает в подписях теги вида [b] и [size=…]. Почти всякая посторонняя
скобка проходит насквозь, но [size=нечисло] разбирается всерьёз и роняет
отрисовку. Опасен здесь не столько причудливо названный лес, сколько окно
аварии: в него уходит текст исключения, а он бывает каким угодно. Окно,
которое падает, показывая ошибку, не оставляет человеку ничего.
"""

import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "android")
sys.path.insert(0, ROOT)

import markup  # noqa: E402


def test_brackets_become_entities():
    assert markup.esc("[b]жирный[/b]") == "&bl;b&br;жирный&bl;/b&br;"


def test_ampersand_goes_first():
    """Иначе добавленные следом &bl; сами оказались бы испорчены."""
    assert markup.esc("&") == "&amp;"
    assert markup.esc("[a&b]") == "&bl;a&amp;b&br;"


def test_plain_text_is_untouched():
    assert markup.esc("Ельник у просеки, 3 км") == "Ельник у просеки, 3 км"


def test_numbers_and_objects_survive():
    assert markup.esc(42) == "42"
    assert markup.esc(ValueError("[size=x]")).startswith("&bl;size")


def _src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_crash_dialog_escapes_the_traceback():
    src = _src("main.py")
    i = src.index("def handle_exception")
    body = src[i:i + 1200]
    assert "markup.esc(tb)" in body
    assert "markup.esc(self._headline(tb))" in body


def test_place_name_is_escaped_where_it_meets_markup():
    """Название места человек придумывает сам, и оно едет в разметку."""
    src = _src("walkjournal.py")
    assert src.count("markup.esc(walk.place") == 2
