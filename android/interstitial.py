# -*- coding: utf-8 -*-
"""
interstitial.py — полноэкранная реклама myTarget, один раз за запуск.

Отдельный SDK от ads.py: там баннер Яндекс Рекламы внизу главного экрана,
здесь — полноэкранное объявление myTarget при старте приложения. Разные
сети, разные кабинеты, разные slotId — не путать.

Класс, методы и сигнатуры ниже — из документации, которую дал заказчик
(вставлена в разговор дословно), не собраны по общей форме API вслепую,
как banner в ads.py. Это ощутимо надёжнее, но и это не гарантия: SDK
меняется version к version, и без прогона на реальном телефоне возможны
расхождения — прежде всего в JNI-сигнатурах методов слушателя ниже (та
строка вида "(Lcom/my/target/ads/InterstitialAd;)V" — это подпись метода
в формате JVM, и если myTarget когда-то изменит порядок или тип
параметров колбэка, jnius откажется явно, а не молча.

Почему один раз за сессию, а не при каждом обновлении прогноза.
Полноэкранная реклама куда навязчивее баннера — она перекрывает весь
экран и требует явного закрытия. Показывать её при каждом запросе
прогноза (человек может обновлять место несколько раз за один присест)
было бы гораздо агрессивнее, чем принято даже для бесплатных приложений.
Придержано глобальным флагом _shown_this_run, который не сбрасывается до
перезапуска процесса — «за сессию» здесь буквально означает «за жизнь
процесса приложения», как и для ads.init().

Почему отключается той же покупкой, что и баннер. premium.is_premium() —
одна и та же проверка для обоих SDK: купил «Без рекламы» — реклама
пропадает вся, а не только её часть. Разных переключателей для разных
сетей в интерфейсе нет и не планируется — усложнение без пользы для
человека, который просто хочет тишины.
"""

from __future__ import annotations

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

#: Почему объявление не показалось в последний раз. Пусто — либо ещё не
#: пытались, либо показ прошёл. Тот же приём, что last_error в ads.py и
#: notify.py: без явного следа сбой неотличим от «просто нечего было
#: показывать».
last_error = ""

_ad = None                 # текущий Java-объект InterstitialAd
_listener = None           # держим ссылку живой — jnius не продлевает
                           # жизнь Python-объекта дольше, чем на него есть
                           # ссылка с питоновской стороны
_shown_this_run = False


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
    «один раз за сессию» обязаны выполняться железно и не зависеть от
    того, добрался ли код до настоящего Android-вызова.
    """
    return on_android() and not premium.is_premium() and not _shown_this_run


def show_once() -> bool:
    """Запускает загрузку и (по готовности) показ. True — попытка начата.

    Не «объявление показано» — как и в ads.attach(), это решает сеть: без
    неё onNoAd() просто придёт вместо onLoad(), и приложение продолжит
    работать без рекламы, как если бы её не было вовсе.

    Вызывается один раз при старте (см. main.py, тем же способом, что и
    ads.init()/ads.attach() — через Clock.schedule_once с задержкой, чтобы
    не отложить готовность главного экрана). Повторные вызовы в течение
    одного запуска приложения ничего не делают — see should_show().
    """
    global _ad, _listener, _shown_this_run, last_error
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
        _shown_this_run = True
        last_error = ""
        return True
    except Exception as e:                                        # noqa: BLE001
        last_error = f"{type(e).__name__}: {e}"[:200]
        return False


def reset_for_tests() -> None:
    """Сбрасывает флаг «уже показывали за сессию» — только для тестов."""
    global _shown_this_run, last_error, _ad, _listener
    _shown_this_run = False
    last_error = ""
    _ad = None
    _listener = None
