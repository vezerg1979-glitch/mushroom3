# -*- coding: utf-8 -*-
"""Тесты окна поддержки.

Смысл проверок один: реквизиты меняются редко, а ошибка в них стоит дорого —
деньги уходят чужому человеку, и узнаётся это далеко не сразу.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

sys.path.insert(0, APP)

import donate  # noqa: E402


# --------------------------------------------------------------------------- #
#  Карта
# --------------------------------------------------------------------------- #

def test_card_passes_luhn():
    """Контрольная сумма: страховка от опечатки при смене карты."""
    assert donate.luhn_ok()


def test_luhn_catches_typo():
    n = donate.digits()
    swapped = n[:4] + n[5] + n[4] + n[6:]
    assert not donate.luhn_ok(swapped)
    assert not donate.luhn_ok("1234567890123456")
    assert not donate.luhn_ok("не число")
    assert not donate.luhn_ok("220424")


def test_card_digits_are_clean():
    d = donate.digits()
    assert d.isdigit() and len(d) == 16


# --------------------------------------------------------------------------- #
#  СБП
# --------------------------------------------------------------------------- #

def test_phone_normalises_eight_to_seven(monkeypatch):
    """Человек пишет 8..., банк ждёт +7... — приводим сами."""
    monkeypatch.setattr(donate, "SBP_PHONE", "8 916 123-45-67")
    assert donate.phone_digits() == "+79161234567"


def test_phone_pretty_is_readable(monkeypatch):
    monkeypatch.setattr(donate, "SBP_PHONE", "+79161234567")
    assert donate.phone_pretty() == "+7 916 123-45-67"


def test_sbp_hidden_until_filled(monkeypatch):
    """Пустые реквизиты не должны показываться пустым местом."""
    monkeypatch.setattr(donate, "SBP_PHONE", "")
    monkeypatch.setattr(donate, "SBP_BANK", "")
    monkeypatch.setattr(donate, "SBP_LINK", "")
    monkeypatch.setattr(donate, "SBP_QR_LINK", "")
    assert not donate.sbp_ready()
    assert "СБП" not in donate.text()


def test_sbp_needs_bank_too(monkeypatch):
    """Без названия банка перевод уйдёт на счёт в другом банке."""
    monkeypatch.setattr(donate, "SBP_PHONE", "+79161234567")
    monkeypatch.setattr(donate, "SBP_BANK", "")
    assert not donate.sbp_ready()


def test_sbp_shown_first_when_filled(monkeypatch):
    """СБП удобнее, поэтому стоит выше карты."""
    monkeypatch.setattr(donate, "SBP_PHONE", "+79161234567")
    monkeypatch.setattr(donate, "SBP_BANK", "Сбербанк")
    t = donate.text()
    assert t.index("СБП") < t.index("карту")
    assert "Сбербанк" in t


def test_short_phone_rejected(monkeypatch):
    monkeypatch.setattr(donate, "SBP_PHONE", "+7916")
    monkeypatch.setattr(donate, "SBP_BANK", "Сбербанк")
    assert not donate.sbp_ready()


# --------------------------------------------------------------------------- #
#  Текст
# --------------------------------------------------------------------------- #

def test_text_explains_why_the_app_exists():
    """Окно доната — единственное место, где автор говорит от себя.

    Просьба о деньгах без объяснения, зачем всё это, читается как реклама.
    Поэтому текст начинается с того, откуда приложение взялось, и только
    потом переходит к реквизитам.
    """
    t = donate.text()
    assert donate.CARD in t
    low = t.lower()
    assert "для себя" in low, "нет объяснения, откуда приложение"
    assert "без сети" in low, "не сказано, чем оно полезно потерявшемуся"
    assert low.index("для себя") < low.index(donate.CARD.lower())


def test_text_promises_no_ads_or_paywall():
    """Обещание должно оставаться правдой: появятся платные функции —
    этот тест напомнит переписать формулировку."""
    t = donate.text().lower()
    for word in ("рекламы", "бесплатн"):
        assert word in t


def test_open_url_ignores_empty():
    assert donate.open_url("") is False


def test_module_imports_without_kivy():
    assert callable(donate.show)
    assert isinstance(donate.INTRO, str)


# --------------------------------------------------------------------------- #
#  Готовность к публикации
# --------------------------------------------------------------------------- #

def test_sbp_filled_before_release():
    """Напоминание: без телефона и банка окно показывает только карту.

    Тест намеренно мягкий — падать он не должен, пока СБП не настроен,
    иначе сломается сборка отладочных версий. Но предупреждение видно.
    """
    if not donate.sbp_ready():
        pytest.skip("СБП не заполнен: укажите SBP_PHONE и SBP_BANK в donate.py")
    assert len(donate.phone_digits()) == 12


# --------------------------------------------------------------------------- #
#  Читаемость
# --------------------------------------------------------------------------- #
#
# Окно поддержки открывали в лесу и жаловались, что текста не видно: содержимое
# рисовалось без собственного фона, поверх тёмной подложки Popup, и тёмный
# текст сливался с ней (контраст 1.2 при норме 4.5). Теперь под содержимым
# белая карточка, а пары цветов проверяются здесь.

@pytest.mark.parametrize("fg,bg,limit", [
    ("INK_HEX", "BG_HEX", donate.MIN_CONTRAST),
    ("MUTED_HEX", "BG_HEX", donate.MIN_CONTRAST),
    ("INK_HEX", "SOFT_HEX", donate.MIN_CONTRAST),
    ("ON_DARK_HEX", "ACCENT_HEX", donate.MIN_CONTRAST_LARGE),
])
def test_palette_is_readable(fg, bg, limit):
    ratio = donate.contrast(getattr(donate, fg), getattr(donate, bg))
    assert ratio >= limit, f"{fg} на {bg}: контраст {ratio:.2f}, нужно {limit}"


def test_contrast_extremes():
    assert donate.contrast("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.05)
    assert donate.contrast("#808080", "#808080") == pytest.approx(1.0, abs=0.01)


def test_contrast_is_symmetric():
    a = donate.contrast(donate.INK_HEX, donate.BG_HEX)
    b = donate.contrast(donate.BG_HEX, donate.INK_HEX)
    assert a == pytest.approx(b)


def test_dark_text_on_dark_popup_would_fail():
    """Тот самый случай, ради которого проверка и заведена."""
    assert donate.contrast(donate.INK_HEX, "#3B3B3B") < donate.MIN_CONTRAST


def test_luminance_rejects_broken_colour():
    with pytest.raises(ValueError):
        donate.luminance("#ABC")


# --------------------------------------------------------------------------- #
#  Платёжная ссылка СБП
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("url", [
    "https://qr.nspk.ru/AS10003P3RH0LJ2A9ROO038L6NT5RU1M",
    "https://qr.nspk.ru/BD1P004FM8U22B8B8N1RHCRJSAB6C4TS"
    "?type=02&bank=100000000008&sum=100&cur=RUB&crc=A1A3",
    "https://sub.nspk.ru/AS1R004PRL5RNGBA9ARPLJLTDO94S3J9",
])
def test_real_sbp_links_accepted(url):
    assert donate.link_ok(url)


@pytest.mark.parametrize("url", [
    "",
    "https://qr.nspk.ru/",                      # без идентификатора
    "http://qr.nspk.ru/AS10003P3RH0LJ2A9ROO",   # без шифрования
    "https://qr.nspk.ru.example.com/AS10003",   # чужой хост с похожим началом
    "https://example.com/AS10003P3RH0LJ2A9RO",
    "qr.nspk.ru/AS10003P3RH0LJ2A9ROO038L6NT",
])
def test_wrong_links_rejected(url):
    """Кнопка про деньги не должна вести на посторонний сайт."""
    assert not donate.link_ok(url)


def test_sbp_link_empty_until_filled():
    assert donate.sbp_link() == "" or donate.link_ok(donate.sbp_link())


def test_sbp_link_returned_unchanged(monkeypatch):
    """Ссылку нельзя дописывать: параметры подписаны контрольной суммой."""
    url = ("https://qr.nspk.ru/AS10003P3RH0LJ2A9ROO038L6NT5RU1M"
           "?type=01&bank=100000000061&crc=5D90")
    monkeypatch.setattr(donate, "SBP_LINK", url)
    assert donate.sbp_link() == url


def test_bad_link_is_not_shown(monkeypatch):
    monkeypatch.setattr(donate, "SBP_LINK", "https://example.com/донат")
    monkeypatch.setattr(donate, "SBP_QR_LINK", "")
    assert donate.sbp_link() == ""
    assert "Оплата через СБП" not in donate.text()


def test_link_section_appears_in_text(monkeypatch):
    monkeypatch.setattr(donate, "SBP_LINK",
                        "https://qr.nspk.ru/AS10003P3RH0LJ2A9ROO038L6NT5RU1M")
    t = donate.text()
    assert "Оплата через СБП" in t
    assert t.index("СБП") < t.index("карту")


def test_old_setting_name_still_works(monkeypatch):
    """SBP_QR_LINK из прежних версий не должен молча перестать работать."""
    monkeypatch.setattr(donate, "SBP_LINK", "")
    monkeypatch.setattr(donate, "SBP_QR_LINK",
                        "https://qr.nspk.ru/AS10003P3RH0LJ2A9ROO038L6NT5RU1M")
    assert donate.sbp_link()


def test_copy_ignores_empty():
    assert donate.copy("") is False


# --------------------------------------------------------------------------- #
#  Банковские реквизиты
# --------------------------------------------------------------------------- #
#
# Реквизиты переносят руками из приложения банка, и одна переставленная цифра
# означает, что перевод уйдёт в никуда. У номера счёта для этого есть
# контрольный разряд, считающийся вместе с БИК, — им и пользуемся.

def test_account_matches_bic():
    assert donate.account_ok(), "номер счёта не сходится с БИК"


def test_corr_account_matches_bic():
    assert donate.corr_account_ok(), "корр. счёт не сходится с БИК"


def test_bank_inn_valid():
    assert donate.inn_ok()


def test_requisites_complete():
    assert donate.requisites_ok()
    assert donate.RECIPIENT.strip()
    assert len(donate.ACCOUNT) == 20 and donate.ACCOUNT.isdigit()
    assert len(donate.CORR_ACCOUNT) == 20 and donate.CORR_ACCOUNT.isdigit()


def test_account_typo_is_caught():
    """Перестановка соседних цифр — самая частая ошибка при переносе."""
    a = donate.ACCOUNT
    swapped = a[:7] + a[8] + a[7] + a[9:]
    assert swapped != a
    assert not donate.account_ok(swapped)


def test_account_rejects_wrong_bank():
    """Верный счёт с чужим БИК не должен проходить."""
    assert not donate.account_ok(donate.ACCOUNT, "044525225")


def test_corr_account_not_confused_with_client_account():
    """Префикс у корреспондентского счёта другой: перепутать нельзя."""
    assert not donate.account_ok(donate.CORR_ACCOUNT)
    assert not donate.corr_account_ok(donate.ACCOUNT)


@pytest.mark.parametrize("bad", ["04452506", "0445250688", "144525068",
                                 "04452506x"])
def test_bic_rejects_malformed(bad):
    assert not donate.bic_ok(bad)


def test_empty_argument_means_configured_value():
    """Соглашение всего модуля: пустая строка — «проверь то, что в файле»."""
    assert donate.bic_ok("") is donate.bic_ok(donate.BIC)
    assert donate.luhn_ok("") is donate.luhn_ok(donate.digits())


@pytest.mark.parametrize("inn,ok", [
    ("9703077050", True),      # Озон Банк
    ("7707083893", True),      # Сбербанк
    ("9703077051", False),     # испорченный контрольный разряд
    ("770708389", False),      # девять знаков
    ("не число", False),
])
def test_inn_checksum(inn, ok):
    assert donate.inn_ok(inn) is ok


def test_requisites_block_has_every_field():
    b = donate.requisites_block()
    for value in (donate.RECIPIENT, donate.ACCOUNT, donate.BIC,
                  donate.CORR_ACCOUNT, donate.BANK_INN, donate.BANK_KPP,
                  donate.PURPOSE):
        assert value in b


def test_requisites_shown_in_window_text():
    t = donate.text()
    assert donate.ACCOUNT in t
    assert donate.BIC in t
    assert t.index("карту") < t.index("реквизитам")


def test_broken_requisites_are_hidden(monkeypatch):
    """Неверные реквизиты хуже отсутствующих: раздел не показываем."""
    monkeypatch.setattr(donate, "ACCOUNT", "40914810300007365154")
    assert not donate.requisites_ok()
    assert "реквизитам" not in donate.text()


def test_purpose_is_not_own_funds():
    """«Переводы собственных средств» — формулировка для пополнения своего
    же счёта, донат приходит от постороннего человека."""
    assert "собственных" not in donate.PURPOSE.lower()


# --------------------------------------------------------------------------- #
#  Согласованность способов оплаты
# --------------------------------------------------------------------------- #

def test_configured_phone_is_russian_mobile():
    d = donate.phone_digits()
    assert len(d) == 12 and d.startswith("+79"), f"странный номер: {d}"


def test_sbp_bank_matches_account_bank():
    """Банк в подсказке СБП и банк из реквизитов — один и тот же.

    Если счёт переедет в другой банк, а строка СБП останется прежней,
    человек выберет в списке получателей не тот банк и перевод уйдёт
    туда, где счёта уже нет. Тест напомнит поправить оба места.
    """
    short = donate.SBP_BANK.lower().replace("ё", "е")
    full = donate.BANK_NAME.lower().replace("ё", "е")
    core = short.replace("банк", "").strip()
    assert core and core in full, (
        f"SBP_BANK {donate.SBP_BANK!r} не совпадает с BANK_NAME "
        f"{donate.BANK_NAME!r}")


def test_all_three_ways_are_offered():
    """В окне должны быть все способы, которые настроены."""
    t = donate.text()
    assert donate.phone_pretty() in t
    assert donate.CARD in t
    assert donate.ACCOUNT in t


# --------------------------------------------------------------------------- #
#  Ссылка конкретного банка и QR
# --------------------------------------------------------------------------- #
#
# Формат платёжной ссылки у каждого банка свой: НСПК выдаёт qr.nspk.ru/AS1000…,
# Озон — finance.ozon.ru/apps/sbp/ozonbankpay/… с косыми чертами в пути.
# Проверка, написанная под один формат, молча отвергала бы второй, и кнопка
# оплаты просто не появлялась бы — без единого сообщения.

def test_configured_link_is_accepted():
    assert donate.link_ok(), f"настроенная ссылка не проходит проверку: {donate.SBP_LINK}"
    assert donate.sbp_link() == donate.SBP_LINK


def test_link_names_its_bank():
    assert donate.link_bank() == "Озон Банк"
    assert donate.link_bank("https://qr.nspk.ru/AS10003P3RH0LJ2A9ROO") == "СБП"
    assert donate.link_bank("https://example.com/что-то") == ""


@pytest.mark.parametrize("url", [
    "https://finance.ozon.ru/apps/sbp/ozonbankpay/01a00bc5-dd2b-7b0b-875e-6805ddfff2ae",
    "https://qr.nspk.ru/AS10003P3RH0LJ2A9ROO038L6NT5RU1M",
    "https://sub.nspk.ru/AS1R004PRL5RNGBA9ARPLJLTDO94S3J9",
])
def test_real_bank_links_accepted(url):
    assert donate.link_ok(url)


@pytest.mark.parametrize("url", [
    "https://finance.ozon.ru/",                       # витрина банка, не перевод
    "https://finance.ozon.ru/apps",                   # путь слишком короткий
    "https://finance.ozon.ru.example.com/apps/sbp/12345678",   # похожий чужой хост
    "http://finance.ozon.ru/apps/sbp/ozonbankpay/01a0",        # без шифрования
    "https://example.com/apps/sbp/ozonbankpay/01a00bc5",
])
def test_wrong_bank_links_rejected(url):
    assert not donate.link_ok(url)


def test_window_text_names_the_bank():
    assert "Озон Банк" in donate.text()


def test_qr_image_ships_with_the_app():
    """Картинка QR нужна не себе: свой экран не отсканируешь."""
    path = donate.qr_path()
    assert path, "файл QR не найден рядом с кодом"
    assert os.path.getsize(path) > 1000


def test_qr_matches_the_link():
    """Картинка и ссылка должны вести в одно место.

    Разойтись им проще простого: банк перевыпустил код, ссылку в файле
    поправили, а картинку забыли — и человек, отсканировавший QR, переведёт
    деньги неизвестно куда.
    """
    try:
        import zxingcpp
        from PIL import Image
    except ImportError:
        pytest.skip("нет декодера QR")
    found = zxingcpp.read_barcodes(Image.open(donate.qr_path()))
    assert found, "QR не читается"
    assert found[0].text == donate.SBP_LINK
