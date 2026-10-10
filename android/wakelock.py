# -*- coding: utf-8 -*-
"""
wakelock.py — не дать процессору уснуть, пока пишется трек.

Зачем. Значок «фоновый сервис» в шторке обманчив: он мешает системе убить
процесс, но не мешает процессору уснуть. Экран погас, телефон в кармане —
и через несколько минут Android уводит аппарат в глубокий сон. Питоновский
цикл сервиса замирает между двумя `time.sleep()`, обработчик координат,
висящий на главном Looper'е, перестаёт вызываться, и запись останавливается,
хотя сервис формально жив. Достанешь телефон, разбудишь экран — запись
продолжится как ни в чём не бывало, и в логе будет ровная дыра на полчаса.

Ровно от этого и нужен PARTIAL_WAKE_LOCK: он держит процессор, не трогая
экран. Разрешение WAKE_LOCK в манифесте уже есть — не хватало самого вызова.

Цена. Удержанный процессор — это заряд. По опыту Android-разработки лишний
расход на партиальном локе заметно меньше, чем на самом приёме GPS, который
при записи трека работает всё равно; и несравнимо меньше, чем от включённого
экрана, которым иначе приходится «будить» телефон вручную. Но бесплатным он
не бывает, поэтому лок берётся только на время записи и отпускается сразу.

Страховка от вечного лока. Берём с ограничением по времени: если процесс
умрёт, не дойдя до release(), система всё равно отпустит лок сама. Плюс
периодическое обновление из цикла сервиса — refresh() перезабирает лок,
если тот истёк или был снят системой.
"""

from __future__ import annotations

#: Метка видна в `adb shell dumpsys power` — по ней ищут виновника расхода.
TAG = "mushroom-forecast:track"

#: Ограничение на один захват, миллисекунды. Больше предельной длительности
#: похода, но конечно: вечных локов не бывает даже при падении процесса.
TIMEOUT_MS = 14 * 3600 * 1000

#: PowerManager.PARTIAL_WAKE_LOCK. Константу берём из Java, но подстраховка
#: нужна: на части сборок поле у обёртки не читается.
_PARTIAL = 1


def _context():
    """Контекст сервиса или приложения — смотря откуда позвали."""
    from jnius import autoclass

    try:
        service = autoclass("org.kivy.android.PythonService").mService
        if service is not None:
            return service
    except Exception:                                             # noqa: BLE001
        pass
    return autoclass("org.kivy.android.PythonActivity").mActivity


class WakeLock:
    """Партиальный лок с безопасным поведением вне Android."""

    def __init__(self, tag: str = TAG):
        self.tag = tag
        self.error = ""
        self._lock = None

    # --- состояние ----------------------------------------------------------
    @property
    def held(self) -> bool:
        if self._lock is None:
            return False
        try:
            return bool(self._lock.isHeld())
        except Exception:                                         # noqa: BLE001
            return False

    # --- управление ---------------------------------------------------------
    def acquire(self) -> bool:
        """Забирает лок. False — не Android или система отказала."""
        if self.held:
            return True
        try:
            from jnius import autoclass

            Context = autoclass("android.content.Context")
            PowerManager = autoclass("android.os.PowerManager")
            pm = _context().getSystemService(Context.POWER_SERVICE)
            if pm is None:
                self.error = "PowerManager недоступен"
                return False
            flag = getattr(PowerManager, "PARTIAL_WAKE_LOCK", _PARTIAL)
            if not isinstance(flag, int):
                flag = _PARTIAL
            lock = pm.newWakeLock(flag, self.tag)
            # Без этого повторный acquire() увеличивает счётчик, и один
            # release() лок не отпускает — классическая утечка заряда.
            lock.setReferenceCounted(False)
            lock.acquire(TIMEOUT_MS)
            self._lock = lock
            self.error = ""
            return self.held
        except ImportError:
            self.error = "не Android"
            return False
        except Exception as e:                                    # noqa: BLE001
            self.error = str(e)[:80]
            return False

    def refresh(self) -> bool:
        """Перезабрать, если лок истёк или снят. Зовётся из цикла сервиса."""
        if self.held:
            return True
        self._lock = None
        return self.acquire()

    def release(self):
        """Отпустить. Вызывать обязательно и в ветке ошибки тоже."""
        lock, self._lock = self._lock, None
        if lock is None:
            return
        try:
            if lock.isHeld():
                lock.release()
        except Exception:                                         # noqa: BLE001
            pass

    # --- удобство -----------------------------------------------------------
    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False

    def status(self) -> str:
        """Строка для журнала диагностики."""
        if self.held:
            return "процессор удержан"
        return f"лок не взят ({self.error})" if self.error else "лок не взят"
