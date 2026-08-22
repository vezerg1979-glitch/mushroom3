# -*- coding: utf-8 -*-
"""
offlinemap.py — окно «Карта без интернета».

Три вещи в одном месте, потому что они об одном: сколько карты уже лежит на
телефоне, как скачать нужный квадрат впрок и откуда эта карта берётся.

Скачивание идёт в отдельном потоке: сотня тайлов с паузой в одну восьмую
секунды — это полминуты, и всё это время окно должно оставаться живым, а
кнопка «Отмена» — нажиматься. Прогресс возвращается в интерфейс через
@mainthread: трогать виджеты из чужого потока в Kivy нельзя.

Про источник подложки — см. tilesource.py. Коротко: общие серверы OSM
скачивание впрок запрещают, поэтому кнопка при них не работает и говорит,
почему.
"""

from __future__ import annotations

import threading

from kivy.clock import mainthread
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.utils import get_color_from_hex as hexc

import palette
import theme
import tiles
import tilesource

def _apply_palette():
    """Перечитывает цвета после смены темы.

    Цвета копируются в константы модуля при загрузке — так быстрее, но
    после переключения копии остаются прежними. theme вызывает эту функцию
    и пересобирает экран: у виджета цвет выставлен в момент создания, и
    задним числом палитра его не изменит.
    """
    global INK, MUTED, CARD, SOFT, ACCENT, RED
    INK = hexc(palette.INK)
    MUTED = hexc(palette.MUTED)
    CARD = hexc(palette.CARD)
    SOFT = hexc(palette.SOFT)
    ACCENT = hexc(palette.ACCENT)
    RED = hexc(palette.RED)


_apply_palette()
theme.register(_apply_palette)
TOUCH = dp(48)

RADII = ("1 км", "2 км", "3 км", "5 км")


def _fill(widget, color):
    with widget.canvas.before:
        Color(*color)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(pos=lambda w, v: setattr(rect, "pos", v),
                size=lambda w, v: setattr(rect, "size", v))


def _label(text, size=12, color=None, bold=False):
    # Цвет по умолчанию берётся при вызове, а не при объявлении:
    # значения по умолчанию вычисляются один раз, при загрузке
    # модуля, и после смены темы остались бы дневными.
    color = MUTED if color is None else color
    lbl = Label(text=text, font_size=sp(size), color=color, bold=bold,
                markup=True, halign="left", valign="top", size_hint_y=None)
    lbl.bind(width=lambda w, x: setattr(w, "text_size", (x, None)),
             texture_size=lambda w, t: setattr(w, "height", t[1]))
    return lbl


def _button(text, action, color=None, bg=None, bold=False, size=13):
    # Цвет по умолчанию берётся при вызове, а не при объявлении:
    # значения по умолчанию вычисляются один раз, при загрузке
    # модуля, и после смены темы остались бы дневными.
    color = INK if color is None else color
    bg = SOFT if bg is None else bg
    b = Button(text=text, font_size=sp(size), bold=bold, background_normal="",
               background_color=bg, color=color, halign="center",
               valign="middle", shorten=True, shorten_from="right")
    b.bind(size=lambda w, v: setattr(w, "text_size", v))
    b.bind(on_release=lambda *_: action())
    return b


class OfflineMap(Popup):
    """Сохранение квадрата карты вокруг точки."""

    def __init__(self, lat, lon, place="", **kw):
        self.lat, self.lon = lat, lon
        self.place = place
        self._thread = None
        self._stop = False

        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        _fill(root, CARD)

        sv = ScrollView()
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        box.bind(minimum_height=box.setter("height"))

        box.add_widget(_label(
            f"[b]{place or 'выбранная точка'}[/b]\n{lat:.5f}, {lon:.5f}",
            13, INK))
        box.add_widget(_label(
            "Карта в лесу не грузится: сети там нет. Скачанный квадрат "
            "остаётся на телефоне и работает без связи — на трёх масштабах: "
            "обзор района, просеки и поляны, тропинки."))

        # --- радиус ---
        row = BoxLayout(size_hint_y=None, height=TOUCH, spacing=dp(6))
        row.add_widget(Label(text="Радиус", font_size=sp(12), color=MUTED,
                             size_hint_x=None, width=dp(70)))
        self.sp_radius = Spinner(text="2 км", values=RADII, font_size=sp(14),
                                 background_normal="", background_color=SOFT,
                                 color=INK)
        self.sp_radius.bind(text=lambda *_: self._recount())
        row.add_widget(self.sp_radius)
        box.add_widget(row)

        self.estimate = _label("", 12, INK)
        box.add_widget(self.estimate)

        self.bar = ProgressBar(max=1, value=0, size_hint_y=None, height=dp(8))
        box.add_widget(self.bar)

        self.status = _label("", 11)
        box.add_widget(self.status)

        # --- источник подложки ---
        box.add_widget(_label("[b]Откуда берётся карта[/b]", 12, INK))
        self.source = _label("", 11)
        box.add_widget(self.source)

        self.ti_url = TextInput(
            text="", multiline=False, font_size=sp(12), size_hint_y=None,
            height=dp(44), padding=(dp(8), dp(12)),
            hint_text="https://ваш-сервер/{z}/{x}/{y}.png")
        box.add_widget(self.ti_url)

        srow = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        srow.add_widget(_button("Использовать свой", self._use_custom))
        srow.add_widget(_button("Вернуть OSM", self._use_osm))
        box.add_widget(srow)

        # --- кэш ---
        box.add_widget(_label("[b]Что уже сохранено[/b]", 12, INK))
        self.cache = _label("", 11)
        box.add_widget(self.cache)

        sv.add_widget(box)
        root.add_widget(sv)

        btns = BoxLayout(size_hint_y=None, height=TOUCH, spacing=dp(6))
        self.b_go = _button("Скачать", self._start, bg=ACCENT, color=(1, 1, 1, 1),
                            bold=True, size=15)
        btns.add_widget(self.b_go)
        btns.add_widget(_button("Очистить", self._clear, color=RED))
        btns.add_widget(_button("Закрыть", self._close))
        root.add_widget(btns)

        super().__init__(title="Карта без интернета", content=root,
                         size_hint=(0.96, 0.92), title_size=sp(15),
                         separator_color=ACCENT, auto_dismiss=False, **kw)
        self._recount()
        self._show_source()
        self._show_cache()

    # --- сводки -------------------------------------------------------------
    def _radius_km(self) -> float:
        return float(self.sp_radius.text.split()[0])

    def _plan(self):
        return tiles.plan(self.lat, self.lon, self._radius_km())

    def _recount(self):
        info = tiles.estimate(self.lat, self.lon, self._radius_km())
        if info["too_many"]:
            self.estimate.text = tiles.describe(self.lat, self.lon,
                                                self._radius_km())
            return
        have = tiles.cached(self._plan(), tiles.cache_dir())
        left = info["tiles"] - have
        if not left:
            self.estimate.text = (f"{info['tiles']} клеток — весь квадрат "
                                  f"уже на телефоне.")
            return
        share = left / info["tiles"]
        self.estimate.text = (
            f"{info['tiles']} клеток, примерно "
            f"{info['megabytes']:.1f} МБ и {info['minutes'] * share:.0f} мин.\n"
            f"Уже есть {have}, скачать {left}.")

    def _show_source(self):
        mark = "скачивание разрешено" if tilesource.allows_offline() \
            else "[b]скачивание впрок запрещено[/b]"
        self.source.text = f"{tilesource.name()} — {mark}.\n{tilesource.note()}"
        self.b_go.disabled = not tilesource.allows_offline()
        self.b_go.background_color = ACCENT if not self.b_go.disabled else SOFT
        self.b_go.color = (1, 1, 1, 1) if not self.b_go.disabled else MUTED

    def _show_cache(self):
        mb = tiles.cache_size_mb(tiles.cache_dir())
        self.cache.text = (f"Кэш карты занимает {mb:.1f} МБ."
                           if mb >= 0.05 else "Кэш карты пуст.")

    # --- источник -----------------------------------------------------------
    def _use_custom(self):
        try:
            tilesource.save("custom", self.ti_url.text)
        except (ValueError, OSError) as e:
            self.status.text = f"Не принято: {e}"
            return
        self.status.text = f"Источник: {tilesource.name()}"
        self._show_source()

    def _use_osm(self):
        try:
            tilesource.save("osm")
        except OSError as e:
            self.status.text = f"Не сохранилось: {e}"
            return
        self.status.text = "Вернулись на общие серверы OpenStreetMap"
        self._show_source()

    # --- скачивание ---------------------------------------------------------
    def _start(self):
        if self._thread is not None:
            self._stop = True
            self.status.text = "Останавливаю…"
            return
        info = tiles.estimate(self.lat, self.lon, self._radius_km())
        if info["too_many"]:
            self.status.text = "Квадрат слишком большой — уменьшите радиус"
            return
        try:
            tiles.check_allowed()
        except tiles.NotAllowed as e:
            self.status.text = str(e)
            return

        items = self._plan()
        self.bar.max = max(1, len(items))
        self.bar.value = 0
        self._stop = False
        self.b_go.text = "Отмена"
        self.status.text = "Качаю…"
        # Скачивание блокирующее и небыстрое: сотня клеток с паузой к серверу
        # это полминуты. В главном потоке окно бы просто замерло.
        self._thread = threading.Thread(
            target=self._work, args=(items,), daemon=True)
        self._thread.start()

    def _work(self, items):
        try:
            result = tiles.download(items, tiles.cache_dir(),
                                    on_progress=self._progress,
                                    should_stop=lambda: self._stop)
        except tiles.NotAllowed as e:
            result = {"error": str(e)}
        except OSError as e:
            result = {"error": f"не удалось записать: {e}"}
        self._finished(result)

    @mainthread
    def _progress(self, done, total):
        self.bar.value = done
        self.status.text = f"Скачано {done} из {total}"

    @mainthread
    def _finished(self, result):
        self._thread = None
        self.b_go.text = "Скачать"
        if "error" in result:
            self.status.text = result["error"]
        elif self._stop:
            self.status.text = (f"Остановлено. Успело сохраниться "
                                f"{result['downloaded']} клеток — "
                                f"они никуда не денутся.")
        elif result["failed"]:
            self.status.text = (
                f"Сохранено {result['downloaded']}, не отдал сервер "
                f"{result['failed']}. Повторите — уже скачанное "
                f"перекачиваться не будет.")
        else:
            self.status.text = (f"Готово: {result['downloaded']} клеток, "
                                f"{result['skipped']} уже были.")
        self._recount()
        self._show_cache()

    # --- прочее -------------------------------------------------------------
    def _clear(self):
        gone = tiles.clear_cache(tiles.cache_dir())
        self.status.text = (f"Удалено {gone} клеток. Карта не сломалась — "
                            f"подгрузится заново при сети.")
        self._recount()
        self._show_cache()

    def _close(self):
        self._stop = True
        self.dismiss()


def show(lat, lon, place=""):
    dialog = OfflineMap(lat, lon, place)
    dialog.open()
    return dialog
