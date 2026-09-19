# -*- coding: utf-8 -*-
"""
power.py — сколько осталось заряда.

Зачем. Поход часто длиннее заряда: экран, GPS и фоновый сервис едят батарею
быстрее, чем кажется. Телефон, севший в лесу, — это не только потерянный
трек, но и потерянная дорога к машине, потому что стрелка возврата живёт
в том же телефоне. Предупредить об этом стоит заранее и один раз, а не
показывать проценты постоянно: лишняя цифра на экране только отвлекает.

Источники, по очереди:

  1. Android через pyjnius — registerReceiver с ACTION_BATTERY_CHANGED
     возвращает последнее «липкое» сообщение системы сразу, без ожидания;
  2. plyer.battery — тот же вызов, но через прослойку, которая на части
     сборок отсутствует;
  3. /sys/class/power_supply/*/capacity — работает на многих аппаратах
     и на настольном Linux, где ноутбук тоже имеет батарею.

Ничего не получилось — level() возвращает None, и приложение просто молчит.
Выдумывать «наверное, 50%» здесь нельзя: на ложном спокойствии человек
останется в лесу без телефона.
"""

from __future__ import annotations

import glob
import time

#: Ниже этого — первое предупреждение, проценты.
LOW = 15

#: Ниже этого — второе, последнее.
CRITICAL = 5

#: Как часто спрашивать систему, секунды. Заряд не меняется быстрее, а вызов
#: через jnius не бесплатный: раз в секунду он заметен на слабом аппарате.
PERIOD = 60.0

_cache: tuple[float, int | None] = (0.0, None)


def _from_jnius():
    from jnius import autoclass

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    IntentFilter = autoclass("android.content.IntentFilter")
    Intent = autoclass("android.content.Intent")
    BatteryManager = autoclass("android.os.BatteryManager")
    activity = PythonActivity.mActivity
    intent = activity.registerReceiver(
        None, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
    if intent is None:
        return None
    level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
    scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
    if level < 0 or scale <= 0:
        return None
    return int(round(100.0 * level / scale))


def _from_plyer():
    from plyer import battery

    status = battery.status or {}
    pct = status.get("percentage")
    return None if pct is None else int(round(float(pct)))


def _from_sysfs():
    for path in sorted(glob.glob("/sys/class/power_supply/*/capacity")):
        try:
            with open(path, encoding="ascii") as f:
                return max(0, min(100, int(f.read().strip())))
        except (OSError, ValueError):
            continue
    return None


SOURCES = (_from_jnius, _from_plyer, _from_sysfs)


def level(now: float | None = None) -> int | None:
    """Заряд в процентах или None, если узнать не удалось."""
    global _cache
    now = time.time() if now is None else now
    when, value = _cache
    if value is not None and now - when < PERIOD:
        return value
    for source in SOURCES:
        try:
            got = source()
        except Exception:                                         # noqa: BLE001
            continue
        if got is not None:
            _cache = (now, int(got))
            return _cache[1]
    _cache = (now, None)
    return None


def reset() -> None:
    """Забыть кэш. Нужен тестам."""
    global _cache
    _cache = (0.0, None)


def warning(pct: int | None, already: int = 0) -> tuple[str, int]:
    """Что сказать про заряд и на каком пороге это сказано.

    already — порог, о котором уже предупреждали (0 — ещё ни о чём). Возврат
    («», already) означает «молчать»: повторять одно и то же каждую минуту
    хуже, чем не сказать вовсе — человек перестаёт читать подсказку совсем.
    """
    if pct is None:
        return "", already
    if pct <= CRITICAL and already != CRITICAL:
        return (f"Заряд {pct}%. Выходите к машине сейчас: без телефона "
                f"не будет ни карты, ни стрелки возврата.", CRITICAL)
    if pct <= LOW and already not in (LOW, CRITICAL):
        return (f"Заряд {pct}%. Погасите экран — запись продолжит фоновая "
                f"служба, а заряд уйдёт втрое медленнее.", LOW)
    return "", already
