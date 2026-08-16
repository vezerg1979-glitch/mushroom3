# -*- coding: utf-8 -*-
"""
icons.py — значки кнопок, нарисованные линиями, а не шрифтом.

Зачем. Кнопки доната и журнала были подписаны символами «♥» и «≡». На
компьютере при отладке они рисуются, потому что системный шрифт полный. На
телефоне Kivy берёт свой Roboto, в котором этих знаков нет, и человек видит
пустой квадрат с крестом — «сломанная кнопка», нажимать которую страшно.
Символ вместо надписи вообще ненадёжен: набор глифов зависит от шрифта,
прошивки и версии Android, и проверить это на своём телефоне недостаточно.

Поэтому значки здесь — геометрия, а не текст. Функция shapes() возвращает
список примитивов в координатах Kivy (начало отсчёта — левый нижний угол),
IconButton переводит их в инструкции холста. Геометрия отделена от виджета
не ради красоты: так её проверяет тест на компьютере, где Kivy не поднять.

Все размеры считаются от стороны значка, поэтому одна и та же кнопка годится
и на 48 dp в строке, и крупнее в диалоге.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
#  Геометрия
# --------------------------------------------------------------------------- #
#
# Примитивы:
#   ("ellipse", x, y, w, h)               — залитый овал по описанному прямоугольнику
#   ("quad", (x1, y1, ... x4, y4))        — залитый четырёхугольник
#   ("line", (x1, y1, x2, y2, ...), lw)   — ломаная толщиной lw
#   ("rrect", x, y, w, h, r, lw)          — контур прямоугольника со скруглением r

# Доля кнопки, которую занимает значок. Меньше — значок теряется, больше —
# упирается в края и выглядит случайно попавшим в кнопку.
FILL = 0.52


def heart(x: float, y: float, w: float, h: float) -> list:
    """Сердце: квадрат, повёрнутый на 45°, и два полукруга на верхних сторонах.

    Классическое построение — оно даёт ровно тот силуэт, который человек ждёт
    от «♥», без подгонки кривых на глаз.
    """
    s = min(w, h)
    # Ширина фигуры выходит 1.2071 диагонали, высота — 1.1036. Считаем от
    # ширины, иначе на узкой кнопке сердце вылезет за края.
    d = s / 1.2071
    cx = x + w / 2.0
    # Центр описанного прямоугольника выше центра квадрата: сверху полукруги.
    cy = y + h / 2.0 - 0.0518 * d

    r = 0.35355 * d                      # половина стороны квадрата
    out = []
    for sign in (-1.0, 1.0):
        ccx = cx + sign * 0.25 * d
        ccy = cy + 0.25 * d
        out.append(("ellipse", ccx - r, ccy - r, 2 * r, 2 * r))
    out.append(("quad", (cx, cy - 0.5 * d,          # нижний кончик
                         cx + 0.5 * d, cy,
                         cx, cy + 0.5 * d,
                         cx - 0.5 * d, cy)))
    return out


def journal(x: float, y: float, w: float, h: float) -> list:
    """Тетрадь: обложка, корешок слева и две строки записей.

    Строки разной длины не для красоты: одинаковые вместе с корешком читались
    как буква «Е». Короткая нижняя — конец абзаца, и значок сразу становится
    «где что-то записано». Третью строку пробовал — на слабой плотности экрана
    просвет между ними становится меньше толщины линии и всё сливается.
    """
    s = min(w, h)
    lw = s * 0.085
    bw, bh = 0.78 * s, 0.94 * s
    x0 = x + w / 2.0 - bw / 2.0
    y0 = y + h / 2.0 - bh / 2.0

    spine = x0 + bw * 0.24
    x1 = x0 + bw * 0.42
    return [
        ("rrect", x0 + lw / 2, y0 + lw / 2, bw - lw, bh - lw, s * 0.09, lw),
        ("line", (spine, y0 + lw, spine, y0 + bh - lw), lw),
        ("line", (x1, y0 + bh * 0.64, x0 + bw * 0.80, y0 + bh * 0.64), lw),
        ("line", (x1, y0 + bh * 0.38, x0 + bw * 0.62, y0 + bh * 0.38), lw),
    ]


ICONS = {"heart": heart, "journal": journal}


def shapes(name: str, x: float, y: float, w: float, h: float) -> list:
    """Примитивы значка name, вписанные в прямоугольник (x, y, w, h)."""
    try:
        draw = ICONS[name]
    except KeyError:
        raise ValueError(f"нет значка {name!r}; есть: {', '.join(sorted(ICONS))}")
    return draw(x, y, w, h)


# --------------------------------------------------------------------------- #
#  Виджет
# --------------------------------------------------------------------------- #

try:                                                  # pragma: no cover
    from kivy.graphics import (Color, Ellipse, Line, Quad,  # noqa: F401
                               RoundedRectangle)
    from kivy.metrics import dp
    from kivy.uix.behaviors import ButtonBehavior
    from kivy.uix.widget import Widget
except ImportError:                                   # тесты геометрии без Kivy
    Widget = object
    ButtonBehavior = object
else:
    class IconButton(ButtonBehavior, Widget):
        """Кнопка со значком вместо надписи.

        Ведёт себя как обычный Button: bind(on_release=...). Фон рисуется
        сам, поэтому background_normal подсовывать не нужно.
        """

        def __init__(self, icon="heart", color=(0, 0, 0, 1), bg=(1, 1, 1, 1),
                     radius=None, fill=FILL, **kw):
            super().__init__(**kw)
            self.icon = icon
            self.color = color
            self.bg = bg
            self.radius = dp(8) if radius is None else radius
            self.fill = fill
            self.bind(pos=self.redraw, size=self.redraw, state=self.redraw)
            self.redraw()

        def _bg_color(self):
            """При нажатии фон темнеет: без этого палец не видит отклика."""
            if self.state == "down":
                return [c * 0.90 for c in self.bg[:3]] + [
                    self.bg[3] if len(self.bg) > 3 else 1]
            return self.bg

        def redraw(self, *_):
            self.canvas.clear()
            side = min(self.width, self.height) * self.fill
            bx = self.center_x - side / 2.0
            by = self.center_y - side / 2.0
            with self.canvas:
                Color(*self._bg_color())
                RoundedRectangle(pos=self.pos, size=self.size,
                                 radius=[self.radius])
                Color(*self.color)
                for item in shapes(self.icon, bx, by, side, side):
                    kind = item[0]
                    if kind == "ellipse":
                        Ellipse(pos=(item[1], item[2]), size=(item[3], item[4]))
                    elif kind == "quad":
                        Quad(points=list(item[1]))
                    elif kind == "line":
                        Line(points=list(item[1]), width=item[2] / 2.0,
                             cap="round", joint="round")
                    elif kind == "rrect":
                        Line(rounded_rectangle=(item[1], item[2], item[3],
                                                item[4], item[5]),
                             width=item[6] / 2.0, joint="round")
