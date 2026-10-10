# -*- coding: utf-8 -*-
"""
prefs.py — мелкие настройки, которые должны переживать закрытие приложения.

Зачем отдельный файл. Человек ходит за одним и тем же грибом в один и тот же
лес: за белым в ельник, за лисичками в сосняк. При каждом запуске выбор
сбрасывался на «Все виды сезона» и «смешанный лес», и первое, что приходилось
делать, — заново ставить то же самое, двумя выпадающими списками, на ходу.

Настройки не смешаны с местами (places.py) намеренно: места — это данные,
которые человек создаёт и которых ему жалко, а настройки можно потерять без
последствий. Поэтому здесь всё написано в расчёте на потерю: битый файл,
отсутствующий каталог и незнакомые ключи не должны мешать приложению
открыться — тогда вместо настройки берётся значение по умолчанию.

Ключи хранятся строками, значения — что угодно, что переживает json.
"""

from __future__ import annotations

import json
import os

import places as places_mod

FILE = "prefs.json"


def _path() -> str:
    return os.path.join(places_mod.data_dir(), FILE)


def load() -> dict:
    """Все настройки. Ошибка чтения — это пустой словарь, а не исключение."""
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get(key: str, default=None):
    return load().get(key, default)


def save(**values) -> bool:
    """Дописывает настройки, не трогая остальные. True — записано.

    Через временный файл: телефон выключается в кармане в любой момент, и
    оборванная запись превратила бы файл в мусор — то есть отняла бы
    настройки вообще все, а не одну.
    """
    data = load()
    data.update(values)
    path = _path()
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
