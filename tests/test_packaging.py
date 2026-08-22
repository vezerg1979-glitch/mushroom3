# -*- coding: utf-8 -*-
"""Тесты упаковки APK.

Каждая проверка здесь соответствует поломке, которую уже ловили в поле.
Настройки сборки терялись при переносе между репозиториями по несколько раз,
и каждая потеря стоила получасового прогона CI плюс отладки на телефоне.
"""

import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SPEC = os.path.join(ROOT, "android", "buildozer.spec")


@pytest.fixture(scope="module")
def spec():
    with open(SPEC, encoding="utf-8") as f:
        return f.read()


def value(spec, key):
    m = re.search(rf"^{re.escape(key)}\s*=\s*(.+)$", spec, re.M)
    return m.group(1).strip() if m else None


def test_filetype_stub_exists():
    """Без заглушки Kivy падает на импорте графики, экран остаётся чёрным."""
    assert os.path.exists(os.path.join(ROOT, "android", "filetype.py"))


def test_filetype_not_in_requirements(spec):
    """Настоящий пакет с PyPI ломает сборку: рецепта у p4a нет."""
    assert "filetype" not in value(spec, "requirements")


def test_p4a_branch_pinned(spec):
    """На develop собирается Python 3.14 и колёса не подходят."""
    assert value(spec, "p4a.branch") == "v2024.01.21"


def test_ndk_pinned_to_25b(spec):
    """r28c тянет за собой несовместимый Python."""
    assert value(spec, "android.ndk") == "25b"


def test_ndk_api_24(spec):
    """При 21 у r25b не хватает заголовков — обрыв на этапе create."""
    assert value(spec, "android.ndk_api") == "24"


def test_tracker_service_declared(spec):
    """Без этой строки класс ServiceTracker в APK отсутствует."""
    line = value(spec, "services")
    assert line and line.startswith("Tracker:service_tracker.py")


def test_service_file_exists_and_class_name_matches():
    """Имя в spec и имя, которое ищет service_ctl, должны сходиться."""
    assert os.path.exists(os.path.join(ROOT, "android", "service_tracker.py"))
    with open(os.path.join(ROOT, "android", "service_ctl.py"), encoding="utf-8") as f:
        ctl = f.read()
    assert "ru.grezev.mushroomforecast.ServiceTracker" in ctl


def test_target_api_33_while_p4a_cannot_write_fgs_type(spec):
    """На api 34 Android требует foregroundServiceType, p4a его не пишет."""
    assert value(spec, "android.api") == "33"


def test_permissions_cover_background_tracking(spec):
    perms = value(spec, "android.permissions")
    for need in ("ACCESS_FINE_LOCATION", "ACCESS_BACKGROUND_LOCATION",
                 "FOREGROUND_SERVICE", "INTERNET"):
        assert need in perms


def test_spec_version_matches_engine():
    """Имя APK должно говорить, какая версия модели внутри."""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "android"))
    import mushroom_forecast as engine
    with open(SPEC, encoding="utf-8") as f:
        assert value(f.read(), "version") == engine.VERSION


# --------------------------------------------------------------------------- #
#  Готовность к публикации в магазине
# --------------------------------------------------------------------------- #

def test_icon_and_presplash_exist():
    """Без иконки магазин карточку не примет, а система нарисует заглушку."""
    for name in ("icon.png", "presplash.png"):
        path = os.path.join(ROOT, "android", name)
        assert os.path.exists(path), f"нет {name}"
        assert os.path.getsize(path) > 1000


def test_icon_is_square_512(spec):
    """RuStore требует иконку 512x512."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("PIL не установлен")
    with Image.open(os.path.join(ROOT, "android", "icon.png")) as im:
        assert im.size == (512, 512)


def test_icon_declared_in_spec(spec):
    """Файл на диске без строки в spec в APK не попадёт."""
    assert value(spec, "icon.filename")
    assert value(spec, "presplash.filename")


def test_small_icon_kept_in_step_with_the_big_one():
    """Значок 192 нужен карточке магазина и правится вместе с основным.

    Разъезжались уже: основной значок переделали, мелкий остался прежним, и
    в магазине висела картинка от старой версии.
    """
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("PIL не установлен")
    small = os.path.join(ROOT, "android", "icon-192.png")
    assert os.path.exists(small)
    with Image.open(small) as im:
        assert im.size == (192, 192)
        thumb_small = im.convert("RGB").resize((16, 16))
    with Image.open(os.path.join(ROOT, "android", "icon.png")) as big:
        thumb_big = big.convert("RGB").resize((16, 16))
    diff = sum(abs(a - b) for a, b in zip(thumb_small.tobytes(),
                                          thumb_big.tobytes()))
    assert diff / (16 * 16 * 3) < 12, "мелкий значок не от этой картинки"


def test_icon_is_not_a_blank_fill():
    """Сторож против пустого файла: однажды в сборку уехал залитый квадрат."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("PIL не установлен")
    with Image.open(os.path.join(ROOT, "android", "icon.png")) as im:
        colors = im.convert("RGB").resize((64, 64)).getcolors(maxcolors=1 << 20)
    assert len(colors) > 200


def test_icon_carries_no_caption():
    """В значке не должно быть надписи.

    На рабочем столе значок занимает 48 dp: подпись там не читается даже как
    подпись — получается светлая полоса, отъедающая площадь у единственной
    картинки, которую вообще можно узнать. Признак полосы — строка, где
    больше десятой части пикселей почти белые.
    """
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("PIL не установлен")
    with Image.open(os.path.join(ROOT, "android", "icon.png")) as im:
        px = im.convert("L").load()
        w, h = im.size
    worst = max(sum(1 for x in range(w) if px[x, y] > 205) for y in range(h))
    assert worst < w * 0.10, "похоже, в значок попала надпись"


def test_presplash_is_square_and_its_field_colour_declared(spec):
    """Иначе полосы вокруг заставки на вытянутом экране будут белыми.

    Цвет поля сверяется с углом самой картинки: заставку меняют целиком, а
    строку в spec забывают, и тёмная заставка на белом фоне выглядит как
    ошибка загрузки.
    """
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("PIL не установлен")
    declared = value(spec, "android.presplash_color")
    assert declared, "нет android.presplash_color"
    want = tuple(int(declared.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    with Image.open(os.path.join(ROOT, "android", "presplash.png")) as im:
        assert im.width == im.height
        corner = im.convert("RGB").getpixel((2, 2))
    assert max(abs(a - b) for a, b in zip(corner, want)) <= 12, (
        f"угол заставки {corner}, а в spec {want}")


def test_app_title_matches_the_spec(spec):
    """Название на экране телефона и в магазине должно быть одним и тем же.

    Заголовок живёт в двух местах: buildozer.spec задаёт подпись под значком
    на рабочем столе, App.title — то, что видно в списке запущенных программ.
    Разъезжались они уже дважды.
    """
    with open(os.path.join(ROOT, "android", "main.py"), encoding="utf-8") as f:
        src = f.read()
    m = re.search(r'^\s*title = "(.+)"$', src, re.M)
    assert m, "в main.py не нашлось App.title"
    assert m.group(1) == value(spec, "title")


def test_package_name_is_not_renamed(spec):
    """Имя пакета менять нельзя, как бы ни менялось название приложения.

    Для Android и для магазина это другое приложение: обновление поверх
    установленного не встанет, а журнал, треки и снимки останутся в старом.
    """
    assert value(spec, "package.name") == "mushroomforecast"
    assert value(spec, "package.domain") == "ru.grezev"


def test_numeric_version_present_and_matches(spec):
    """Магазин отвергает загрузку с тем же кодом версии, что и предыдущая."""
    code = value(spec, "android.numeric_version")
    assert code and code.isdigit()
    major, minor = value(spec, "version").split(".")[:2]
    assert code.startswith(f"{int(major)}{int(minor):02d}")


def test_store_profile_exists(spec):
    """Профиль магазина отдельно от отладочного: buildozer --profile store."""
    assert "[app@store]" in spec
    assert "android.release_artifact" in spec.split("[app@store]")[1]


def test_privacy_policy_lists_every_permission(spec):
    """Модерация сверяет разрешения с политикой: расхождение — отказ."""
    with open(os.path.join(ROOT, "docs", "privacy.md"), encoding="utf-8") as f:
        privacy = f.read()
    for perm in value(spec, "android.permissions").split(","):
        short = perm.strip().rsplit(".", 1)[-1]
        assert short in privacy, f"{short} не описан в политике"


def test_release_workflow_runs_tests_before_signing():
    """Подписывать несобирающуюся модель незачем."""
    path = os.path.join(ROOT, ".github", "workflows", "build-release.yml")
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        wf = f.read()
    assert wf.index("pytest") < wf.index("android release")
    assert "KEYSTORE_BASE64" in wf


def test_keystore_never_committed():
    """Ключ подписи в репозитории — это чужие обновления от вашего имени."""
    bad = []
    for base, _dirs, files in os.walk(ROOT):
        if ".git" in base:
            continue
        for name in files:
            if name.endswith((".keystore", ".jks", ".b64")):
                bad.append(os.path.join(base, name))
    assert not bad, f"в репозитории лежат ключи: {bad}"


def test_release_tests_run_without_kivy():
    """Прогон перед релизом не должен требовать Kivy.

    Релиз собирается в образе buildozer, где Kivy для системного Python не
    установлен. Модуль тестов, импортирующий его на верхнем уровне, роняет
    не себя, а сбор всех тестов целиком — и подписанный APK не собирается
    вовсе. Один такой импорт уже стоил сорванной сборки.
    """
    import re
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    bad = []
    for name in sorted(os.listdir(tests_dir)):
        if not name.startswith("test_") or not name.endswith(".py"):
            continue
        with open(os.path.join(tests_dir, name), encoding="utf-8") as f:
            for num, line in enumerate(f, 1):
                if re.match(r"^\s*(import|from)\s+kivy\b", line):
                    bad.append(f"{name}:{num}")
    assert not bad, f"Kivy импортируется на верхнем уровне: {bad}"


def test_ui_modules_are_not_imported_at_test_top_level():
    """То же про свои модули, которые тянут Kivy за собой."""
    import re
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    # icons сюда не входит: там чистая геометрия без единого импорта Kivy,
    # ради того и написана.
    heavy = ("walkjournal", "walkscreen", "mapview", "finddialog",
             "navwidget", "offlinemap", "donate_ui")
    bad = []
    for name in sorted(os.listdir(tests_dir)):
        if not name.startswith("test_") or not name.endswith(".py"):
            continue
        with open(os.path.join(tests_dir, name), encoding="utf-8") as f:
            for num, line in enumerate(f, 1):
                m = re.match(r"^(import|from)\s+(\w+)", line)
                if m and m.group(2) in heavy:
                    bad.append(f"{name}:{num}: {line.strip()}")
    assert not bad, f"модуль с виджетами импортируется на верхнем уровне: {bad}"
