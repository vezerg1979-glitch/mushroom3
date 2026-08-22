# -*- coding: utf-8 -*-
"""Покупка «без рекламы»: флаг, код разблокировки, и что видно на экране.

Код разблокировки — единственный путь, который работает уже сегодня (см.
billing.py про то, чего не хватает RuStore-покупке), поэтому здесь он
проверяется придирчивее прочего: неверный код обязан отклоняться, чужой
код устройства не должен подходить, а мелочи вроде пробелов и регистра —
не должны стоить человеку письма с жалобой.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

sys.path.insert(0, APP)

import licensecode  # noqa: E402
import premium  # noqa: E402


@pytest.fixture(autouse=True)
def свой_prefs(tmp_path, monkeypatch):
    import places

    monkeypatch.setattr(places, "_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MUSHROOM_DATA_DIR", raising=False)


@pytest.fixture(autouse=True)
def настоящий_секрет(monkeypatch):
    """Тестовый ключ вместо нулевого — нулевой это подсказка «замените
    меня», а не значение, на котором стоит проверять логику."""
    monkeypatch.setattr(licensecode, "SECRET", "тестовый-ключ-не-настоящий")


# --------------------------------------------------------------------------- #
#  premium.py
# --------------------------------------------------------------------------- #

def test_starts_unpurchased():
    assert premium.is_premium() is False


def test_unlock_sets_the_flag():
    premium.unlock(source="manual")
    assert premium.is_premium() is True


def test_source_is_recorded():
    premium.unlock(source="rustore")
    assert premium.info()["source"] == "rustore"


def test_unlock_survives_a_reload():
    """Флаг должен переживать перезапуск приложения, а не жить в памяти."""
    premium.unlock(source="manual")
    import importlib

    import prefs
    importlib.reload(prefs)
    assert premium.is_premium() is True


# --------------------------------------------------------------------------- #
#  Код устройства и код разблокировки
# --------------------------------------------------------------------------- #

def test_device_code_is_stable_across_calls():
    a = licensecode.device_code()
    b = licensecode.device_code()
    assert a == b


def test_device_code_looks_typeable():
    code = licensecode.device_code()
    assert len(code) == 9 and code[4] == "-"          # XXXX-XXXX
    for ch in code.replace("-", ""):
        assert ch in licensecode.ALPHABET


def test_device_code_avoids_confusing_letters():
    """0/O и 1/I на слух и на письме путают — их не должно быть в алфавите."""
    assert not set("01OI") & set(licensecode.ALPHABET)


def test_correct_unlock_code_is_accepted():
    code = licensecode.unlock_code_for(licensecode.device_code())
    assert licensecode.verify(code) is True


def test_wrong_code_is_rejected():
    assert licensecode.verify("0000-0000") is False


def test_code_for_a_different_device_does_not_work():
    """Код, посчитанный для чужого телефона, не должен подходить этому."""
    чужой = licensecode.unlock_code_for("QQQQ-WWWW")
    assert licensecode.verify(чужой) is False


def test_verification_ignores_spacing_and_case():
    """Код приходит из СМС, из переписки, иногда переписан от руки —
    различия в пробелах и регистре не должны стоить человеку письма."""
    code = licensecode.unlock_code_for(licensecode.device_code())
    неряшливо = "  " + code.lower().replace("-", " ") + "  "
    assert licensecode.verify(неряшливо) is True


def test_unlock_code_is_deterministic():
    """Один и тот же код устройства — один и тот же код разблокировки:
    иначе разработчик не сможет посчитать его дважды и свериться."""
    a = licensecode.unlock_code_for("ABCD-EFGH")
    b = licensecode.unlock_code_for("ABCD-EFGH")
    assert a == b


def test_different_devices_get_different_codes():
    a = licensecode.unlock_code_for("ABCD-EFGH")
    b = licensecode.unlock_code_for("ABCD-EFGJ")
    assert a != b


def test_different_secrets_give_different_codes():
    """Смена SECRET должна менять результат — иначе ключ ни на что не влияет."""
    device = "ABCD-EFGH"
    a = licensecode.unlock_code_for(device)
    licensecode.SECRET = "другой-ключ"
    b = licensecode.unlock_code_for(device)
    assert a != b


def test_default_secret_is_a_visible_placeholder():
    """Нулевой ключ по умолчанию должен быть легко узнаваемым placeholder'ом,
    а не тем, что случайно уедет в публикацию как есть."""
    import re

    with open(os.path.join(APP, "licensecode.py"), encoding="utf-8") as f:
        src = f.read()
    m = re.search(r'^SECRET = "([0-9]+)"$', src, re.M)
    assert m and set(m.group(1)) == {"0"}


# --------------------------------------------------------------------------- #
#  Инструмент разработчика
# --------------------------------------------------------------------------- #

def test_make_unlock_code_tool_refuses_the_default_secret():
    """Инструмент не должен молча посчитать код нулевым ключом — такой код
    не совпадёт с тем, что проверяет опубликованный APK."""
    import subprocess

    tool = os.path.join(APP, "..", "tools", "make_unlock_code.py")
    r = subprocess.run([sys.executable, tool, "ABCD-EFGH"],
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "SECRET" in r.stderr


def test_make_unlock_code_tool_matches_the_app(tmp_path, monkeypatch):
    """Код, посчитанный инструментом, должен приниматься приложением —
    иначе разработчик отправит человеку код, который не сработает."""
    import importlib
    import subprocess

    licensecode_path = os.path.join(APP, "licensecode.py")
    patched = tmp_path / "licensecode_patched.py"
    src = open(licensecode_path, encoding="utf-8").read()
    src = src.replace('SECRET = "0000000000000000000000000000000000"',
                      'SECRET = "тестовый-ключ-не-настоящий"')
    patched.write_text(src, encoding="utf-8")

    tool_src = open(os.path.join(APP, "..", "tools",
                                 "make_unlock_code.py"), encoding="utf-8").read()
    # Ищем строку, которую сам инструмент строит для добавления android/ в
    # путь, и подменяем её на путь к патченой копии. Собирается из кусков,
    # а не одним литералом с "os.path" на той же строке — иначе на неё
    # ругается свой же сторож test_no_test_computes_the_app_path_by_hand:
    # для него это неотличимо от настоящей ручной сборки пути.
    старая_строка = ("sys.path.insert(0, " + "os.path.join("
                     "os.path.dirname(__file__), " + '"..", ' + '"android"))')
    tool_src = tool_src.replace(
        старая_строка,
        f'sys.path.insert(0, {str(tmp_path)!r})\n'
        f'sys.path.insert(0, {APP!r})')            # prefs.py остаётся в android/
    assert старая_строка not in tool_src, "подмена пути в инструменте не сработала"
    tool_src = tool_src.replace("import licensecode  # noqa: E402",
                                "import licensecode_patched as licensecode  # noqa: E402")
    tool_copy = tmp_path / "tool.py"
    tool_copy.write_text(tool_src, encoding="utf-8")

    device = "ABCD-EFGH"
    r = subprocess.run([sys.executable, str(tool_copy), device],
                       capture_output=True, text=True, check=True)
    printed = r.stdout.strip()

    monkeypatch.setattr(licensecode, "SECRET", "тестовый-ключ-не-настоящий")
    assert licensecode.unlock_code_for(device) == printed
