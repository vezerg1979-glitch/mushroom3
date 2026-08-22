# -*- coding: utf-8 -*-
"""
theme.py — какая тема сейчас и кого об этом оповестить.

Палитра знает только цвета. Здесь — выбор между ними: что человек попросил,
что из этого следует прямо сейчас и кому сообщить о смене.

Режима три. «День» и «Ночь» очевидны, а «авто» переключает по солнцу в той
точке, для которой считается прогноз: тёмная тема нужна не в определённые
часы, а когда темно, и в июне под Питером это одно время, в ноябре под
Ростовом — совсем другое. Часы для этого не годятся.

Про оповещение. Модули интерфейса читают цвета один раз, при загрузке:
`INK = hexc(palette.INK)`. Так быстрее, но после смены темы такие копии
остаются прежними. Поэтому каждый модуль регистрирует здесь функцию,
которая перечитывает цвета, а экран после этого пересобирается заново.
Обойтись без пересборки нельзя: у кнопки цвет фона выставлен в момент
создания, и никакая палитра его задним числом не изменит.
"""

from __future__ import annotations

import time

import palette
import prefs
import sun

MODES = ("авто", "день", "ночь")
DEFAULT = "авто"

#: Функции модулей, перечитывающие цвета. Регистрируются при загрузке.
_listeners = []


def register(fn):
    """Добавляет функцию обновления цветов. Возвращает её же — удобно как
    декоратор и не мешает обычному вызову."""
    if fn not in _listeners:
        _listeners.append(fn)
    return fn


def mode() -> str:
    """Что выбрал человек: «авто», «день» или «ночь»."""
    value = prefs.get("theme", DEFAULT)
    return value if value in MODES else DEFAULT


def resolve(name: str, lat: float = None, lon: float = None,
            now: float = None) -> str:
    """Во что превращается режим прямо сейчас.

    Без координат «авто» остаётся днём: гадать наугад хуже, чем показать
    привычное. Заполярье, где солнце не встаёт или не садится, sun.py
    отдаёт как None — там тоже остаётся день, и это честнее, чем
    переключать экран по формуле, которая в этих широтах не работает.
    """
    if name == "ночь":
        return "ночь"
    if name == "день" or lat is None or lon is None:
        return "день"
    now = time.time() if now is None else now
    left = sun.seconds_to_sunset(lat, lon, now)
    if left is None:
        return "день"
    if left <= 0:
        return "ночь"                      # солнце село
    # До рассвета: sun.seconds_to_sunset считает до ближайшего заката, и
    # ранним утром это положительное число, хотя на улице ещё темно.
    up = sun.sunrise(_date(now), lat, lon)
    if up is not None and now < up:
        return "ночь"
    return "день"


def _date(now: float):
    from datetime import datetime
    return datetime.fromtimestamp(now).date()


def apply(lat: float = None, lon: float = None, now: float = None) -> str:
    """Применяет текущий режим. Возвращает получившуюся тему."""
    name = resolve(mode(), lat, lon, now)
    if name != palette.current():
        palette.use(name)
        for fn in list(_listeners):
            try:
                fn()
            except Exception:                                     # noqa: BLE001
                # Один упрямый модуль не должен оставить остальные с
                # половиной старых цветов: это выглядит как поломка экрана.
                continue
    return name


def set_mode(name: str, lat: float = None, lon: float = None,
             now: float = None) -> str:
    """Запоминает выбор человека и применяет его."""
    if name not in MODES:
        raise ValueError(f"нет такого режима: {name!r}")
    prefs.save(theme=name)
    return apply(lat, lon, now)


def next_mode(name: str = None) -> str:
    """Следующий режим по кругу: авто — день — ночь.

    Кнопка одна, а состояний три: отдельный экран настроек ради этого
    заводить не из-за чего, а по кругу человек проходит их за два касания.
    """
    name = name or mode()
    return MODES[(MODES.index(name) + 1) % len(MODES)]


def label(name: str = None) -> str:
    """Подпись на кнопке: что выбрано и что из этого вышло."""
    name = name or mode()
    if name == "авто":
        return f"Авто · {palette.current()}"
    return name.capitalize()
