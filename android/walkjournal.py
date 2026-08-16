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

from datetime import datetime

from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.utils import get_color_from_hex as hexc

import mushroom_forecast as engine
import palette
import photos as photos_mod
import track as track_mod
from finddialog import show_photo
from mapview import TileMap

INK = hexc(palette.INK)
MUTED = hexc(palette.MUTED)
CARD = hexc(palette.CARD)
SOFT = hexc(palette.SOFT)
ACCENT = hexc(palette.ACCENT)
RED = hexc(palette.RED)
TOUCH = dp(48)
THUMB = dp(72)

RU_MONTH = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
            "августа", "сентября", "октября", "ноября", "декабря")


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
#  Человеческие подписи
# --------------------------------------------------------------------------- #

def when_text(walk) -> str:
    """«16 августа, 9:40» — год добавляется только если он не нынешний."""
    d = datetime.fromtimestamp(walk.started)
    text = f"{d.day} {RU_MONTH[d.month - 1]}"
    if d.year != datetime.now().year:
        text += f" {d.year}"
    return f"{text}, {d:%H:%M}"


def duration_text(seconds: float) -> str:
    """«2 ч 15 мин», «40 мин». Секунды в лесу никого не интересуют."""
    minutes = int(max(0.0, seconds) // 60)
    if minutes < 60:
        return f"{minutes} мин"
    return f"{minutes // 60} ч {minutes % 60:02d} мин"


def distance_text(metres: float) -> str:
    if metres < 1000:
        return f"{int(round(metres / 10.0)) * 10} м"
    return f"{metres / 1000.0:.1f} км".replace(".", ",")


def species_line(walk) -> str:
    """«Белый гриб 4, лисичка 12» — по убыванию количества.

    Именно это человек ищет в списке глазами: не километры и не время, а
    что взяли. Поэтому строка идёт крупно и первой после места.
    """
    counts = {}
    for f in walk.finds:
        if not f.species:
            continue
        counts[f.species] = counts.get(f.species, 0) + max(1, f.count)
    if not counts:
        return "без находок" if walk.finds else ""
    order = sorted(counts.items(), key=lambda kv: -kv[1])
    parts = []
    for key, n in order[:4]:
        name = engine.SPECIES[key].name if key in engine.SPECIES else key
        parts.append(f"{name.lower()} {n}")
    if len(order) > 4:
        parts.append(f"и ещё {len(order) - 4}")
    return ", ".join(parts)


def stats_line(walk) -> str:
    bits = [distance_text(walk.distance), duration_text(walk.duration)]
    n = len(walk.photo_names())
    if n:
        bits.append(f"снимков {n}")
    return " · ".join(bits)


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

        head = _wrapping(Label(text=f"[b]{walk.place or 'без названия'}[/b]\n"
                                    f"{stats_line(walk)}",
                               markup=True, font_size=sp(13), color=INK))
        box.add_widget(head)

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
        try:
            path = track_mod.export_gpx(self.walk)
        except (OSError, ValueError) as e:
            self.status.text = f"Не выгрузилось: {e}"
            return
        self.status.text = f"Сохранено: {path}"

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

        close = Button(text="Закрыть", size_hint_y=None, height=TOUCH,
                       font_size=sp(14), background_normal="",
                       background_color=SOFT, color=INK)
        close.bind(on_release=lambda *_: self.dismiss())
        self.box.add_widget(close)

        super().__init__(title="Журнал походов", content=self.box,
                         size_hint=(0.96, 0.9), title_size=sp(15),
                         separator_color=ACCENT, **kw)
        self.reload()

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
        rows = [f"[b]{walk.place or 'без названия'}[/b]  "
                f"[size=11sp][color={hint}]{when_text(walk)}[/color][/size]"]
        species = species_line(walk)
        if species:
            rows.append(f"[size=12sp]{species}[/size]")
        rows.append(f"[size=11sp][color={hint}]{stats_line(walk)}[/color][/size]")

        btn = Button(text="\n".join(rows), markup=True, font_size=sp(14),
                     color=INK, background_normal="", background_color=SOFT,
                     halign="left", valign="middle", size_hint_y=None,
                     height=dp(78), padding=(dp(10), dp(8)))
        btn.bind(width=lambda w, x: setattr(w, "text_size", (x - dp(20), None)),
                 texture_size=lambda w, t: setattr(w, "height",
                                                   max(dp(64), t[1] + dp(18))))
        btn.bind(on_release=lambda *_: WalkCard(walk, on_change=self.reload).open())
        return btn


def show():
    """Открывает журнал походов."""
    journal = WalkJournal()
    journal.open()
    return journal
