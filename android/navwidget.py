# -*- coding: utf-8 -*-
"""
navwidget.py — стрелка «куда идти» поверх карты.

Виджет намеренно тупой: он ничего не вычисляет, а только рисует то, что ему
дали в set_fix(). Вся арифметика — в nav.py, который проверяется тестами
на компьютере. Здесь остаётся то, что тестами не покроешь: линии и цвета.

Читаемость важнее красоты: в лесу телефон смотрят на ходу, в перчатках,
против солнца. Поэтому стрелка крупная и одноцветная, а текст под ней
короткий — «↑ прямо · 740 м».

Полоса появляется только при включённой навигации к метке. Направление
«куда я смотрю» показывает не она, а сама стрелка на карте (mapview) —
отдельный прибор под картой заставлял переводить взгляд и в уме поворачивать
одно относительно другого.
"""

from __future__ import annotations

import math

from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Ellipse, Line, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.widget import Widget
from kivy.utils import get_color_from_hex as hexc

import palette

INK = hexc(palette.INK)
MUTED = hexc(palette.MUTED)
ACCENT = hexc(palette.ACCENT)
ARRIVED = hexc(palette.BLUE)


class NavArrow(Widget):
    """Круг со стрелкой: направление на цель и расстояние до неё."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.fix = None
        self.title = ""
        self.bind(pos=self.redraw, size=self.redraw)

    def set_fix(self, fix, title=""):
        """fix — объект nav.Fix или None, чтобы спрятать стрелку."""
        self.fix = fix
        self.title = title
        self.redraw()

    def _text(self, s, cx, y, size=11, color=MUTED, bold=False):
        lbl = CoreLabel(text=s, font_size=sp(size), bold=bold)
        lbl.refresh()
        t = lbl.texture
        Color(*color)
        Rectangle(texture=t, pos=(cx - t.width / 2, y), size=t.size)

    def redraw(self, *_):
        self.canvas.clear()
        if not self.fix:
            return
        f = self.fix
        col = ARRIVED if f.arrived else ACCENT
        cx = self.center_x
        r = min(self.height * 0.42, dp(46))
        cy = self.top - r - dp(4)

        with self.canvas:
            # круг-циферблат
            Color(col[0], col[1], col[2], 0.10)
            Ellipse(pos=(cx - r, cy - r), size=(2 * r, 2 * r))
            Color(col[0], col[1], col[2], 0.55)
            Line(circle=(cx, cy, r), width=dp(1.2))

            if f.arrived:
                # дошли: галочка вместо стрелки
                Color(*col)
                Line(points=[cx - r * 0.35, cy,
                             cx - r * 0.08, cy - r * 0.3,
                             cx + r * 0.4, cy + r * 0.35],
                     width=dp(3), cap="round", joint="round")
            else:
                a = math.radians(f.arrow_deg)      # 0 — вверх, по часовой
                sin_a, cos_a = math.sin(a), math.cos(a)

                def pt(dx, dy):
                    """Поворот точки локальных координат стрелки."""
                    return (cx + dx * cos_a + dy * sin_a,
                            cy - dx * sin_a + dy * cos_a)

                tip = pt(0, r * 0.78)
                left = pt(-r * 0.42, -r * 0.45)
                right = pt(r * 0.42, -r * 0.45)
                tail = pt(0, -r * 0.18)

                Color(*col)
                Line(points=[*left, *tip, *right], width=dp(3.4),
                     cap="round", joint="round")
                Line(points=[*tail, *tip], width=dp(3.4), cap="round")

                # север на ободе — чтобы стрелку можно было соотнести с картой
                if f.course is not None:
                    na = math.radians(-f.course % 360.0)
                    nx = cx + math.sin(na) * r
                    ny = cy + math.cos(na) * r
                    Color(MUTED[0], MUTED[1], MUTED[2], 0.8)
                    Line(circle=(nx, ny, dp(3)), width=dp(1.4))
                    self._text("С", nx, ny + dp(5), 8, MUTED)

            y = cy - r - dp(20)
            if self.title:
                self._text(self.title, cx, y + dp(16), 10, MUTED)
            self._text(f.text, cx, y, 15, INK, bold=True)
            if f.detail:
                self._text(f.detail, cx, y - dp(15), 10, MUTED)
