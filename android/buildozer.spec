[app]

title = Навигатор грибника
package.name = mushroomforecast
package.domain = ru.grezev

source.dir = .
source.include_exts = py,png,jpg,ttf,json

version = 2.9

# Ветку p4a обязательно держать закреплённой: на develop собирается
# Python 3.14, под который не подходят колёса, и сборка обрывается
p4a.branch = v2024.01.21

# urllib3 убран намеренно — код им не пользуется, сеть идёт через
# stdlib urllib.request. plyer нужен для GPS (кнопка «Определить место»)
requirements = python3,kivy==2.3.1,certifi,openssl,plyer

# Фоновая запись трека. Имя до двоеточия задаёт Java-класс:
# Tracker -> ru.grezev.mushroomforecast.ServiceTracker, именно его ищет
# service_ctl.py. Без этой строки класса в APK нет и сервис не стартует.
services = Tracker:service_tracker.py:foreground

orientation = portrait
fullscreen = 0

presplash.filename = %(source.dir)s/presplash.png
icon.filename = %(source.dir)s/icon.png

# Числовой код версии. Магазин требует, чтобы он рос с каждой загрузкой,
# иначе новая сборка не принимается. Формат: 2.7 -> 20700, 2.7.1 -> 20701.
android.numeric_version = 20900

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
#                    стартует и тут же убивается
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
log_level = 1
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

# Магазины требуют свежий targetSdk. Прежде чем поднимать до 34, читайте
# примечание про foregroundServiceType в docs/rustore.md: на 34 фоновому
# сервису нужен атрибут, который p4a 2024.01.21 не выставляет.
android.api = 33
