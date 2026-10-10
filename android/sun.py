# -*- coding: utf-8 -*-
"""
sun.py — восход, закат и сколько осталось светлого времени.

Зачем. В лесу это второе по важности число после расстояния до машины.
Темнеет быстро и незаметно: под пологом ельника сумерки начинаются за
полчаса до заката, а грибник в это время как раз входит во вкус. Ошибка
стоит дорого — искать просеку с телефонным фонариком по мокрой траве.

Часов до заката приложение до сих пор не показывало нигде, хотя всё нужное
у него есть: координаты и дата. Считается это арифметикой, без сети и без
разрешений, поэтому работает и в глухом лесу с выключенными данными.

Точность. Формулы NOAA в упрощённом виде: ошибка порядка минуты в средних
широтах — на порядок меньше, чем разница между «закатом» и «стало темно»
в лесу. Полярный день и полярная ночь возвращают None: там солнце за сутки
не пересекает горизонт, и «время заката» не существует, а не равно нулю.

Модуль ничего не знает ни про Kivy, ни про часовые пояса: на вход дата и
координаты, на выход — момент времени в UTC-секундах (то же, что time.time()).
"""

from __future__ import annotations

import math
import time
from datetime import date, datetime, timezone

# Высота центра солнца в момент восхода и заката: −0.833°. Не ноль, потому
# что атмосфера приподнимает изображение примерно на 34 угловые минуты, а
# закатом считают уход за горизонт верхнего края диска, а не центра (ещё 16').
ZENITH = 90.833

#: Сколько до заката считается «пора выходить», секунды.
WARN_S = 45 * 60


def _day_number(d: date) -> int:
    """Номер солнечных суток от 1 января 2000 года (n в формулах NOAA)."""
    unix = datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()
    # Юлианская дата минус эпоха J2000; 10957.5 — расстояние между эпохой
    # Unix и J2000 в сутках. Округление вверх переводит счёт на солнечные
    # сутки, которые начинаются в полдень.
    return math.ceil(unix / 86400.0 - 10957.5 + 0.0008)


def _event(d: date, lat: float, lon: float, rising: bool) -> float | None:
    """Момент восхода (rising=True) или заката, unix-секунды, или None."""
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"широта вне диапазона: {lat}")

    # Поправка на долготу: солнечные сутки в точке наблюдения смещены
    # относительно гринвичских. Долгота здесь восточно-положительная.
    j_star = _day_number(d) - lon / 360.0
    m = math.radians((357.5291 + 0.98560028 * j_star) % 360.0)
    c = (1.9148 * math.sin(m) + 0.0200 * math.sin(2 * m)
         + 0.0003 * math.sin(3 * m))
    lam = math.radians((math.degrees(m) + c + 180.0 + 102.9372) % 360.0)
    j_transit = (2451545.0 + j_star + 0.0053 * math.sin(m)
                 - 0.0069 * math.sin(2 * lam))       # истинный солнечный полдень
    # Склонение солнца.
    decl = math.asin(math.sin(lam) * math.sin(math.radians(23.4397)))

    p = math.radians(lat)
    cos_h = ((math.cos(math.radians(ZENITH)) - math.sin(decl) * math.sin(p))
             / (math.cos(decl) * math.cos(p)))
    if cos_h > 1.0 or cos_h < -1.0:
        return None                    # полярная ночь или полярный день
    h = math.degrees(math.acos(cos_h))
    j = j_transit + (-h if rising else h) / 360.0
    return (j - 2440587.5) * 86400.0


def sunset(d: date, lat: float, lon: float) -> float | None:
    """Момент заката, unix-секунды. None — солнце в этот день не садится."""
    return _event(d, lat, lon, rising=False)


def sunrise(d: date, lat: float, lon: float) -> float | None:
    return _event(d, lat, lon, rising=True)


def seconds_to_sunset(lat: float, lon: float, now: float | None = None):
    """Сколько осталось до заката, секунды. Отрицательное — уже стемнело.

    None означает «сказать нечего»: заполярье или испорченные координаты.
    Ноль не годится — «до заката 0» человек прочтёт как «пора выходить»,
    а за полярным кругом это может быть неправдой в любую сторону.
    """
    now = time.time() if now is None else now
    try:
        today = datetime.fromtimestamp(now, timezone.utc).date()
    except (OSError, OverflowError, ValueError):
        return None
    try:
        t = sunset(today, lat, lon)
    except ValueError:
        return None
    if t is None:
        return None
    # Закат этих суток мог остаться позади: местная полночь и календарная
    # дата UTC не совпадают, и для восточных долгот «сегодня» по Гринвичу
    # заканчивается раньше, чем у человека.
    if t < now - 6 * 3600:
        t = sunset(datetime.fromtimestamp(now + 86400, timezone.utc).date(),
                   lat, lon)
        if t is None:
            return None
    return t - now


def text(seconds: float | None) -> str:
    """Короткая подпись для счётчика: «2 ч 40», «35 мин», «стемнело»."""
    if seconds is None or not math.isfinite(seconds):
        return "—"
    if seconds <= 0:
        return "стемнело"
    mins = int(seconds // 60)
    h, m = divmod(mins, 60)
    return f"{h} ч {m:02d}" if h else f"{m} мин"
