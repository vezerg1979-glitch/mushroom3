# -*- coding: utf-8 -*-
"""
Проверка wakelock.py — удержания процессора на время записи трека.

Что здесь можно проверить: что вне Android модуль молчит и ничего не роняет,
что вызовы к системе идут в правильном порядке и с правильными аргументами,
что лок отпускается при любом исходе и что refresh() перезабирает истёкший.

Чего проверить нельзя: удержит ли система процессор на самом деле. Это
остаётся живому телефону — как и всё в этом проекте, что упирается в Android.
"""

from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

sys.path.insert(0, APP)

import wakelock  # noqa: E402


# --------------------------------------------------------------------------- #
#  Без Android
# --------------------------------------------------------------------------- #

def test_bez_androida_ne_padaet():
    """На сборочной машине jnius нет: молча возвращаем False."""
    lock = wakelock.WakeLock()
    assert lock.acquire() is False
    assert lock.held is False
    assert lock.error == "не Android"
    lock.release()                      # не должно бросать


def test_status_bez_androida():
    lock = wakelock.WakeLock()
    lock.acquire()
    assert "не взят" in lock.status()


def test_kontekstnyy_menedzher_bez_androida():
    with wakelock.WakeLock() as lock:
        assert lock.held is False


# --------------------------------------------------------------------------- #
#  С поддельным Android
# --------------------------------------------------------------------------- #

class FakeLock:
    """Java-объект PowerManager.WakeLock: считает вызовы."""

    def __init__(self):
        self.acquired = 0
        self.released = 0
        self.ref_counted = None
        self.timeout = None
        self._held = False

    def setReferenceCounted(self, value):
        self.ref_counted = value

    def acquire(self, timeout=None):
        self.acquired += 1
        self.timeout = timeout
        self._held = True

    def isHeld(self):
        return self._held

    def release(self):
        self.released += 1
        self._held = False

    def expire(self):
        """Система сняла лок по таймауту — снаружи это выглядит так."""
        self._held = False


class FakePowerManager:
    PARTIAL_WAKE_LOCK = 1

    def __init__(self):
        self.locks = []
        self.tags = []

    def newWakeLock(self, flag, tag):
        self.flag = flag
        self.tags.append(tag)
        lock = FakeLock()
        self.locks.append(lock)
        return lock


def _install_fake(monkeypatch, pm=None):
    """Подменяет jnius так, чтобы getSystemService отдавал наш PowerManager."""
    pm = pm or FakePowerManager()

    class Ctx:
        def getSystemService(self, name):
            return pm

    monkeypatch.setattr(wakelock, "_context", lambda: Ctx())

    module = types.ModuleType("jnius")

    def autoclass(name):
        if name.endswith("PowerManager"):
            return FakePowerManager
        obj = type("C", (), {"POWER_SERVICE": "power"})
        return obj

    module.autoclass = autoclass
    monkeypatch.setitem(sys.modules, "jnius", module)
    return pm


def test_zahvat_i_osvobozhdenie(monkeypatch):
    pm = _install_fake(monkeypatch)
    lock = wakelock.WakeLock()
    assert lock.acquire() is True
    assert lock.held is True
    assert len(pm.locks) == 1
    lock.release()
    assert lock.held is False
    assert pm.locks[0].released == 1


def test_lok_ne_schetnyy(monkeypatch):
    """setReferenceCounted(False) обязателен: иначе один release() не отпустит."""
    pm = _install_fake(monkeypatch)
    wakelock.WakeLock().acquire()
    assert pm.locks[0].ref_counted is False


def test_zahvat_s_ogranicheniem_po_vremeni(monkeypatch):
    """Вечных локов не бывает: берём с таймаутом на случай падения процесса."""
    pm = _install_fake(monkeypatch)
    wakelock.WakeLock().acquire()
    assert pm.locks[0].timeout == wakelock.TIMEOUT_MS
    assert pm.locks[0].timeout > 12 * 3600 * 1000


def test_metka_vidna_v_dumpsys(monkeypatch):
    """По метке ищут виновника расхода заряда — она должна быть осмысленной."""
    pm = _install_fake(monkeypatch)
    wakelock.WakeLock().acquire()
    assert pm.tags == [wakelock.TAG]
    assert "mushroom" in wakelock.TAG


def test_povtornyy_zahvat_ne_plodit_loki(monkeypatch):
    pm = _install_fake(monkeypatch)
    lock = wakelock.WakeLock()
    lock.acquire()
    lock.acquire()
    lock.acquire()
    assert len(pm.locks) == 1


def test_refresh_perezabiraet_istekshiy(monkeypatch):
    """Главное в цикле сервиса: лок истёк — берём заново."""
    pm = _install_fake(monkeypatch)
    lock = wakelock.WakeLock()
    lock.acquire()
    pm.locks[0].expire()
    assert lock.held is False
    assert lock.refresh() is True
    assert lock.held is True
    assert len(pm.locks) == 2


def test_refresh_nichego_ne_delaet_poka_derzhit(monkeypatch):
    pm = _install_fake(monkeypatch)
    lock = wakelock.WakeLock()
    lock.acquire()
    lock.refresh()
    assert len(pm.locks) == 1


def test_povtornoe_osvobozhdenie_bezopasno(monkeypatch):
    pm = _install_fake(monkeypatch)
    lock = wakelock.WakeLock()
    lock.acquire()
    lock.release()
    lock.release()
    assert pm.locks[0].released == 1


def test_otkaz_sistemy_ne_ronyaet(monkeypatch):
    """PowerManager может не отдаться — это не повод падать посреди леса."""
    class Ctx:
        def getSystemService(self, name):
            return None

    monkeypatch.setattr(wakelock, "_context", lambda: Ctx())
    module = types.ModuleType("jnius")
    module.autoclass = lambda name: type("C", (), {"POWER_SERVICE": "power",
                                                   "PARTIAL_WAKE_LOCK": 1})
    monkeypatch.setitem(sys.modules, "jnius", module)

    lock = wakelock.WakeLock()
    assert lock.acquire() is False
    assert "PowerManager" in lock.error
    assert lock.held is False


def test_status_pri_uderzhanii(monkeypatch):
    _install_fake(monkeypatch)
    lock = wakelock.WakeLock()
    lock.acquire()
    assert lock.status() == "процессор удержан"
