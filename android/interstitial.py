# -*- coding: utf-8 -*-
"""
interstitial.py — полноэкранная реклама myTarget: при запуске и при
переходах между делами, не только один раз.

Отдельный SDK от ads.py: там баннер Яндекс Рекламы внизу главного экрана,
здесь — полноэкранное объявление myTarget. Разные сети, разные кабинеты,
разные slotId — не путать.

Класс, методы и сигнатуры ниже — из документации, которую дал заказчик
(вставлена в разговор дословно), не собраны по общей форме API вслепую,
как banner в ads.py. Это ощутимо надёжнее, но и это не гарантия: SDK
меняется version к version, и без прогона на реальном телефоне возможны
расхождения — прежде всего в JNI-сигнатурах методов слушателя ниже (та
строка вида "(Lcom/my/target/ads/InterstitialAd;)V" — это подпись метода
в формате JVM, и если myTarget когда-то изменит порядок или тип
параметров колбэка, jnius откажется явно, а не молча.

Почему не на каждое действие подряд, а с перерывом. Полноэкранная реклама
куда навязчивее баннера — она перекрывает весь экран и требует явного
закрытия. Показывать её на каждое действие означало бы, что человек,
который за пять минут открыл журнал, сохранил место и закрыл поход,
увидел бы три полноэкранных объявления подряд — это уже не монетизация,
а причина удалить приложение. Поэтому вместо флага «один раз за сессию»
здесь порог по времени (MIN_INTERVAL_S): показ возможен снова только
через несколько минут после предыдущего, из какой бы точки приложения его
ни попросили. Функция называется maybe_show(), а не show(): вызывающий
код (main.py) зовёт её на каждом подходящем переходе — после итогов
похода, после закрытия журнала, после сохранения карты или резервной
копии, — а решение «пора или ещё рано» модуль принимает сам.

Где реклама НЕ показывается — и это не забывчивость, а правило. Экран
похода (walkscreen.py) не импортирует ни этот модуль, ни ads.py вообще —
не как условие, которое можно случайно обойти, а как отсутствующий код;
test_interstitial_never_touched_from_the_walk_screen следит, чтобы это
не появилось незаметно при следующей правке. В лесу у рекламы всё равно
нет сети, а прерывать поход, отметку находки или прогулку с корзиной
полноэкранным объявлением — ровно то, из-за чего разработчиков подобных
объявлений не любят больше, чем самих объявлений.

Почему отключается той же покупкой, что и баннер. premium.is_premium() —
одна и та же проверка для обоих SDK: купил «Без рекламы» — реклама
пропадает вся, а не только её часть. Разных переключателей для разных
сетей в интерфейсе нет и не планируется — усложнение без пользы для
человека, который просто хочет тишины.
"""

from __future__ import annotations

import time

import premium

# СВЕРИТЬ с текущей документацией myTarget для Android перед сборкой, если
# после этой правки прошло много времени:
# https://target.my.com/help/partner/adnetwork
SDK_PACKAGE = "com.my.target.ads"
INTERSTITIAL_CLASS = f"{SDK_PACKAGE}.InterstitialAd"
LISTENER_INTERFACE = f"{SDK_PACKAGE}.InterstitialAd$InterstitialAdListener"
LISTENER_INTERFACE_JNI = "com/my/target/ads/InterstitialAd$InterstitialAdListener"
LOADING_ERROR_CLASS = "com.my.target.common.models.IAdLoadingError"

#: Slot ID из кабинета myTarget — один на приложение, не на пользователя.
SLOT_ID = 2056349

#: Не чаще одного показа за этот промежуток, из какой бы точки приложения
#: его ни попросили. Пять минут — обычный минимум для полноэкранной
#: рекламы в бесплатных приложениях: реже баннера на порядки, потому что
#: cтоит человеку внимания и явного закрытия, а не просто взгляда.
MIN_INTERVAL_S = 5 * 60

#: Почему объявление не показалось в последний раз. Пусто — либо ещё не
#: пытались, либо показ прошёл. Тот же приём, что last_error в ads.py и
#: notify.py: без явного следа сбой неотличим от «просто нечего было
#: показывать».
last_error = ""

_ad = None                 # текущий Java-объект InterstitialAd
_listener = None           # держим ссылку живой — jnius не продлевает
                           # жизнь Python-объекта дольше, чем на него есть
                           # ссылка с питоновской стороны
_last_shown_at = 0.0       # unix-время последней начатой попытки показа


def on_android() -> bool:
    try:
        from jnius import autoclass
        autoclass("org.kivy.android.PythonActivity")
        return True
    except Exception:                                             # noqa: BLE001
        return False


def should_show() -> bool:
    """Решение «показывать ли вообще» — без единого обращения к Android.

    Проверяемо на компьютере: правило «купил — рекламы нет» и правило
    «не чаще, чем раз в MIN_INTERVAL_S» обязаны выполняться железно и не
    зависеть от того, добрался ли код до настоящего Android-вызова.
    """
    return (on_android() and not premium.is_premium()
           and time.time() - _last_shown_at >= MIN_INTERVAL_S)


def maybe_show() -> bool:
    """Запускает загрузку и (по готовности) показ, если время пришло.

    True — попытка начата, а не «объявление показано»: как и в
    ads.attach(), дальше решает сеть — без неё onNoAd() придёт вместо
    onLoad(), и приложение продолжит работать без рекламы, как если бы
    её не было вовсе.

    Вызывать можно из любого подходящего места — после итогов похода,
    после закрытия журнала или карты, при запуске приложения (см.
    main.py) — с любой частотой: если предыдущий показ был недавно,
    функция сама молча откажется, никакого отдельного контроля частоты
    на стороне вызывающего кода не нужно.
    """
    global _ad, _listener, _last_shown_at, last_error
    if not should_show():
        return False
    try:
        from jnius import autoclass, PythonJavaClass, java_method

        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        InterstitialAd = autoclass(INTERSTITIAL_CLASS)

        class _Listener(PythonJavaClass):
            __javainterfaces__ = [LISTENER_INTERFACE_JNI]
            __javacontext__ = "app"

            @java_method("(Lcom/my/target/ads/InterstitialAd;)V")
            def onLoad(self, ad):
                def на_ui_потоке():
                    ad.show()
                activity.runOnUiThread(на_ui_потоке)

            @java_method(
                "(Lcom/my/target/common/models/IAdLoadingError;"
                "Lcom/my/target/ads/InterstitialAd;)V")
            def onNoAd(self, error, ad):
                global last_error
                try:
                    last_error = str(error.getMessage())[:200]
                except Exception:                                 # noqa: BLE001
                    last_error = "onNoAd"

            @java_method("(Lcom/my/target/ads/InterstitialAd;)V")
            def onClick(self, ad):
                pass

            @java_method("(Lcom/my/target/ads/InterstitialAd;)V")
            def onDisplay(self, ad):
                pass

            @java_method("(Lcom/my/target/ads/InterstitialAd;)V")
            def onDismiss(self, ad):
                pass

            @java_method("(Lcom/my/target/ads/InterstitialAd;)V")
            def onVideoCompleted(self, ad):
                pass

        def на_ui_потоке():
            global _ad, _listener
            ad = InterstitialAd(SLOT_ID, activity)
            listener = _Listener()
            ad.setListener(listener)
            ad.load()
            _ad = ad
            _listener = listener               # держим живым, см. выше

        activity.runOnUiThread(на_ui_потоке)
        _last_shown_at = time.time()
        last_error = ""
        return True
    except Exception as e:                                        # noqa: BLE001
        last_error = f"{type(e).__name__}: {e}"[:200]
        return False


def reset_for_tests() -> None:
    """Сбрасывает таймер «когда показывали в последний раз» — только для тестов."""
    global _last_shown_at, last_error, _ad, _listener
    _last_shown_at = 0.0
    last_error = ""
    _ad = None
    _listener = None
