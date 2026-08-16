# -*- coding: utf-8 -*-
"""
mapview.py — выбор точки на карте для мобильной версии.

Тайлы OpenStreetMap рисуются средствами Kivy, скачиваются встроенным
UrlRequest и кэшируются в каталоге приложения. Никаких сторонних пакетов:
kivy_garden.mapview тянет requests и свой рецепт сборки, а здесь всё
укладывается в математику Web Mercator и штатные средства.

Если тайлы не грузятся (нет сети), карта продолжает работать как
координатная сетка: касание всё равно даёт верные широту и долготу.

Данные карты © OpenStreetMap contributors, ODbL.
"""

from __future__ import annotations

import math
import os
import threading

from kivy.clock import mainthread
from kivy.core.image import Image as CoreImage
from kivy.core.text import Label as CoreLabel
from kivy.graphics import (Color, Ellipse, Line, Mesh, Rectangle, StencilPop,
                           StencilPush, StencilUnUse, StencilUse)
from kivy.metrics import dp, sp
from kivy.network.urlrequest import UrlRequest
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import get_color_from_hex as hexc

import palette
import tilesource

import mushroom_forecast as engine
import places as places_mod

TILE = 256
MIN_Z, MAX_Z = 3, 17
# Адрес тайлов намеренно не зашит в код: правила OSM это прямо советуют, а
# офлайн-карта вообще требует другого источника — см. tilesource.py.
UA = "mushroom-forecast/2.9 (personal use)"

INK = hexc(palette.INK)
MUTED = hexc(palette.MUTED)
CARD = hexc(palette.CARD)
ACCENT = hexc(palette.ACCENT)
GRIDC = hexc("#D5D0C4")


# --------------------------------------------------------------------------- #
#  Проекция
# --------------------------------------------------------------------------- #

def deg2num(lat: float, lon: float, z: int) -> tuple[float, float]:
    n = 2.0 ** z
    lat = max(-85.0511, min(85.0511, lat))
    r = math.radians(lat)
    return ((lon + 180.0) / 360.0 * n,
            (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n)


def num2deg(x: float, y: float, z: int) -> tuple[float, float]:
    n = 2.0 ** z
    return (math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n)))),
            x / n * 360.0 - 180.0)


# --------------------------------------------------------------------------- #
#  Карта
# --------------------------------------------------------------------------- #

class TileMap(Widget):
    """Панорамируемая карта. Перетаскивание — сдвиг, касание — метка."""

    def __init__(self, lat=55.9606, lon=38.0456, zoom=11, on_pick=None, **kw):
        super().__init__(**kw)
        self.zoom = zoom
        self.cx, self.cy = deg2num(lat, lon, zoom)
        self.marker = (lat, lon)
        self.on_pick = on_pick
        self._tex: dict = {}
        self._pending: set = set()
        self._offline = False
        self._moved = False
        self._touches: dict = {}
        self._pinch = None
        self.walk = None          # track.Walk — рисуется траектория и находки
        self.history = None       # history.History — прошлые походы подложкой
        self.show_history = True  # слой можно выключить кнопкой
        self.on_spot = None       # касание по старой находке: f(spot)
        self.here = None          # текущее положение (lat, lon)
        self.heading = None       # куда повёрнут человек, градусы от севера
        self.follow = False       # держать текущее положение в центре
        self.bind(pos=self.redraw, size=self.redraw)

    # --- кэш тайлов ---------------------------------------------------------
    def _dir(self) -> str:
        d = os.path.join(places_mod.data_dir(), "tiles")
        os.makedirs(d, exist_ok=True)
        return d

    def _path(self, z, x, y) -> str:
        return os.path.join(self._dir(), f"{z}_{x}_{y}.png")

    def _tile(self, z, x, y):
        key = (z, x, y)
        if key in self._tex:
            return self._tex[key]
        path = self._path(z, x, y)
        if os.path.exists(path):
            try:
                tex = CoreImage(path).texture
                self._tex[key] = tex
                return tex
            except Exception:                                     # noqa: BLE001
                try:
                    os.remove(path)
                except OSError:
                    pass
        if key not in self._pending and len(self._pending) < 12:
            self._pending.add(key)
            UrlRequest(tilesource.url().format(z=z, x=x, y=y),
                       req_headers={"User-Agent": UA},
                       on_success=lambda req, res, k=key: self._got(k, res),
                       on_failure=lambda req, res, k=key: self._failed(k),
                       on_error=lambda req, err, k=key: self._failed(k),
                       decode=False, timeout=20)
        return None

    @mainthread
    def _got(self, key, result):
        self._pending.discard(key)
        data = result if isinstance(result, bytes) else None
        if not data:
            self._offline = True
            self.redraw()
            return
        try:
            with open(self._path(*key), "wb") as f:
                f.write(data)
        except OSError:
            pass
        self._offline = False
        self.redraw()

    @mainthread
    def _failed(self, key):
        self._pending.discard(key)
        self._offline = True
        self.redraw()

    # --- координаты ---------------------------------------------------------
    def _screen(self, lat, lon):
        x, y = deg2num(lat, lon, self.zoom)
        return (self.center_x + (x - self.cx) * TILE,
                self.center_y - (y - self.cy) * TILE)

    def _latlon(self, px, py):
        x = self.cx + (px - self.center_x) / TILE
        y = self.cy - (py - self.center_y) / TILE
        return num2deg(x, y, self.zoom)

    def center_on(self, lat, lon, zoom=None):
        if zoom is not None:
            self.zoom = max(MIN_Z, min(MAX_Z, int(zoom)))
        self.cx, self.cy = deg2num(lat, lon, self.zoom)
        self.redraw()

    def set_here(self, lat, lon):
        """Текущее положение; при включённом слежении карта едет за ним."""
        self.here = (lat, lon)
        if self.follow:
            self.center_on(lat, lon)
        else:
            self.redraw()

    def set_marker(self, lat, lon):
        self.marker = (lat, lon)
        if self.on_pick:
            self.on_pick(lat, lon)
        self.redraw()

    def fit(self, points, pad=0.18, max_zoom=MAX_Z) -> bool:
        """Подбирает центр и масштаб так, чтобы все точки попали на экран.

        Отвечает на вопрос «где я относительно машины», который иначе решается
        прокруткой карты пальцем — а прокрутив, человек теряет своё положение
        и включает слежение обратно.

        pad — доля пустого поля по краям: точка вплотную к рамке наполовину
        срезается собственным значком.
        """
        pts = [(float(a), float(b)) for a, b in points if a is not None]
        if not pts or self.width <= 1 or self.height <= 1:
            return False
        lo_lat = min(p[0] for p in pts)
        hi_lat = max(p[0] for p in pts)
        lo_lon = min(p[1] for p in pts)
        hi_lon = max(p[1] for p in pts)

        best = MIN_Z
        for z in range(MIN_Z, min(int(max_zoom), MAX_Z) + 1):
            x0, y0 = deg2num(hi_lat, lo_lon, z)          # верхний левый угол
            x1, y1 = deg2num(lo_lat, hi_lon, z)
            w = (x1 - x0) * TILE
            h = (y1 - y0) * TILE
            if w <= self.width * (1 - pad) and h <= self.height * (1 - pad):
                best = z
            else:
                break
        self.zoom = best
        # Центр считается в координатах проекции, а не как среднее широт:
        # у Меркатора градус широты по высоте не постоянен, и трек, вытянутый
        # с севера на юг, уезжал бы вниз экрана.
        x0, y0 = deg2num(hi_lat, lo_lon, best)
        x1, y1 = deg2num(lo_lat, hi_lon, best)
        self.cx, self.cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        self.redraw()
        return True

    def zoom_by(self, step):
        lat, lon = self._latlon(self.center_x, self.center_y)
        self.zoom = max(MIN_Z, min(MAX_Z, self.zoom + step))
        self.center_on(lat, lon)

    # --- ввод ---------------------------------------------------------------
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        self._touches[touch.uid] = touch.pos
        self._moved = False
        if len(self._touches) == 2:
            a, b = list(self._touches.values())
            self._pinch = math.dist(a, b)
        touch.grab(self)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return False
        self._touches[touch.uid] = touch.pos
        if len(self._touches) >= 2:
            a, b = list(self._touches.values())[:2]
            d = math.dist(a, b)
            if self._pinch and abs(d - self._pinch) > dp(60):
                self.zoom_by(1 if d > self._pinch else -1)
                self._pinch = d
            self._moved = True
            return True
        if abs(touch.dx) + abs(touch.dy) > dp(2):
            self._moved = True
        self.cx -= touch.dx / TILE
        self.cy += touch.dy / TILE
        self.redraw()
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return False
        touch.ungrab(self)
        self._touches.pop(touch.uid, None)
        if not self._touches:
            self._pinch = None
            if not self._moved and self.collide_point(*touch.pos):
                # Касание по старому месту находок открывает его карточку.
                # Метка при этом не двигается: человек целился в точку, а не
                # в пустое место, и увести из-под пальца ориентир обиднее,
                # чем не поставить метку.
                spot = self._spot_at(*touch.pos)
                if spot is not None:
                    self.on_spot(spot)
                    return True
                self.set_marker(*self._latlon(*touch.pos))
        return True

    # --- отрисовка ----------------------------------------------------------
    def set_heading(self, deg):
        """Куда повёрнут человек. None — направление неизвестно."""
        new = None if deg is None else float(deg) % 360.0
        if new is None and self.heading is None:
            return
        # Перерисовывать карту ради поворота на полградуса незачем: тайлы
        # тяжёлые, а стрелка всё равно дрожит в пределах точности компаса.
        if (new is not None and self.heading is not None
                and abs((new - self.heading + 180.0) % 360.0 - 180.0) < 2.0):
            return
        self.heading = new
        self.redraw()

    def _draw_here(self, x, y):
        """Своё положение: круг точности, а поверх — стрелка направления.

        Стрелка вместо точки затем же, зачем она в автомобильных
        навигаторах: точка говорит только «вы здесь», а на развилке нужно
        знать, куда вы смотрите. Соотнести карту с местностью по стрелке
        можно не задумываясь, а по отдельному компасу под картой — только
        переводя взгляд и в уме поворачивая одно относительно другого.

        Направление неизвестно (компаса нет, человек стоит) — рисуется
        обычная точка: врущая стрелка хуже её отсутствия.
        """
        Color(0.12, 0.45, 0.85, 0.22)
        Ellipse(pos=(x - dp(18), y - dp(18)), size=(dp(36), dp(36)))

        if self.heading is None:
            Color(1, 1, 1, 1)
            Ellipse(pos=(x - dp(9), y - dp(9)), size=(dp(18), dp(18)))
            Color(*hexc(palette.BLUE))
            Ellipse(pos=(x - dp(7), y - dp(7)), size=(dp(14), dp(14)))
            return

        a = math.radians(self.heading)
        sin_a, cos_a = math.sin(a), math.cos(a)

        def pt(dx, dy):
            """Локальные координаты стрелки поворачиваются по часовой:
            ноль градусов — остриё вверх, на север."""
            return (x + dx * cos_a + dy * sin_a,
                    y - dx * sin_a + dy * cos_a)

        tip = pt(0, dp(15))
        left = pt(-dp(9), -dp(9))
        right = pt(dp(9), -dp(9))
        notch = pt(0, -dp(4))          # выемка сзади: остриё видно сразу

        # Белая подложка: над тёмным лесом и над светлой вырубкой стрелка
        # должна читаться одинаково.
        Color(1, 1, 1, 1)
        Line(points=[*left, *tip, *right, *notch, *left],
             width=dp(3.4), joint="round", cap="round", close=True)
        Color(*hexc(palette.BLUE))
        Mesh(vertices=[tip[0], tip[1], 0, 0,
                       left[0], left[1], 0, 0,
                       notch[0], notch[1], 0, 0,
                       right[0], right[1], 0, 0],
             indices=[0, 1, 2, 0, 2, 3], mode="triangles")

    def _text(self, s, x, y, size=9, color=MUTED):
        lbl = CoreLabel(text=s, font_size=sp(size))
        lbl.refresh()
        Color(*color)
        Rectangle(texture=lbl.texture, pos=(x, y), size=lbl.texture.size)

    # --- слой прошлых походов ----------------------------------------------
    #
    # Подложка, а не полноценная карта: старые маршруты нужны боковым зрением
    # («сюда я уже ходил»), а внимание должно оставаться на живом треке и на
    # своей точке. Поэтому нитки тонкие и блёклые, а всё яркое — сегодняшнее.

    #: Насколько блёклой рисуется нитка старого маршрута.
    OLD_TRAIL_A = 0.38

    #: Радиус, в котором касание считается попаданием по старой находке.
    SPOT_TOUCH = dp(18)

    def _spot_radius(self, spot):
        """Размер точки места: чем больше там брали, тем крупнее.

        Логарифм, а не пропорция: между «взял 2» и «взял 10» разница важная,
        между «40» и «80» — уже нет, а точка размером с полэкрана закрыла бы
        сам лес.
        """
        return dp(3.5) + dp(3.5) * min(1.0, math.log10(max(1, spot.count)) / 1.6)

    def _spot_color(self, spot):
        """Цвет по виду — тот же, что в легенде графика на главном экране."""
        sp_obj = engine.SPECIES.get(spot.species)
        if sp_obj is None:
            return hexc("#8A8F7E")
        return hexc(palette.SPECIES.get(sp_obj.name, "#8A8F7E"))

    def _visible(self, lat, lon, margin=TILE) -> bool:
        x, y = self._screen(lat, lon)
        return (self.x - margin <= x <= self.right + margin
                and self.y - margin <= y <= self.top + margin)

    def _draw_history(self):
        h = self.history
        # Маршруты. Отсекаем по описанному прямоугольнику: в лесу карта
        # сдвигается на каждый тик GPS, и гонять через проекцию точки
        # соседнего района незачем.
        Color(0.36, 0.42, 0.31, self.OLD_TRAIL_A)
        for tr in h.trails:
            lo_lat, lo_lon, hi_lat, hi_lon = tr.bbox()
            x0, y0 = self._screen(lo_lat, lo_lon)
            x1, y1 = self._screen(hi_lat, hi_lon)
            if (max(x0, x1) < self.x - TILE or min(x0, x1) > self.right + TILE
                    or max(y0, y1) < self.y - TILE
                    or min(y0, y1) > self.top + TILE):
                continue
            pts = []
            for lat, lon in tr.points:
                px, py = self._screen(lat, lon)
                pts += [px, py]
            if len(pts) >= 4:
                Line(points=pts, width=dp(1.1), joint="round", cap="round")

        # Места находок.
        for s in h.spots:
            if not self._visible(s.lat, s.lon):
                continue
            x, y = self._screen(s.lat, s.lon)
            r = self._spot_radius(s)
            # Светлый ободок: без него точка теряется и на тёмном ельнике,
            # и на светлой вырубке.
            Color(1, 1, 1, 0.7)
            Ellipse(pos=(x - r - dp(1.2), y - r - dp(1.2)),
                    size=(2 * (r + dp(1.2)), 2 * (r + dp(1.2))))
            c = self._spot_color(s)
            Color(c[0], c[1], c[2], 0.7)
            Ellipse(pos=(x - r, y - r), size=(2 * r, 2 * r))

    def _spot_at(self, px, py):
        """Старая находка под пальцем или None."""
        if not (self.history and self.show_history and self.on_spot):
            return None
        best, best_d = None, self.SPOT_TOUCH
        for s in self.history.spots:
            x, y = self._screen(s.lat, s.lon)
            d = math.hypot(x - px, y - py)
            if d <= best_d:
                best, best_d = s, d
        return best

    def redraw(self, *_):
        self.canvas.clear()
        n = 2 ** self.zoom
        half_w = self.width / 2 / TILE
        half_h = self.height / 2 / TILE
        x0, x1 = int(math.floor(self.cx - half_w)), int(math.ceil(self.cx + half_w))
        y0, y1 = int(math.floor(self.cy - half_h)), int(math.ceil(self.cy + half_h))
        missing = 0
        with self.canvas:
            # отсечение: тайлы не должны вылезать за границы виджета
            StencilPush()
            Rectangle(pos=self.pos, size=self.size)
            StencilUse()
            Color(0.91, 0.90, 0.86, 1)
            Rectangle(pos=self.pos, size=self.size)
            for tx in range(x0, x1 + 1):
                for ty in range(y0, y1 + 1):
                    if not (0 <= ty < n):
                        continue
                    sx = self.center_x + (tx - self.cx) * TILE
                    sy = self.center_y - (ty - self.cy) * TILE - TILE
                    tex = self._tile(self.zoom, tx % n, ty)
                    if tex is not None:
                        Color(1, 1, 1, 1)
                        Rectangle(texture=tex, pos=(sx, sy), size=(TILE, TILE))
                    else:
                        missing += 1
                        Color(*GRIDC)
                        Line(rectangle=(sx, sy, TILE, TILE), width=1)
                        if self._offline:
                            lat, lon = num2deg(tx, ty, self.zoom)
                            self._text(f"{lat:.2f}, {lon:.2f}", sx + dp(5),
                                       sy + TILE - dp(16), 8)
            # Прошлые походы — под всем сегодняшним: подложка не должна
            # спорить с живым треком и своей точкой.
            if self.history is not None and self.show_history:
                self._draw_history()

            # Начало маршрута: заметная точка. Раньше при одной записанной
            # координате не рисовалось ничего, и человек думал, что запись
            # не идёт, хотя она шла — просто он ещё не отошёл от машины.
            if self.walk is not None and len(self.walk.points) == 1:
                p0 = self.walk.points[0]
                x, y = self._screen(p0.lat, p0.lon)
                Color(1, 1, 1, 0.85)
                Line(circle=(x, y, dp(6)), width=dp(3.0))
                Color(*hexc(palette.BLUE))
                Line(circle=(x, y, dp(6)), width=dp(1.8))

            # траектория похода
            if self.walk is not None and len(self.walk.points) >= 2:
                pts = []
                for p in self.walk.points:
                    x, y = self._screen(p.lat, p.lon)
                    pts += [x, y]
                Color(1, 1, 1, 0.85)
                Line(points=pts, width=dp(3.4), joint="round", cap="round")
                Color(*hexc(palette.BLUE))
                Line(points=pts, width=dp(2.0), joint="round", cap="round")
                # начало маршрута кружком: к нему ведёт кнопка «К машине»
                Color(1, 1, 1, 0.9)
                Line(circle=(pts[0], pts[1], dp(6)), width=dp(3.0))
                Color(*hexc(palette.BLUE))
                Line(circle=(pts[0], pts[1], dp(6)), width=dp(1.8))

            # находки
            if self.walk is not None:
                for f in self.walk.finds:
                    x, y = self._screen(f.lat, f.lon)
                    Color(1, 1, 1, 0.9)
                    Ellipse(pos=(x - dp(7), y - dp(7)), size=(dp(14), dp(14)))
                    Color(*hexc(palette.RED))
                    Ellipse(pos=(x - dp(5), y - dp(5)), size=(dp(10), dp(10)))

            # текущее положение
            if self.here:
                self._draw_here(*self._screen(*self.here))

            # метка
            if self.marker:
                mx, my = self._screen(*self.marker)
                Color(1, 1, 1, 1)
                Line(points=[mx, my, mx, my + dp(16)], width=dp(2.5))
                Color(0.78, 0.23, 0.17, 1)
                Line(points=[mx, my, mx, my + dp(14)], width=dp(1.6))
                Ellipse(pos=(mx - dp(7), my + dp(11)), size=(dp(14), dp(14)))
            # атрибуция
            Color(1, 1, 1, 0.75)
            Rectangle(pos=(self.right - dp(150), self.y), size=(dp(150), dp(15)))
            self._text(tilesource.attribution(), self.right - dp(146),
                       self.y + dp(2), 8, hexc("#4A5142"))
            if self._offline and missing:
                Color(1, 0.96, 0.90, 0.95)
                Rectangle(pos=(self.x, self.top - dp(20)), size=(self.width, dp(20)))
                self._text("Карта не загружается — координаты по касанию верны",
                           self.x + dp(6), self.top - dp(16), 9, hexc("#8A5A1A"))
            StencilUnUse()
            Rectangle(pos=self.pos, size=self.size)
            StencilPop()


# --------------------------------------------------------------------------- #
#  Экран выбора места
# --------------------------------------------------------------------------- #

class PlacePicker(Popup):
    """Карта, поиск по названию и список сохранённых мест в одном окне."""

    def __init__(self, lat, lon, on_done, **kw):
        self.lat, self.lon = lat, lon
        self.on_done = on_done
        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        with root.canvas.before:
            Color(*CARD)
            self._bg = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=lambda w, v: setattr(self._bg, "pos", v),
                  size=lambda w, v: setattr(self._bg, "size", v))

        spots = places_mod.load()
        if spots:
            self.sp_saved = Spinner(text="Мои места", size_hint_y=None, height=dp(40),
                                    font_size=sp(13), background_normal="",
                                    background_color=hexc(palette.SOFT), color=INK,
                                    values=[s.name for s in spots])
            self.sp_saved.bind(text=self._pick_saved)
            root.add_widget(self.sp_saved)

        search = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.ti = TextInput(hint_text="Населённый пункт, например Щёлково",
                            multiline=False, font_size=sp(14),
                            padding=(dp(10), dp(11)))
        self.ti.bind(on_text_validate=lambda *_: self.search())
        search.add_widget(self.ti)
        b_find = Button(text="Найти", size_hint_x=None, width=dp(72), font_size=sp(13),
                        background_normal="", background_color=hexc(palette.SOFT), color=INK)
        b_find.bind(on_release=lambda *_: self.search())
        search.add_widget(b_find)
        root.add_widget(search)

        self.map = TileMap(lat, lon, 11, on_pick=self._picked)
        root.add_widget(self.map)
        # Свои прошлые находки видны и здесь: выбор места для прогноза чаще
        # всего и есть выбор «куда съездить», а решают его те же точки, что
        # и в лесу. Касание тут по-прежнему ставит метку — карточка находки
        # открывается только в походе, где от неё можно идти по стрелке.
        threading.Thread(target=self._load_history, daemon=True).start()

        zrow = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        for txt, step in (("–", -1), ("+", 1)):
            b = Button(text=txt, font_size=sp(18), bold=True, size_hint_x=None,
                       width=dp(52), background_normal="",
                       background_color=hexc(palette.SOFT), color=INK)
            b.bind(on_release=lambda _b, s=step: self.map.zoom_by(s))
            zrow.add_widget(b)
        self.lbl = Label(text=f"{lat:.5f}, {lon:.5f}", color=MUTED, font_size=sp(12),
                         halign="left", valign="middle")
        self.lbl.bind(size=lambda w, s: setattr(w, "text_size", s))
        zrow.add_widget(self.lbl)
        root.add_widget(zrow)

        # Кнопка сохранения карты стоит здесь, а не на главном экране:
        # человек уже смотрит на нужный кусок местности и видит, что именно
        # сохраняет. На главном экране это была бы кнопка «сохранить
        # неизвестно что».
        b_offline = Button(text="Сохранить карту для леса", size_hint_y=None,
                           height=dp(44), font_size=sp(13), background_normal="",
                           background_color=hexc(palette.SOFT), color=INK)
        b_offline.bind(on_release=lambda *_: self._save_offline())
        root.add_widget(b_offline)

        btns = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        cancel = Button(text="Отмена", background_normal="", background_color=CARD,
                        color=INK, font_size=sp(14))
        cancel.bind(on_release=lambda *_: self.dismiss())
        ok = Button(text="Считать здесь", background_normal="", background_color=ACCENT,
                    bold=True, font_size=sp(14))
        ok.bind(on_release=self._accept)
        btns.add_widget(cancel)
        btns.add_widget(ok)
        root.add_widget(btns)

        super().__init__(title="Где считать прогноз", content=root,
                         size_hint=(0.96, 0.92), separator_color=ACCENT,
                         title_size=sp(15), **kw)

    def _load_history(self):
        """Слой прошлых походов. Ошибку глотаем: карта важнее подложки."""
        try:
            import history as history_mod
            h = history_mod.load()
        except Exception:                                         # noqa: BLE001
            return
        self._history_ready(h)

    @mainthread
    def _history_ready(self, h):
        self.map.history = h
        self.map.redraw()

    def _save_offline(self):
        """Скачать квадрат карты вокруг выбранной точки."""
        import offlinemap
        offlinemap.show(self.lat, self.lon, self.ti.text.strip())

    def _picked(self, lat, lon):
        self.lat, self.lon = lat, lon
        self.lbl.text = f"{lat:.5f}, {lon:.5f}"

    def _pick_saved(self, _sp, name):
        spot = next((s for s in places_mod.load() if s.name == name), None)
        if spot:
            self.map.center_on(spot.lat, spot.lon, 12)
            self.map.set_marker(spot.lat, spot.lon)

    def search(self):
        name = self.ti.text.strip()
        if not name:
            return
        self.lbl.text = "Ищу…"
        threading.Thread(target=self._search_worker, args=(name,), daemon=True).start()

    def _search_worker(self, name):
        try:
            place = engine.geocode(name)
        except BaseException as e:                                # noqa: BLE001
            self._search_done(None, str(e))
            return
        self._search_done(place, "")

    @mainthread
    def _search_done(self, place, err):
        if place is None:
            self.lbl.text = err[:70]
            return
        self.map.center_on(place.lat, place.lon, 12)
        self.map.set_marker(place.lat, place.lon)
        self.ti.text = place.name

    def _accept(self, *_):
        self.dismiss()
        if self.on_done:
            self.on_done(self.lat, self.lon)
