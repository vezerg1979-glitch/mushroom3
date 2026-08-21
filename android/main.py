#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Навигатор грибника — мобильное приложение (Kivy) поверх ядра mushroom_forecast.py.

Сборка APK:  buildozer -v android debug
Отладка на ПК: python main.py
"""

from __future__ import annotations

import math
import os
import ssl
import threading
import traceback
from datetime import datetime


def _crash_path() -> str:
    """Куда писать протокол аварии (приватный каталог приложения на Android)."""
    base = (os.environ.get("ANDROID_PRIVATE")
            or os.environ.get("ANDROID_APP_PATH")
            or os.path.expanduser("~"))
    return os.path.join(base, "mushroom-crash.txt")


def _log_crash(text: str) -> str:
    path = _crash_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\n\n{text}\n")
    except OSError:
        pass
    return path

# --- сертификаты для https на Android -------------------------------------- #
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    ssl._create_default_https_context = lambda *a, **k: ssl.create_default_context(
        cafile=certifi.where())
except ImportError:
    pass

from kivy.app import App
from kivy.base import ExceptionHandler, ExceptionManager
from kivy.clock import Clock, mainthread
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.widget import Widget
from kivy.utils import get_color_from_hex as hexc

import ads
import premium
import premium_screen
import icons
import mushroom_forecast as engine
import markup
import layout
import palette
import theme
import places as places_mod
import prefs
import notify
import track as track_mod
import wave
from mapview import PlacePicker
from walkscreen import WalkScreen

# --------------------------------------------------------------------------- #
#  Палитра
# --------------------------------------------------------------------------- #

# Цвета живут в palette.py: один источник на все экраны, и там же проверка
# контраста, которой заведует тест. Здесь только перевод в формат Kivy.

def _apply_palette():
    """Перечитывает цвета после смены темы.

    Цвета копируются в константы модуля при загрузке — так быстрее, но
    после переключения копии остаются прежними. theme вызывает эту функцию
    и пересобирает экран: у виджета цвет выставлен в момент создания, и
    задним числом палитра его не изменит.
    """
    global BG, CARD, GRID, INK, MUTED, ACCENT, BLUE, RAIN
    global LEVEL_COLORS, SPECIES_COLORS
    BG = hexc(palette.BG)
    CARD = hexc(palette.CARD)
    GRID = hexc(palette.GRID)
    INK = hexc(palette.INK)
    MUTED = hexc(palette.MUTED)
    ACCENT = hexc(palette.ACCENT)
    BLUE = hexc(palette.BLUE)
    RAIN = palette.RAIN

    LEVEL_COLORS = [(th, hexc(bg), hexc(fg)) for th, bg, fg in palette.LEVELS]

    SPECIES_COLORS = palette.SPECIES


_apply_palette()
theme.register(_apply_palette)


@theme.register
def _repaint_window():
    """Фон окна живёт вне виджетов и пересборкой экрана не меняется."""
    Window.clearcolor = hexc(palette.BG)


#: Знак для полосок в объяснениях. Длинные тире смыкаются в сплошную линию,
#: и, в отличие от блочных знаков, они в шрифте есть — проверено тестом.
BAR = "—"

# Минимальный размер элемента, в который надо попасть пальцем. Меньше 48 dp
# промахиваются даже дома на диване, а в лесу телефон держат в перчатке.
TOUCH = dp(48)

_repaint_window()


def level_colors(v: float):
    for th, bg, fg in LEVEL_COLORS:
        if v >= th:
            return bg, fg
    return LEVEL_COLORS[-1][1], LEVEL_COLORS[-1][2]


# --------------------------------------------------------------------------- #
#  Вспомогательные виджеты
# --------------------------------------------------------------------------- #

class Card(BoxLayout):
    """Прямоугольник со скруглением и фоном."""

    def __init__(self, bg=None, radius=dp(10), **kw):
        # Цвет по умолчанию берётся при вызове, а не при объявлении:
        # значения по умолчанию вычисляются один раз, при загрузке
        # модуля, и после смены темы остались бы дневными.
        bg = CARD if bg is None else bg
        super().__init__(**kw)
        self._bg = bg
        self._radius = radius
        with self.canvas.before:
            self._col = Color(*bg)
            self._rect = RoundedRectangle(radius=[radius])
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def set_bg(self, color):
        self._col.rgba = color


class Chart(Widget):
    """Кривая индекса + столбики осадков. Тап по графику — детали дня."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.res = None
        self.names = []
        self.highlight = None
        self.on_pick = None
        self._legend_h = dp(0)
        self.bind(pos=self.redraw, size=self.redraw)

    def set_data(self, res, names, highlight=None, on_pick=None):
        self.res = res
        self.names = list(names)
        self.highlight = highlight
        self.on_pick = on_pick
        self.redraw()

    # --- геометрия --------------------------------------------------------
    def _bounds(self):
        return max(0, self.res.today - 5), len(self.res.days)

    def _px(self, i):
        lo, hi = self._bounds()
        n = max(1, hi - lo - 1)
        left, right = self.x + dp(28), self.right - dp(10)
        return left + (right - left) * (i - lo) / n

    def _py(self, v):
        bot, top = self.y + dp(20), self.top - dp(6) - self._legend_h
        return bot + (top - bot) * max(0.0, min(100.0, v)) / 100.0

    def _legend(self):
        """Раскладка легенды; возвращает её высоту."""
        rows, x, items = 1, self.x + dp(2), []
        for n in self.names:
            lbl = CoreLabel(text=n, font_size=sp(9))
            lbl.refresh()
            w = lbl.texture.width + dp(20)
            if x + w > self.right - dp(4):
                rows, x = rows + 1, self.x + dp(2)
            items.append((n, lbl.texture, x, rows))
            x += w
        h = rows * dp(14) + dp(4)
        return items, h

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos) or not self.res or not self.on_pick:
            return super().on_touch_down(touch)
        lo, hi = self._bounds()
        best, bi = 1e9, lo
        for i in range(lo, hi):
            d = abs(self._px(i) - touch.x)
            if d < best:
                best, bi = d, i
        self.on_pick(bi)
        return True

    # --- отрисовка --------------------------------------------------------
    def _text(self, s, x, y, size=9, color=None, anchor="left"):
        # Цвет по умолчанию берётся при вызове, а не при объявлении:
        # значения по умолчанию вычисляются один раз, при загрузке
        # модуля, и после смены темы остались бы дневными.
        color = MUTED if color is None else color
        lbl = CoreLabel(text=s, font_size=sp(size))
        lbl.refresh()
        t = lbl.texture
        px = x - (t.width if anchor == "right" else t.width / 2 if anchor == "center" else 0)
        Color(*color)
        Rectangle(texture=t, pos=(px, y), size=t.size)

    def redraw(self, *_):
        self.canvas.clear()
        if not self.res or not self.names:
            return
        r = self.res
        items, self._legend_h = self._legend()
        lo, hi = self._bounds()
        with self.canvas:
            # легенда над полем графика
            for n, tex, x, row in items:
                Color(*hexc(SPECIES_COLORS.get(n, "#555555")))
                Rectangle(pos=(x, self.top - row * dp(14) + dp(2)), size=(dp(8), dp(8)))
                Color(*MUTED)
                Rectangle(texture=tex, pos=(x + dp(11), self.top - row * dp(14)),
                          size=tex.size)
            # зоны уровней
            for th, col, _ in LEVEL_COLORS:
                if th == 0:
                    continue
                y0, y1 = self._py(th), self._py(min(100, th + 17))
                Color(col[0], col[1], col[2], 0.16)
                Rectangle(pos=(self.x + dp(28), y0),
                          size=(self.right - dp(10) - self.x - dp(28), y1 - y0))
            # сетка
            for v in (0, 50, 100):
                Color(*GRID)
                Line(points=[self.x + dp(28), self._py(v), self.right - dp(10), self._py(v)],
                     width=dp(0.6))
                self._text(str(v), self.x + dp(24), self._py(v) - dp(6), 8, MUTED, "right")
            # осадки
            pmax = max(8.0, max(r.days[i].precip for i in range(lo, hi)) * 1.25)
            bw = max(dp(3), (self._px(lo + 1) - self._px(lo)) * 0.45)
            for i in range(lo, hi):
                pr = r.days[i].precip
                if pr <= 0.05:
                    continue
                h = (self.top - dp(8) - self.y - dp(20)) * 0.5 * pr / pmax
                Color(*RAIN)
                Rectangle(pos=(self._px(i) - bw / 2, self.y + dp(20)), size=(bw, h))
            # кривые: выделенный вид рисуется последним и толще
            order = [n for n in self.names if n != self.highlight]
            if self.highlight in self.names:
                order.append(self.highlight)
            for n in order:
                pts = []
                for i in range(lo, hi):
                    v = r.idx[n][i]
                    if v is None or math.isnan(v):
                        continue
                    pts += [self._px(i), self._py(v)]
                if len(pts) < 4:
                    continue
                top = n == self.highlight
                col = hexc(SPECIES_COLORS.get(n, "#555555"))
                Color(col[0], col[1], col[2], 1.0 if top else 0.45)
                Line(points=pts, width=dp(1.9) if top else dp(1.1))
                if top:
                    for k in range(0, len(pts), 2):
                        Line(circle=(pts[k], pts[k + 1], dp(2.2)), width=dp(1.5))
            # сегодня
            Color(ACCENT[0], ACCENT[1], ACCENT[2], 0.85)
            Line(points=[self._px(r.today), self.y + dp(20),
                         self._px(r.today), self.top - dp(8)],
                 width=dp(1.0), dash_length=dp(4), dash_offset=dp(3))
            # даты
            step = max(1, (hi - lo) // 6)
            for i in range(lo, hi, step):
                self._text(r.days[i].d.strftime("%d.%m"), self._px(i), self.y + dp(3),
                           8, MUTED, "center")


class ScaleBar(Widget):
    """Цветовая шкала индекса с расшифровкой словами."""

    STEPS = [(0, 8, ""), (8, 18, ""), (18, 33, "единично"), (33, 50, "умеренно"),
             (50, 68, "хорошо"), (68, 85, "обильно"), (85, 100, "массовый")]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(pos=self._draw, size=self._draw)

    def _draw(self, *_):
        self.canvas.clear()
        with self.canvas:
            lbl = CoreLabel(text="Шкала индекса:", font_size=sp(10))
            lbl.refresh()
            Color(*MUTED)
            Rectangle(texture=lbl.texture, pos=(self.x, self.top - dp(13)),
                      size=lbl.texture.size)
            for lo, hi, name in self.STEPS:
                x0 = self.x + self.width * lo / 100.0
                x1 = self.x + self.width * hi / 100.0
                bg, fg = level_colors(lo + 1)
                Color(*bg)
                Rectangle(pos=(x0, self.y), size=(x1 - x0 - dp(1), dp(17)))
                if name and x1 - x0 > dp(46):
                    t = CoreLabel(text=name, font_size=sp(9))
                    t.refresh()
                    Color(*fg)
                    Rectangle(texture=t.texture,
                              pos=(x0 + (x1 - x0 - t.texture.width) / 2,
                                   self.y + dp(3)), size=t.texture.size)


class DayRow(Card):
    """Строка списка дней."""

    def __init__(self, res, i, name, on_tap, **kw):
        super().__init__(orientation="horizontal", size_hint_y=None, height=dp(48),
                         padding=(dp(10), dp(4)), spacing=dp(8), **kw)
        v = res.value(name, i) if name else res.best_value(i)
        bg, fg = level_colors(v)
        d = res.days[i]
        today = i == res.today
        self.set_bg(CARD if not today else hexc(palette.TODAY))
        self._tap, self._i = on_tap, i

        # Ширина текста берётся из фактического размера ярлыка. Прежние
        # жёсткие dp(120) на узком экране обрезали «Подберёзовик» до
        # «Подберёзо», а на широком оставляли пустое поле справа.
        def _wrap(w, x):
            w.text_size = (x, None)

        left = BoxLayout(orientation="vertical", size_hint_x=0.42)
        wd = engine.RU_WD[d.d.weekday()]
        l_day = Label(text=("сегодня" if today else f"{wd} {d.d:%d.%m}").capitalize(),
                      color=INK, font_size=sp(13), bold=today, halign="left",
                      valign="bottom", shorten=True, shorten_from="right")
        l_wx = Label(text=f"{d.precip:.1f} мм · {d.tmean:.0f}°C",
                     color=MUTED, font_size=sp(11), halign="left", valign="top",
                     shorten=True, shorten_from="right")
        for l in (l_day, l_wx):
            l.bind(width=_wrap)
            left.add_widget(l)
        self.add_widget(left)

        box = Card(bg=bg, size_hint_x=0.18)
        box.add_widget(Label(text=f"{v:.0f}", color=fg, font_size=sp(17), bold=True))
        self.add_widget(box)
        l_lvl = Label(text=engine.level(v), color=INK, font_size=sp(12),
                      halign="left", valign="middle", size_hint_x=0.4,
                      shorten=True, shorten_from="right")
        l_lvl.bind(width=_wrap)
        self.add_widget(l_lvl)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._tap(self._i)
            return True
        return super().on_touch_down(touch)


# --------------------------------------------------------------------------- #
#  Результат
# --------------------------------------------------------------------------- #

class Result:
    def __init__(self, place, days, today_idx):
        self.place, self.days, self.today = place, days, today_idx
        self.m = engine.water_balance(days)
        self.ts = engine.soil_temperature(days)
        self.idx = {sp.name: engine.species_index(sp, days, self.m, self.ts)
                    for sp in engine.SPECIES.values()}
        self.stamp = datetime.now()
        self.stale = None

    def value(self, name, i):
        v = self.idx[name][i]
        return 0.0 if (v is None or math.isnan(v)) else v

    def season_names(self):
        month = self.days[self.today].d.month
        return [sp.name for sp in engine.SPECIES.values() if sp.months.get(month, 0) > 0] \
            or [sp.name for sp in engine.SPECIES.values()]

    def best(self, i):
        return max((self.value(n, i), n) for n in self.season_names())

    def best_value(self, i):
        return self.best(i)[0]


# --------------------------------------------------------------------------- #
#  Приложение
# --------------------------------------------------------------------------- #

class _Catcher(ExceptionHandler):
    """Ошибка в обработчике события не должна закрывать приложение."""

    app = None

    @staticmethod
    def _headline(tb: str) -> str:
        """Самое важное из трассировки: тип ошибки, место и строка кода.

        Питон печатает это последним, и в окне на телефоне оно оказывается
        за пределами экрана: человек фотографирует «Ошибка» и десяток путей
        внутрь Kivy, по которым сказать нельзя ничего. Поэтому суть выносится
        наверх, а полная трассировка остаётся ниже — она нужна редко.
        """
        lines = [l for l in tb.strip().splitlines() if l.strip()]
        if not lines:
            return "Причина неизвестна"
        out = [lines[-1]]
        # Последний кадр, относящийся к самому приложению, а не к библиотеке.
        for line in reversed(lines[:-1]):
            text = line.strip()
            if text.startswith("File ") and "/app/" in text:
                out.insert(0, text.split("/app/")[-1])
                break
        return "\n".join(out)

    def handle_exception(self, inst):
        tb = traceback.format_exc()
        path = _log_crash(tb)
        if self.app is not None:
            try:
                # Текст исключения экранируется: в нём бывают скобки, а
                # окно, которое падает, показывая ошибку, не оставляет
                # человеку ни причины, ни возможности её снять.
                head = markup.esc(self._headline(tb))
                self.app._sheet(
                    "Ошибка",
                    f"[b]{head}[/b]\n"
                    f"[size=10sp][color=5C6353]Протокол: {markup.esc(path)}"
                    f"[/color][/size]\n\n"
                    f"[size=11sp]{markup.esc(tb)}[/size]", 0.8)
            except Exception:                                     # noqa: BLE001
                pass
        return ExceptionManager.PASS


class MushroomApp(App):
    title = "Навигатор грибника"

    def build(self):
        try:
            places_mod.set_data_dir(self.user_data_dir)
        except Exception:                                         # noqa: BLE001
            pass
        handler = _Catcher()
        handler.app = self
        ExceptionManager.add_handler(handler)
        self.res = None
        # Последнее место переживает закрытие приложения. Фрязино остаётся
        # только для самого первого запуска: человек, который ездит в другую
        # сторону, иначе каждый раз начинал с чужого леса и лез в карту,
        # чтобы вернуться к своему.
        self.lat, self.lon, self._place_name = self._saved_place()
        # Тема выбирается до сборки экрана: собранные виджеты перекрасить
        # уже нельзя.
        theme.apply(self.lat, self.lon)
        self.sel = None                      # выбранный вид или None = лучший
                                             # (восстанавливается ниже из prefs)
        root = self._build_ui()
        Window.bind(size=self._on_window_size)
        Clock.schedule_once(lambda *_: self.calculate(), 0.6)
        # Реклама встаёт в очередь отдельно от расчёта прогноза: ads.init()
        # и attach() каждый оборачивают свою неудачу в try, и заминка сети
        # для рекламы не должна отложить главный экран.
        Clock.schedule_once(lambda *_: (ads.init(), ads.attach()), 1.2)
        return root

    def _build_ui(self):
        """Собирает экран из текущих цветов.

        Вынесено из build отдельно ради смены темы: перекрасить уже
        созданные виджеты нельзя — цвет фона у кнопки выставлен в
        момент создания. Поэтому экран собирается заново, а данные
        (место, прогноз, выбранный вид) остаются в приложении и
        переживают пересборку.
        """
        # Части экрана сначала собираются по отдельности, а расставляются в
        # самом конце: в горизонтали они раскладываются иначе, а собирать их
        # дважды означало бы две расходящиеся копии одного экрана.
        parts = {}

        # --- строка места ---
        # Ряд разделён надвое: название места отдельно, мелкие кнопки
        # отдельно. Причина простая: на телефоне шириной 360 точек пять
        # кнопок и сердце съедают 290, названию остаётся полсотни, и
        # «Фрязино» вставало в столбик по одной букве — «я з и». В
        # горизонтали, где ширины хватает, обе половины снова сходятся в
        # одну строку (см. _arrange).
        top = BoxLayout(size_hint_y=None, height=TOUCH, spacing=dp(6))
        tools = BoxLayout(size_hint_y=None, height=TOUCH, spacing=dp(6))
        self.btn_place = Button(text=self._place_name, font_size=sp(15), halign="left",
                                valign="middle", background_normal="",
                                background_color=CARD, color=INK)
        self.btn_place.bind(size=lambda w, v: setattr(w, "text_size",
                                                      (v[0] - dp(16), v[1])))
        self.btn_place.bind(on_release=lambda *_: self.pick_place())
        top.add_widget(self.btn_place)
        b_gps = Button(text="GPS", size_hint_x=None, width=TOUCH + dp(6), font_size=sp(12),
                       bold=True, background_normal="", background_color=CARD,
                       color=ACCENT)
        b_gps.bind(on_release=lambda *_: self.locate_me())
        tools.add_widget(b_gps)
        b_star = Button(text="Сохр.", size_hint_x=None, width=TOUCH + dp(12), font_size=sp(12),
                        bold=True, background_normal="", background_color=CARD,
                        color=ACCENT)
        b_star.bind(on_release=lambda *_: self.save_spot())
        tools.add_widget(b_star)
        # Переключатель темы. Три состояния по кругу, а не отдельный экран
        # настроек: ради одной настройки экран заводить не из-за чего, а по
        # кругу человек проходит их за два касания. Подпись показывает и
        # выбор, и что из него вышло: «Авто · ночь» — иначе непонятно,
        # почему экран тёмный.
        self.b_theme = Button(text=theme.label(), size_hint_x=None,
                              width=TOUCH + dp(30), font_size=sp(11),
                              background_normal="", background_color=CARD,
                              color=MUTED)
        self.b_theme.bind(on_release=lambda *_: self.switch_theme())
        tools.add_widget(self.b_theme)

        b_help = Button(text="?", size_hint_x=None, width=TOUCH, font_size=sp(16),
                        bold=True, background_normal="", background_color=CARD,
                        color=MUTED)
        b_help.bind(on_release=lambda *_: self.show_help())
        tools.add_widget(b_help)
        # Кнопка есть только пока рекламу не купили: после покупки
        # предлагать купить снова — не забота, а неуважение к тому, что
        # человек уже сделал.
        self.b_premium = None
        if not premium.is_premium():
            self.b_premium = Button(text="Без\nрекламы", size_hint_x=None,
                                    width=TOUCH + dp(6), font_size=sp(10),
                                    background_normal="",
                                    background_color=CARD, color=MUTED,
                                    halign="center")
            self.b_premium.bind(
                size=lambda w, v: setattr(w, "text_size", v),
                on_release=lambda *_: self.show_premium())
            tools.add_widget(self.b_premium)
        parts["top"] = top
        parts["tools"] = tools

        # --- сохранённые места одной строкой ---
        # Раньше добраться до своего места можно было только через карту:
        # открыть окно, дождаться подгрузки плиток по мобильной сети, найти
        # список в выпадашке. В лесу это полминуты и почти всегда впустую.
        # Здесь те же места лежат кнопками, прокручиваются вбок и работают
        # без сети. Пустой список полосу не показывает.
        self.spots_sv = ScrollView(size_hint_y=None, height=0, do_scroll_y=False,
                                   bar_width=0)
        self.spots_row = BoxLayout(size_hint_x=None, spacing=dp(6),
                                   size_hint_y=None, height=dp(36))
        self.spots_row.bind(minimum_width=self.spots_row.setter("width"))
        self.spots_sv.add_widget(self.spots_row)
        parts["spots"] = self.spots_sv

        # --- строка параметров ---
        row2 = BoxLayout(size_hint_y=None, height=TOUCH, spacing=dp(6))
        self.sp_days = Spinner(text="10 сут", values=[f"{n} сут" for n in (5, 7, 10, 14, 16)],
                               size_hint_x=None, width=dp(90), font_size=sp(13),
                               background_normal="", background_color=CARD, color=INK)
        self.sp_days.bind(text=lambda *_: self.calculate())
        row2.add_widget(self.sp_days)
        self.btn = Button(text="Прогноз", font_size=sp(15), bold=True,
                          background_normal="", background_color=ACCENT)
        self.btn.bind(on_release=lambda *_: self.calculate())
        row2.add_widget(self.btn)
        b_walk = Button(text="В лес", size_hint_x=None, width=dp(76), font_size=sp(14),
                        bold=True, background_normal="",
                        background_color=BLUE)
        b_walk.bind(on_release=lambda *_: self.start_walk())
        row2.add_widget(b_walk)
        # Журнал стоит рядом с «В лес» не случайно: это две стороны одного
        # дела — сходить и посмотреть, как ходил раньше. Значок вместо
        # надписи, потому что строка уже занята «Прогнозом»; сам значок —
        # из icons.py, на шрифт полагаться нельзя (см. кнопку доната).
        b_log = icons.IconButton(icon="journal", color=INK, bg=CARD,
                                 size_hint_x=None, width=TOUCH)
        b_log.bind(on_release=lambda *_: self.show_walk_journal())
        row2.add_widget(b_log)
        parts["row2"] = row2

        # --- вердикт ---
        # Вердикт. Высота карточки следует за текстом: строка вида
        # «Подосиновик — обильно, лучший день суббота 23.08» на узком экране
        # переносится на две строки, и при фиксированных 72 dp вторая просто
        # исчезала — человек видел обрубок фразы.
        self.card = Card(orientation="vertical", size_hint_y=None, height=dp(72),
                         padding=(dp(12), dp(8)), spacing=dp(2))
        self.l_main = Label(text="Данные не загружены", font_size=sp(17), bold=True,
                            color=INK, halign="left", valign="top", size_hint_y=None)
        self.l_sub = Label(text="Укажите место и нажмите «Прогноз»", font_size=sp(12),
                           color=MUTED, halign="left", valign="top", size_hint_y=None)
        # Строка про начинающийся слой. Пустая — не занимает места: сообщать
        # «волны нет» каждый день незачем, а карточка от лишней пустой
        # строки становится выше и отодвигает график.
        self.l_wave = Label(text="", font_size=sp(12), bold=True,
                            color=hexc(palette.ACCENT), halign="left",
                            valign="top", size_hint_y=None)
        for l in (self.l_main, self.l_sub, self.l_wave):
            l.bind(width=lambda w, x: setattr(w, "text_size", (x, None)),
                   texture_size=lambda w, t: setattr(w, "height", t[1]))
        self.l_wave.bind(text=lambda w, v: setattr(w, "opacity", 1.0 if v else 0.0))
        self.card.bind(minimum_height=lambda w, v: setattr(
            w, "height", max(dp(72), v)))
        self.card.add_widget(self.l_main)
        self.card.add_widget(self.l_sub)
        self.card.add_widget(self.l_wave)
        parts["card"] = self.card

        # --- выбор вида ---
        # Вид и тип леса восстанавливаются с прошлого запуска: человек ходит
        # за одним и тем же грибом в один и тот же лес, и заново выставлять
        # два списка при каждом открытии — работа на пустом месте.
        saved = prefs.load()
        picks = BoxLayout(size_hint_y=None, height=TOUCH - dp(4), spacing=dp(6))
        self.sp_bio = Spinner(text=self._saved_biotope(saved), font_size=sp(12),
                              background_normal="", background_color=CARD, color=INK,
                              values=[b.name for b in engine.BIOTOPES.values()])
        self.sp_bio.bind(text=self._on_biotope)
        self.sp_kind = Spinner(text=self._saved_kind(saved), size_hint_y=None,
                               height=TOUCH - dp(4),
                               font_size=sp(13), background_normal="",
                               background_color=CARD, color=INK,
                               values=["Все виды сезона"]
                                      + [s.name for s in engine.SPECIES.values()])
        self.sp_kind.bind(text=self._on_kind)
        if self.sp_kind.text != self.ALL_KINDS:
            self.sel = self.sp_kind.text
        picks.add_widget(self.sp_kind)
        picks.add_widget(self.sp_bio)
        parts["picks"] = picks

        self._reload_spots()

        # --- график ---
        # Высота считается от экрана, а не задана числом. Сумма постоянных
        # частей экрана — около 300 dp; на пятидюймовом телефоне жёсткие
        # 230 dp под график не оставляли списку дней ни строки, и главное
        # («когда ехать») приходилось искать прокруткой.
        holder = Card(size_hint_y=None, height=dp(230), padding=dp(6))
        self.chart = Chart()
        holder.add_widget(self.chart)
        parts["chart"] = holder
        self._chart_holder = holder
        self._fit_chart()

        # --- шкала индекса ---
        parts["scale"] = ScaleBar(size_hint_y=None, height=dp(34))

        # --- список дней ---
        sv = ScrollView(do_scroll_x=False, bar_width=dp(3))
        self.list = GridLayout(cols=1, spacing=dp(6), size_hint_y=None, padding=(0, dp(2)))
        self.list.bind(minimum_height=self.list.setter("height"))
        sv.add_widget(self.list)
        parts["list"] = sv

        self.status = Label(text=f"v{engine.VERSION} · погода: Open-Meteo (CC-BY)", font_size=sp(10),
                            color=MUTED, size_hint_y=None, height=dp(18))
        parts["status"] = self.status
        return self._arrange(parts)

    def _arrange(self, parts):
        """Расставляет готовые части: столбцом или в две колонки.

        В горизонтали высоты остаётся вдвое меньше, и привычный столбец
        превращается в ленту, где виден один график, а список дней — то
        главное, ради чего экран открывают, — уезжает за край. Поэтому
        слева то, на что смотрят (карточка и график), справа то, что
        нажимают, и список: под правую руку, которой держат телефон.

        Узкий экран на боку (маленький телефон, 640×360) остаётся столбцом:
        две колонки по 180 точек — это два огрызка вместо одного читаемого.
        """
        # То же, что в экране похода: при повороте части приходят из старой
        # раскладки и без открепления Kivy откажется добавлять их снова.
        for part in parts.values():
            if part.parent is not None:
                part.parent.remove_widget(part)
        self._wide = layout.two_columns(Window.width, Window.height, dp(1))
        if not self._wide:
            root = BoxLayout(orientation="vertical", padding=dp(10),
                             spacing=dp(8))
            for key in ("top", "tools", "spots", "row2", "card", "picks",
                        "chart", "scale", "list", "status"):
                root.add_widget(parts[key])
            return root

        left_share, right_share = layout.split(Window.width)
        root = BoxLayout(padding=dp(8), spacing=dp(8))
        left = BoxLayout(orientation="vertical", spacing=dp(8),
                         size_hint_x=left_share)
        right = BoxLayout(orientation="vertical", spacing=dp(8),
                          size_hint_x=right_share)
        # График тянется на всю высоту своей колонки: снизу его больше не
        # поджимают список и кнопки, и в горизонтали это единственное место,
        # где он наконец виден целиком.
        parts["chart"].size_hint_y = 1
        # Верхний ряд уезжает в широкую колонку. В узкой ему не хватало
        # места: шесть кнопок съедали её целиком, а название места
        # («Фрязино») ломалось в три строки по буквам.
        # На боку ширины хватает, и обе половины шапки снова сходятся в одну
        # строку: лишний ряд там съедал бы высоту, которой и так мало.
        шапка = BoxLayout(size_hint_y=None, height=TOUCH, spacing=dp(6))
        шапка.add_widget(parts["top"])
        шапка.add_widget(parts["tools"])
        parts["tools"].size_hint_x = None
        parts["tools"].width = TOUCH * 5 + dp(60)
        left.add_widget(шапка)
        for key in ("card", "chart", "scale", "status"):
            left.add_widget(parts[key])
        for key in ("spots", "row2", "picks", "list"):
            right.add_widget(parts[key])
        root.add_widget(left)
        root.add_widget(right)
        return root

    def _on_window_size(self, *_):
        """Поворот экрана. Пересобираем только при смене самой раскладки.

        Android присылает десятки событий размера за один поворот, и
        пересборка на каждое — это моргание и потерянная прокрутка.
        """
        self._fit_chart()
        wide = layout.two_columns(Window.width, Window.height, dp(1))
        if wide != getattr(self, "_wide", None):
            self._repaint()

    def switch_theme(self, mode=None):
        """Следующая тема по кругу и пересборка экрана.

        Прогноз при этом не пересчитывается: он уже посчитан и лежит в
        self.res, а лезть в сеть из-за смены цветов — это и ожидание, и
        трафик там, где человек просто хотел, чтобы не слепило.
        """
        theme.set_mode(mode or theme.next_mode(), self.lat, self.lon)
        self._repaint()

    def _apply_theme_now(self):
        """Пересчитывает «авто» и перекрашивает, если тема сменилась."""
        before = palette.current()
        theme.apply(self.lat, self.lon)
        if palette.current() != before:
            self._repaint()

    def _repaint(self):
        """Пересобирает экран под текущие цвета, сохраняя состояние."""
        from kivy.core.window import Window

        old = self.root
        new = self._build_ui()
        if old is not None and old.parent is not None:
            old.parent.remove_widget(old)
        # canvas="before" — главный экран всегда нижний слой.
        #
        # Без этого пересобранный экран добавлялся последним и рисовался
        # ПОВЕРХ открытых окон: сменил тему, не закрыв поход, — и карта с
        # кнопками похода просвечивает сквозь прогноз. Kivy рисует окна в
        # порядке добавления на холст, а не по списку детей, поэтому «новое
        # сверху» тут получается само собой.
        Window.add_widget(new, canvas="before")
        self.root = new
        if self.res is not None:
            self.refresh()
        self.b_theme.text = theme.label()

    def _fit_chart(self, *_):
        """График занимает треть экрана, но не меньше 150 и не больше 230 dp."""
        holder = getattr(self, "_chart_holder", None)
        if holder is None:
            return
        holder.height = max(dp(150), min(dp(230), Window.height * 0.30))

    # --- расчёт ------------------------------------------------------------
    def calculate(self):
        if self.btn.disabled:
            return
        self.btn.disabled = True
        self.btn.text = "…"
        self.status.text = "Запрос погодных данных…"
        place = f"{self.lat:.5f}, {self.lon:.5f}"
        fdays = int(self.sp_days.text.split()[0])
        threading.Thread(target=self._work, args=(place, fdays), daemon=True).start()

    def _work(self, place_text, fdays):
        try:
            parts = [p.strip().replace(",", ".") for p in place_text.replace(";", ",").split(",")]
            if len(parts) == 2 and all(_isnum(p) for p in parts):
                place = engine.Place(f"{float(parts[0]):.3f}, {float(parts[1]):.3f}",
                                     float(parts[0]), float(parts[1]))
            else:
                place = engine.geocode(place_text)
            stale = None
            spot = places_mod.Spot(place.name, place.lat, place.lon)
            try:
                days = engine.fetch_weather(place, fdays)
                places_mod.cache_forecast(spot, days)
            except Exception:                                     # noqa: BLE001
                got = places_mod.cached_forecast(spot)
                if got is None:
                    raise
                days, stale = got
            today = datetime.now().date()
            ti = next((i for i, d in enumerate(days) if d.d >= today), len(days) - fdays)
            res = Result(place, days, ti)
            res.stale = stale
            self._ok(res)
        except BaseException as e:                                 # noqa: BLE001
            self._err(f"{type(e).__name__}: {e}" if not str(e) else str(e))

    @mainthread
    def _ok(self, res):
        self.res = res
        self.btn.disabled = False
        self.btn.text = "Прогноз"
        if getattr(res, "stale", None):
            self.status.text = (f"{res.place.name} · нет сети, данные из кэша "
                                f"({places_mod.cache_age_text(res.stale)})")
        else:
            self.status.text = (f"{res.place.name} · обновлено {res.stamp:%H:%M} · "
                                f"Open-Meteo (CC-BY)")
        self.refresh()
        self._check_wave(res)

    def _check_wave(self, res):
        """Начинается ли слой — и сказать об этом, пока есть время собраться.

        Проверка идёт при каждом обновлении прогноза, то есть когда человек
        открыл приложение. Разбудить его в среду самостоятельно программа
        не может: для этого нужен будильник системы с собственным
        приёмником на Java, которого в сборке нет (см. README). Поэтому
        уведомление здесь делает одно, но важное дело — переживает закрытие
        приложения и висит в шторке, попадаясь на глаза, когда человек ещё
        может подвинуть дела.
        """
        try:
            idx = {key: res.idx[sp.name] for key, sp in engine.SPECIES.items()
                   if sp.name in res.idx}
            found = wave.find(res.days, idx, res.today)
        except Exception:                                          # noqa: BLE001
            return
        self.l_wave.text = wave.line(found)
        fresh = wave.fresh(found, getattr(res.place, "name", ""))
        if not fresh:
            return
        title, text = wave.message(fresh)
        if notify.post(title, f"{text} {res.place.name}."):
            wave.remember(fresh, getattr(res.place, "name", ""))

    @mainthread
    def _err(self, msg):
        self.btn.disabled = False
        self.btn.text = "Прогноз"
        self.status.text = "Ошибка загрузки"
        self._sheet("Не удалось получить данные",
                    f"{msg}\n\nПроверьте название места и подключение к сети. "
                    f"Вместо названия можно ввести координаты: 55.9606, 38.0456", 0.45)

    def show_walk_journal(self):
        """Журнал походов: куда ходили, что нашли, снимки находок."""
        import walkjournal
        walkjournal.show()

    def start_walk(self):
        """Режим похода: запись маршрута, метки находок, счётчик метров."""
        bio = next((b.key for b in engine.BIOTOPES.values()
                    if b.name == self.sp_bio.text), "смешанный")
        # Реклама снимается на время похода и не спрашивается заново: в лесу
        # ей всё равно взять нечего, а место под ней на маленьком экране
        # нужнее карте.
        ads.detach()
        WalkScreen(self.lat, self.lon, bio, self.btn_place.text,
                   index=self._index_today(),
                   on_close=self._walk_done).open()

    def _index_today(self) -> dict:
        """Прогноз на сегодня по видам — снимок в поход.

        Берётся здесь, а не в экране похода: расчёт живёт на главном экране,
        и в лесу его уже не повторить — там нет сети. Если прогноз ещё не
        считался, снимок пустой, и это нормально: поход всё равно ценнее.
        """
        if self.res is None:
            return {}
        i = self.res.today
        out = {}
        for key, sp in engine.SPECIES.items():
            try:
                out[key] = round(float(self.res.value(sp.name, i)), 1)
            except (KeyError, IndexError, TypeError, ValueError):
                continue
        return out

    def _walk_done(self, walk, saved):
        # Реклама возвращается на главный экран вместе с человеком.
        ads.attach()
        if not walk.points and not walk.finds:
            return
        counts = walk.species_counts()
        rows = [f"[b]{markup.esc(walk.summary())}[/b]", ""]
        if counts:
            rows.append("Находки:")
            for key, n in counts.items():
                rows.append(f"  {engine.SPECIES[key].name}: {n} шт "
                            f"(балл обилия {track_mod.count_to_score(n)})")
        else:
            rows.append("Находок не отмечено.")
        if saved:
            rows += ["", f"[size=11sp][color=7b8272]{markup.esc(saved)}[/color][/size]"]

        # Про оборванную запись говорится сразу после похода, а не молчком.
        # Иначе человек видит короткий трек, решает, что приложение врёт, и
        # больше не берёт его в лес — при том что чинится это один раз, в
        # настройках телефона.
        import survival
        broken = survival.report(walk)
        if broken:
            rows += ["", f"[color=a8564f]{markup.esc(broken)}[/color]"]
            if survival.looks_killed(walk):
                rows += ["", markup.esc(survival.advice()),
                         "", "[size=11sp][color=7b8272]Те же кнопки — в походе, "
                             "«Приём и сервис».[/color][/size]"]
        if counts:
            try:
                import journal
                n = track_mod.to_journal(walk, journal,
                                         path=os.path.join(places_mod.data_dir(),
                                                           "journal.csv"))
                rows += ["", f"[size=11sp][color=7b8272]Записано в журнал "
                             f"наблюдений строк: {n}[/color][/size]"]
            except Exception as e:                                # noqa: BLE001
                rows += ["", f"[size=11sp][color=a8564f]Журнал: {markup.esc(e)}[/color][/size]"]
        self._sheet("Итоги похода", "\n".join(rows), 0.6)

    def pick_place(self):
        """Карта: касание ставит метку, есть поиск и список сохранённых мест."""
        PlacePicker(self.lat, self.lon, self._place_chosen).open()

    def _place_chosen(self, lat, lon):
        self.lat, self.lon = lat, lon
        spot = next((s for s in places_mod.load()
                     if abs(s.lat - lat) < 3e-4 and abs(s.lon - lon) < 3e-4), None)
        self.btn_place.text = spot.name if spot else f"{lat:.4f}, {lon:.4f}"
        if spot:
            bio = engine.BIOTOPES.get(spot.biotope)
            if bio:
                self.sp_bio.text = bio.name
        self._remember_place()
        self.calculate()

    def _reload_spots(self):
        """Перерисовывает полосу сохранённых мест."""
        row = getattr(self, "spots_row", None)
        if row is None:
            return
        row.clear_widgets()
        try:
            spots = places_mod.load()
        except (OSError, ValueError):
            spots = []
        if not spots:
            self.spots_sv.height = 0
            return
        self.spots_sv.height = dp(40)
        for spot in spots:
            b = Button(text=spot.name, size_hint=(None, None), height=dp(36),
                       width=dp(80), font_size=sp(12), background_normal="",
                       background_color=CARD, color=INK, padding=(dp(12), 0))
            # Ширина по фактической надписи: «Дальний бор» и «Ель» не должны
            # занимать одинаковое место.
            b.bind(texture_size=lambda w, t: setattr(
                w, "width", max(dp(64), t[0] + dp(24))))
            b.bind(on_release=lambda _b, sp=spot: self._use_spot(sp))
            row.add_widget(b)

    def _use_spot(self, spot):
        """Переход на сохранённое место одним касанием."""
        self.lat, self.lon = spot.lat, spot.lon
        self.btn_place.text = spot.name
        self._remember_place(spot.name)
        bio = engine.BIOTOPES.get(spot.biotope)
        if bio and self.sp_bio.text != bio.name:
            self.sp_bio.text = bio.name      # пересчёт индекса без сети
        self.calculate()

    def save_spot(self):
        """Запомнить текущую точку как место."""
        if self.res is None:
            self._sheet("Место не определено",
                        "Сначала рассчитайте прогноз — тогда точку можно запомнить.", 0.35)
            return
        from kivy.uix.textinput import TextInput as _TI
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        with box.canvas.before:
            Color(*CARD)
            rect = Rectangle(pos=box.pos, size=box.size)
        box.bind(pos=lambda w, v: setattr(rect, "pos", v),
                 size=lambda w, v: setattr(rect, "size", v))
        field = _TI(text=self.res.place.name[:40], multiline=False, size_hint_y=None,
                    height=dp(42), font_size=sp(15))
        box.add_widget(Label(text="Название места:", color=INK, size_hint_y=None,
                             height=dp(24), font_size=sp(13)))
        box.add_widget(field)
        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        ok = Button(text="Сохранить", background_normal="", background_color=ACCENT, bold=True)
        cancel = Button(text="Отмена", background_normal="", background_color=CARD, color=INK)
        btns.add_widget(cancel)
        btns.add_widget(ok)
        box.add_widget(btns)
        pop = Popup(title="Запомнить место", content=box, size_hint=(0.9, 0.4),
                    separator_color=ACCENT)

        def do_save(*_):
            name = field.text.strip()
            if name:
                bio = next((b.key for b in engine.BIOTOPES.values()
                            if b.name == self.sp_bio.text), "смешанный")
                places_mod.add(places_mod.Spot(name, self.lat, self.lon, bio))
                self._reload_spots()
                self.btn_place.text = name
                self.status.text = f"Место сохранено: {name}"
            pop.dismiss()

        ok.bind(on_release=do_save)
        cancel.bind(on_release=lambda *_: pop.dismiss())
        pop.open()

    #: Место по умолчанию для самого первого запуска.
    HOME = (55.9606, 38.0456, "Фрязино")

    @classmethod
    def _saved_place(cls):
        """Место с прошлого запуска: (широта, долгота, подпись).

        Координаты проверяются на осмысленность: испорченный файл настроек
        не должен унести человека в Атлантику, где прогноз считается вечно
        и ничем не кончается.
        """
        saved = prefs.load()
        try:
            lat = float(saved["lat"])
            lon = float(saved["lon"])
        except (KeyError, TypeError, ValueError):
            return cls.HOME
        if not (-85.0 <= lat <= 85.0 and -180.0 <= lon <= 180.0):
            return cls.HOME
        name = saved.get("place") or f"{lat:.4f}, {lon:.4f}"
        return lat, lon, str(name)[:60]

    def _remember_place(self, name=None):
        """Запоминает текущую точку. Вызывается после любого её изменения."""
        prefs.save(lat=round(self.lat, 6), lon=round(self.lon, 6),
                   place=name or self.btn_place.text)

    #: Подпись «любой вид» в списке. Пустой sel означает то же самое.
    ALL_KINDS = "Все виды сезона"

    @staticmethod
    def _saved_biotope(saved: dict) -> str:
        """Тип леса с прошлого запуска.

        Сверяемся со справочником: за обновление приложения вид или биотоп
        могли переименовать, и подставленная вслепую строка оставила бы в
        списке подпись, которой ни в одном профиле нет.
        """
        key = saved.get("biotope")
        b = engine.BIOTOPES.get(key) if key else None
        if b is None:
            return engine.BIOTOPES["смешанный"].name
        engine.set_biotope(b.key)
        return b.name

    @classmethod
    def _saved_kind(cls, saved: dict) -> str:
        name = saved.get("kind")
        if name and any(sp.name == name for sp in engine.SPECIES.values()):
            return name
        return cls.ALL_KINDS

    def _on_biotope(self, _sp, text):
        key = next((b.key for b in engine.BIOTOPES.values() if b.name == text), None)
        if not key:
            return
        engine.set_biotope(key)
        prefs.save(biotope=key)
        if self.res is not None:
            self.res = Result(self.res.place, self.res.days, self.res.today)
            self.refresh()

    def _on_kind(self, _sp, text):
        self.sel = None if text == self.ALL_KINDS else text
        prefs.save(kind="" if self.sel is None else self.sel)
        self.refresh()

    # --- вывод -------------------------------------------------------------
    def refresh(self):
        r = self.res
        if not r:
            return
        i = r.today
        v, who = (r.value(self.sel, i), self.sel) if self.sel else r.best(i)
        bg, fg = level_colors(v)
        self.card.set_bg(bg)
        self.l_main.color = fg
        self.l_main.text = f"Сегодня: {v:.0f} — {engine.level(v)}"
        peak = max((r.value(self.sel, j) if self.sel else r.best_value(j), j)
                   for j in range(i, len(r.days)))
        sub = who if (who and v >= 18) else ""
        if peak[1] != i and peak[0] > v + 6:
            sub += ("   ·   " if sub else "") + \
                f"пик {r.days[peak[1]].d.strftime('%d.%m')}: {peak[0]:.0f}"
        elif peak[0] < 18:
            sub = "выхода в ближайшие дни не ожидается"
        self.l_sub.text = sub or engine.level(v)
        self.l_sub.color = fg

        names = [self.sel] if self.sel else r.season_names()
        self.chart.set_data(r, names, self.sel or r.best(i)[1], self.show_day)

        self.list.clear_widgets()
        for j in range(i, len(r.days)):
            self.list.add_widget(DayRow(r, j, self.sel, self.show_day))

    def locate_me(self):
        """Своё положение: подписка на приёмник, первая же точка идёт в расчёт.

        Разрешение спрашивается с обратным вызовом: диалог Android
        показывается асинхронно, и запускать приёмник до ответа человека
        бессмысленно — система откажет.
        """
        import location as location_mod
        if location_mod.has_permission():
            self._locate_now()
            return
        self.status.text = "Жду разрешения на доступ к координатам…"
        location_mod.request_permission(self._on_location_permission)

    @mainthread
    def _on_location_permission(self, granted):
        if granted:
            self._locate_now()
        else:
            self._sheet("Определение координат",
                        "Разрешение на доступ к координатам не дано.\n\n"
                        "Его можно включить в настройках приложения, а место "
                        "выбрать на карте — кнопка с названием вверху экрана.",
                        0.42)

    def _locate_now(self):
        import location as location_mod
        last = location_mod.Locator(lambda *a: None).last_known()
        if last:
            self._on_gps(last[0], last[1])
            return
        self._locator = location_mod.Locator(self._on_gps)
        if self._locator.start():
            self.status.text = "Определяю координаты со спутника…"
        else:
            self._sheet("Определение координат",
                        f"Не удалось получить координаты: "
                        f"{self._locator.error or 'приёмник недоступен'}.\n\n"
                        f"Выберите место на карте — кнопка с названием вверху экрана.",
                        0.42)

    @mainthread
    def _on_gps(self, lat, lon, acc=0.0):
        if getattr(self, "_locator", None):
            self._locator.stop()
            self._locator = None
        self.lat, self.lon = float(lat), float(lon)
        self.btn_place.text = f"Моё положение · {self.lat:.4f}, {self.lon:.4f}"
        self.status.text = "Координаты определены"
        self._remember_place()
        self.calculate()

    def _sheet(self, title, text, height=0.88):
        """Читаемый попап: светлая подложка под тёмный текст."""
        box = Card(bg=CARD, padding=dp(4))
        sv = ScrollView(bar_width=dp(3))
        lbl = Label(text=text, markup=True, color=INK, font_size=sp(13),
                    halign="left", valign="top", size_hint_y=None,
                    padding=(dp(10), dp(10)))
        lbl.bind(width=lambda w, x: setattr(w, "text_size", (x - dp(22), None)),
                 texture_size=lambda w, t: setattr(w, "height", t[1] + dp(20)))
        sv.add_widget(lbl)
        box.add_widget(sv)
        Popup(title=title, content=box, size_hint=(0.94, height),
              separator_color=ACCENT, title_size=sp(15)).open()

    def show_help(self):
        self._sheet("Как работает прогноз", HELP)

    def show_premium(self):
        premium_screen.show(on_unlocked=self._premium_unlocked)

    def _premium_unlocked(self):
        """Кнопка «Без рекламы» исчезает из шапки сразу после покупки —
        предлагать купить то, что уже куплено, незачем."""
        if self.b_premium is not None and self.b_premium.parent is not None:
            self.b_premium.parent.remove_widget(self.b_premium)
            self.b_premium = None

    def show_day(self, i):
        r = self.res
        d = r.days[i]
        rows = [f"[b]{d.d.strftime('%d.%m.%Y')}[/b]",
                f"Осадки: {d.precip:.1f} мм",
                f"Воздух: {d.tmean:.1f} °C  ({d.tmin:.0f}…{d.tmax:.0f})",
                f"Почва: {r.ts[i]:.1f} °C",
                f"Влагозапас: {r.m[i]*100:.0f}%", ""]
        dsr = engine.days_since_rain(i, r.days)
        rows.append("Последний дождь ≥5 мм: " +
                    (f"{dsr} сут назад" if dsr is not None else "не было за месяц"))
        src_w, src_t = engine.sources(r.days)
        rows.append(f"[size=11sp][color=7b8272]влага: {src_w}; "
                    f"T почвы: {src_t}\nлес: {engine.CURRENT_BIOTOPE.name}"
                    f"\nмодель: {engine.calibration_info()}[/color][/size]")
        rows.append("")
        for n in sorted(r.season_names(), key=lambda n: -r.value(n, i))[:6]:
            rows.append(f"{n}: [b]{r.value(n, i):.0f}[/b] — {engine.level(r.value(n, i))}")
        spec = next(x for x in engine.SPECIES.values()
                    if x.name == (self.sel or r.best(i)[1]))
        rows += ["", f"[b]Почему такой индекс — {spec.name.lower()}[/b]",
                 "[size=11sp]Индекс — произведение сомножителей;",
                 "самый короткий столбик и есть причина.[/size]", ""]
        for nm, val, why in engine.explain(spec, i, r.days, r.m, r.ts):
            filled = int(round(val * 10))
            rows.append(f"{nm}  [b]{val*100:.0f}%[/b]")
            # Полоска набрана длинными тире, а не блоками «▇»: блочных знаков
            # в шрифте Kivy нет, и на телефоне вместо столбика выходил ряд
            # пустых квадратов — то есть объяснение «почему такой индекс»
            # не работало ровно там, где его читают.
            rows.append(f"[size=15sp][color=3e7d2c]{BAR * filled}[/color]"
                        f"[color=cfd4c8]{BAR * (10 - filled)}[/color][/size]")
            rows.append(f"[size=11sp][color=7b8272]{why}[/color][/size]")
        rows += ["", "[i]" + engine.plain_summary(spec, i, r.days, r.m, r.ts,
                                                  r.value(spec.name, i)) + "[/i]"]
        self._sheet(d.d.strftime("%d.%m.%Y"), "\n".join(rows), 0.82)


HELP = """[b]Что показывает индекс[/b]
Оценка шансов застать плодоношение в типичном для вида лесу, 0–100. Не количество
грибов и не гарантия: программа знает погоду, но не знает ваш лес и грибные места.

[b]Откуда данные[/b]
Погода с сервиса Open-Meteo: 31 сутки назад и до 16 суток вперёд. История нужна не
меньше прогноза — гриб, который вылезет послезавтра, заложился неделю назад.

[b]Как считается[/b]
1. [b]Влага почвы.[/b] Берётся из погодной модели — влажность слоя 0–7 см,
пересчитанная в долю доступной растениям влаги. Резерв, если слоя нет: резервуар
подстилки 55 мм, где дождь пополняет, а испарение опустошает.
2. [b]Температура почвы.[/b] Тоже из модели, слой 0–7 см. Резерв — сглаженная
температура воздуха с задержкой около трёх суток.
3. [b]Закладка.[/b] Влага × температура × импульс дождя. Плодоношение — реакция на
[i]событие[/i] увлажнения, а не на ровную сырость: после ливня будет волна, под
непрерывной моросью — умеренный фон.
4. [b]Лаг вида.[/b] Заложенное сегодня вылезает через 3–16 суток: маслёнок за 3–7,
белый за 6–12, опёнок за 8–16.
5. [b]Поправки.[/b] Сезон месяца, гибель урожая от заморозка и жары, для осеннего
опёнка — обязательный триггер похолодания.

[b]Как пользоваться[/b]
Смотрите не на само число, а на форму волны: где подъём, где пик — в сроках модель
точнее, чем в амплитуде. Тап по строке дня показывает разбор: что именно тормозит.

[b]Чего программа не умеет[/b]
Не знает тип леса и почвы, экспозицию склона, микроклимат низин и состояние мицелия.
Модель эвристическая, константы подобраны по литературе, а не по вашим наблюдениям."""


def _isnum(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _show_crash(text: str):
    """Аварийный экран: если основное приложение не поднялось."""
    try:
        from kivy.app import App as _App
        from kivy.uix.label import Label as _Label
        from kivy.uix.scrollview import ScrollView as _SV

        class Crash(_App):
            title = "Ошибка запуска"

            def build(self):
                sv = _SV()
                lbl = _Label(text=text, font_size="12sp", halign="left", valign="top",
                             size_hint_y=None, padding=(10, 10))
                lbl.bind(width=lambda w, x: setattr(w, "text_size", (x - 20, None)),
                         texture_size=lambda w, t: setattr(w, "height", t[1] + 20))
                sv.add_widget(lbl)
                return sv

        Crash().run()
    except BaseException:                                         # noqa: BLE001
        pass


if __name__ == "__main__":
    try:
        MushroomApp().run()
    except BaseException:                                         # noqa: BLE001
        tb = traceback.format_exc()
        path = _log_crash(tb)
        _show_crash(f"Приложение не запустилось.\n\n{tb}\nПротокол: {path}")
