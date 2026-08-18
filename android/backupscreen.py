# -*- coding: utf-8 -*-
"""
backupscreen.py — окно резервной копии: собрать, отправить, восстановить.

Отделено от backup.py по той же причине, по какой summary отделён от
walkjournal: сама работа с архивом не знает про Kivy и проверяется на
сборочной машине, где экрана нет.

Главная забота этого окна — не обмануть. Кнопка «Отправить» не отправляет
письмо: она отдаёт архив системе, и человек выбирает почту, облако или
мессенджер сам. Написать на ней «Отправить на почту» было бы удобнее и
неправдой, а неправда здесь дорогая: человек решит, что копия ушла, и
перестанет о ней думать.
"""

from __future__ import annotations

import os
import tempfile
import threading

from kivy.clock import mainthread
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.utils import get_color_from_hex as hexc

import backup
import palette

INK = hexc(palette.INK)
MUTED = hexc(palette.MUTED)
CARD = hexc(palette.CARD)
ACCENT = hexc(palette.ACCENT)
SOFT = hexc(palette.SOFT)
RED = hexc(palette.RED)
TOUCH = dp(48)


def _fill(widget, color):
    with widget.canvas.before:
        Color(*color)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(pos=lambda w, v: setattr(rect, "pos", v),
                size=lambda w, v: setattr(rect, "size", v))


def _wrapping(label):
    label.size_hint_y = None
    label.halign = "left"
    label.valign = "top"
    label.bind(width=lambda w, x: setattr(w, "text_size", (x, None)),
               texture_size=lambda w, t: setattr(w, "height", t[1]))
    return label


class BackupScreen(Popup):
    """Окно резервной копии."""

    def __init__(self, **kw):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        _fill(box, CARD)

        sv = ScrollView()
        inner = BoxLayout(orientation="vertical", size_hint_y=None,
                          spacing=dp(8))
        inner.bind(minimum_height=inner.setter("height"))

        inner.add_widget(_wrapping(Label(
            text="Журнал, походы, места и снимки хранятся только на этом "
                 "телефоне. Копия — единственный способ их не потерять.",
            font_size=sp(13), color=INK)))

        self.info = _wrapping(Label(text="Считаю…", font_size=sp(12),
                                    color=MUTED))
        inner.add_widget(self.info)

        self.b_records = self._button("Копия без снимков", self._make_records,
                                      bold=True)
        self.b_full = self._button("Копия со снимками", self._make_full)
        inner.add_widget(self.b_records)
        inner.add_widget(self.b_full)

        inner.add_widget(_wrapping(Label(
            text="Готовый файл кладётся в «Загрузки» — оттуда его видно "
                 "любым проводником и с компьютера по USB. Сразу после "
                 "этого открывается выбор, куда его отправить: почта, "
                 "облако, мессенджер. Письмо уходит из вашей почтовой "
                 "программы — приложение не знает ни вашего ящика, ни "
                 "пароля и не отправляет ничего само.",
            font_size=sp(11), color=MUTED)))

        inner.add_widget(_wrapping(Label(text="Восстановление",
                                         font_size=sp(13), color=INK)))
        inner.add_widget(_wrapping(Label(
            text="Выберите файл копии. Существующие записи не затираются: "
                 "то, что уже есть на телефоне, остаётся как есть.",
            font_size=sp(11), color=MUTED)))
        self.b_restore = self._button("Восстановить из файла", self._restore)
        inner.add_widget(self.b_restore)

        self.status = _wrapping(Label(text="", font_size=sp(12), color=MUTED))
        inner.add_widget(self.status)

        sv.add_widget(inner)
        box.add_widget(sv)

        close = Button(text="Закрыть", size_hint_y=None, height=TOUCH,
                       font_size=sp(14), background_normal="",
                       background_color=SOFT, color=INK)
        close.bind(on_release=lambda *_: self.dismiss())
        box.add_widget(close)

        super().__init__(title="Резервная копия", content=box,
                         size_hint=(0.94, 0.9), title_size=sp(15),
                         separator_color=ACCENT, **kw)
        self._refresh_info()

    def _button(self, text, action, bold=False):
        b = Button(text=text, size_hint_y=None, height=TOUCH, font_size=sp(14),
                   bold=bold, background_normal="",
                   background_color=ACCENT if bold else SOFT,
                   color=hexc("#FFFFFF") if bold else INK)
        b.bind(on_release=lambda *_: action())
        return b

    # --- размеры ------------------------------------------------------------
    def _refresh_info(self):
        try:
            full = backup.contents(with_photos=True)
            light = backup.contents(with_photos=False)
        except OSError as e:
            self.info.text = f"Не читается каталог данных: {e}"
            return
        self.info.text = (
            f"Записей {light['records']}, снимков {full['photos']}.\n"
            f"Без снимков — {backup.size_text(light['bytes'])}, "
            f"со снимками — {backup.size_text(full['bytes'])}.")
        self.b_records.text = (f"Копия без снимков · "
                               f"{backup.size_text(light['bytes'])}")
        self.b_full.text = (f"Копия со снимками · "
                            f"{backup.size_text(full['bytes'])}")
        if not full["fits_mail"]:
            # Предупреждение до нажатия, а не после: узнать про предел
            # вложения от почтовой программы, когда архив уже собран, —
            # значит потратить минуты и место впустую.
            self.info.text += (f"\nПо почте обычно проходит до "
                               f"{backup.MAIL_LIMIT_MB:.0f} МБ: копию со "
                               f"снимками лучше сохранить в «Загрузки» или "
                               f"отправить в облако.")

    # --- сборка -------------------------------------------------------------
    def _make_records(self):
        self._make(with_photos=False)

    def _make_full(self):
        self._make(with_photos=True)

    def _make(self, with_photos):
        self._busy(True)
        self.status.text = "Собираю копию…"
        threading.Thread(target=self._work, args=(with_photos,),
                         daemon=True).start()

    def _work(self, with_photos):
        """Сборка в потоке: сотня снимков жмётся секундами, а экран должен
        оставаться живым — иначе Android покажет «приложение не отвечает»."""
        try:
            path = os.path.join(tempfile.gettempdir(), backup.archive_name())
            info = backup.create(path, with_photos=with_photos)
            uri = None
            if backup.on_android():
                uri = backup.publish(path)
            self._done(info, path, uri, "")
        except BaseException as e:                                # noqa: BLE001
            self._done(None, "", None, f"{type(e).__name__}: {e}"[:120])

    @mainthread
    def _done(self, info, path, uri, error):
        self._busy(False)
        if error:
            self.status.text = "Не получилось: " + error
            return
        size = backup.size_text(info["bytes"])
        if not backup.on_android():
            self.status.text = f"Копия собрана: {path} ({size})"
            return
        if uri is None:
            # Android 9 и старше: ссылки нет, отдать файл системе нельзя.
            self.status.text = (f"Копия сохранена в «Загрузки» ({size}). "
                                f"Отправить её можно из проводника: "
                                f"{os.path.basename(path)}")
            return
        self.status.text = f"Копия в «Загрузках» ({size}). Выберите, куда отправить."
        backup.share(uri, text="Резервная копия наблюдений грибника",
                     title="Куда отправить копию")

    def _busy(self, on):
        for b in (self.b_records, self.b_full, self.b_restore):
            b.disabled = on

    # --- восстановление -----------------------------------------------------
    def _restore(self):
        if not backup.on_android():
            self.status.text = "Выбор файла доступен только на телефоне."
            return
        self.status.text = "Выберите файл копии…"
        backup.pick(self._picked)

    @mainthread
    def _picked(self, path, error):
        if error:
            self.status.text = "Не получилось: " + error
            return
        if not path:
            self.status.text = ""                 # передумал — не ошибка
            return
        try:
            info = backup.inspect(path)
        except backup.NotOurs as e:
            self.status.text = str(e)
            return
        self._confirm(path, info)

    def _confirm(self, path, info):
        """Подтверждение с описью: что именно сейчас развернётся.

        Восстановление обычно идёт на пустой телефон, но бывает и поверх
        живых данных. Человек должен видеть, сколько походов и снимков в
        копии, прежде чем соглашаться.
        """
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        _fill(box, CARD)
        box.add_widget(_wrapping(Label(
            text=f"В копии походов {info.get('walks', 0)}, "
                 f"снимков {info.get('photos', 0)}.\n"
                 f"Записи, которые уже есть на телефоне, останутся как есть.",
            font_size=sp(13), color=INK)))
        row = BoxLayout(size_hint_y=None, height=TOUCH, spacing=dp(6))
        ask = Popup(title="Восстановить?", content=box, size_hint=(0.9, 0.45),
                    title_size=sp(14), separator_color=ACCENT)
        b_no = Button(text="Отмена", font_size=sp(14), background_normal="",
                      background_color=SOFT, color=INK)
        b_no.bind(on_release=lambda *_: ask.dismiss())
        b_yes = Button(text="Восстановить", font_size=sp(14), bold=True,
                       background_normal="", background_color=ACCENT)
        b_yes.bind(on_release=lambda *_: (ask.dismiss(), self._do_restore(path)))
        row.add_widget(b_no)
        row.add_widget(b_yes)
        box.add_widget(row)
        ask.open()

    def _do_restore(self, path):
        try:
            res = backup.restore(path)
        except (backup.NotOurs, OSError) as e:
            self.status.text = f"Не получилось: {e}"
            return
        self.status.text = (f"Восстановлено файлов: {res['added']}"
                            + (f", пропущено уже имевшихся: {res['skipped']}"
                               if res["skipped"] else ""))
        self._refresh_info()


def show():
    scr = BackupScreen()
    scr.open()
    return scr
