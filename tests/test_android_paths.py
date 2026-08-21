# -*- coding: utf-8 -*-
"""Телефонные пути кода: доезжают ли они до конца.

Эти функции на сборочной машине не исполняются никогда — jnius там нет, и
все обёртки честно возвращают False. Именно поэтому в них дважды подряд
уехала поломка, видимая только на телефоне: пропавшая функция и cast,
которому дали питоновскую строку.

Здесь они прогоняются через поддельный jnius (androidfake.py), который
повторяет строгость настоящего. Проверяется не то, что Android поступит как
надо, — этого на компьютере не узнать, — а то, что наш код не спотыкается
раньше, чем доберётся до системы.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

sys.path.insert(0, APP)

import androidfake  # noqa: E402


@pytest.fixture
def android(monkeypatch, tmp_path):
    """Подделка вместо Android плюс свой каталог данных."""
    import importlib

    import places

    monkeypatch.setattr(places, "_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MUSHROOM_DATA_DIR", raising=False)
    saved = androidfake.install()
    mods = {}
    for name in ("backup", "notify", "survival", "ads", "billing"):
        mods[name] = importlib.reload(importlib.import_module(name))
    try:
        yield mods
    finally:
        androidfake.restore(saved)
        for name in mods:
            importlib.reload(importlib.import_module(name))


# --------------------------------------------------------------------------- #
#  Сама заглушка
# --------------------------------------------------------------------------- #

def test_fake_refuses_a_python_string_in_cast():
    """Если заглушка это разрешит, она перестанет ловить ту самую ошибку."""
    with pytest.raises(TypeError) as e:
        androidfake.cast("java.lang.CharSequence", "просто строка")
    assert "Cannot convert str" in str(e.value)


def test_fake_accepts_a_java_object():
    obj = androidfake.autoclass("java.lang.String")("текст")
    assert androidfake.cast("java.lang.CharSequence", obj) is obj


# --------------------------------------------------------------------------- #
#  Резервная копия
# --------------------------------------------------------------------------- #

def test_share_goes_through(android):
    """Кнопка «Поделиться» после сборки копии. Дважды падала на телефоне."""
    backup = android["backup"]
    uri = androidfake.autoclass("android.net.Uri")("content://downloads/1")
    assert backup.share(uri, subject="Наблюдения", text="Копия") is True


def test_share_without_a_link_says_no(android):
    assert android["backup"].share(None) is False


def test_publish_writes_the_file_out(android, tmp_path):
    backup = android["backup"]
    src = tmp_path / "копия.zip"
    src.write_bytes(b"PK\x03\x04" + b"x" * 1000)
    assert backup.on_android() is True
    backup.publish(str(src))            # падения быть не должно


def test_publish_on_old_android_falls_back_to_downloads(android, tmp_path,
                                                        monkeypatch):
    """Android 9 и старше: MediaStore недоступен, файл кладётся напрямую."""
    backup = android["backup"]
    monkeypatch.setattr(backup, "_sdk_int", lambda: 28)
    src = tmp_path / "копия.zip"
    src.write_bytes(b"PK\x03\x04")
    assert backup.publish(str(src)) is None      # ссылки нет, и это не ошибка


def test_pick_asks_the_system(android):
    got = []
    assert android["backup"].pick(lambda path, err: got.append((path, err)))


# --------------------------------------------------------------------------- #
#  Уведомления
# --------------------------------------------------------------------------- #

def test_notification_is_posted(android):
    """Ошибка здесь гасилась общим except: уведомления о слое просто не было.

    Ни следа в журнале, ни сообщения — поэтому сломанной эта дорога могла
    оставаться сезонами.
    """
    assert android["notify"].post("Белый гриб: слой с четверга",
                                  "Индекс поднимается с 31 до 58.") is True


def test_empty_notification_is_refused(android):
    assert android["notify"].post("", "текст") is False


@pytest.mark.parametrize("sdk", [24, 26, 33])
def test_notification_works_across_versions(android, monkeypatch, sdk):
    """Каналы появились в Android 8, а до этого их нет вовсе."""
    notify = android["notify"]
    monkeypatch.setattr(notify, "_sdk_int", lambda: sdk)
    assert notify.post("Заголовок", "Текст") is True


# --------------------------------------------------------------------------- #
#  Настройки живучести
# --------------------------------------------------------------------------- #

def test_battery_settings_open(android):
    assert android["survival"].open_battery_settings() is True


def test_vendor_settings_open(android):
    assert android["survival"].open_vendor_settings() is True


def test_app_settings_open(android):
    assert android["survival"].open_app_settings() is True


def test_exemption_is_asked_from_the_system(android):
    """Ответ подделки неважен: важно, что вызов не падает по дороге."""
    android["survival"].is_exempt()


def test_a_failed_notification_leaves_a_trace(android, monkeypatch):
    """Молчаливая неудача здесь однажды стоила сезона уведомлений.

    Сломанный вызов падал, общий except возвращал False, и человек просто
    не видел сообщений о слое — ни ошибки, ни следа в журнале.
    """
    import sys

    notify = android["notify"]
    jnius = sys.modules["jnius"]
    real = jnius.autoclass

    def boom(name):
        # Ломается ровно то, что вызывается внутри защищённого участка:
        # проверки доступности идут раньше и ловят свои ошибки сами.
        if "Notification$Builder" in name:
            raise RuntimeError("система отказала")
        return real(name)

    monkeypatch.setattr(jnius, "autoclass", boom)
    assert notify.post("Заголовок", "Текст") is False
    assert "система отказала" in notify.last_error


def test_a_good_notification_clears_the_trace(android):
    notify = android["notify"]
    notify.last_error = "старая беда"
    assert notify.post("Заголовок", "Текст") is True
    assert notify.last_error == ""


# --------------------------------------------------------------------------- #
#  Выгрузка трека
# --------------------------------------------------------------------------- #

def test_track_export_reaches_the_share_sheet(android, tmp_path, monkeypatch):
    """Кнопка «Выгрузить» должна отдавать файл человеку, а не в никуда.

    Раньше трек писался во внутренний каталог приложения, и сообщался путь,
    по которому файл не достать ничем: кнопка формально работала, а по сути
    нет. Проверяется весь путь: GPX собран, положен в «Загрузки», передан
    системе.

    Пропускается без Kivy: walkjournal.py — настоящий экран, в отличие от
    backup.py/notify.py/survival.py он не оборачивает импорт Kivy в try —
    и правильно, это не android-обвязка, а виджеты. android/, откуда взят
    остальной этот файл, до Kivy добраться не требует; этот один тест —
    требует, и без него на машине без Kivy падал сбор всего файла целиком.

    Пропуск по одному только import kivy недостаточен: в контейнере
    kivy/buildozer, где собирается релиз, сам пакет kivy стоит, а вот
    графический бэкенд (SDL2/GL) в headless-окружении — нет. import kivy
    там проходит, а kivy.graphics, который и использует walkjournal.py,
    уже падает. Поэтому пропускаем по нему, а не по верхнему пакету.
    """
    pytest.importorskip("kivy.graphics")
    import importlib

    import track

    backup = android["backup"]
    calls = {}
    monkeypatch.setattr(backup, "publish",
                        lambda path, mime="application/zip":
                        calls.setdefault("publish", (path, mime))
                        or androidfake.autoclass("android.net.Uri")("content://x"))
    monkeypatch.setattr(backup, "share",
                        lambda uri, **kw: calls.setdefault("share", kw) or True)

    walkjournal = importlib.import_module("walkjournal")
    monkeypatch.setattr(walkjournal, "backup", backup)

    w = track.Walk(place="Ельник")
    w.add_point(56.0, 38.0, t=1000.0)
    w.add_point(56.001, 38.0, t=1200.0)
    w.stop()

    card = walkjournal.WalkCard.__new__(walkjournal.WalkCard)
    card.walk = w
    card.status = type("L", (), {"text": ""})()
    walkjournal.WalkCard._export(card)

    assert calls["publish"][0].endswith(".gpx")
    assert calls["publish"][1] == walkjournal.GPX_MIME
    assert calls["share"]["mime"] == walkjournal.GPX_MIME
    assert "Загрузк" in card.status.text


# --------------------------------------------------------------------------- #
#  Реклама
# --------------------------------------------------------------------------- #

def test_banner_attaches_when_free(android, monkeypatch):
    """Обычный ход: телефон, реклама не куплена — баннер встаёт на место."""
    ads = android["ads"]
    monkeypatch.setattr(ads.premium, "is_premium", lambda: False)
    assert ads.init() is True
    assert ads.attach() is True
    assert ads.last_error == ""


def test_banner_does_not_attach_after_purchase(android, monkeypatch):
    """Правило «купил — рекламы нет» проверяется тем же кодом, что решает,
    показывать баннер или нет: не отдельной галочкой в интерфейсе."""
    ads = android["ads"]
    monkeypatch.setattr(ads.premium, "is_premium", lambda: True)
    assert ads.should_show() is False
    assert ads.attach() is False


def test_detach_after_never_attaching_is_harmless():
    """Снять баннер, которого не было (например, купили ДО первого показа),
    не должно падать."""
    import ads

    ads.detach()             # не должно бросить исключение


def test_ad_failure_is_recorded_not_raised(android, monkeypatch):
    """Сеть, старая прошивка без нужного класса, что угодно — сбой рекламы
    не должен быть виден нигде, кроме last_error. Та же идея, что у
    notify.py: молчаливый except, который забывает след, однажды уже стоил
    сезона уведомлений."""
    import androidfake

    ads = android["ads"]
    monkeypatch.setattr(ads.premium, "is_premium", lambda: False)

    настоящий_autoclass = androidfake.autoclass

    def падает(name):
        if "BannerAdView" in name:
            raise RuntimeError("нет такого класса в этой версии SDK")
        return настоящий_autoclass(name)

    import jnius
    monkeypatch.setattr(jnius, "autoclass", падает)
    assert ads.attach() is False
    assert "нет такого класса" in ads.last_error


def test_init_failure_is_recorded_not_raised(android, monkeypatch):
    """То же самое, что для attach(), но для init(): не так очевидно, что
    оба места ловят исключение по отдельности, — тест на attach() уже
    однажды не заметил дыру в init(), пока не появился этот."""
    import androidfake

    ads = android["ads"]
    monkeypatch.setattr(ads.premium, "is_premium", lambda: False)
    настоящий_autoclass = androidfake.autoclass

    def падает(name):
        if "MobileAds" in name:
            raise RuntimeError("SDK не проинициализирован")
        return настоящий_autoclass(name)

    import jnius
    monkeypatch.setattr(jnius, "autoclass", падает)
    assert ads.init() is False
    assert "SDK не проинициализирован" in ads.last_error


def test_ads_never_touched_from_the_walk_screen():
    """Экран похода не должен даже импортировать ads — реклама там не
    нужна физически, а не просто выключена условием."""
    with open(os.path.join(APP, "walkscreen.py"), encoding="utf-8") as f:
        src = f.read()
    assert "import ads" not in src


# --------------------------------------------------------------------------- #
#  Покупка через RuStore
# --------------------------------------------------------------------------- #

def test_billing_is_honestly_unavailable_for_now(android):
    """До настоящей интеграции модуль обязан говорить «недоступно», а не
    делать вид, что покупка проходит."""
    billing = android["billing"]
    assert billing.is_available() is False


def test_purchase_does_not_pretend_to_work(android):
    billing = android["billing"]
    итог = []
    assert billing.purchase(lambda ok, err: итог.append((ok, err))) is False
    assert итог == [(False, billing.last_error)]


def test_restore_does_not_pretend_to_work(android):
    billing = android["billing"]
    итог = []
    assert billing.restore(lambda ok, err: итог.append((ok, err))) is False
    assert итог and итог[0][0] is False
