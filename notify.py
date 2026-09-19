# -*- coding: utf-8 -*-
"""
notify.py — уведомление в шторке. Одно на всё приложение.

Единственный смысл — пережить закрытие программы. Сообщение о начинающемся
слое ценно тем, что висит в шторке до среды и попадается на глаза, когда
человек ещё может подвинуть дела. Показать его окном внутри приложения
означало бы показать тому, кто и так смотрит на экран.

Канал заводится один и с обычной важностью: звук есть, но экран не
включается. Приложение сообщает про грибы, а не про пожар.

Вне Android всё молча возвращает False: на компьютере шторки нет, а падать
из-за этого приложение не должно.
"""

from __future__ import annotations

CHANNEL_ID = "waves"
CHANNEL_NAME = "Начало слоя"
NOTIFICATION_ID = 4201


#: Почему последнее уведомление не показалось. Пусто — всё в порядке.
last_error = ""


def available() -> bool:
    try:
        from jnius import autoclass
        autoclass("org.kivy.android.PythonActivity")
        return True
    except Exception:                                             # noqa: BLE001
        return False


def _sdk_int() -> int:
    try:
        from jnius import autoclass
        return autoclass("android.os.Build$VERSION").SDK_INT
    except Exception:                                             # noqa: BLE001
        return 0


def allowed() -> bool:
    """Разрешены ли уведомления. Начиная с Android 13 их спрашивают.

    Отказ — это не ошибка: человек имеет право не хотеть сообщений, и
    приложение обязано молчать, а не переспрашивать при каждом запуске.
    """
    if not available():
        return False
    if _sdk_int() < 33:
        return True
    try:
        from android.permissions import Permission, check_permission
        return bool(check_permission(Permission.POST_NOTIFICATIONS))
    except Exception:                                             # noqa: BLE001
        return True


def post(title: str, text: str, notification_id: int = NOTIFICATION_ID) -> bool:
    """Кладёт уведомление в шторку. True — получилось.

    Причина неудачи остаётся в notify.last_error: без неё поломка здесь
    неотличима от «сейчас нечего показывать».
    """
    global last_error
    last_error = ""
    if not title or not available() or not allowed():
        return False
    try:
        from jnius import autoclass, cast

        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        Context = autoclass("android.content.Context")
        Builder = autoclass("android.app.Notification$Builder")
        String = autoclass("java.lang.String")

        def chars(value):
            """Python-строка -> java.lang.CharSequence.

            cast переводит один Java-объект в другой и питоновскую строку
            не принимает: «Cannot convert str to jnius.JavaClass». Здесь
            эта ошибка была особенно вредной — она молча гасилась общим
            except ниже, и уведомление о начале слоя не появлялось никогда,
            без единого следа в журнале.
            """
            return cast("java.lang.CharSequence", String(value))
        manager = activity.getSystemService(Context.NOTIFICATION_SERVICE)

        if _sdk_int() >= 26:
            Channel = autoclass("android.app.NotificationChannel")
            Manager = autoclass("android.app.NotificationManager")
            channel = Channel(CHANNEL_ID, CHANNEL_NAME,
                              Manager.IMPORTANCE_DEFAULT)
            manager.createNotificationChannel(channel)
            builder = Builder(activity, CHANNEL_ID)
        else:
            builder = Builder(activity)

        # Значок берётся из самого приложения: своего маленького значка для
        # шторки в сборке нет, а без иконки система уведомление не покажет
        # вовсе — молча, что хуже всего.
        icon = activity.getApplicationInfo().icon
        builder.setSmallIcon(icon)
        builder.setContentTitle(chars(title))
        builder.setContentText(chars(text))
        builder.setAutoCancel(True)

        # Длинный текст раскрывается по нажатию: в одну строку шторки
        # помещается половина фразы, а обрезанная фраза про грибы читается
        # ровно наоборот — «идти или нет» становится непонятно.
        Style = autoclass("android.app.Notification$BigTextStyle")
        style = Style()
        style.bigText(chars(text))
        builder.setStyle(style)

        # Нажатие открывает приложение, а не пустой экран.
        Intent = autoclass("android.content.Intent")
        PendingIntent = autoclass("android.app.PendingIntent")
        intent = Intent(activity, activity.getClass())
        intent.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
        flags = PendingIntent.FLAG_UPDATE_CURRENT
        if _sdk_int() >= 23:
            flags |= PendingIntent.FLAG_IMMUTABLE
        builder.setContentIntent(
            PendingIntent.getActivity(activity, 0, intent, flags))

        manager.notify(notification_id, builder.build())
        last_error = ""
        return True
    except Exception as e:                                        # noqa: BLE001
        # Молчаливый except здесь уже стоил сезона уведомлений: cast получал
        # питоновскую строку, всё падало, и никто об этом не узнавал —
        # человек просто не видел сообщений о слое. Ошибка теперь оседает в
        # last_error и в журнале сервиса, который показывает «Приём и сервис».
        last_error = f"{type(e).__name__}: {e}"[:200]
        try:
            import tracklog
            tracklog.log("уведомление не показано: " + last_error)
        except Exception:                                         # noqa: BLE001
            pass
        return False


def request_permission(callback=None) -> bool:
    """Спрашивает разрешение на уведомления (Android 13+)."""
    if not available() or _sdk_int() < 33:
        if callback:
            callback(True)
        return False
    try:
        from android.permissions import Permission, request_permissions
        if callback is None:
            request_permissions([Permission.POST_NOTIFICATIONS])
        else:
            request_permissions(
                [Permission.POST_NOTIFICATIONS],
                lambda _p, res: callback(bool(res) and any(res)))
        return True
    except Exception:                                             # noqa: BLE001
        if callback:
            callback(False)
        return False
