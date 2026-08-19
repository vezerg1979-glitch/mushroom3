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


# --------------------------------------------------------------------------- #
#  Обещание модели против того, что вышло
# --------------------------------------------------------------------------- #
#
# Прогноз в приложении был односторонним: он что-то обещал, и на этом всё
# заканчивалось. Между тем поход записывает как раз ответ — сколько нашли, —
# и с версии, где индекс сохраняется вместе с походом, эти две половины
# наконец можно свести.
#
# Смысл не в том, чтобы поставить модели оценку. Смысл в том, что у каждого
# леса своя шкала: в одном месте индекс 45 уже означает полную корзину, в
# другом и при 70 пусто. Общий прогноз этого знать не может, а полсотни
# собственных походов — могут.

# Ниже этого числа находок на километр поход считается пустым. Порог не
# теоретический: одна-две случайные находки на пять километров — это «ничего
# не было», как ни назови, и в шкалу они попадать не должны.
GOOD_PER_KM = 1.0

# Меньше этого числа походов со снимком прогноза — молчим. Три точки не
# шкала, а совпадение, и показывать их как вывод нечестно.
MIN_WALKS = 6


def walk_index(walk, key: str = "") -> float | None:
    """Индекс, обещанный на день похода: по виду или лучший из всех.

    None означает «прогноз тогда не снимали» — у походов, записанных до
    появления снимка, или когда человек вышел, не обновив прогноз.
    """
    idx = getattr(walk, "index", None) or {}
    if key:
        v = idx.get(key)
        return float(v) if v is not None else None
    values = [float(v) for v in idx.values() if v is not None]
    return max(values) if values else None


def index_line(walk) -> str:
    """Строка для карточки похода: что обещали и по какому виду."""
    idx = getattr(walk, "index", None) or {}
    if not idx:
        return ""
    best_key = max(idx, key=lambda k: idx[k])
    name = (engine.SPECIES[best_key].name.lower()
            if best_key in engine.SPECIES else best_key)
    out = f"Прогноз в тот день: {idx[best_key]:.0f} ({name})"
    # Если что-то нашли, интереснее индекс именно этого вида: он и есть
    # проверка обещания, а не общий максимум по всем видам сразу.
    found = sorted({f.species for f in walk.finds if f.species})
    parts = [f"{engine.SPECIES[k].name.lower()} {idx[k]:.0f}"
             for k in found
             if k != best_key and k in idx and k in engine.SPECIES]
    if parts:
        out += "; нашли — " + ", ".join(parts[:3])
    return out


def _rated(walks) -> list:
    """(индекс, находок на км) по походам, где есть и то и другое."""
    out = []
    for w in walks:
        v = walk_index(w)
        if v is None or w.km <= 0.2:
            continue
        out.append((v, len(w.finds) / w.km))
    return out


def personal_scale(walks) -> str:
    """Своя шкала: с какого индекса походы этого человека были удачными.

    Считается нарочно грубо — граница между лучшим пустым и худшим удачным
    выездом, — потому что данных мало и любая тонкая статистика на двух
    десятках точек соврёт увереннее, чем поможет. Числа говорят сами за
    себя, поэтому вывод даётся одной фразой и без процентов.
    """
    data = _rated(walks)
    if len(data) < MIN_WALKS:
        if not data:
            return ""
        # Без склонения числительных намеренно: «после ещё 1 походов» —
        # ровно та мелочь, из-за которой текст выглядит машинным.
        return (f"Своя шкала появится, когда походов с прогнозом станет "
                f"{MIN_WALKS} (сейчас {len(data)}).")
    good = [v for v, rate in data if rate >= GOOD_PER_KM]
    empty = [v for v, rate in data if rate < GOOD_PER_KM]
    if not good:
        return (f"По {len(data)} походам удачных пока не было — "
                f"сравнивать не с чем.")
    if not empty:
        return (f"По {len(data)} походам вы возвращались с находками при "
                f"любом индексе от {min(good):.0f}.")
    lo = min(good)
    hi = max(empty)
    if lo > hi:
        return (f"По {len(data)} походам: с находками — от индекса {lo:.0f}, "
                f"пусто — до {hi:.0f}.")
    # Границы перекрываются: честнее сказать об этом, чем рисовать порог,
    # которого в данных нет.
    return (f"По {len(data)} походам чёткой границы не видно: удачные "
            f"выезды случались и при {lo:.0f}, пустые — и при {hi:.0f}.")


