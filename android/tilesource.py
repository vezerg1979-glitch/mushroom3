# -*- coding: utf-8 -*-
"""
tilesource.py — откуда берётся подложка карты и можно ли качать её впрок.

Почему это отдельный модуль, а не строка в mapview.

Карта в лесу без интернета нужна, спору нет. Но тайлы tile.openstreetmap.org
раздаются на пожертвования, и правила их использования запрещают именно то,
что для этого требуется: возможность «скачать область впрок» и любые фоновые
докачки того, что человек прямо сейчас не смотрит. Нарушителей блокируют без
предупреждения и по User-Agent — то есть блокировка накрыла бы карту у всех,
кто поставил приложение, а не у того, кто нажал кнопку.

Поэтому источник подложки сделан настраиваемым (сами правила OSM это и
советуют: не зашивать адрес тайлов в код), а у каждого источника есть признак
offline — разрешает ли его владелец скачивание впрок. Для серверов OSM он
False, и кнопка сохранения области честно объясняет, почему не работает.

Что делать человеку, которому карта в лесу всё-таки нужна:

  * поднять свой сервер тайлов — для одного района это посильно;
  * взять поставщика, который прямо разрешает офлайн: у большинства есть
    бесплатный уровень с ключом (Thunderforest, MapTiler, Stadia, Jawg,
    Geoapify). Ключ вставляется прямо в адрес;
  * пользоваться готовым офлайн-навигатором (OsmAnd, Guru Maps) — трек из
    похода выгружается в GPX и открывается там.

Данные карты в любом случае © OpenStreetMap contributors, ODbL — меняется
только тот, кто их отрисовывает и раздаёт.
"""

from __future__ import annotations

import json
import os

OSM_ATTRIBUTION = "© OpenStreetMap contributors"

# Готовые источники. offline=True означает, что владелец сервера разрешает
# скачивание области впрок, а не то, что нам так удобнее.
PRESETS = {
    "osm": {
        "name": "OpenStreetMap",
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": OSM_ATTRIBUTION,
        "offline": False,
        "note": "Общие серверы OSM. Запрещают скачивание карты впрок: "
                "они живут на пожертвования, и нарушителей блокируют.",
    },
    "custom": {
        "name": "Свой сервер",
        "url": "",
        "attribution": OSM_ATTRIBUTION,
        "offline": True,
        "note": "Свой сервер тайлов или поставщик, разрешающий офлайн. "
                "Адрес вида https://…/{z}/{x}/{y}.png, ключ можно "
                "дописать прямо в него.",
    },
}

DEFAULT = "osm"
FILE = "tilesource.json"

_current = None


def _path() -> str:
    import places as places_mod
    return os.path.join(places_mod.data_dir(), FILE)


def load() -> dict:
    """Текущий источник. При любой неисправности — обратно на OSM."""
    global _current
    if _current is not None:
        return _current
    data = dict(PRESETS[DEFAULT], key=DEFAULT)
    try:
        with open(_path(), encoding="utf-8") as f:
            saved = json.load(f)
        key = saved.get("key", DEFAULT)
        base = dict(PRESETS.get(key, PRESETS[DEFAULT]), key=key)
        if key == "custom":
            base["url"] = str(saved.get("url", "")).strip()
            base["attribution"] = (str(saved.get("attribution", "")).strip()
                                   or OSM_ATTRIBUTION)
        if not valid_url(base["url"]):
            base = dict(PRESETS[DEFAULT], key=DEFAULT)
        data = base
    except (OSError, ValueError, TypeError):
        pass
    _current = data
    return _current


def save(key: str, url: str = "", attribution: str = "") -> dict:
    """Запоминает выбор. Неверный адрес не сохраняется."""
    global _current
    if key == "custom" and not valid_url(url):
        raise ValueError("адрес должен начинаться с https:// и содержать "
                         "{z}, {x} и {y}")
    payload = {"key": key, "url": url.strip(),
               "attribution": attribution.strip()}
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, _path())
    _current = None
    return load()


def valid_url(url: str) -> bool:
    """Адрес шаблона тайлов.

    Проверка нужна не от злого умысла: адрес переписывают с сайта поставщика
    руками, и потерянная фигурная скобка превращает карту в пустые клетки
    без единого сообщения об ошибке.
    """
    url = (url or "").strip()
    if not url.startswith("https://"):
        return False
    return all(part in url for part in ("{z}", "{x}", "{y}"))


def url() -> str:
    return load()["url"]


def name() -> str:
    return load()["name"]


def attribution() -> str:
    return load()["attribution"]


def note() -> str:
    return load().get("note", "")


def allows_offline() -> bool:
    """Разрешает ли владелец источника скачивать область впрок."""
    return bool(load().get("offline"))


def reset():
    """Сброс кэша модуля. Нужен тестам и после смены каталога данных."""
    global _current
    _current = None
