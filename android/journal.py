#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
journal.py — журнал выездов. Основа для калибровки модели под ваши места.

Формат — CSV с разделителем «;» в кодировке UTF-8 BOM, открывается Excel
двойным щелчком и правится вручную. Одна строка — один вид в одном выезде.

    дата;место;широта;долгота;вид;обилие;заметка
    2026-08-14;Дальний бор;55.9606;38.0456;белый;3;по краю просеки
    2026-08-14;Дальний бор;55.9606;38.0456;подберёзовик;4;
    2026-08-14;Дальний бор;55.9606;38.0456;опёнок;0;не смотрел пни

Шкала обилия:
    0 — не было совсем (важнейшие записи, без них калибровка слепа)
    1 — единичные находки, час на гриб
    2 — мало, на жарёху
    3 — умеренно, обычный выезд
    4 — обильно, набрал сколько хотел
    5 — массовый слой, хоть косой коси

Команды:
    python journal.py init                      создать пустой журнал с примером
    python journal.py add --species белый --score 3 --place "Дальний бор"
    python journal.py check                     проверить на ошибки
    python journal.py stats                     сводка по накопленному
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict
from datetime import date

import mushroom_forecast as engine

JOURNAL = "journal.csv"
FIELDS = ["дата", "место", "широта", "долгота", "биотоп", "вид", "обилие", "заметка"]

SCORE_NAMES = {0: "не было", 1: "единично", 2: "мало", 3: "умеренно",
               4: "обильно", 5: "массово"}

# Обилие -> целевое значение индекса при калибровке.
SCORE_TO_INDEX = {0: 4.0, 1: 22.0, 2: 40.0, 3: 58.0, 4: 76.0, 5: 92.0}


class Entry:
    __slots__ = ("d", "place", "lat", "lon", "key", "score", "note", "biotope")

    def __init__(self, d, place, lat, lon, key, score, note="", biotope="смешанный"):
        self.d, self.place = d, place
        self.lat, self.lon = lat, lon
        self.key, self.score, self.note = key, score, note
        self.biotope = biotope if biotope in engine.BIOTOPES else "смешанный"

    @property
    def target(self) -> float:
        return SCORE_TO_INDEX[self.score]


def species_key(name: str) -> str | None:
    """Приводит написание вида к ключу словаря SPECIES."""
    n = name.strip().lower()
    if n in engine.SPECIES:
        return n
    for k, sp in engine.SPECIES.items():
        if sp.name.lower() == n or k.startswith(n) or n.startswith(k):
            return k
    return None


def read(path: str = JOURNAL) -> list[Entry]:
    if not os.path.exists(path):
        raise SystemExit(f"Журнал не найден: {path}. Создайте его: python journal.py init")
    out, problems = [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.DictReader(f, delimiter=";"), start=2):
            if not (row.get("дата") or "").strip():
                continue
            try:
                d = date.fromisoformat(row["дата"].strip())
                lat = float(str(row["широта"]).replace(",", "."))
                lon = float(str(row["долгота"]).replace(",", "."))
                score = int(str(row["обилие"]).strip())
                key = species_key(row["вид"])
                if key is None:
                    raise ValueError(f"неизвестный вид {row['вид']!r}")
                if not 0 <= score <= 5:
                    raise ValueError("обилие вне диапазона 0-5")
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError("координаты вне допустимых значений")
            except (KeyError, ValueError, TypeError) as e:
                problems.append(f"  строка {n}: {e}")
                continue
            out.append(Entry(d, (row.get("место") or "").strip(), lat, lon, key,
                             score, (row.get("заметка") or "").strip(),
                             (row.get("биотоп") or "смешанный").strip().lower()))
    if problems:
        print("Пропущены строки с ошибками:", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
    return out


def write_header(path: str, example: bool = True):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(FIELDS)
        if example:
            w.writerow([date.today().isoformat(), "Дальний бор", "55.9606", "38.0456",
                        "березняк", "белый", "3", "пример строки, замените своей"])


def append(path: str, e: Entry):
    exists = os.path.exists(path)
    if not exists:
        write_header(path, example=False)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f, delimiter=";").writerow(
            [e.d.isoformat(), e.place, f"{e.lat:.5f}", f"{e.lon:.5f}",
             e.biotope, e.key, e.score, e.note])


# --------------------------------------------------------------------------- #

def cmd_stats(entries: list[Entry]):
    if not entries:
        print("Журнал пуст.")
        return
    by_sp = defaultdict(list)
    for e in entries:
        by_sp[e.key].append(e)
    days = {(e.d, e.place) for e in entries}
    print(f"Записей: {len(entries)} · выездов: {len(days)} · "
          f"период: {min(e.d for e in entries)} — {max(e.d for e in entries)}")
    places = Counter(e.place for e in entries)
    print("Места: " + ", ".join(f"{p} ({n})" for p, n in places.most_common(6)))
    bios = Counter(e.biotope for e in entries)
    print("Биотопы: " + ", ".join(f"{b} ({n})" for b, n in bios.most_common()))
    print()
    print(f"  {'вид':<20}{'записей':>9}{'нулей':>7}{'средн.':>8}   распределение")
    for key, es in sorted(by_sp.items(), key=lambda kv: -len(kv[1])):
        scores = [e.score for e in es]
        hist = Counter(scores)
        bar = "".join(f"{hist.get(s, 0):>3}" for s in range(6))
        print(f"  {engine.SPECIES[key].name:<20}{len(es):>9}"
              f"{sum(1 for s in scores if s == 0):>7}"
              f"{sum(scores) / len(scores):>8.2f}   {bar}")
    print("                                              " + "".join(f"{s:>3}" for s in range(6)))
    print()
    n_zero = sum(1 for e in entries if e.score == 0)
    if len(entries) < 30:
        print("Для калибровки нужно хотя бы 30 записей, лучше 60+.")
    elif n_zero < len(entries) * 0.2:
        print("Мало записей с обилием 0. Пустые выезды тоже фиксируйте — "
              "без них модель не научится говорить «не ехать».")
    else:
        print("Объёма достаточно: можно запускать python calibrate.py")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Журнал грибных выездов.")
    ap.add_argument("command", choices=["init", "add", "check", "stats"])
    ap.add_argument("--file", default=JOURNAL)
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--place", default="")
    ap.add_argument("--lat", type=float, default=55.9606)
    ap.add_argument("--lon", type=float, default=38.0456)
    ap.add_argument("--species")
    ap.add_argument("--score", type=int)
    ap.add_argument("--note", default="")
    ap.add_argument("--biotope", default="смешанный",
                    help="тип леса: " + ", ".join(engine.BIOTOPES))
    a = ap.parse_args(argv)

    if a.command == "init":
        if os.path.exists(a.file):
            print(f"Файл уже существует: {a.file}")
            return 1
        write_header(a.file)
        print(f"Создан {os.path.abspath(a.file)}. Откройте в Excel и заполняйте.")
        print("Шкала обилия: " + ", ".join(f"{k} — {v}" for k, v in SCORE_NAMES.items()))
        return 0

    if a.command == "add":
        if a.species is None or a.score is None:
            print("Нужны --species и --score", file=sys.stderr)
            return 1
        key = species_key(a.species)
        if key is None:
            print(f"Неизвестный вид: {a.species}. Доступно: {', '.join(engine.SPECIES)}",
                  file=sys.stderr)
            return 1
        e = Entry(date.fromisoformat(a.date), a.place, a.lat, a.lon, key, a.score,
                  a.note, a.biotope)
        append(a.file, e)
        print(f"Записано: {e.d} · {engine.SPECIES[key].name} · "
              f"{a.score} ({SCORE_NAMES[a.score]})")
        return 0

    entries = read(a.file)
    if a.command == "check":
        print(f"Прочитано записей: {len(entries)}")
        return 0
    cmd_stats(entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
