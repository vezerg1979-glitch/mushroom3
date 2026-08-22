[app]

title = Навигатор грибника
package.name = mushroomforecast
package.domain = ru.grezev

source.dir = .
source.include_exts = py,png,jpg,ttf,json

version = 3.5

# Ветку p4a обязательно держать закреплённой: на develop собирается
# Python 3.14, под который не подходят колёса, и сборка обрывается
p4a.branch = v2024.01.21

# urllib3 убран намеренно — код им не пользуется, сеть идёт через
# stdlib urllib.request. plyer нужен для GPS (кнопка «Определить место»)
requirements = python3,kivy==2.3.1,certifi,openssl,plyer

# Нативные Java-SDK рекламных сетей — не pip-пакеты, requirements их не
# берёт. Без этой строки interstitial.py (myTarget) честно ловит
# ClassNotFoundException и молча остаётся без рекламы: код работает
# правильно, просто самого SDK физически нет в APK.
#
# Яндекс (ads.py, баннер) исключён из сборки с версии 3.5. Не из-за
# самого ads.py — код там рабочий — а потому что зависимости SDK
# заданы диапазонами версий (appmetrica [7.13.0,8.0.0), div
# [32.18.1,33.0.0)), и Gradle сам подтягивает последнюю версию внутри
# диапазона на момент сборки. Закрепить mobileads одной цифрой
# оказалось недостаточно: транзитивные библиотеки всё равно уехали
# вперёд и стали требовать compileSdk 34 — то же самое ограничение,
# что и у myTarget ниже, только без возможности зафиксировать точку
# отката единственной версией. Код ads.py, ads.init()/attach() в
# main.py и вызовы из premium_screen.py при этом убраны из вызовов, а
# не удалены — с рабочим SDK баннер можно вернуть, просто вписав его
# сюда обратно и восстановив вызовы.
#
# myTarget версия ЗАФИКСИРОВАНА на 5.20.1 нарочно, не «последняя из
# коробки»: начиная с 5.21.0 (03.06.2024) myTarget перешёл с
# com.google.android.exoplayer на androidx.media3, а тот требует
# compileSdk >= 34 — Gradle прямо отказывается собирать со всеми
# зависимостями android.media3, если compileSdk ниже. Поднять
# android.api до 34 сейчас нельзя — сломается ForegroundServiceType у
# сервиса записи похода (см. комментарий у android.api ниже, это уже
# стоило одного сломанного релиза). 5.20.1 — последняя версия myTarget
# перед этим переходом, ещё на старом ExoPlayer, без требования
# compileSdk 34, и её собственные зависимости зафиксированы, а не
# заданы диапазоном — этот риск здесь не повторяется. Проверено по
# официальному changelog:
# https://target.vk.ru/help/partners/mob/androidhistory/en
android.gradle_dependencies = com.my.target:mytarget-sdk:5.20.1

# AndroidX обязателен при таких gradle-зависимостях — без него сборка с
# androidx-пакетами внутри SDK не соберётся.
android.enable_androidx = True


# Фоновая запись трека. Имя до двоеточия задаёт Java-класс:
# Tracker -> ru.grezev.mushroomforecast.ServiceTracker, именно его ищет
# service_ctl.py. Без этой строки класса в APK нет и сервис не стартует.
services = Tracker:service_tracker.py:foreground

# Поворот разрешён. В лесу телефон держат стоймя, но карту похода на боку
# видно вдвое шире, а на планшете портретная раскладка растягивает кнопки на
# полэкрана. Экраны при повороте пересобираются в две колонки — см. layout.py.
orientation = all
fullscreen = 0

presplash.filename = %(source.dir)s/presplash.png
icon.filename = %(source.dir)s/icon.png

# Цвет поля вокруг заставки. Картинка квадратная, экран вытянутый, и по
# умолчанию p4a заливает полосы сверху и снизу белым: тёмная заставка на
# белом фоне выглядит как ошибка загрузки. Цвет взят из углов самой картинки.
android.presplash_color = #171A1F

# Числовой код версии. Магазин требует, чтобы он рос с каждой загрузкой,
# иначе новая сборка не принимается. Формат: 2.7 -> 20700, 2.7.1 -> 20701.
android.numeric_version = 30500

# POST_NOTIFICATIONS добавлено для Android 13+: без него уведомление
# переднего плана не показывается, и сервис выглядит «мёртвым».
#
# WRITE_EXTERNAL_STORAGE нужен только до Android 10: там запись снимка через
# MediaStore требует разрешения, начиная с Android 10 — нет. Спрашивается в
# работе и только на старых аппаратах (см. photos.Photographer).
#
# CAMERA здесь намеренно НЕТ. Съёмка идёт через системное приложение камеры
# по ACTION_IMAGE_CAPTURE, своей камерой приложение не пользуется. А если
# объявить это разрешение, Android начнёт требовать его в работе — лишний
# вопрос человеку на ровном месте.
android.permissions = android.permission.INTERNET,android.permission.ACCESS_NETWORK_STATE,android.permission.ACCESS_FINE_LOCATION,android.permission.ACCESS_COARSE_LOCATION,android.permission.ACCESS_BACKGROUND_LOCATION,android.permission.FOREGROUND_SERVICE,android.permission.POST_NOTIFICATIONS,android.permission.WAKE_LOCK,android.permission.WRITE_EXTERNAL_STORAGE,android.permission.VIBRATE

# Комбинация ниже подобрана отладкой, менять только осознанно:
#   ndk = 25b      — на r28c python-for-android собирает Python 3.14 и падает
#   ndk_api = 24   — при 21 у r25b не хватает заголовков, обрыв на этапе create
#   api = 33       — на 34 (Android 14) системе нужен foregroundServiceType
#                    в манифесте, а p4a 2024.01.21 его не выставляет: сервис
#                    стартует и тут же убивается. Из-за этого же versionов
#                    myTarget SDK зафиксирован на 5.20.1 выше — свежее
#                    требует compileSdk 34, поднять которое сейчас нельзя.
#   одна архитектура — телефоны новее 2015 года все 64-битные, сборка вдвое быстрее
android.api = 33
android.minapi = 24
android.ndk_api = 24
android.ndk = 25b
android.archs = arm64-v8a

# Разрешить автоматическое принятие лицензий SDK при сборке в CI
android.accept_sdk_license = True

[buildozer]

# Подробность 1, а не 2: диагностика берётся grep-ом по build.log в workflow,
# а полный дамп на гигабайты только замедляет сборку
log_level = 2
warn_on_root = 0


# --------------------------------------------------------------------------- #
#  Профиль для магазина: buildozer --profile store android release
# --------------------------------------------------------------------------- #
#
# Отдельный профиль, а не правка основного: отладочные сборки должны
# продолжать работать как раньше, без ключей и подписи.
#
[app@store]

# Подписанный релиз вместо debug-подписи. Ключи берутся из переменных
# окружения P4A_RELEASE_* — см. .github/workflows/build-release.yml
android.release_artifact = apk

