# -*- coding: utf-8 -*-
"""
walkjournal.py — журнал походов: что было в прошлые выезды.

Зачем. Грибные места запоминаются плохо, а решения принимаются по памяти:
«вроде в том ельнике в конце августа брали». Журнал отвечает на это точно —
куда ходили, сколько прошли, что нашли, и показывает снимки, по которым
спорное определение можно пересмотреть на трезвую голову.

Устройство простое: список походов сверху вниз от свежих к старым, касание
раскрывает карточку с маршрутом на карте и находками. Из карточки можно
выгрузить GPX и удалить поход.

Отдельно от journal.py: тот хранит наблюдения по видам для модели прогноза
(строка на вид за выход), этот показывает походы как они были. Одно
собирается из другого, но живут они разной жизнью — модель не интересуют
снимки, а человека не интересует балл обилия.
"""

from __future__ import annotations

import os
from datetime import datetime

from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.button import Button
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.utils import get_color_from_hex as hexc

import mushroom_forecast as engine
import markup
import palette
import backup
import photos as photos_mod
import track as track_mod
# Подписи живут в summary.py: там нет ни одного виджета, поэтому их можно
# проверять на машине без Kivy — например, на сборочной.
from summary import (index_line, personal_scale, season_line,
                     species_line, stats_line, when_text)
from finddialog import show_photo
from mapview import TileMap

INK = hexc(palette.INK)
MUTED = hexc(palette.MUTED)
CARD = hexc(palette.CARD)
SOFT = hexc(palette.SOFT)
ACCENT = hexc(palette.ACCENT)
RED = hexc(palette.RED)
TOUCH = dp(48)
GPX_MIME = "application/gpx+xml"
#: Миниатюра в строке списка: список листают глазами, а снимок
#: узнаётся быстрее, чем читается название места.
ROW_THUMB = dp(56)
THUMB = dp(72)

def _fill(widget, color):
    with widget.canvas.before:
        Color(*color)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(pos=lambda w, v: setattr(rect, "pos", v),
                size=lambda w, v: setattr(rect, "size", v))


def _wrapping(label):
    label.bind(width=lambda w, x: setattr(w, "text_size", (x, None)),
               texture_size=lambda w, t: setattr(w, "height", t[1]))
    label.size_hint_y = None
    label.halign = "left"
    label.valign = "top"
    return label


# --------------------------------------------------------------------------- #
#  Карточка одного похода
# --------------------------------------------------------------------------- #

class WalkCard(Popup):
    """Один поход целиком: маршрут на карте, находки, заметки, снимки."""

    def __init__(self, walk, on_change=None, **kw):
        self.walk = walk
        self._on_change = on_change

        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        _fill(box, CARD)

        head = _wrapping(Label(text=f"[b]{markup.esc(walk.place or 'без названия')}[/b]\n"
                                    f"{stats_line(walk)}",
                               markup=True, font_size=sp(13), color=INK))
        box.add_widget(head)

        # Что модель обещала на этот день. Строка стоит рядом с итогами
        # похода, а не в отдельном разделе: обещание и результат имеют
        # смысл только вместе, порознь это два бесполезных числа.
        forecast = index_line(walk)
        if forecast:
            box.add_widget(_wrapping(Label(text=forecast, font_size=sp(11),
                                           color=MUTED)))

        # Карта с маршрутом. Центр — первая точка: конец маршрута обычно
        # совпадает с началом, а вот начало всегда осмысленно.
        if walk.points:
            first = walk.points[0]
            self.map = TileMap(lat=first.lat, lon=first.lon, zoom=14)
            self.map.walk = walk
            self.map.marker = None
            self.map.size_hint_y = None
            self.map.height = dp(220)
            box.add_widget(self.map)

        sv = ScrollView()
        inner = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8),
                          padding=(0, dp(4)))
        inner.bind(minimum_height=inner.setter("height"))
        for find in walk.finds:
            inner.add_widget(self._find_block(find))
        if not walk.finds:
            inner.add_widget(_wrapping(Label(text="Находок не отмечено",
                                             font_size=sp(12), color=MUTED)))
        sv.add_widget(inner)
        box.add_widget(sv)

        self.status = _wrapping(Label(text="", font_size=sp(11), color=MUTED))
        box.add_widget(self.status)

        btns = BoxLayout(size_hint_y=None, height=TOUCH, spacing=dp(6))
        for text, action, color in (("Выгрузить GPX", self._export, INK),
                                    ("Удалить", self._confirm_delete, RED),
                                    ("Закрыть", self.dismiss, INK)):
            b = Button(text=text, font_size=sp(13), background_normal="",
                       background_color=SOFT, color=color, halign="center",
                       valign="middle", shorten=True, shorten_from="right")
            b.bind(size=lambda w, v: setattr(w, "text_size", v))
            b.bind(on_release=lambda _b, a=action: a())
            btns.add_widget(b)
        box.add_widget(btns)

        super().__init__(title=when_text(walk), content=box,
                         size_hint=(0.96, 0.92), title_size=sp(14),
                         separator_color=ACCENT, **kw)

    def _find_block(self, find):
        row = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        row.bind(minimum_height=row.setter("height"))

        name = (engine.SPECIES[find.species].name
                if find.species in engine.SPECIES else "метка")
        head = f"[b]{name}[/b]"
        if find.count > 1:
            head += f" · {find.count} шт."
        head += f"  [size=10sp][color={palette.MUTED.lstrip('#')}]" \
                f"{datetime.fromtimestamp(find.t):%H:%M}[/color][/size]"
        row.add_widget(_wrapping(Label(text=head, markup=True, font_size=sp(13),
                                       color=INK)))
        if find.note:
            row.add_widget(_wrapping(Label(text=find.note, font_size=sp(12),
                                           color=MUTED)))
        shown = [n for n in find.photos if photos_mod.exists(n)]
        if shown:
            strip = BoxLayout(size_hint=(None, None), height=THUMB, spacing=dp(4))
            strip.bind(minimum_width=strip.setter("width"))
            for photo in shown:
                img = AsyncImage(source=photos_mod.path_for(photo),
                                 size_hint=(None, None), size=(THUMB, THUMB),
                                 fit_mode="contain")
                img.bind(on_touch_down=lambda w, touch, n=photo:
                         bool(w.collide_point(*touch.pos)) and show_photo(n))
                strip.add_widget(img)
            holder = ScrollView(size_hint_y=None, height=THUMB,
                                do_scroll_y=False, bar_width=0)
            holder.add_widget(strip)
            row.add_widget(holder)
        return row

    # --- действия -----------------------------------------------------------
    def _export(self):
        """Трек в GPX — и сразу человеку в руки.

        Раньше файл писался во внутренний каталог приложения и оттуда
        сообщался путь вида /data/user/0/ru.grezev.../tracks/2026-08-01.gpx.
        Достать его человек не мог ничем: это закрытая память приложения.
        Кнопка формально работала, а по сути нет.

        Теперь тот же файл кладётся в общие «Загрузки» (там его видит любой
        проводник и компьютер по USB) и передаётся системе — оттуда трек
        уходит другу в мессенджер или открывается в OsmAnd. Механика та же,
        что у резервной копии, поэтому и живёт в backup.
        """
        try:
            path = track_mod.export_gpx(self.walk)
        except (OSError, ValueError) as e:
            self.status.text = f"Не выгрузилось: {e}"
            return
        if not backup.on_android():
            self.status.text = f"Сохранено: {path}"
            return
        try:
            uri = backup.publish(path, mime=GPX_MIME)
        except Exception as e:                                    # noqa: BLE001
            self.status.text = f"Не выгрузилось: {type(e).__name__}: {e}"[:120]
            return
        name = os.path.basename(path)
        if uri is None:
            # Android 9 и старше: content-ссылки нет, отдать файл системе
            # нельзя — но в «Загрузках» он лежит, и это уже не тупик.
            self.status.text = f"Трек сохранён в «Загрузки»: {name}"
            return
        self.status.text = f"Трек в «Загрузках» ({name}). Выберите, куда отправить."
        backup.share(uri, subject=f"Трек: {self.walk.place or 'поход'}",
                     text="Маршрут в формате GPX — открывается в OsmAnd, "
                          "Google Earth и других картах.",
                     mime=GPX_MIME, title="Куда отправить трек")

    def _confirm_delete(self):
        """Удаление в два шага: поход не восстановить, а кнопка рядом с «Закрыть»."""
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        _fill(box, CARD)
        box.add_widget(_wrapping(Label(
            text=f"Удалить поход «{self.walk.place or 'без названия'}» "
                 f"от {when_text(self.walk)}?\n\n"
                 f"Вместе с ним пропадут заметки и "
                 f"{len(self.walk.photo_names())} снимков. Отменить нельзя.",
            font_size=sp(13), color=INK)))
        row = BoxLayout(size_hint_y=None, height=TOUCH, spacing=dp(6))
        ask = Popup(title="Удаление похода", content=box, size_hint=(0.9, 0.42),
                    title_size=sp(14), separator_color=RED)
        b_no = Button(text="Оставить", font_size=sp(14), bold=True,
                      background_normal="", background_color=ACCENT)
        b_no.bind(on_release=lambda *_: ask.dismiss())
        b_yes = Button(text="Удалить", font_size=sp(13), background_normal="",
                       background_color=SOFT, color=RED)
        b_yes.bind(on_release=lambda *_: (ask.dismiss(), self._delete()))
        row.add_widget(b_no)
        row.add_widget(b_yes)
        box.add_widget(row)
        ask.open()

    def _delete(self):
        track_mod.delete(self.walk)
        self.dismiss()
        if self._on_change:
            self._on_change()


# --------------------------------------------------------------------------- #
#  Список походов
# --------------------------------------------------------------------------- #

class WalkJournal(Popup):
    """Все сохранённые походы, свежие сверху."""

    def __init__(self, **kw):
        self.box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        _fill(self.box, CARD)

        self.total = _wrapping(Label(text="", font_size=sp(12), color=MUTED))
        self.box.add_widget(self.total)

        self.sv = ScrollView()
        self.list = BoxLayout(orientation="vertical", size_hint_y=None,
                              spacing=dp(6))
        self.list.bind(minimum_height=self.list.setter("height"))
        self.sv.add_widget(self.list)
        self.box.add_widget(self.sv)

        # Копия живёт здесь, а не в настройках: о ней вспоминают, глядя на
        # накопленное, а не листая список переключателей.
        row = BoxLayout(size_hint_y=None, height=TOUCH, spacing=dp(6))
        b_backup = Button(text="Резервная копия", font_size=sp(14),
                          background_normal="", background_color=SOFT,
                          color=INK)
        b_backup.bind(on_release=lambda *_: self._backup())
        close = Button(text="Закрыть", font_size=sp(14), background_normal="",
                       background_color=SOFT, color=INK)
        close.bind(on_release=lambda *_: self.dismiss())
        row.add_widget(b_backup)
        row.add_widget(close)
        self.box.add_widget(row)

        super().__init__(title="Журнал походов", content=self.box,
                         size_hint=(0.96, 0.9), title_size=sp(15),
                         separator_color=ACCENT, **kw)
        self.reload()

    def _backup(self):
        import backupscreen
        backupscreen.show()

    def reload(self):
        self.list.clear_widgets()
        try:
            walks = track_mod.load_all()
        except OSError:
            walks = []
        if not walks:
            self.total.text = ""
            self.list.add_widget(_wrapping(Label(
                text="Походов пока нет.\n\nНажмите «В лес» на главном экране — "
                     "маршрут запишется сам, а находки можно отмечать кнопкой "
                     "«Нашёл!».",
                font_size=sp(13), color=MUTED)))
            return

        km = sum(w.distance for w in walks) / 1000.0
        finds = sum(len(w.finds) for w in walks)
        self.total.text = (f"Походов {len(walks)}, пройдено "
                           f"{km:.1f} км".replace(".", ",")
                           + f", находок {finds}, снимки занимают "
                             f"{photos_mod.size_text()}")
        # Своя шкала: с какого индекса походы этого человека были удачными.
        # У каждого леса она своя, и узнать её можно только так — из
        # собственных выездов, а не из общего прогноза.
        scale = personal_scale(walks)
        if scale:
            self.total.text += "\n" + scale
        # Итог сезона — то, ради чего журнал открывают зимой. Всё это
        # посчитано и по отдельным походам, но чтобы понять, каким был
        # сентябрь, человеку пришлось бы листать список и складывать в уме.
        # Итог сезона показывается, только если есть с чем его сравнивать.
        # У человека первого года он слово в слово повторял бы строку выше:
        # те же походы, те же километры, те же находки.
        import time as _time

        year = _time.localtime().tm_year
        if any(_time.localtime(w.started).tm_year != year for w in walks):
            season = season_line(walks)
            if season:
                self.total.text += "\n" + season

        for walk in walks:
            self.list.add_widget(self._row(walk))

    def _row(self, walk):
        """Строка списка.

        Kivy-кнопка — не контейнер, вложенные виджеты она не размещает,
        поэтому подпись собирается в одну размеченную строку, а высота
        считается по её тексту. У похода с четырьмя видами находок подпись
        длиннее, чем у пустого, и обрезать её нельзя: именно ради неё
        журнал и открывают.
        """
        hint = palette.MUTED.lstrip("#")
        # Дата ушла из первой строки к остальным цифрам: рядом с миниатюрой
        # места на подпись меньше, и «Ельник у Гряды 17 / августа» ломалось
        # пополам ровно посередине даты.
        rows = [f"[b]{markup.esc(walk.place or 'без названия')}[/b]"]
        species = species_line(walk)
        if species:
            rows.append(f"[size=12sp]{species}[/size]")
        rows.append(f"[size=11sp][color={hint}]{when_text(walk)} · "
                    f"{stats_line(walk)}[/color][/size]")

        btn = Button(text="\n".join(rows), markup=True, font_size=sp(14),
                     color=INK, background_normal="", background_color=SOFT,
                     halign="left", valign="middle", size_hint_y=None,
                     height=dp(78), padding=(dp(10), dp(8)))
        btn.bind(width=lambda w, x: setattr(w, "text_size", (x - dp(20), None)),
                 texture_size=lambda w, t: setattr(w, "height",
                                                   max(dp(64), t[1] + dp(18))))
        btn.bind(on_release=lambda *_: WalkCard(walk, on_change=self.reload).open())

        shot = self._first_photo(walk)
        if shot is None:
            return btn
        # Снимок кладётся ПОВЕРХ кнопки, а не рядом с ней. Соседний виджет
        # съел бы полсотни точек, на которых нажатие не работает, — а строка
        # должна нажиматься целиком, как и всё остальное в приложении.
        # Картинка касания не перехватывает: Image их не обрабатывает и
        # пропускает вниз, к кнопке.
        #
        # Во FloatLayout ребёнку нужны и pos_hint, и size_hint: без них
        # кнопка встаёт в угол окна собственного размера, а строки списка
        # наезжают друг на друга.
        btn.padding = (dp(14) + ROW_THUMB, dp(8))
        btn.size_hint = (1, 1)
        btn.pos_hint = {"x": 0, "y": 0}
        btn.bind(width=lambda w, x: setattr(w, "text_size",
                                            (x - dp(24) - ROW_THUMB, None)))

        holder = FloatLayout(size_hint_y=None,
                             height=max(dp(64), btn.texture_size[1] + dp(18)))
        btn.bind(texture_size=lambda w, t: setattr(
            holder, "height", max(dp(64), t[1] + dp(18))))
        img = AsyncImage(source=shot, fit_mode="cover", size_hint=(None, None),
                         size=(ROW_THUMB, ROW_THUMB))
        holder.add_widget(btn)
        holder.add_widget(img)

        def place(*_):
            img.pos = (holder.x + dp(8), holder.center_y - ROW_THUMB / 2)

        holder.bind(pos=place, size=place)
        place()
        return holder

    @staticmethod
    def _first_photo(walk):
        """Первый уцелевший снимок похода или None.

        Проверка существования не лишняя: снимок могли удалить из галереи
        телефона, а ссылка на него в походе осталась. Пустой чёрный
        прямоугольник в списке выглядит как поломка.
        """
        for name in walk.photo_names():
            if photos_mod.exists(name):
                return photos_mod.path_for(name)
        return None


def show():
    """Открывает журнал походов."""
    journal = WalkJournal()
    journal.open()
    return journal
