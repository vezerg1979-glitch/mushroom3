# -*- coding: utf-8 -*-
"""
survival.py — почему фоновая запись обрывается и что с этим делать.

Приложение честно поднимает сервис переднего плана с постоянным
уведомлением — по правилам Android этого достаточно, чтобы писать трек с
погашенным экраном. На аппаратах Xiaomi, Huawei, Oppo, Vivo, Realme,
Samsung и части других этого НЕ достаточно: поверх системного механизма
производитель ставит собственный «оптимизатор», который через десять-сорок
минут убивает всё, чего нет в его белом списке. Программа при этом ничего
не нарушает и никакой ошибки не получает: её просто больше нет.

Для человека это выглядит однозначно — «приложение сломалось», и винить его
не в чем: он нажал «Старт», убрал телефон в карман, а на выходе из леса
получил трек из первых двадцати минут. Поэтому здесь три вещи, и ни одна из
них не заменяет двух других:

  1. Заметить. Разрывы во времени между точками видны в самом маршруте, и
     после похода про них надо сказать прямо, а не оставлять человека
     гадать. Перерывы, которые он сделал сам, при этом исключаются — иначе
     обед на пне выглядит как убитый сервис.

  2. Объяснить, где крутить. Путь в настройках у каждого производителя свой
     и словами «разрешите работу в фоне» не описывается. Поэтому — точный
     путь для конкретного аппарата, взятый по Build.MANUFACTURER.

  3. Довести до места. Кнопка открывает нужный экран настроек, потому что
     найти «Автозапуск» в MIUI по описанию почти невозможно.

Про разрешение REQUEST_IGNORE_BATTERY_OPTIMIZATIONS. Оно позволяет вызвать
системное окно «разрешить работу в фоне?» одним нажатием, но Google Play
принимает его лишь для узкого списка назначений и снимает приложения с
публикации за неоправданное использование. Поэтому его в сборке нет, а
вместо окна открывается системный СПИСОК оптимизации батареи — он доступен
без всяких разрешений. На одно касание больше, зато приложение нельзя снять
с публикации.
"""

from __future__ import annotations

# Разрыв, о котором стоит говорить. Меньше — обычные дела: спутники ушли под
# полог, человек стоял в овраге, приёмник задумался. Пять минут молчания при
# идущей записи — уже не помеха приёму, а остановка записи.
GAP_S = 300.0

# Разрыв, после которого причина почти наверняка в убитом процессе: столько
# приёмник не молчит даже в ельнике под дождём.
KILLED_S = 900.0


# --------------------------------------------------------------------------- #
#  Что случилось
# --------------------------------------------------------------------------- #

def gaps(walk, min_gap: float = GAP_S) -> list:
    """Промежутки без единой точки: [(начало, конец, секунды), ...].

    Считается по времени точек, а не по их числу: редкие точки в овраге —
    это плохой приём, а полное молчание — это остановленная запись.
    """
    points = getattr(walk, "points", None) or []
    out = []
    for a, b in zip(points, points[1:]):
        span = b.t - a.t
        if span < min_gap:
            continue
        if walk.paused_between(a.t, b.t):
            continue                    # перерыв, который человек сделал сам
        out.append((a.t, b.t, span))
    return out


def lost_time(walk, min_gap: float = GAP_S) -> float:
    return sum(span for _, _, span in gaps(walk, min_gap))


def looks_killed(walk) -> bool:
    """Похоже ли, что запись убили извне, а не она сама не справилась.

    Признак грубый и намеренно осторожный: один разрыв в четверть часа при
    походе длиннее получаса. Обвинять телефон зря не хочется — человек
    пойдёт крутить настройки, которые ни при чём.
    """
    if walk.duration < 1800:
        return False
    return any(span >= KILLED_S for _, _, span in gaps(walk))


def _minutes(seconds: float) -> str:
    m = int(round(seconds / 60.0))
    if m < 60:
        return f"{m} мин"
    h, m = divmod(m, 60)
    return f"{h} ч {m} мин" if m else f"{h} ч"


def report(walk) -> str:
    """Что сказать человеку после похода. Пусто — говорить нечего."""
    found = gaps(walk)
    if not found:
        return ""
    total = _minutes(sum(span for _, _, span in found))
    if len(found) == 1:
        head = f"Запись прерывалась на {_minutes(found[0][2])}"
    else:
        head = f"Запись прерывалась {len(found)} раза, всего {total}"
    if looks_killed(walk):
        return (head + ". Похоже, систему телефона не устроила работа в "
                "фоне: так делают Xiaomi, Huawei, Oppo, Vivo и Samsung. "
                "Это лечится один раз — в настройках.")
    return head + ". Возможно, приёмник надолго потерял спутники."


# --------------------------------------------------------------------------- #
#  Где крутить
# --------------------------------------------------------------------------- #
#
# Пути к настройкам у производителей разные и меняются от версии к версии,
# поэтому текст описывает, ЧТО искать, а не только куда нажать: даже если
# пункт переехал, по названию его находят.

# Шаги пишутся через тире, а не стрелку: знака «→» в шрифте сборки нет, и
# на телефоне он выглядит пустым квадратом (тест это стережёт).
VENDORS = {
    "xiaomi": {
        "name": "Xiaomi, Redmi, POCO (MIUI, HyperOS)",
        "steps": [
            "Настройки — Приложения — Навигатор грибника — Автозапуск: включить",
            "Там же — Экономия батареи: выбрать «Без ограничений»",
            "В списке недавних задач потянуть карточку приложения вниз и "
            "нажать замок — так система не закроет её при нехватке памяти",
        ],
        "activity": ("com.miui.securitycenter",
                     "com.miui.permcenter.autostart.AutoStartManagementActivity"),
    },
    "huawei": {
        "name": "Huawei, Honor (EMUI)",
        "steps": [
            "Настройки — Батарея — Запуск приложений: выключить "
            "автоматическое управление для приложения",
            "В открывшемся окне включить все три: автозапуск, косвенный "
            "запуск, работа в фоне",
        ],
        "activity": ("com.huawei.systemmanager",
                     "com.huawei.systemmanager.startupmgr."
                     "ui.StartupNormalAppListActivity"),
    },
    "oppo": {
        "name": "OPPO, Realme (ColorOS)",
        "steps": [
            "Настройки — Батарея — Энергопотребление приложений: "
            "разрешить работу в фоне",
            "Настройки — Приложения — Автозапуск: включить",
        ],
        "activity": ("com.coloros.safecenter",
                     "com.coloros.safecenter.permission.startup."
                     "StartupAppListActivity"),
    },
    "vivo": {
        "name": "vivo (Funtouch OS, OriginOS)",
        "steps": [
            "Настройки — Батарея — Высокое потребление в фоне: разрешить",
            "i Manager — Управление приложениями — Автозапуск: включить",
        ],
        "activity": ("com.vivo.permissionmanager",
                     "com.vivo.permissionmanager.activity."
                     "BgStartUpManagerActivity"),
    },
    "samsung": {
        "name": "Samsung (One UI)",
        "steps": [
            "Настройки — Батарея — Ограничения фоновой работы — "
            "Спящие приложения: убрать приложение из списка",
            "Настройки — Батарея — Оптимизация: выбрать «Без ограничений»",
        ],
        "activity": ("com.samsung.android.lool",
                     "com.samsung.android.sm.ui.battery.BatteryActivity"),
    },
    "meizu": {
        "name": "Meizu (Flyme)",
        "steps": ["Настройки — Приложения — Разрешения — Работа в фоне: включить"],
        "activity": ("com.meizu.safe",
                     "com.meizu.safe.permission.SmartBGActivity"),
    },
    "oneplus": {
        "name": "OnePlus (OxygenOS)",
        "steps": [
            "Настройки — Батарея — Оптимизация батареи: выбрать "
            "«Не оптимизировать»",
            "Настройки — Батарея — Расширенная оптимизация: выключить",
        ],
        "activity": None,
    },
}

GENERIC = {
    "name": "Android",
    "steps": [
        "Настройки — Приложения — Навигатор грибника — Батарея: "
        "выбрать «Без ограничений»",
    ],
    "activity": None,
}

# Синонимы: производитель в Build.MANUFACTURER пишется по-разному.
ALIASES = {
    "redmi": "xiaomi", "poco": "xiaomi", "blackshark": "xiaomi",
    "honor": "huawei",
    "realme": "oppo",
    "iqoo": "vivo",
}


def manufacturer() -> str:
    try:
        from jnius import autoclass
        return str(autoclass("android.os.Build").MANUFACTURER or "").lower()
    except Exception:                                             # noqa: BLE001
        return ""


def vendor(name: str = None) -> dict:
    """Подсказка для конкретного аппарата. Незнакомый — общая."""
    name = (name if name is not None else manufacturer()).strip().lower()
    if not name:
        return GENERIC
    key = ALIASES.get(name, name)
    return VENDORS.get(key, GENERIC)


def advice(name: str = None) -> str:
    """Текст подсказки: что именно искать в настройках этого телефона."""
    v = vendor(name)
    lines = [f"{v['name']}:"]
    lines += [f"·  {s}" for s in v["steps"]]
    if v is GENERIC:
        lines.append("·  Если пункта нет, ищите «Автозапуск», «Работа в "
                     "фоне» или «Оптимизация батареи» в настройках "
                     "приложения.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Довести до места
# --------------------------------------------------------------------------- #

def on_android() -> bool:
    try:
        from jnius import autoclass
        autoclass("org.kivy.android.PythonActivity")
        return True
    except Exception:                                             # noqa: BLE001
        return False


def is_exempt():
    """Разрешена ли системой работа в фоне. None — выяснить не удалось.

    Отвечает только за штатный механизм Android. Собственный «оптимизатор»
    производителя про этот флаг ничего не знает и может убивать процесс,
    даже когда здесь True, — поэтому одного этого ответа мало и подсказка
    про автозапуск показывается в любом случае.
    """
    if not on_android():
        return None
    try:
        from jnius import autoclass
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        Context = autoclass("android.content.Context")
        pm = activity.getSystemService(Context.POWER_SERVICE)
        if pm is None or not hasattr(pm, "isIgnoringBatteryOptimizations"):
            return None
        return bool(pm.isIgnoringBatteryOptimizations(activity.getPackageName()))
    except Exception:                                             # noqa: BLE001
        return None


def open_battery_settings() -> bool:
    """Системный список оптимизации батареи.

    Именно список, а не окно «разрешить?»: то окно требует разрешения
    REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, за которое Google Play снимает
    приложения с публикации. Одно лишнее касание против снятия с
    публикации — обмен выгодный.
    """
    if not on_android():
        return False
    try:
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")
        Settings = autoclass("android.provider.Settings")
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        intent = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
        activity.startActivity(intent)
        return True
    except Exception:                                             # noqa: BLE001
        return open_app_settings()


def open_vendor_settings() -> bool:
    """Экран автозапуска производителя, если он известен и существует.

    Имена этих экранов не документированы и переезжают между версиями
    оболочки, поэтому неудача здесь — обычное дело, а не поломка: тогда
    открывается страница приложения в настройках, откуда путь короче, чем
    из главного меню.
    """
    v = vendor()
    comp = v.get("activity")
    if not on_android() or not comp:
        return open_app_settings()
    try:
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")
        ComponentName = autoclass("android.content.ComponentName")
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        intent = Intent()
        intent.setComponent(ComponentName(comp[0], comp[1]))
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity.startActivity(intent)
        return True
    except Exception:                                             # noqa: BLE001
        return open_app_settings()


def open_app_settings() -> bool:
    """Страница приложения в настройках: работает везде."""
    if not on_android():
        return False
    try:
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")
        Settings = autoclass("android.provider.Settings")
        Uri = autoclass("android.net.Uri")
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
        intent.setData(Uri.parse("package:" + activity.getPackageName()))
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity.startActivity(intent)
        return True
    except Exception:                                             # noqa: BLE001
        return False
