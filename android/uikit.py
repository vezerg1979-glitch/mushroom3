# -*- coding: utf-8 -*-
"""
uikit.py — общие мелочи оформления, вынесенные из отдельных экранов.

До этого файла каждый экран (premium_screen.py, backupscreen.py,
finddialog.py, offlinemap.py, walkjournal.py, walkscreen.py,
mushroom_forecast.py) держал свою копию функции _fill() — семь одинаковых
кусков кода, красящих виджет плоским прямоугольником. Здесь — одно место,
которое красит его скруглённым прямоугольником вместо плоского; экраны
по-прежнему зовут свою локальную _fill(widget, color) с той же сигнатурой,
она просто теперь на одну строчку и делегирует сюда.

RADIUS — насколько скруглены углы у карточек и попапов. dp(8) — заметно,
но не настолько, чтобы спорить с прямоугольной формой попапа Kivy вокруг.
"""

from __future__ import annotations

from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp

RADIUS = dp(8)

#: Отступы между элементами внутри окон/карточек — три стандартных шага.
#: По коду уже преобладает dp(6) (около 46 мест) и dp(8) (около 19 мест);
#: это не хаос, а фактически сложившийся стандарт с редкими отклонениями
#: в dp(2)/dp(4)/dp(10) (десяток мест). Здесь эти шаги просто получают
#: имена, чтобы новый код брал готовую константу вместо dp(N) на глаз.
#: Существующие вызовы не переписаны намеренно: их 75+ по всему проекту,
#: и правка каждого — это визуальная проверка на телефоне, а не то, что
#: можно сделать безопасно вслепую одним поиском-заменой.
SPACE_TIGHT = dp(6)
SPACE = dp(8)
SPACE_LOOSE = dp(16)


def fill_rounded(widget, color, radius=None):
    """Красит widget сплошным цветом со скруглёнными углами.

    Замена прежнего Rectangle на RoundedRectangle — сам widget и его
    прямоугольный hit-test (на что реагируют тапы) не меняются, меняется
    только то, что нарисовано под ним, так что переход безопасен для
    существующих экранов и тестов.
    """
    r = radius if radius is not None else RADIUS
    with widget.canvas.before:
        tint = Color(*color)
        rect = RoundedRectangle(pos=widget.pos, size=widget.size,
                                radius=[r])
    widget.bind(pos=lambda w, v: setattr(rect, "pos", v),
               size=lambda w, v: setattr(rect, "size", v))
    # Keep the canvas color reachable: changing Button.background_color does
    # not affect a RoundedRectangle drawn separately on canvas.before.
    widget._ui_fill_color = tint
    return rect


def press_feedback(button, base_color, darken=0.15):
    """Visible pressed state for rounded canvas buttons in both themes.

    A transparent native Button background cannot tint canvas.before. Update
    the actual Color instruction and restore it on release/cancel instead.
    """
    darker = tuple(max(0.0, c * (1 - darken)) for c in base_color[:3]) + (
        base_color[3] if len(base_color) > 3 else 1.0,)

    def _paint(color):
        tint = getattr(button, "_ui_fill_color", None)
        if tint is not None:
            tint.rgba = color
        else:
            button.background_color = color

    button.bind(on_press=lambda *_: _paint(darker),
                on_release=lambda *_: _paint(base_color),
                on_touch_up=lambda *_: _paint(base_color) if button.state == "normal" else None)


def style_secondary(widget, color, text_color, radius=None):
    """Shared, theme-aware secondary button/spinner treatment."""
    widget.background_normal = ""
    widget.background_color = (0, 0, 0, 0)
    widget.color = text_color
    fill_rounded(widget, color, radius=radius)
    press_feedback(widget, color, darken=0.10)
    return widget


def spin_status(label, base_text, interval=0.4):
    """Бегущие точки после текста статуса, пока идёт сетевой запрос.

    Существующий код и так честно меняет label.text на «Запрос погодных
    данных…» перед долгим вызовом — просто эта надпись потом стоит
    неподвижно до самого ответа сервера, и на медленной сети непонятно,
    работает приложение или зависло. Здесь тот же текст, только с
    «Запрос погодных данных.» → «..» → «...» по кругу.

    Возвращает функцию-остановку: её нужно вызвать в колбэке успеха или
    ошибки, иначе Clock.schedule_interval продолжит тикать впустую даже
    после того, как label покажет что-то другое.
    """
    from kivy.clock import Clock

    state = {"n": 0}

    def _tick(_dt):
        state["n"] = (state["n"] + 1) % 4
        label.text = base_text + "." * state["n"]

    ev = Clock.schedule_interval(_tick, interval)

    def stop():
        ev.cancel()

    return stop


def open_soft(popup, duration=0.15):
    """Popup.open(), только не мгновенно, а с коротким проявлением.

    Kivy рисует Popup сразу в полный размер и с opacity=1 — на глаз это
    как щелчок, особенно на попапах побольше (окно покупки, конфиденциаль-
    ность, условия использования). Здесь то же самое окно, но открывается
    прозрачным и за duration секунд становится видимым — та же техника,
    что дают за деньги в интерфейсных библиотеках, тут в четыре строки.

    Применён точечно — на попапах, тронутых в этом заходе (покупка,
    конфиденциальность, условия). Остальные ~10 Popup по проекту
    (журнал похода, резервная копия, поиск вида и т. д.) продолжают
    открываться как раньше: одинаковое поведение по всему приложению —
    отдельная задача, не эта правка.
    """
    from kivy.animation import Animation

    popup.opacity = 0
    popup.open()
    Animation(opacity=1, duration=duration, t="out_quad").start(popup)
    return popup
