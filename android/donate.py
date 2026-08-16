# -*- coding: utf-8 -*-
"""
donate.py — окно «Поддержать проект».

Порядок способов выбран по удобству для человека, а не для получателя.
Сверху платёжная ссылка СБП: одно касание — и открывается приложение банка
с уже подставленными реквизитами. Ниже перевод по номеру телефона: три
касания, но зато работает у всех. Карта оставлена последней как запасной
путь — для тех, у кого банк без СБП или кто привык переводить именно так.

Реквизиты собраны в константах вверху файла: карту перевыпускают, телефон
меняют, и когда всё лежит в одном месте с проверками, ошибиться труднее.

Про цвета. Окно рисуется поверх стандартной подложки Popup, а она тёмная.
Раньше содержимое окна не имело собственного фона, и тёмный текст ложился
на тёмную подложку — читать было нечем. Теперь под содержимым лежит белая
карточка, а вся палитра вынесена в константы и проверяется тестом на
контраст по WCAG: подобрать цвет «на глаз» в редакторе легко, а увидеть
результат на телефоне под солнцем — уже нет.
"""

from __future__ import annotations

import palette

# --------------------------------------------------------------------------- #
#  Реквизиты
# --------------------------------------------------------------------------- #

# Платёжная ссылка. Это то же самое, что зашито в статический QR банка:
# телефон открывает по ней приложение банка сразу на экране перевода, а
# сканировать собственный экран нельзя — поэтому ссылка удобнее QR.
#
# Здесь ссылка Озон Банка. Формат у каждого банка свой: НСПК выдаёт
# qr.nspk.ru/AS1000…, Озон — finance.ozon.ru/apps/sbp/ozonbankpay/…
# Список допустимых хостов — в PAY_HOSTS ниже. Пустая строка — кнопка не
# показывается.
#
# ВАЖНО: ссылку нельзя дописывать руками. В расширенном виде она содержит
# параметр crc — контрольную сумму по всей строке, и приложение банка её
# проверяет. Добавив к ссылке свою сумму (?sum=10000), вы получите отказ
# в оплате. Сумму человек указывает сам в приложении банка.
SBP_LINK = "https://finance.ozon.ru/apps/sbp/ozonbankpay/01a00bc5-dd2b-7b0b-875e-6805ddfff2ae"

# Старое имя той же настройки. Оставлено, чтобы не ломать чужие сборки.
SBP_QR_LINK = ""

# Картинка того же QR — лежит рядом с кодом. Нужна не себе, а другому
# человеку: со своего экрана QR не отсканируешь, а показать телефон
# приятелю в лесу или вывести код на большой экран — вполне.
QR_IMAGE = "donate-qr.png"

# Телефон для перевода по СБП, в формате +7XXXXXXXXXX.
SBP_PHONE = "+79261572965"

# Банк, который у вас основной в СБП. Название обязательно: в списке
# получателей человек выбирает банк сам, и без подсказки деньги легко
# уходят в другой банк, если номер привязан к нескольким.
SBP_BANK = "Озон Банк"

CARD = "2204 2402 0609 9725"
BANK = "Мир"

# --- Перевод по банковским реквизитам --------------------------------------
#
# Самый неудобный способ для отправителя, но единственный, который работает
# из любого банка и из бухгалтерии организации. Все числа ниже проверяются
# контрольными суммами при запуске окна: см. account_ok/corr_account_ok.

RECIPIENT = "Грезев Николай Витальевич"
ACCOUNT = "40914810300007365153"
BANK_NAME = "ООО «Озон Банк»"
BANK_NAME_FULL = "ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ «ОЗОН БАНК»"
BIC = "044525068"
CORR_ACCOUNT = "30101810645374525068"
BANK_INN = "9703077050"
BANK_KPP = "770301001"

# Назначение платежа. В приложении Озон Банка на этом месте написано
# «Переводы собственных средств» — эта формулировка рассчитана на пополнение
# своего же счёта. Донат приходит от постороннего человека, и писать ему
# «собственных средств» неверно: часть банков придирается к несовпадению
# назначения с характером операции. Нейтральная формулировка ниже проходит
# везде и не создаёт впечатления оплаты услуг.
PURPOSE = "Перевод денежных средств. НДС не облагается."

TITLE = "Поддержать проект"

INTRO = """Это приложение я делал для себя. Ходить с ним в лес оказалось
настолько спокойнее, что я решил им поделиться: польза здесь не только
грибная. Карта, маршрут и стрелка к машине работают без сети, и человек,
который в лесу теряется, в любой момент видит, где он и как выйти обратно.
Свои грибные места при этом никуда не деваются — они остаются на телефоне
и больше не забываются к следующему сезону."""

OUTRO = """Приложение бесплатное и таким останется. Рекламы, платных функций
и сбора данных о вас здесь нет и не будет.

Если пригодилось и хочется поддержать — любая сумма идёт на время: новые
виды грибов, уточнение модели по реальным находкам, офлайн-карты.

Спасибо всем, кто поддержал. И хорошего слоя."""


# --------------------------------------------------------------------------- #
#  Палитра и контраст
# --------------------------------------------------------------------------- #
#
# Цифры контраста — отношение яркостей по WCAG 2.1. Порог 4.5:1 для обычного
# текста и 3:1 для крупного взят не из любви к стандартам: окно открывают
# в лесу, с рук, на солнце и часто через плёнку с отпечатками пальцев.

# Цвета и арифметика контраста — из общего palette.py. Имена с суффиксом
# _HEX оставлены прежними: на них ссылается код окна и тесты.

BG_HEX = palette.CARD          # окно доната — белая карточка
INK_HEX = palette.INK
MUTED_HEX = palette.MUTED
ACCENT_HEX = palette.ACCENT
SOFT_HEX = palette.SOFT
ON_DARK_HEX = palette.ON_DARK

MIN_CONTRAST = palette.MIN_CONTRAST
MIN_CONTRAST_LARGE = palette.MIN_CONTRAST_LARGE

luminance = palette.luminance
contrast = palette.contrast


# --------------------------------------------------------------------------- #
#  Реквизиты в машинном виде
# --------------------------------------------------------------------------- #

def digits() -> str:
    """Номер карты без пробелов — для буфера обмена."""
    return CARD.replace(" ", "")


def phone_digits() -> str:
    """Телефон в виде +7XXXXXXXXXX: банки принимают именно так."""
    raw = "".join(c for c in SBP_PHONE if c.isdigit())
    if not raw:
        return ""
    if raw.startswith("8"):
        raw = "7" + raw[1:]
    return "+" + raw


def phone_pretty() -> str:
    """Телефон для показа: +7 999 123-45-67."""
    d = phone_digits()
    if len(d) != 12:
        return SBP_PHONE
    return f"{d[:2]} {d[2:5]} {d[5:8]}-{d[8:10]}-{d[10:]}"


def sbp_ready() -> bool:
    """Заполнены ли реквизиты СБП. Пока нет — раздел не показывается,
    чтобы человек не смотрел на пустое место."""
    return len(phone_digits()) == 12 and bool(SBP_BANK.strip())


# Хосты Системы быстрых платежей. qr.nspk.ru — статические и динамические
# коды, sub.nspk.ru — подписочные, b2b.cbrpay.ru — платежи между юрлицами.
# Хосты, с которых бывают платёжные ссылки, и чьи они. Название нужно не
# для красоты: кнопка «Оплатить через Озон Банк» честнее, чем «через СБП»,
# когда ссылка ведёт в конкретный банк, а не в общий переключатель НСПК.
#
# qr.nspk.ru и sub.nspk.ru — Система быстрых платежей, b2b.cbrpay.ru —
# расчёты между юрлицами, finance.ozon.ru — ссылки Озон Банка.
PAY_HOSTS = {
    "qr.nspk.ru": "СБП",
    "sub.nspk.ru": "СБП",
    "b2b.cbrpay.ru": "СБП",
    "finance.ozon.ru": "Озон Банк",
}

# Старое имя. Осталось у тестов и у чужих сборок.
SBP_HOSTS = tuple(PAY_HOSTS)

# Из чего может состоять путь после хоста. Пусто или один-два знака —
# это адрес заглавной страницы банка, а не перевода.
_PATH_OK = set("abcdefghijklmnopqrstuvwxyz0123456789-_./")


def link_host(url: str = None) -> str:
    u = ((SBP_LINK or SBP_QR_LINK) if url is None else url or "").strip()
    if not u.startswith("https://"):
        return ""
    return u[len("https://"):].split("/", 1)[0].split("?", 1)[0].lower()


def link_ok(url: str = None) -> bool:
    """Похожа ли строка на настоящую платёжную ссылку.

    Проверка нужна не от злого умысла, а от опечатки при переносе ссылки
    из письма банка: кнопка про деньги, ведущая на посторонний сайт, —
    худшее, что может случиться в этом окне.
    """
    u = ((SBP_LINK or SBP_QR_LINK) if url is None else url or "").strip()
    host = link_host(u)
    if host not in PAY_HOSTS:
        return False
    # После хоста обязателен путь: сам по себе qr.nspk.ru ведёт на страницу
    # НСПК, а finance.ozon.ru — на витрину банка, но не на перевод.
    path = u[len("https://") + len(host):].lstrip("/").split("?", 1)[0]
    if len(path) < 8:
        return False
    return set(path.lower()) <= _PATH_OK


def link_bank(url: str = None) -> str:
    """Чья это ссылка — для подписи на кнопке."""
    return PAY_HOSTS.get(link_host(url), "")


def sbp_link() -> str:
    """Платёжная ссылка СБП или пустая строка.

    Ссылка отдаётся ровно в том виде, в каком её выдал банк: параметры
    подписаны контрольной суммой crc, и любая правка делает её негодной.
    """
    url = (SBP_LINK or SBP_QR_LINK or "").strip()
    return url if link_ok(url) else ""


# --------------------------------------------------------------------------- #
#  Проверка банковских реквизитов
# --------------------------------------------------------------------------- #
#
# У номера счёта есть контрольный разряд, считающийся вместе с БИК банка.
# Проверка та же по смыслу, что Луна для карты: реквизиты переносят руками
# из приложения банка, и одна переставленная цифра означает, что перевод
# уйдёт в никуда, а узнается это через неделю от расстроенного человека.
#
# Алгоритм ЦБ: к 20 знакам счёта слева приписывается трёхзначный префикс —
# для счёта клиента это последние три цифры БИК, для корреспондентского
# счёта «0» плюс пятая и шестая цифры БИК. Полученные 23 знака умножаются
# на веса 7-1-3, от каждого произведения берётся последняя цифра, и сумма
# должна делиться на десять.

ACCOUNT_WEIGHTS = ((7, 1, 3) * 8)[:23]


def _account_checksum(prefix: str, account: str) -> bool:
    s = (prefix or "") + (account or "")
    if len(s) != 23 or not s.isdigit():
        return False
    return sum(int(c) * w % 10 for c, w in zip(s, ACCOUNT_WEIGHTS)) % 10 == 0


def bic_ok(bic: str = "") -> bool:
    """БИК: девять цифр, российские начинаются с 04."""
    b = bic or BIC
    return len(b) == 9 and b.isdigit() and b.startswith("04")


def account_ok(account: str = "", bic: str = "") -> bool:
    """Счёт получателя против БИК его банка."""
    b = bic or BIC
    if not bic_ok(b):
        return False
    return _account_checksum(b[-3:], account or ACCOUNT)


def corr_account_ok(account: str = "", bic: str = "") -> bool:
    """Корреспондентский счёт банка против того же БИК."""
    b = bic or BIC
    if not bic_ok(b):
        return False
    return _account_checksum("0" + b[4:6], account or CORR_ACCOUNT)


def inn_ok(inn: str = "") -> bool:
    """ИНН: десять знаков у организации, двенадцать у человека."""
    n = inn or BANK_INN
    if not n.isdigit():
        return False

    def digit(weights):
        return sum(int(n[i]) * w for i, w in enumerate(weights)) % 11 % 10

    if len(n) == 10:
        return int(n[9]) == digit((2, 4, 10, 3, 5, 9, 4, 6, 8))
    if len(n) == 12:
        return (int(n[10]) == digit((7, 2, 4, 10, 3, 5, 9, 4, 6, 8))
                and int(n[11]) == digit((3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)))
    return False


def requisites_ok() -> bool:
    """Сходятся ли все контрольные суммы. Не сходятся — раздел не показываем:
    неверные реквизиты хуже отсутствующих."""
    return (bool(RECIPIENT.strip()) and account_ok() and corr_account_ok()
            and inn_ok())


def requisites_block() -> str:
    """Реквизиты одним куском — для буфера обмена и для пересылки."""
    rows = [f"Получатель: {RECIPIENT}",
            f"Счёт: {ACCOUNT}",
            f"Банк: {BANK_NAME}",
            f"БИК: {BIC}",
            f"Корр. счёт: {CORR_ACCOUNT}",
            f"ИНН банка: {BANK_INN}",
            f"КПП банка: {BANK_KPP}",
            f"Назначение: {PURPOSE}"]
    return "\n".join(rows)


def luhn_ok(number: str = "") -> bool:
    """Контрольная сумма номера карты.

    Проверка живёт в коде, а не только в тестах, ради одного случая: если
    при смене реквизитов в номере окажется опечатка, кнопка копирования
    промолчит, а деньги уйдут неизвестно кому.
    """
    n = (number or digits()).replace(" ", "")
    if not n.isdigit() or len(n) not in (16, 18, 19):
        return False
    total, parity = 0, len(n) % 2
    for i, ch in enumerate(n):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def text() -> str:
    """Текст окна: СБП первым, карта следом."""
    hint = MUTED_HEX.lstrip("#")
    parts = [INTRO, ""]
    if sbp_link():
        parts += [f"[b]Оплата через {link_bank() or 'СБП'}[/b] — одно "
                  "касание, приложение банка откроется само:",
                  "",
                  f"[size=11sp][color={hint}]Сумму укажете там же. "
                  "Комиссии за перевод по СБП нет. Рядом — тот же QR: "
                  "его можно показать другому телефону.[/color][/size]",
                  ""]
    if sbp_ready():
        parts += ["[b]Перевод по СБП[/b] — по номеру телефона, три касания:",
                  "",
                  f"[b][size=19sp]{phone_pretty()}[/size][/b]",
                  f"Банк получателя: [b]{SBP_BANK}[/b]",
                  "",
                  # Шаги разделены знаком «»», а не стрелкой: стрелок в
                  # шрифте Kivy нет, и на телефоне подсказка про перевод
                  # выглядела как «Платежи □ По номеру телефона □».
                  f"[size=11sp][color={hint}]В приложении банка: Платежи » "
                  "По номеру телефона » вставить номер » выбрать банк "
                  "из списка.[/color][/size]",
                  ""]
    parts += [f"[b]Перевод на карту {BANK}[/b]" if (sbp_ready() or sbp_link())
              else f"Перевод на карту {BANK}:",
              "",
              f"[b][size=18sp]{CARD}[/size][/b]",
              ""]
    if requisites_ok():
        parts += ["[b]Перевод по реквизитам[/b] — если банк не умеет "
                  "переводить по номеру карты:",
                  "",
                  f"{RECIPIENT}",
                  f"Счёт: [b]{ACCOUNT}[/b]",
                  f"{BANK_NAME}, БИК [b]{BIC}[/b]",
                  f"Корр. счёт: {CORR_ACCOUNT}",
                  f"[size=11sp][color={hint}]ИНН банка {BANK_INN}, "
                  f"КПП {BANK_KPP}. Назначение платежа: "
                  f"{PURPOSE}[/color][/size]",
                  ""]
    parts += [OUTRO]
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
#  Взаимодействие с системой
# --------------------------------------------------------------------------- #

def copy(value: str) -> bool:
    """Кладёт строку в буфер обмена. False — если буфера нет."""
    if not value:
        return False
    try:
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(value)
        return True
    except Exception:                                             # noqa: BLE001
        return False


def qr_path() -> str:
    """Файл с картинкой QR рядом с кодом, или пустая строка.

    Проверка существования, а не просто имя: файл могли не положить в
    сборку, и кнопка «Показать QR», открывающая пустоту, хуже её отсутствия.
    """
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), QR_IMAGE)
    return path if QR_IMAGE and os.path.isfile(path) else ""


def show_qr():
    """QR во весь экран — чтобы его отсканировал другой телефон."""
    path = qr_path()
    if not path:
        return None
    from kivy.metrics import dp, sp
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.image import Image
    from kivy.uix.label import Label
    from kivy.uix.popup import Popup
    from kivy.utils import get_color_from_hex as hexc

    box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
    box.add_widget(Image(source=path, fit_mode="contain"))
    box.add_widget(Label(text=f"{link_bank() or 'СБП'} · {RECIPIENT}",
                         font_size=sp(12), color=hexc(MUTED_HEX),
                         size_hint_y=None, height=dp(20)))
    pop = Popup(title="Код для перевода", content=box, size_hint=(0.94, 0.8),
                title_size=sp(14), separator_color=hexc(ACCENT_HEX))
    close = Button(text="Закрыть", size_hint_y=None, height=dp(44),
                   font_size=sp(14), background_normal="",
                   background_color=hexc(SOFT_HEX), color=hexc(INK_HEX))
    close.bind(on_release=lambda *_: pop.dismiss())
    box.add_widget(close)
    pop.open()
    return pop


def open_url(url: str) -> bool:
    """Открывает ссылку системой: на Android — через Intent, иначе браузером.

    Ссылку СБП перехватывает приложение банка; если банков несколько,
    Android сам покажет выбор. Если ни одно приложение ссылку не заявило,
    открывается страница НСПК со списком банков — тоже рабочий путь.
    """
    if not url:
        return False
    try:
        from jnius import autoclass, cast
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity = cast("android.app.Activity", PythonActivity.mActivity)
        activity.startActivity(intent)
        return True
    except Exception:                                             # noqa: BLE001
        pass
    try:
        import webbrowser
        return bool(webbrowser.open(url))
    except Exception:                                             # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
#  Окно
# --------------------------------------------------------------------------- #

def show():
    """Открывает окно поддержки. Импорты Kivy внутри — чтобы модуль
    оставался пригодным для тестов на компьютере без Kivy."""
    from kivy.graphics import Color, RoundedRectangle
    from kivy.metrics import dp, sp
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.popup import Popup
    from kivy.uix.scrollview import ScrollView
    from kivy.utils import get_color_from_hex as hexc

    BG = hexc(BG_HEX)
    INK = hexc(INK_HEX)
    MUTED = hexc(MUTED_HEX)
    ACCENT = hexc(ACCENT_HEX)
    SOFT = hexc(SOFT_HEX)
    ON_DARK = hexc(ON_DARK_HEX)

    def fill(widget, color):
        """Своя подложка под содержимым: у Popup она тёмная, и без этого
        тёмный текст на ней не читается."""
        with widget.canvas.before:
            Color(*color)
            rect = RoundedRectangle(pos=widget.pos, size=widget.size,
                                    radius=[dp(6)])
        widget.bind(pos=lambda w, v: setattr(rect, "pos", v),
                    size=lambda w, v: setattr(rect, "size", v))

    box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
    fill(box, BG)

    sv = ScrollView(bar_width=dp(3))
    lbl = Label(text=text(), markup=True, color=INK, font_size=sp(13),
                halign="left", valign="top", size_hint_y=None,
                padding=(dp(10), dp(10)))
    lbl.bind(width=lambda w, x: setattr(w, "text_size", (x - dp(20), None)),
             texture_size=lambda w, t: setattr(w, "height", t[1] + dp(20)))
    sv.add_widget(lbl)
    box.add_widget(sv)

    # Строка состояния переносится по словам: сообщения тут длиннее одной
    # строки, а обрезанное на середине слово выглядит как сбой.
    status = Label(text="", font_size=sp(11), color=MUTED, halign="left",
                   valign="middle", size_hint_y=None, height=dp(20))
    status.bind(width=lambda w, x: setattr(w, "text_size", (x, None)),
                texture_size=lambda w, t: setattr(w, "height",
                                                  max(dp(20), t[1] + dp(4))))

    def announce(ok: bool, good: str, bad: str):
        status.text = good if ok else bad

    # --- главное действие: платёжная ссылка СБП ---------------------------
    link = sbp_link()
    if link:
        b_pay = Button(text=f"Оплатить через {link_bank() or 'СБП'}",
                       font_size=sp(16), bold=True,
                       size_hint_y=None, height=dp(52), background_normal="",
                       background_color=ACCENT, color=ON_DARK)
        b_pay.bind(on_release=lambda *_: announce(
            open_url(link),
            "Открываю приложение банка",
            "Не нашлось приложения для этой ссылки — скопируйте её"))
        box.add_widget(b_pay)

        row_link = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        b_link = Button(text="Скопировать ссылку", font_size=sp(13),
                        background_normal="", background_color=SOFT, color=INK)
        b_link.bind(on_release=lambda *_: announce(
            copy(link),
            "Ссылка в буфере — откройте её в приложении банка",
            "Не удалось скопировать ссылку"))
        row_link.add_widget(b_link)
        if qr_path():
            # Свой экран не отсканируешь, поэтому QR нужен не себе: показать
            # телефон другому человеку или вывести код на большой экран.
            b_qr = Button(text="Показать QR", font_size=sp(13),
                          background_normal="", background_color=SOFT, color=INK)
            b_qr.bind(on_release=lambda *_: show_qr())
            row_link.add_widget(b_qr)
        box.add_widget(row_link)

    # --- перевод по номеру телефона ---------------------------------------
    if sbp_ready():
        b_phone = Button(text="Скопировать телефон", font_size=sp(15),
                         bold=not link, size_hint_y=None, height=dp(48),
                         background_normal="",
                         background_color=SOFT if link else ACCENT,
                         color=INK if link else ON_DARK)
        b_phone.bind(on_release=lambda *_: announce(
            copy(phone_digits()),
            "Номер телефона в буфере — вставьте его в приложении банка",
            "Не удалось скопировать, введите вручную"))
        box.add_widget(b_phone)

    # --- карта -------------------------------------------------------------
    b_card = Button(text="Скопировать номер карты", font_size=sp(13),
                    size_hint_y=None, height=dp(42), background_normal="",
                    background_color=SOFT, color=INK)

    def copy_card(*_):
        if not luhn_ok():
            status.text = "Номер карты записан с ошибкой — не копирую"
            return
        announce(copy(digits()), "Номер карты в буфере обмена",
                 "Не удалось скопировать, введите вручную")

    b_card.bind(on_release=copy_card)
    box.add_widget(b_card)

    # --- реквизиты ---------------------------------------------------------
    if requisites_ok():
        row_req = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        b_acc = Button(text="Скопировать счёт", font_size=sp(13),
                       background_normal="", background_color=SOFT, color=INK)
        b_acc.bind(on_release=lambda *_: announce(
            copy(ACCOUNT),
            "Номер счёта в буфере обмена",
            "Не удалось скопировать, введите вручную"))
        b_all = Button(text="Все реквизиты", font_size=sp(13),
                       background_normal="", background_color=SOFT, color=INK)
        b_all.bind(on_release=lambda *_: announce(
            copy(requisites_block()),
            "Реквизиты в буфере — их можно вставить целиком",
            "Не удалось скопировать"))
        row_req.add_widget(b_acc)
        row_req.add_widget(b_all)
        box.add_widget(row_req)

    box.add_widget(status)

    pop = Popup(title=TITLE, content=box, size_hint=(0.94, 0.82),
                separator_color=ACCENT, title_size=sp(15))
    b_close = Button(text="Закрыть", font_size=sp(13), size_hint_y=None,
                     height=dp(40), background_normal="",
                     background_color=SOFT, color=INK)
    b_close.bind(on_release=lambda *_: pop.dismiss())
    box.add_widget(b_close)
    pop.open()
    return pop
