# -*- coding: utf-8 -*-
"""
premium_screen.py — окно «Без рекламы за 300 руб.».

Два пути к одной цели, и честно про оба.

RuStore-покупка — то, что должно быть основным путём, но сегодня не
работает: `billing.is_available()` отвечает False, пока модуль не доведён
до конца на реальном телефоне (см. billing.py — там расписано, чего не
хватает). Кнопка появляется на экране, только когда `is_available()` вернёт
True; до тех пор её попросту нет, а не есть, но не нажимается.

Код по СБП — рабочий путь уже сегодня. Экран прямо говорит, что это не
защита от списывания: секрет живёт в самом приложении, и человек, который
захочет, найдёт способ обойтись без оплаты. Это тот же порядок вещей, что
у любого маленького приложения без сервера — плата не техническая мера, а
что-то вроде честного вклада в работу, которую готовы поддержать.
"""

from __future__ import annotations

from kivy.clock import mainthread
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.utils import get_color_from_hex as hexc

import ads
import billing
import buzz
import donate
import legal
import licensecode
import palette
import premium
import theme
import uikit


def _apply_palette():
    global INK, MUTED, CARD, ACCENT, RED, SOFT
    INK = hexc(palette.INK)
    MUTED = hexc(palette.MUTED)
    CARD = hexc(palette.CARD)
    ACCENT = hexc(palette.ACCENT)
    RED = hexc(palette.RED)
    SOFT = hexc(palette.SOFT)


_apply_palette()
theme.register(_apply_palette)

TOUCH = dp(48)


def _fill(widget, color):
    """Скруглённая заливка — сама реализация в uikit.fill_rounded()."""
    uikit.fill_rounded(widget, color)


def _wrapping(label):
    label.size_hint_y = None
    label.halign = "left"
    label.valign = "top"
    label.bind(width=lambda w, x: setattr(w, "text_size", (x, None)),
              texture_size=lambda w, t: setattr(w, "height", t[1]))
    return label


class PremiumScreen(Popup):
    """Окно покупки. on_unlocked() зовётся один раз, при успехе — не раньше."""

    def __init__(self, on_unlocked=None, **kw):
        self.on_unlocked = on_unlocked
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        _fill(box, CARD)

        if premium.is_premium():
            box.add_widget(_wrapping(Label(
                text="Реклама уже выключена — спасибо.",
                font_size=sp(14), color=INK)))
            close = Button(text="Закрыть", size_hint_y=None, height=TOUCH,
                           font_size=sp(14), background_normal="",
                           background_color=SOFT, color=INK)
            close.bind(on_release=lambda *_: self.dismiss())
            box.add_widget(close)
            super().__init__(title="Без рекламы", content=box,
                             size_hint=(0.9, 0.4), title_size=sp(15),
                             separator_color=ACCENT, **kw)
            return

        sv = ScrollView()
        inner = BoxLayout(orientation="vertical", size_hint_y=None,
                          spacing=dp(10))
        inner.bind(minimum_height=inner.setter("height"))

        inner.add_widget(_wrapping(Label(
            text="300 руб. — и реклама на главном экране пропадает насовсем, "
                 "на этом телефоне. В походе рекламы и так никогда не было.",
            font_size=sp(13), color=INK)))

        if billing.is_available():
            b_rustore = Button(text="Купить через RuStore — 300 руб.",
                               size_hint_y=None, height=TOUCH, bold=True,
                               font_size=sp(14), background_normal="",
                               background_color=ACCENT, color=(1, 1, 1, 1))
            b_rustore.bind(on_release=lambda *_: self._buy_rustore())
            uikit.press_feedback(b_rustore, ACCENT)
            inner.add_widget(b_rustore)
            inner.add_widget(_wrapping(Label(
                text="Или переводом — если RuStore недоступен:",
                font_size=sp(12), color=MUTED)))

        # --- путь по СБП ---
        if donate.sbp_ready():
            b_pay = Button(text=f"Оплатить {donate.phone_pretty()} · СБП",
                           size_hint_y=None, height=TOUCH, font_size=sp(14),
                           background_normal="", background_color=SOFT,
                           color=INK)
            b_pay.bind(on_release=lambda *_: donate.open_url(donate.sbp_link()))
            uikit.press_feedback(b_pay, SOFT)
            inner.add_widget(b_pay)

        inner.add_widget(_wrapping(Label(
            text="После перевода пришлите код устройства человеку, у "
                 "которого покупали приложение, — взамен придёт код "
                 "разблокировки.",
            font_size=sp(12), color=MUTED)))

        code_row = BoxLayout(size_hint_y=None, height=TOUCH, spacing=dp(6))
        self.device_label = Label(text=licensecode.device_code(),
                                  font_size=sp(16), bold=True, color=INK)
        b_copy = Button(text="Скопировать", size_hint_x=None, width=dp(110),
                        font_size=sp(12), background_normal="",
                        background_color=SOFT, color=INK)
        b_copy.bind(on_release=lambda *_: self._copy_device_code())
        code_row.add_widget(self.device_label)
        code_row.add_widget(b_copy)
        inner.add_widget(code_row)

        inner.add_widget(_wrapping(Label(text="Код разблокировки:",
                                         font_size=sp(12), color=MUTED)))
        entry_row = BoxLayout(size_hint_y=None, height=TOUCH, spacing=dp(6))
        self.entry = TextInput(text="", multiline=False, font_size=sp(16),
                               size_hint_y=None, height=TOUCH,
                               padding=(dp(10), dp(12)))
        b_apply = Button(text="Ввести", size_hint_x=None, width=dp(90),
                         font_size=sp(14), background_normal="",
                         background_color=ACCENT, color=(1, 1, 1, 1))
        b_apply.bind(on_release=lambda *_: self._apply_code())
        uikit.press_feedback(b_apply, ACCENT)
        entry_row.add_widget(self.entry)
        entry_row.add_widget(b_apply)
        inner.add_widget(entry_row)

        self.status = _wrapping(Label(text="", font_size=sp(12), color=MUTED))
        inner.add_widget(self.status)

        inner.add_widget(_wrapping(Label(
            text="Это не защита от списывания — код проверяется прямо на "
                 "телефоне, без сервера. Это способ честно поддержать "
                 "работу над приложением, а не замок.",
            font_size=sp(11), color=MUTED)))

        legal_row = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(6))
        b_privacy = Button(text="Конфиденциальность", font_size=sp(11),
                           background_normal="", background_color=(0, 0, 0, 0),
                           color=MUTED)
        b_privacy.bind(on_release=lambda *_: legal.show_privacy())
        b_terms = Button(text="Условия использования", font_size=sp(11),
                         background_normal="", background_color=(0, 0, 0, 0),
                         color=MUTED)
        b_terms.bind(on_release=lambda *_: legal.show_terms())
        legal_row.add_widget(b_privacy)
        legal_row.add_widget(b_terms)
        inner.add_widget(legal_row)

        sv.add_widget(inner)
        box.add_widget(sv)

        close = Button(text="Закрыть", size_hint_y=None, height=TOUCH,
                       font_size=sp(14), background_normal="",
                       background_color=SOFT, color=INK)
        close.bind(on_release=lambda *_: self.dismiss())
        box.add_widget(close)

        super().__init__(title="Без рекламы за 300 руб.", content=box,
                         size_hint=(0.94, 0.9), title_size=sp(15),
                         separator_color=ACCENT, **kw)

    def _copy_device_code(self):
        if donate.copy(licensecode.device_code()):
            self.status.text = "Код устройства скопирован."

    def _apply_code(self):
        if licensecode.verify(self.entry.text):
            premium.unlock(source="manual")
            self._unlocked()
        else:
            self.status.text = "Код не подошёл — проверьте, не потерялся ли символ."

    def _buy_rustore(self):
        self.status.text = "Открываю RuStore…"
        billing.purchase(self._rustore_done)

    @mainthread
    def _rustore_done(self, ok, error):
        if ok:
            premium.unlock(source="rustore")
            self._unlocked()
        else:
            self.status.text = f"Не получилось: {error}" if error else "Не получилось."

    def _unlocked(self):
        ads.detach()
        buzz.tap()
        self.status.text = "Готово — реклама выключена."
        if self.on_unlocked:
            self.on_unlocked()
        self.dismiss()


def show(on_unlocked=None):
    scr = PremiumScreen(on_unlocked=on_unlocked)
    uikit.open_soft(scr)
    return scr
