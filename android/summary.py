# -*- coding: utf-8 -*-
"""
summary.py — человеческие подписи к походу: когда, сколько, что взяли.

Отдельно от walkjournal.py по той же причине, по какой арифметика компаса
отделена от стрелки: здесь нет ни одного виджета, поэтому модуль
импортируется и проверяется где угодно, включая сборочную машину, на
которой Kivy не установлен вовсе.

Повод был буквальный: тесты журнала импортировали walkjournal, тот тянул
kivy.graphics, и релизная сборка падала на прогоне тестов — при том что
проверялись в них одни только строки вида «2 ч 15 мин».
"""

from __future__ import annotations

from datetime import datetime

import mushroom_forecast as engine

RU_MONTH = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
            "августа", "сентября", "октября", "ноября", "декабря")


def when_text(walk) -> str:
    """«16 августа, 9:40» — год добавляется только если он не нынешний."""
    d = datetime.fromtimestamp(walk.started)
    text = f"{d.day} {RU_MONTH[d.month - 1]}"
    if d.year != datetime.now().year:
        text += f" {d.year}"
    return f"{text}, {d:%H:%M}"


def duration_text(seconds: float) -> str:
    """«2 ч 15 мин», «40 мин». Секунды в лесу никого не интересуют."""
    minutes = int(max(0.0, seconds) // 60)
    if minutes < 60:
        return f"{minutes} мин"
    return f"{minutes // 60} ч {minutes % 60:02d} мин"


def distance_text(metres: float) -> str:
    if metres < 1000:
        return f"{int(round(metres / 10.0)) * 10} м"
    return f"{metres / 1000.0:.1f} км".replace(".", ",")


def species_line(walk) -> str:
    """«Белый гриб 4, лисичка 12» — по убыванию количества.

    Именно это человек ищет в списке глазами: не километры и не время, а
    что взяли. Поэтому строка идёт крупно и первой после места.
    """
    counts = {}
    for f in walk.finds:
        if not f.species:
            continue
        counts[f.species] = counts.get(f.species, 0) + max(1, f.count)
    if not counts:
        return "без находок" if walk.finds else ""
    order = sorted(counts.items(), key=lambda kv: -kv[1])
    parts = []
    for key, n in order[:4]:
        name = engine.SPECIES[key].name if key in engine.SPECIES else key
        parts.append(f"{name.lower()} {n}")
    if len(order) > 4:
        parts.append(f"и ещё {len(order) - 4}")
    return ", ".join(parts)


def stats_line(walk) -> str:
    bits = [distance_text(walk.distance), duration_text(walk.duration)]
    n = len(walk.photo_names())
    if n:
        bits.append(f"снимков {n}")
    return " · ".join(bits)


