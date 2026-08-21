# -*- coding: utf-8 -*-
"""
walk2journal.py — превращает пройденный маршрут в записи журнала.

Зачем. Журнал (`journal.csv`) — это то, по чему `calibrate.py` подгоняет
константы модели под конкретный лес. До сих пор его нужно было заполнять
руками, а значит, он оставался пустым: после трёх часов ходьбы садиться и
вбивать координаты никто не будет.

Поход же содержит ровно те сведения, которые нужны журналу: дата, место,
координаты, вид, количество. Остаётся перевести одно в другое.

Главная тонкость — обилие. В журнале это оценка 0-5 по всей вылазке, а не
число грибов в конкретной точке. Поэтому находки одного вида сводятся вместе,
и оценка выставляется по их количеству с поправкой на длину маршрута: пять
белых на километр и пять белых на десять километров — это разные события.

Вторая тонкость — пустой поход. Если человек прошёл пять километров и не
нашёл ничего, это ценная запись, а не отсутствие записи: модель должна знать
и про промахи, иначе она обучится только на удачных днях.
"""

from __future__ import annotations

from datetime import date, datetime

import journal
import mushroom_forecast as engine

# Сколько находок на километр маршрута соответствует какой оценке.
# Числа взяты из здравого смысла грибника, а не из литературы: одна находка
# на километр — «единично», пять — «умеренно», больше двадцати — «массово».
DENSITY_TO_SCORE = [
    (0.0, 0),      # ничего
    (0.3, 1),      # единично
    (1.5, 2),      # мало
    (4.0, 3),      # умеренно
    (10.0, 4),     # обильно
    (20.0, 5),     # массовый слой
]

# Минимальная длина маршрута для расчёта плотности. Если человек прошёл
# двести метров и набрал ведро, делить на 0.2 км нельзя — получится
# фантастическая плотность.
MIN_KM = 0.5


def score_for(count: int, km: float) -> int:
    """Оценка обилия 0-5 по числу находок и длине маршрута."""
    if count <= 0:
        return 0
    density = count / max(MIN_KM, km)
    score = 1
    for threshold, s in DENSITY_TO_SCORE:
        if density >= threshold:
            score = s
    return max(1, score)


# Сколько знаков заметок грибника переносить в журнал. Журнал открывают
# в Excel, и колонка на пол-экрана делает таблицу нечитаемой; полный текст
# всё равно остаётся в файле похода и в GPX.
NOTE_LIMIT = 120


def note_for(finds, count: int, tail: str) -> str:
    """Заметка строки журнала: сводка плюс то, что человек написал сам.

    Собственные слова грибника ценнее автоматики: «все червивые» или
    «только по краю вырубки» объясняют оценку обилия так, как её не
    объяснит ни одна формула. Поэтому они идут первыми.
    """
    said = []
    photos = 0
    for f in finds:
        text = (getattr(f, "note", "") or "").strip()
        if text and text not in said:
            said.append(text)
        photos += len(getattr(f, "photos", ()) or ())
    parts = []
    if said:
        joined = "; ".join(said)
        if len(joined) > NOTE_LIMIT:
            joined = joined[:NOTE_LIMIT - 1].rstrip() + "…"
        parts.append(joined)
    parts.append(f"{count} шт.")
    if photos:
        parts.append(f"снимков {photos}")
    parts.append(tail)
    return ", ".join(parts)


def centroid(finds) -> tuple[float, float]:
    """Средняя точка находок: журналу нужна одна координата на запись."""
    n = len(finds)
    return (sum(f.lat for f in finds) / n, sum(f.lon for f in finds) / n)


def walk_date(walk) -> date:
    return datetime.fromtimestamp(walk.started).date()


def check_biotope(biotope: str) -> str:
    """Сверяет биотоп со списком модели.

    journal.Entry молча подменяет незнакомое значение на «смешанный»,
    и в журнал уходят данные не про тот лес. Опечатка вроде «берёзовый»
    вместо «березняк» так и осталась бы незамеченной до самой калибровки,
    поэтому здесь она превращается в явную ошибку.
    """
    if biotope and biotope not in engine.BIOTOPES:
        raise ValueError(
            f"неизвестный биотоп {biotope!r}; допустимы: "
            f"{', '.join(engine.BIOTOPES)}")
    return biotope or "смешанный"


def entries_from_walk(walk, place: str = "", biotope: str = "") -> list:
    """Записи журнала по одному походу.

    На каждый найденный вид — одна запись со средней координатой и оценкой
    обилия. Если находок не было вовсе, возвращается одна запись с нулевой
    оценкой по последней точке маршрута: отрицательный опыт тоже данные.
    """
    place = place or walk.place or ""
    biotope = check_biotope(biotope or getattr(walk, "biotope", "смешанный"))
    d = walk_date(walk)
    km = walk.distance / 1000.0
    note = f"маршрут {km:.1f} км, автозапись"

    by_species: dict[str, list] = {}
    for f in walk.finds:
        if f.species and f.species in engine.SPECIES:
            by_species.setdefault(f.species, []).append(f)

    out = []
    for key, finds in by_species.items():
        count = sum(max(1, getattr(f, "count", 1)) for f in finds)
        lat, lon = centroid(finds)
        out.append(journal.Entry(d, place, lat, lon, key,
                                 score_for(count, km),
                                 note_for(finds, count, note), biotope))

    if not out and walk.points:
        last = walk.points[-1]
        out.append(journal.Entry(d, place, last.lat, last.lon, "",
                                 0, f"пусто, {note}", biotope))
    return out


def export(walk, place: str = "", biotope: str = "",
           path: str = None) -> int:
    """Дописывает поход в журнал. Возвращает число добавленных записей."""
    entries = entries_from_walk(walk, place, biotope)
    target = path or journal_path()
    for e in entries:
        journal.append(target, e)
    return len(entries)


def journal_path() -> str:
    """Журнал лежит рядом с остальными данными приложения."""
    import os

    import places as places_mod
    return os.path.join(places_mod.data_dir(), journal.JOURNAL)


def summary(walk) -> str:
    """Короткая сводка для показа человеку перед записью в журнал."""
    entries = entries_from_walk(walk)
    if not entries:
        return "Записывать нечего: маршрут пуст"
    if len(entries) == 1 and not entries[0].key:
        return f"Пустой выход, {walk.distance / 1000.0:.1f} км — тоже запись"
    parts = []
    for e in entries:
        name = engine.SPECIES[e.key].name if e.key else "метка"
        parts.append(f"{name}: {journal.SCORE_NAMES[e.score]}")
    return "; ".join(parts)
