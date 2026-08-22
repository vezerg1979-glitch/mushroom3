# -*- coding: utf-8 -*-
"""
ads.py — баннер Яндекс Рекламы на главном экране, и только там.

Что здесь можно проверить, а что нет. Порог показа рекламы, отключение при
покупке, порядок вызовов и то, что сбой рекламы не роняет приложение, —
это чистая логика, и она под тестами наравне со всем остальным. Сам вызов
SDK Яндекс Рекламы — нет: настоящий рекламный SDK это нативная Java/Kotlin-
библиотека, её вызов через jnius нельзя проверить без сборки на реальном
телефоне и настоящего показа объявления. Класс, метод и константы ниже,
отмеченные «СВЕРИТЬ», взяты по общей форме API Яндекс Рекламы для Android,
но сам SDK меняется version к version, и без прогона на телефоне ручаться
за точность нельзя. Если что-то из этого разойдётся с документацией —
здесь единственное место, где это чинить.

Почему баннер — обычный Android View, а не виджет Kivy. Kivy рисует один
OpenGL-холст на весь экран; сторонний рекламный SDK кладёт готовую картинку
в свой собственный `android.view.View`, который через Kivy нарисовать
нельзя. Поэтому вид добавляется НАПРЯМУЮ в дерево Android-активности, поверх
Kivy-холста, через `runOnUiThread` — операции с Android View обязаны идти
из UI-потока, а Python-код Kivy выполняется в другом.

Почему реклама живёт только на главном экране. Показ требует сети, а
приложение специально построено так, чтобы работать в лесу без неё —
экран похода не должен зависеть от того, загрузилась реклама или нет.
Здесь этому ничто физически не мешает: banner просто не создаётся, если
активный экран — не главный. См. main.py: attach() вызывается там и только
там.
"""

from __future__ import annotations

import time

import premium

# СВЕРИТЬ с текущей документацией Яндекс Рекламы для Android перед сборкой:
# https://yandex.ru/dev/mobile-ads/doc/ru/android/quick-start
# Ниже — форма API на момент подготовки кода, не гарантированно точная.
SDK_PACKAGE = "com.yandex.mobile.ads"
BANNER_CLASS = f"{SDK_PACKAGE}.banner.BannerAdView"
BANNER_SIZE_CLASS = f"{SDK_PACKAGE}.banner.BannerAdSize"
AD_REQUEST_CLASS = f"{SDK_PACKAGE}.common.AdRequest"
MOBILE_ADS_CLASS = f"{SDK_PACKAGE}.common.MobileAds"

# Идентификатор рекламного блока выдаёт кабинет Яндекс Рекламы отдельно на
# каждое приложение — вписать после регистрации, тестовый id сюда не
# годится для боевой сборки.
AD_UNIT_ID = "R-M-XXXXXXX-1"

#: Почему баннер не показался в последний раз. Пусто — либо не пытались,
#: либо получилось. Та же идея, что в notify.last_error: без явного следа
#: сбой рекламы неотличим от «сейчас просто нечего показывать».
last_error = ""

_banner = None            # текущий нативный View, если прикреплён


def on_android() -> bool:
    try:
        from jnius import autoclass
        autoclass("org.kivy.android.PythonActivity")
        return True
    except Exception:                                             # noqa: BLE001
        return False


def should_show() -> bool:
    """Решение «показывать ли рекламу вообще» — без единого обращения к Android.

    Отдельная функция ровно для того, чтобы её можно было проверить на
    компьютере: правило «купил — рекламы нет» обязано выполняться железно,
    и доверять это правило коду, который исполняется только на телефоне,
    нельзя — как нельзя было доверять уведомлениям молчаливый except (см.
    notify.py).
    """
    return on_android() and not premium.is_premium()


def init() -> bool:
    """Инициализация SDK — один раз за запуск приложения. True — получилось.

    Вызывается из main.py при старте, до первого attach(). Обёрнуто в try
    целиком: сеть, отсутствующий Google Play Services на части устройств,
    не до конца проинициализированный SDK — всё это должно оставить
    приложение рабочим, просто без рекламы, а не уронить главный экран.
    """
    global last_error
    if not should_show():
        return False
    try:
        from jnius import autoclass

        MobileAds = autoclass(MOBILE_ADS_CLASS)
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        MobileAds.initialize(activity, None)
        last_error = ""
        return True
    except Exception as e:                                        # noqa: BLE001
        last_error = f"{type(e).__name__}: {e}"[:200]
        return False


def attach(gravity: str = "bottom") -> bool:
    """Показывает баннер внизу экрана. True — вид создан и запрос отправлен.

    «Запрос отправлен» — не «объявление показано»: загрузка идёт по сети и
    может не завершиться никогда, если сети нет. Здесь это не обрабатывается
    отдельно, потому что и не должно: SDK сам решает, что делать без сети
    (обычно — ничего не показывать), а приложение вокруг этого не крутится.
    """
    global _banner, last_error
    if not should_show():
        return False
    try:
        from jnius import autoclass, cast

        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        Banner = autoclass(BANNER_CLASS)
        BannerSize = autoclass(BANNER_SIZE_CLASS)
        AdRequest = autoclass(AD_REQUEST_CLASS)
        FrameLayout = autoclass("android.widget.FrameLayout")
        Gravity = autoclass("android.view.Gravity")

        banner = Banner(activity)
        banner.setAdUnitId(AD_UNIT_ID)
        # СВЕРИТЬ: стандартный размер вместо адаптивного под ширину экрана —
        # сознательно попроще и понадёжнее. Подгонка под ширину означала бы
        # читать поля DisplayMetrics (widthPixels, density) через jnius, а
        # это те самые особенности отражения Java-класса, которые надёжно
        # проверяются только на реальном устройстве. Обычный баннер
        # (320×50) работает без этого шага; адаптивный можно добавить потом,
        # когда будет на чём проверить.
        banner.setAdSize(BannerSize.inlineSize(activity, 320, 50))

        params = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT,
            FrameLayout.LayoutParams.WRAP_CONTENT)
        params.gravity = (Gravity.BOTTOM if gravity == "bottom"
                          else Gravity.TOP) | Gravity.CENTER_HORIZONTAL

        def на_ui_потоке():
            content = cast("android.view.ViewGroup",
                           activity.findViewById(0x01020002))     # android.R.id.content
            content.addView(banner, params)
            banner.loadAd(AdRequest.Builder().build())

        activity.runOnUiThread(на_ui_потоке)
        _banner = banner
        last_error = ""
        return True
    except Exception as e:                                        # noqa: BLE001
        last_error = f"{type(e).__name__}: {e}"[:200]
        _banner = None
        return False


def detach() -> None:
    """Убирает баннер — при переходе в поход или после покупки."""
    global _banner
    if _banner is None:
        return
    try:
        from jnius import autoclass, cast

        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        banner = _banner

        def на_ui_потоке():
            content = cast("android.view.ViewGroup",
                           activity.findViewById(0x01020002))
            content.removeView(banner)
            banner.destroy()

        activity.runOnUiThread(на_ui_потоке)
    except Exception:                                              # noqa: BLE001
        pass
    finally:
        _banner = None
