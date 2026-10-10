# -*- coding: utf-8 -*-
"""
tracklog.py — обмен координатами между фоновым сервисом и приложением.

Сервис пишет точки построчно в NDJSON, приложение дочитывает файл с того места,
где остановилось. Такой способ выбран намеренно: он переживает перезапуск любой
из сторон, не требует привязки процессов друг к другу и оставляет на диске
полный сырой лог — если приложение убьют, поход не пропадёт.

Формат строки:  {"lat":55.96,"lon":38.04,"t":1755..,"acc":7.0}
"""

from __future__ import annotations

import json
import os
import time

import places as places_mod

LIVE_FILE = "track_live.ndjson"
STATUS_FILE = "track_status.json"
LOG_FILE = "service.log"


def _path(name: str) -> str:
    return os.path.join(places_mod.data_dir(), name)


# --------------------------------------------------------------------------- #
#  Запись (сторона сервиса)
# --------------------------------------------------------------------------- #

def append_point(lat: float, lon: float, acc: float = 0.0, t: float | None = None):
    line = json.dumps({"lat": round(float(lat), 6), "lon": round(float(lon), 6),
                       "t": round(t if t is not None else time.time(), 1),
                       "acc": round(float(acc), 1)}, ensure_ascii=False)
    with open(_path(LIVE_FILE), "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())          # телефон могут выключить в любой момент


def set_status(**fields):
    """Состояние сервиса: приложение по нему понимает, жив ли он."""
    data = get_status()
    data.update(fields)
    data["updated"] = time.time()
    tmp = _path(STATUS_FILE) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _path(STATUS_FILE))
    except OSError:
        pass


def get_status() -> dict:
    try:
        with open(_path(STATUS_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def service_alive(max_silence: float = 90.0) -> bool:
    st = get_status()
    return bool(st.get("running")) and (time.time() - st.get("updated", 0)) < max_silence


def log(msg: str):
    """Диагностика сервиса: без неё отладить фоновую работу невозможно."""
    try:
        with open(_path(LOG_FILE), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def read_log(limit: int = 60) -> str:
    try:
        with open(_path(LOG_FILE), encoding="utf-8") as f:
            return "".join(f.readlines()[-limit:])
    except OSError:
        return "Журнал сервиса пуст."


# --------------------------------------------------------------------------- #
#  Чтение (сторона приложения)
# --------------------------------------------------------------------------- #

class LiveReader:
    """Дочитывает файл с последней позиции; переживает перезапуск приложения."""

    def __init__(self):
        self.offset = 0

    def reset(self):
        self.offset = 0

    def read_new(self) -> list[tuple[float, float, float, float]]:
        path = _path(LIVE_FILE)
        if not os.path.exists(path):
            return []
        out = []
        try:
            size = os.path.getsize(path)
            if size < self.offset:            # файл начали заново
                self.offset = 0
            with open(path, encoding="utf-8") as f:
                f.seek(self.offset)
                for line in f:
                    if not line.endswith("\n"):   # строка ещё пишется
                        break
                    self.offset += len(line.encode("utf-8"))
                    try:
                        r = json.loads(line)
                        out.append((float(r["lat"]), float(r["lon"]),
                                    float(r.get("acc", 0.0)), float(r["t"])))
                    except (ValueError, KeyError, TypeError):
                        continue
        except OSError:
            return out
        return out


def clear_live():
    for name in (LIVE_FILE, STATUS_FILE):
        try:
            os.remove(_path(name))
        except OSError:
            pass


def has_unfinished(min_points: int = 5) -> bool:
    """Остался ли недописанный поход после того, как приложение убили."""
    path = _path(LIVE_FILE)
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for _ in f) >= min_points
    except OSError:
        return False
