# -*- coding: utf-8 -*-
"""
wave.py — когда начнётся слой и стоит ли ради этого будить человека.

Прогноз в приложении односторонний: он ждёт, что человек сам откроет
программу и посмотрит. В среду никто её не открывает — вспоминают в субботу
утром, а слой к этому времени уже неделю как идёт и наполовину собран
соседями. Ровно про это здесь и речь: заметить, что индекс поднимается, и
сказать об этом заранее.

Что считается волной. Не «индекс высокий» — тогда сообщение приходило бы
каждый день всю осень и через неделю перестало бы читаться. Волна — это
ПЕРЕХОД: сегодня ниже порога, в ближайшие дни выше. Один переход — одно
сообщение.

Молчание тут ценнее сообщения, поэтому ограничений несколько и они
намеренно строгие:

  * говорим только про виды, у которых сейчас сезон, и только если рост
    заметный — плюс десять пунктов, а не колебание третьего знака;
  * про один и тот же вид не напоминаем чаще раза в неделю, даже если
    индекс продолжает расти;
  * если волна уже идёт (сегодня и так выше порога), сообщение не имеет
    смысла: человек это увидит, открыв приложение, а будить его новостью
    «то, что вы и так знаете» — верный способ отключить уведомления
    насовсем. А отключённое уведомление не вернёшь: второй раз его никто
    не включит.

Ничего из этого не требует ни сети, ни Android: на вход подаётся готовый
прогноз, на выход — текст или пусто. Поэтому модуль целиком проверяется на
компьютере.
"""

from __future__ import annotations

import json
import os
import time

import mushroom_forecast as engine
import places as places_mod

#: Индекс, ниже которого ехать обычно незачем, а выше — уже стоит.
#: Взят из шкалы ядра: 50 — это «хорошо» (см. engine.LEVELS).
START = 50.0

#: Насколько индекс должен вырасти, чтобы это считалось волной, а не рябью.
RISE = 10.0

#: На сколько дней вперёд смотрим. Дальше прогноз погоды и сам ненадёжен,
#: а человеку нужно время сдвинуть дела — за день до выходных поздно.
HORIZON = 5

#: Не чаще одного сообщения про вид в такой срок.
COOLDOWN_S = 7 * 86400.0

STATE_FILE = "waves.json"


# --------------------------------------------------------------------------- #
#  Поиск волны
# --------------------------------------------------------------------------- #

def find(days, idx_by_key: dict, today: int = 0, horizon: int = HORIZON,
         start: float = START, rise: float = RISE) -> list:
    """Виды, у которых волна начинается в ближайшие дни.

    idx_by_key — {ключ вида: [индекс по дням]}, как его считает ядро.
    Возвращает [{key, name, day, value, now}], отсортированное: сначала то,
    что начнётся раньше, при равенстве — то, чего будет больше.
    """
    out = []
    for key, values in (idx_by_key or {}).items():
        sp = engine.SPECIES.get(key)
        if sp is None or not values or today >= len(values):
            continue
        now = _value(values, today)
        if now >= start:
            continue                       # волна уже идёт, новость не новость
        best = None
        for step in range(1, horizon + 1):
            i = today + step
            if i >= len(values):
                break
            v = _value(values, i)
            if v >= start and v - now >= rise:
                if best is None or v > best[1]:
                    best = (step, v)
                if best[0] == step:
                    break                  # первый же день перехода и важен
        if best is None:
            continue
        if not _in_season(sp, days, today + best[0]):
            continue
        out.append({"key": key, "name": sp.name, "day": best[0],
                    "value": round(best[1], 1), "now": round(now, 1)})
    out.sort(key=lambda r: (r["day"], -r["value"]))
    return out


def _value(values, i) -> float:
    try:
        v = float(values[i])
    except (TypeError, ValueError, IndexError):
        return 0.0
    return 0.0 if v != v else v            # NaN — это ноль, а не сбой


def _in_season(sp, days, i) -> bool:
    """Идёт ли у вида сезон в этот день.

    Проверка нужна из-за края сезона: модель может дать высокий индекс по
    погоде в ноябре, когда лисичек уже нет физически.
    """
    try:
        month = days[i].d.month
    except (AttributeError, IndexError, TypeError):
        return True
    return sp.months.get(month, 0) > 0


# --------------------------------------------------------------------------- #
#  Текст
# --------------------------------------------------------------------------- #

def _when(day: int) -> str:
    if day <= 1:
        return "завтра"
    if day == 2:
        return "послезавтра"
    return f"через {day} дня" if day < 5 else f"через {day} дней"


def message(found: list) -> tuple:
    """(заголовок, текст) для уведомления. Пустой список — пустые строки.

    Вид называется один, максимум два. Перечислять пять — значит писать
    сводку, которую на шторке уведомлений всё равно обрежут на середине.
    """
    if not found:
        return "", ""
    first = found[0]
    when = _when(first["day"])
    title = f"{first['name']}: слой {when}"
    names = [r["name"].lower() for r in found[:2]]
    body = (f"Индекс поднимается с {first['now']:.0f} до "
            f"{first['value']:.0f} — {engine.level(first['value'])}.")
    if len(found) > 1:
        body += f" Заодно {names[1]}."
    if len(found) > 2:
        body += f" И ещё {len(found) - 2} вида."
    return title, body


def line(found: list) -> str:
    """Одна строка для главного экрана: то же самое, но без уведомления."""
    if not found:
        return ""
    first = found[0]
    # Стрелки «→» в шрифте сборки нет: на телефоне вместо неё пустой
    # квадрат, поэтому «с … до …» словами.
    return (f"{first['name']} — слой {_when(first['day'])}: индекс "
            f"с {first['now']:.0f} до {first['value']:.0f}")


# --------------------------------------------------------------------------- #
#  Что уже говорили
# --------------------------------------------------------------------------- #
#
# Память нужна не для порядка, а чтобы не повторяться. Уведомление, которое
# приходит третий день подряд про один и тот же слой, человек отключает — и
# больше не включит никогда.

def _path() -> str:
    return os.path.join(places_mod.data_dir(), STATE_FILE)


def _load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> bool:
    path = _path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def fresh(found: list, place: str = "", now: float = None,
          cooldown: float = COOLDOWN_S) -> list:
    """Оставляет только то, о чём давно не говорили.

    Место входит в ключ: волна в ельнике под Фрязином и волна в бору за
    сотню километров — разные события, и молчать о втором из-за первого
    неправильно.
    """
    now = time.time() if now is None else now
    said = _load()
    out = []
    for r in found:
        key = f"{place}|{r['key']}"
        when = said.get(key, 0)
        try:
            when = float(when)
        except (TypeError, ValueError):
            when = 0.0
        if now - when >= cooldown:
            out.append(r)
    return out


def remember(found: list, place: str = "", now: float = None) -> bool:
    now = time.time() if now is None else now
    said = _load()
    for r in found:
        said[f"{place}|{r['key']}"] = now
    return _save(said)


def forget_all() -> bool:
    """Сброс памяти. Нужен тестам и человеку, сменившему место."""
    return _save({})
