# -*- coding: utf-8 -*-
"""
walkscreen.py — режим похода: запись маршрута и отметки находок.

Экран во весь размер: сверху счётчики (метры, время, находки), в середине
карта с траекторией, снизу крупные кнопки. Расчёт на то, что телефон держат
одной рукой в лесу, поэтому кнопки большие, а лишнего на экране нет.

Координаты берутся из plyer.gps. На компьютере GPS нет, поэтому предусмотрен
ручной ввод точек — им же пользуются тесты.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

from kivy.clock import Clock, mainthread
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.utils import get_color_from_hex as hexc

import palette
import theme

import atlas
import buzz
import history as history_mod
import icons
import location as location_mod
import mushroom_forecast as engine
import compass as compass_mod
import nav
import walk2journal
import service_ctl
import survival
import sun
import track as track_mod
import tracklog
import photos as photos_mod
import prefs
import proximity
import power
from finddialog import FindDialog
from mapview import TileMap
from navwidget import NavArrow

def _apply_palette():
    """Перечитывает цвета после смены темы.

    Цвета копируются в константы модуля при загрузке — так быстрее, но
    после переключения копии остаются прежними. theme вызывает эту функцию
    и пересобирает экран: у виджета цвет выставлен в момент создания, и
    задним числом палитра его не изменит.
    """
    global INK, MUTED, CARD, ACCENT, RED, BLUE, FADED
    INK = hexc(palette.INK)
    MUTED = hexc(palette.MUTED)
    CARD = hexc(palette.CARD)
    ACCENT = hexc(palette.ACCENT)
    RED = hexc(palette.RED)
    BLUE = hexc(palette.BLUE)
    FADED = hexc(palette.FADED)


_apply_palette()
theme.register(_apply_palette)

# Сколько ждать признаков жизни от фонового сервиса, секунды. Ожидание
# неблокирующее: окно всё это время остаётся отзывчивым.
SERVICE_WAIT_S = 8.0

# Через сколько секунд молчания подписки переходить на аварийный опрос.
# Пятнадцать — это заведомо больше обычного промежутка между координатами
# (две-три секунды) и заведомо меньше, чем человек готов идти вслепую.
POLL_AFTER_S = 15.0


def _fill(widget, color):
    with widget.canvas.before:
        Color(*color)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(pos=lambda w, v: setattr(rect, "pos", v),
                size=lambda w, v: setattr(rect, "size", v))


class Counter(BoxLayout):
    """Крупное число с подписью."""

    def __init__(self, title, value="—", color=None, **kw):
        # Цвет по умолчанию берётся при вызове, а не при объявлении:
        # значения по умолчанию вычисляются один раз, при загрузке
        # модуля, и после смены темы остались бы дневными.
        color = INK if color is None else color
        super().__init__(orientation="vertical", **kw)
        self.lbl = Label(text=value, font_size=sp(22), bold=True, color=color)
        self.add_widget(self.lbl)
        self.add_widget(Label(text=title, font_size=sp(11), color=MUTED,
                              size_hint_y=None, height=dp(16)))

    def set(self, text):
        self.lbl.text = text


class WalkScreen(Popup):
    """Режим похода поверх основного экрана."""

    def __init__(self, lat, lon, biotope="смешанный", place="", on_close=None,
                 index=None, **kw):
        self.walk = track_mod.Walk(place=place, biotope=biotope)
        # Снимок прогноза кладётся в поход сразу, при открытии экрана: к
        # моменту, когда человек нажмёт «Стоп», сети уже может не быть, а
        # обещание модели должно остаться записанным именно на день выхода.
        self.walk.index = dict(index or {})
        self.walk.index_stamp = time.time() if index else 0.0
        self._start_at = (lat, lon)        # чем считать закат до первой точки
        self._dusk_warned = False
        self._battery_warned = 0           # порог, о котором уже сказали
        self.on_close = on_close
        self.running = False
        self._gps_on = False
        self._tick = None
        self._service = False              # пишет фоновый сервис
        self._svc_watch = None             # проверка «ожил ли сервис»
        self._svc_deadline = 0.0
        self._locator = None
        self._reader = tracklog.LiveReader()
        self._last_fix = 0.0               # когда пришла последняя координата
        self._polled_t = 0.0               # время точки, взятой аварийным опросом
        # Компас: запасной источник направления, когда человек стоит и курс
        # по треку не вычисляется. Без датчиков включается вхолостую.
        self._compass = compass_mod.Compass()
        self._compass_on = self._compass.start()

        self._car_moved_said = False       # про переезд машины сказали один раз
        self._near = None                  # сторож старых мест, ждёт архива
        self._nav_target = None            # None — навигация выключена,
                                           # "start" — к началу маршрута,
                                           # объект с lat/lon — к метке

        root = BoxLayout(orientation="vertical", padding=dp(6), spacing=dp(6))
        _fill(root, CARD)

        # счётчики
        top = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(4))
        self.c_dist = Counter("метров", "0", BLUE)
        self.c_time = Counter("в пути", "0 мин")
        self.c_finds = Counter("находок", "0", RED)
        # Время до заката — второе по важности число после расстояния до
        # машины. Темнеет незаметно: под пологом ельника сумерки начинаются
        # за полчаса до заката, а грибник в это время как раз входит во вкус.
        # Считается арифметикой по координатам и дате, без сети и разрешений.
        self.c_sun = Counter("до заката", "—")
        for c in (self.c_dist, self.c_time, self.c_finds, self.c_sun):
            top.add_widget(c)
        root.add_widget(top)

        # Состояние приёма отдельной строкой. Без неё стоящий человек час
        # смотрит на «0 метров» и не понимает, сломалось приложение, сел
        # спутник или он просто никуда не идёт.
        self.gps = Label(text="", font_size=sp(11), color=MUTED,
                         size_hint_y=None, height=dp(16))
        root.add_widget(self.gps)

        # карта
        self.map = TileMap(lat, lon, 15)
        self.map.walk = self.walk
        self.map.follow = True
        # Прошлые походы приезжают на карту отдельно, из фонового потока:
        # см. _load_history(). Касание по старому месту открывает карточку.
        self.map.on_spot = self._show_spot
        self.map.set_here(lat, lon)

        # Кнопки масштаба лежат ПОВЕРХ карты, а не отдельной полосой под ней:
        # карта на телефоне и так мала, отдавать ей ещё 40 dp жалко. До сих
        # пор масштаб менялся только щипком двумя пальцами — жест, который в
        # перчатке, одной рукой и с телефоном на шнурке не выходит.
        map_box = FloatLayout()
        self.map.size_hint = (1, 1)
        self.map.pos_hint = {"x": 0, "y": 0}
        map_box.add_widget(self.map)

        # Кнопки собраны в столбик фиксированной высоты, а не расставлены
        # долями экрана: доля от невысокой карты (маленький телефон, открытая
        # полоса навигации) даёт промежуток меньше самой кнопки, и они
        # налезают друг на друга. Столбику это безразлично.
        side = BoxLayout(orientation="vertical", spacing=dp(6),
                         size_hint=(None, None),
                         size=(dp(44), dp(44) * 3 + dp(12)),
                         pos_hint={"right": 0.98, "top": 0.98})
        for txt, step in (("+", 1), ("−", -1)):
            b = Button(text=txt, font_size=sp(20), bold=True,
                       background_normal="", background_color=(1, 1, 1, 0.85),
                       color=INK)
            b.bind(on_release=lambda _b, st=step: self.map.zoom_by(st))
            side.add_widget(b)
        # Переключатель прошлых походов стоит тут же, на карте, а не в ряду
        # кнопок внизу: его действие видно прямо под пальцем, и ряд остаётся
        # трёхкнопочным — подписи в четыре кнопки на 360 dp уже обрезаются.
        self.b_hist = icons.IconButton(icon="journal", color=INK,
                                       bg=(1, 1, 1, 0.85))
        self.b_hist.bind(on_release=lambda *_: self.toggle_history())
        side.add_widget(self.b_hist)
        map_box.add_widget(side)
        root.add_widget(map_box)

        self.arrow = NavArrow(size_hint_y=None, height=0)
        root.add_widget(self.arrow)

        # Подпись переносится по словам и растёт в высоту. Без text_size
        # Kivy рисует ярлык одной строкой в натуральную ширину, и длинные
        # сообщения вроде «Пишет фоновый сервис: можно погасить экран…»
        # уезжали за края окна — видно было середину фразы без начала и конца.
        self.hint = Label(text="Нажмите «Старт», чтобы начать запись маршрута",
                          font_size=sp(12), color=MUTED, halign="left",
                          valign="top", size_hint_y=None, height=dp(20))
        self.hint.bind(
            width=lambda w, x: setattr(w, "text_size", (x, None)),
            texture_size=lambda w, t: setattr(w, "height", max(dp(20), t[1])))
        root.add_widget(self.hint)

        # кнопки
        btns = BoxLayout(size_hint_y=None, height=dp(58), spacing=dp(6))
        self.b_start = Button(text="Старт", font_size=sp(17), bold=True,
                              background_normal="", background_color=ACCENT)
        self.b_start.bind(on_release=lambda *_: self.toggle())
        self.b_find = Button(text="Нашёл!", font_size=sp(17), bold=True,
                             background_normal="", background_color=RED,
                             disabled=True)
        self.b_find.bind(on_release=lambda *_: self.mark_find())
        btns.add_widget(self.b_start)
        btns.add_widget(self.b_find)
        # Отмена стоит вплотную к «Нашёл!»: ошибаются именно этой кнопкой —
        # промахнулись видом, нажали дважды, отметили не сходя с места.
        # Значок вместо надписи, чтобы не отнимать ширину у двух главных.
        self.b_undo = icons.IconButton(icon="undo", color=INK, bg=hexc(palette.SOFT),
                                       size_hint_x=None, width=dp(56),
                                       disabled=True)
        self.b_undo.bind(on_release=lambda *_: self.undo())
        btns.add_widget(self.b_undo)
        root.add_widget(btns)

        # Вспомогательные кнопки в два ряда. Пять штук в одну строку на экране
        # шириной 360 dp дают по 66 dp на кнопку — подписи не помещаются и
        # налезают друг на друга: «Слежение: вк.К машинОтменить мет».
        # Заодно каждая кнопка получает text_size: если надпись всё же длиннее
        # места, она обрежется многоточием внутри своей кнопки, а не поверх
        # соседней.
        def small(text, action, color=None):
            # Цвет по умолчанию берётся при вызове, а не при объявлении:
            # значения по умолчанию вычисляются один раз, при загрузке
            # модуля, и после смены темы остались бы дневными.
            color = INK if color is None else color
            # Подпись в две строки и обрезание многоточием несовместимы:
            # shorten сминает всё в одну строку, и «Заметка\nи фото»
            # превращается в «Заметка и фо…». Поэтому перенос строки
            # отключает обрезание — подпись видна целиком.
            multiline = "\n" in text
            b = Button(text=text, font_size=sp(12), background_normal="",
                       background_color=hexc(palette.SOFT), color=color,
                       halign="center", valign="middle",
                       shorten=not multiline, shorten_from="right")
            b.bind(size=lambda w, v: setattr(w, "text_size", v))
            b.bind(on_release=lambda *_: action())
            return b

        row1 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.b_follow = small("Слежение: вкл", self.toggle_follow)
        self.b_nav = small("К машине", self.toggle_nav)
        row1.add_widget(self.b_follow)
        row1.add_widget(self.b_nav)
        row1.add_widget(small("Весь поход", self.fit_walk))
        root.add_widget(row1)

        # Четыре кнопки в ряд помещаются только с подписями в две строки:
        # в одну «Машина здесь» на 85 dp обрезается до «Машина зд…», а
        # обрезанная подпись у кнопки, которая переносит точку возврата, —
        # ровно тот случай, когда человек её не нажмёт, не поняв, что она
        # делает.
        row2 = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        row2.add_widget(small("Заметка\nи фото", self.edit_last_find))
        row2.add_widget(small("Машина\nздесь", self.mark_car))
        row2.add_widget(small("Приём\nи сервис", self.show_service_log, MUTED))
        row2.add_widget(small("Закрыть\nпоход", self.finish))
        root.add_widget(row2)

        super().__init__(title="Поход", content=root, size_hint=(0.98, 0.96),
                         separator_color=ACCENT, title_size=sp(15),
                         auto_dismiss=False, **kw)

    def on_open(self):
        """Приёмник включается при открытии окна, а не по кнопке «Старт».

        Так и должно быть с точки зрения человека: он открыл поход, и синяя
        точка обязана поехать за ним по карте — иначе непонятно, работает
        ли вообще GPS, и «Старт» жать страшно. Раньше до нажатия «Старт»
        никакой подписки не было вовсе, карта показывала место, выбранное
        на главном экране, и стояла намертво.

        Запись при этом не идёт: feed() кладёт точку в маршрут только когда
        running. До старта приёмник нужен ровно для того, чтобы показать
        текущее положение и точность.
        """
        self._tick = Clock.schedule_interval(lambda dt: self._pump(), 1.0)
        if location_mod.has_permission():
            self._start_gps_foreground()
            self.hint.text = ("Ищу спутники. «Старт» начнёт запись маршрута.")
        self._load_history()
        self._refresh()

    # --- прошлые походы -----------------------------------------------------

    def _load_history(self):
        """Читает архив походов в фоне и кладёт его на карту.

        В отдельном потоке потому, что за несколько сезонов в tracks/
        набирается сотня файлов, и чтение их на телефоне — заметная пауза.
        Окно похода обязано открываться мгновенно: человек жмёт «В лес», уже
        стоя у машины. Подложка доедет через секунду, ничего не задерживая.
        """
        def work():
            try:
                h = history_mod.load(skip_started=self.walk.started)
            except Exception:                                     # noqa: BLE001
                # Испорченный файл трека не повод не пустить человека в лес.
                h = history_mod.History()
            self._history_ready(h)

        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _history_ready(self, h):
        self.map.history = h
        self.map.redraw()
        # Тот же архив идёт и в сторож приближения: места находок уже слиты
        # по расстоянию, считать их заново незачем.
        self._near = proximity.Watcher(spots=list(h.spots),
                                       started=self.walk.started)
        # Подпись показывается только до старта: во время записи там идут
        # сообщения поважнее — приём, метки, паузы.
        if not self.running and h:
            self.hint.text = (h.summary()
                              + ". Точка на карте — где брали; коснитесь её, "
                                "чтобы посмотреть и проложить путь.")

    def toggle_history(self):
        """Слой прошлых походов можно убрать: в знакомом лесу он мешает.

        Своих старых ниток за пять сезонов на любимом квадрате столько, что
        сегодняшний трек в них теряется — а он нужнее всего.
        """
        self.map.show_history = not self.map.show_history
        # Выключенный слой показывает выцветший значок: подписи у кнопки на
        # карте нет, и состояние должно читаться самим значком.
        self.b_hist.color = INK if self.map.show_history else FADED
        self.b_hist.redraw()
        self.hint.text = ("Прошлые походы показаны" if self.map.show_history
                          else "Прошлые походы скрыты")
        self.map.redraw()

    def _show_spot(self, spot):
        """Карточка старого места находок и кнопка «Идти сюда»."""
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        _fill(box, CARD)

        sp_obj = engine.SPECIES.get(spot.species)
        title = sp_obj.name if sp_obj else "Метка"
        when = (datetime.fromtimestamp(spot.last_t).strftime("%d.%m.%Y")
                if spot.last_t else "дата неизвестна")
        lines = [f"[b]{title}[/b] — {spot.count} шт",
                 f"находок здесь: {spot.visits}, последняя {when}"]
        if len(spot.kinds) > 1:
            other = ", ".join(
                f"{engine.SPECIES[k].name if k in engine.SPECIES else k} {n}"
                for k, n in sorted(spot.kinds.items(), key=lambda kv: -kv[1]))
            lines.append(f"[color=5C6353]{other}[/color]")
        lbl = Label(text="\n".join(lines), markup=True, font_size=sp(14),
                    color=INK, halign="left", valign="top")
        lbl.bind(width=lambda w, x: setattr(w, "text_size", (x, None)))
        box.add_widget(lbl)

        btns = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        go = Button(text="Идти сюда", font_size=sp(15), bold=True,
                    background_normal="", background_color=BLUE)
        # Грибной угол, к которому стоит вернуться, должен уметь стать местом
        # с именем и собственным прогнозом. Иначе точка живёт только внутри
        # похода: увидеть её со стартового экрана и посчитать по ней погоду
        # нельзя, а именно за этим человек сюда и вернётся в следующий раз.
        keep = Button(text="В мои места", font_size=sp(15), background_normal="",
                      background_color=hexc(palette.SOFT), color=INK)
        close = Button(text="Закрыть", font_size=sp(15), background_normal="",
                       background_color=hexc(palette.SOFT), color=MUTED)
        btns.add_widget(go)
        btns.add_widget(keep)
        btns.add_widget(close)
        box.add_widget(btns)

        pop = Popup(title="Здесь уже брали", content=box, size_hint=(0.9, None),
                    height=dp(240), separator_color=BLUE, title_size=sp(15))
        go.bind(on_release=lambda *_: (pop.dismiss(), self._go_to_spot(spot)))
        keep.bind(on_release=lambda *_: (pop.dismiss(), self._keep_spot(spot)))
        close.bind(on_release=lambda *_: pop.dismiss())
        pop.open()

    def spot_name(self, spot) -> str:
        """Имя для нового места: вид и дата — «Белый гриб, 24.08.2025».

        Имя предлагается готовым, а не запрашивается: ввод текста стоя в лесу
        с мокрыми руками — это гарантия, что место не сохранят вовсе.
        Переименовать его можно дома, на большом экране.
        """
        sp_obj = engine.SPECIES.get(spot.species)
        head = sp_obj.name if sp_obj else "Грибное место"
        if spot.last_t:
            return f"{head}, {datetime.fromtimestamp(spot.last_t):%d.%m.%Y}"
        return head

    def _keep_spot(self, spot):
        """Сохраняет старую находку как место с прогнозом."""
        import places as places_mod

        name = self.spot_name(spot)
        try:
            places_mod.add(places_mod.Spot(name, spot.lat, spot.lon,
                                           biotope=self.walk.biotope))
        except OSError as e:
            self.hint.text = f"Не удалось сохранить место: {e}"
            return
        buzz.tap()
        self.hint.text = (f"Место «{name}» сохранено — оно появится строкой "
                          f"под названием на главном экране.")

    def _go_to_spot(self, spot):
        """Навигация к старому месту.

        Без записанного маршрута стрелке не от чего считать: своё положение
        она берёт из последней точки трека. Поэтому вместо молчаливого
        бездействия — прямая подсказка, что нажать.
        """
        if not self.walk.points:
            self.hint.text = ("Чтобы вести к месту, нужна запись: нажмите "
                              "«Старт» — стрелка появится с первой точкой.")
            return
        self.navigate_to(spot, "К старой находке")

    # --- управление ---------------------------------------------------------
    def toggle(self):
        self.running = not self.running
        buzz.tap()
        self.b_start.text = "Пауза" if self.running else "Продолжить"
        self.b_start.background_color = MUTED if self.running else ACCENT
        self.b_find.disabled = not self.running
        if self.running:
            self._keep_screen(True)
            self._start_gps()
            self.walk.resume()
            # Старт у машины — самый частый случай, поэтому отметка ставится
            # сама. Не угадывать вовсе было бы хуже: человек, которому
            # ничего не предложили, не отметит ничего и узнает об этом в
            # сумерках, когда стрелка поведёт неизвестно куда.
            if self.walk.car is None and self.map.here:
                self.walk.set_car(*self.map.here)
            self.hint.text = "Идёт запись. Кнопка «Нашёл!» ставит метку на карте."
        else:
            self._keep_screen(False)
            # Перерыв запоминается, чтобы потом не спутать его с прерванной
            # записью: со стороны они выглядят одинаково.
            self.walk.pause()
            self.hint.text = "Пауза. Метры не считаются."

    def fit_walk(self):
        """Вписывает весь маршрут в экран: где я относительно машины.

        Слежение при этом выключается — иначе первая же пришедшая координата
        вернёт карту на своё положение, и человек не успеет посмотреть.
        """
        pts = [(p.lat, p.lon) for p in self.walk.points]
        pts += [(f.lat, f.lon) for f in self.walk.finds]
        if self.map.here:
            pts.append(self.map.here)
        if len(pts) < 2:
            self.hint.text = ("Показывать пока нечего: маршрут не начат. "
                              "Нажмите «Старт».")
            return
        self.map.follow = False
        self.b_follow.text = "Слежение: выкл"
        if self.map.fit(pts):
            self.hint.text = "Весь поход на экране. «Слежение» вернёт карту к вам."

    def toggle_follow(self):
        self.map.follow = not self.map.follow
        self.b_follow.text = f"Слежение: {'вкл' if self.map.follow else 'выкл'}"
        if self.map.follow and self.map.here:
            self.map.center_on(*self.map.here)

    @staticmethod
    def _keep_screen(on: bool):
        """Экран не должен гаснуть на ходу: во сне приёмник перестаёт отдавать точки."""
        try:
            from kivy.core.window import Window
            Window.allow_screensaver = not on
        except Exception:                                         # noqa: BLE001
            pass

    def _start_gps(self):
        """Сначала разрешение, потом фоновый сервис, при неудаче — окно.

        Разрешение спрашивается с обратным вызовом и запись начинается только
        после ответа. Раньше диалог показывался, а приёмник запускался тут же,
        не дожидаясь нажатия «Разрешить»: система бросала SecurityException,
        и приложение сообщало, что координат нет, — хотя через секунду
        разрешение давали.
        """
        if self._gps_on or self._service:
            return
        if location_mod.has_permission():
            self._begin_recording()
            return
        self.hint.text = "Жду разрешения на доступ к координатам…"
        location_mod.request_permission(self._on_permission)

    @mainthread
    def _on_permission(self, granted):
        """Ответ на диалог разрешений приходит из потока Android."""
        if granted:
            self._begin_recording()
        else:
            self.hint.text = ("Без доступа к координатам маршрут не пишется. "
                              "Разрешение можно дать в настройках приложения.")

    def _begin_recording(self):
        """Своя подписка на координаты — сразу, сервис — вдогонку.

        Раньше приложение ставило всё на фоновый сервис и включало
        собственный приёмник только через восемь секунд, если сервис не
        подавал признаков жизни. Но сервис может отчитаться, что жив, и при
        этом не отдать НИ ОДНОЙ координаты — он живёт в отдельном процессе
        со своей подпиской. Тогда второго шанса уже не было: трек оставался
        пустым, хотя тот же приёмник по кнопке «GPS» на главном экране
        отвечал мгновенно.

        Теперь источника два и они не мешают друг другу. Пока экран горит,
        точки идут из своей подписки; сервис нужен, чтобы запись не
        прервалась в кармане. Совпадающие точки отсеет add_point: шаг короче
        шести метров в маршрут не идёт.
        """
        self._start_gps_foreground()
        if service_ctl.available() and service_ctl.start():
            self._reader.reset()
            self._svc_deadline = time.time() + SERVICE_WAIT_S
            if self._svc_watch:
                self._svc_watch.cancel()
            self._svc_watch = Clock.schedule_interval(self._check_service, 0.4)

    def _check_service(self, _dt):
        """Раз в 0.4 с: ожил ли сервис. Возврат False снимает проверку."""
        if tracklog.service_alive():
            self._service = True
            self._svc_watch = None
            if self._gps_on:
                self.hint.text = ("Пишут оба источника: можно погасить экран "
                                  "и убрать телефон в карман.")
            else:
                self.hint.text = ("Пишет фоновый сервис: можно погасить экран "
                                  "и убрать телефон в карман.")
            return False
        if time.time() < self._svc_deadline:
            return True
        self._svc_watch = None
        service_ctl.stop(wait=0.0)
        err = tracklog.get_status().get("error", "")
        # Своя подписка уже работает, поэтому это не отказ, а лишь потеря
        # возможности писать с погашенным экраном.
        self.hint.text = ("Фоновая запись не поднялась"
                          + (f" ({err})" if err else "")
                          + ". Пишу при открытом экране — не гасите телефон.")
        return False

    def _start_gps_foreground(self):
        if self._gps_on:
            return
        self._locator = location_mod.Locator(
            lambda lat, lon, acc: self._on_location(lat, lon, acc))
        if self._locator.start():
            self._gps_on = True
            where = ", ".join(self._locator.providers) or self._locator.kind
            self.hint.text = f"Запись идёт. Источники: {where}."
            # Последняя известная точка сразу: спутники в лесу ловятся
            # минутами, и всё это время человек смотрел на пустой экран,
            # не понимая, работает приём или нет.
            last = self._locator.last_known()
            if last:
                self._on_location(*last)
        else:
            self.hint.text = (f"Координаты недоступны: "
                              f"{self._locator.error or 'нет приёмника'}")

    def _stop_gps(self):
        if self._svc_watch:
            self._svc_watch.cancel()
            self._svc_watch = None
        if self._service:
            service_ctl.stop()
            self._drain()                  # добираем всё, что сервис успел записать
            self._service = False
        if not self._gps_on:
            return
        if getattr(self, "_locator", None):
            self._locator.stop()
        self._gps_on = False

    @mainthread
    def _on_location(self, lat, lon, acc=0.0):
        self.feed(float(lat), float(lon), float(acc or 0.0))

    def _pump(self):
        """Раз в секунду: забираем точки сервиса и обновляем счётчики."""
        self._poll_if_silent()
        if self._service:
            self._drain()
            if not tracklog.service_alive():
                self._service = False
                self._start_gps_foreground()
                self.hint.text = ("Фоновая запись прекратилась. Пишу при "
                                  "открытом экране — не гасите телефон.")
        self._refresh()

    def _poll_if_silent(self):
        """Если подписка молчит — спросить систему напрямую.

        Страховка от того, что уже случилось однажды: подписка проходила
        успешно, точность была четыре метра, а обратный вызов не срабатывал
        ни разу за три минуты. Опрос ничего не включает и батарею не тратит,
        он лишь читает то, что система и так знает.
        """
        if not self._gps_on or self._locator is None:
            return
        if time.time() - (self._last_fix or 0) < POLL_AFTER_S:
            return
        point = self._locator.poll()
        if not point:
            return
        lat, lon, acc, t = point
        if t <= self._polled_t:
            return                        # та же самая точка, что и в прошлый раз
        self._polled_t = t
        self.feed(lat, lon, acc)

    def _drain(self):
        last = None
        for lat, lon, acc, t in self._reader.read_new():
            if self.running:
                self.walk.add_point(lat, lon, acc, t)
            else:
                self.walk.last_acc = acc
            last = (lat, lon)
            self._last_fix = time.time()
        if last:
            self.map.set_here(*last)

    def feed(self, lat, lon, acc=0.0, t=None):
        """Новая координата. Вынесено отдельно: так же кормят тесты."""
        if self.running:
            self.walk.add_point(lat, lon, acc, t)
            self._car_follows_the_drive()
            self._check_old_spots(lat, lon, acc, t)
        else:
            self.walk.last_acc = acc
        self._last_fix = time.time()
        self.map.set_here(lat, lon)
        self._refresh()

    def _check_old_spots(self, lat, lon, acc, t):
        """Короткая вибрация рядом с прошлогодней находкой.

        Правила молчания — в proximity.Watcher: их там больше, чем правил
        срабатывания, и это правильно. Здесь остаётся только тронуть и
        подписать.
        """
        if self._near is None or not prefs.get("near_buzz", True):
            return
        hit = self._near.check(lat, lon, acc, t)
        if hit is None:
            return
        buzz.tap()
        self.hint.text = hit.text

    def _car_follows_the_drive(self):
        """Пока человек едет, отметка машины едет вместе с ним.

        Точка разрыва (track.FAST_BREAK) — это и есть машина: она
        сдвигается следом за ней и останавливается там, где человек вышел.
        Поэтому отметку не надо ни ставить заново после переезда, ни
        снимать — она сама оказывается на стоянке.
        """
        pts = self.walk.points
        if not pts:
            return
        last = pts[-1]
        if not last.gap:
            # Первый пеший шаг после переезда: вот здесь человек и вышел.
            # Сама точка разрыва обновляется раз в несколько координат и
            # отстаёт от места остановки на сотни метров — на такое
            # расстояние в сумерках уже не выйдешь по стрелке.
            prev = pts[-2] if len(pts) > 1 else None
            if (prev is None or not prev.gap or not self.walk.car
                    or track_mod.haversine(self.walk.car[0], self.walk.car[1],
                                           prev.lat, prev.lon) > 5.0):
                return
            self.walk.set_car(last.lat, last.lon, last.t)
            self.map.redraw()
            return
        moved = bool(self.walk.car) and (
            track_mod.haversine(self.walk.car[0], self.walk.car[1],
                                last.lat, last.lon)
            > 50.0)
        self.walk.set_car(last.lat, last.lon, last.t)
        if moved and not self._car_moved_said:
            self._car_moved_said = True
            self.hint.text = ("Похоже, вы ехали: отметка машины переехала "
                              "туда, где вы вышли.")
        self.map.redraw()

    def mark_car(self):
        """Кнопка «Машина здесь»: переносит точку возврата на текущее место.

        Нужна для случаев, которые ни угадать, ни вывести: машину оставили
        за шлагбаумом и дошли пешком, приехали с товарищем, вышли из
        автобуса. Само приложение ставит отметку при старте и двигает её
        при переезде, а это — способ сказать «нет, вот здесь».
        """
        if not self.map.here:
            self.hint.text = "Координат ещё нет — подождите, пока найдётся место."
            return
        lat, lon = self.map.here
        self.walk.set_car(lat, lon)
        buzz.tap()
        self.hint.text = "Машина отмечена здесь. Стрелка «К машине» ведёт сюда."
        self.map.redraw()
        if self._nav_target is not None:
            self._nav_refresh()

    def mark_find(self):
        if not self.map.here:
            return
        self._species_dialog()

    def _species_dialog(self):
        """Выбор вида. Сам список живёт в atlas: им пользуется и карточка метки.

        Последний отмеченный вид поднимается наверх: грибы растут семьями, и
        вторая метка почти всегда того же вида, что первая.
        """
        last = next((f.species for f in reversed(self.walk.finds) if f.species),
                    "")
        atlas.picker(self._add_find, recent=last)

    def _add_find(self, key):
        """Метка ставится сразу, карточка открывается следом.

        Порядок важен: сначала запись, потом уточнения. Если человек
        передумает заполнять карточку или приложение закроют, метка с
        координатами уже сохранена — а координаты и есть самое ценное,
        их потом не восстановить.
        """
        lat, lon = self.map.here
        find = self.walk.add_find(lat, lon, key)
        buzz.tap()                     # подтверждение, когда смотреть некогда
        name = engine.SPECIES[key].name if key else "метка"
        self.hint.text = f"Отмечено: {name}"
        self.map.redraw()
        self._refresh()
        self._edit_find(find, name)

    def _edit_find(self, find, title=""):
        """Карточка метки: заметка, снимки, количество."""
        if not title:
            title = (engine.SPECIES[find.species].name
                     if find.species in engine.SPECIES else "Метка")
        FindDialog(find, title=title,
                   on_done=self._find_saved,
                   on_delete=self._find_deleted).open()

    def _find_saved(self, find):
        bits = []
        if find.count > 1:
            bits.append(f"{find.count} шт.")
        if find.photos:
            bits.append(f"снимков {len(find.photos)}")
        if find.note:
            bits.append("с заметкой")
        self.hint.text = ("Метка записана" if not bits
                          else "Метка записана: " + ", ".join(bits))
        self.map.redraw()
        self._refresh()

    def _find_deleted(self, find):
        if find in self.walk.finds:
            self.walk.finds.remove(find)
        self.hint.text = "Метка удалена"
        self.map.redraw()
        self._refresh()

    def edit_last_find(self):
        """Правка последней метки: дописать заметку или доснять кадр."""
        if not self.walk.finds:
            self.hint.text = "Меток пока нет"
            return
        self._edit_find(self.walk.finds[-1])

    def undo(self):
        f = self.walk.undo_find()
        if f:
            buzz.long()                # отмена ощущается иначе, чем постановка
        self.hint.text = "Последняя метка убрана" if f else "Меток нет"
        self.map.redraw()
        self._refresh()

    # --- навигация ----------------------------------------------------------
    def toggle_nav(self):
        """Кнопка «К машине»: включает и выключает стрелку возврата."""
        if self._nav_target is not None:
            self._nav_target = None
            self.b_nav.text = "К машине"
            self.arrow.height = 0
            self.arrow.set_fix(None)
            return
        if not self.walk.points:
            self.hint.text = ("Маршрут ещё не начат — нечего считать началом. "
                              "Нажмите «Старт» у машины.")
            return
        self._nav_target = "start"
        self.b_nav.text = "Скрыть"
        self.arrow.height = dp(150)
        self._nav_refresh()

    def navigate_to(self, target, title="К метке"):
        """Ведёт к произвольной точке: находке, «моему месту», чему угодно
        с полями lat и lon."""
        self._nav_target = target
        self._nav_title = title
        self.b_nav.text = "Скрыть"
        self.arrow.height = dp(150)
        self._nav_refresh()

    #: Высота полосы со стрелкой. Ноль — полоса спрятана.
    ARROW_H = dp(150)

    def _nav_refresh(self):
        """Стрелка: направление на цель, а без цели — простой компас.

        Раньше выход был только один — если навигация выключена, метод
        возвращался в первой же строке и стрелка не рисовалась никогда.
        А навигация выключена почти весь поход.
        """
        if self._nav_target is None or not self.walk.points:
            self._compass_only()
            return
        pts = self.walk.points
        if self._nav_target == "start":
            fix = nav.guide_to_start(self.walk)
            title = "К началу маршрута"
        else:
            here = pts[-1]
            t = self._nav_target
            fix = nav.guide(here.lat, here.lon, t.lat, t.lon, pts)
            title = getattr(self, "_nav_title", "К метке")
        # Курс по треку точнее, но существует только при движении.
        # Стоящему человеку подставляем показания компаса.
        if fix is not None and fix.course is None and self._compass_on:
            h = self._compass.read()
            if h is not None:
                fix.course = h
        self.arrow.height = self.ARROW_H
        self.arrow.set_fix(fix, title)

    def _compass_only(self):
        """Навигации нет — полоса со стрелкой убирается совсем.

        Отдельный компас под картой убран намеренно: направление теперь
        показывает сама стрелка на карте, как в автомобильных навигаторах.
        Так не приходится переводить взгляд с карты на прибор и в уме
        поворачивать одно относительно другого, а экран освобождается под
        карту — её на телефоне всегда мало.
        """
        self.arrow.height = 0
        self.arrow.set_fix(None)

    def _gps_line(self) -> str:
        """Одна строка про приём: откуда, как точно и как давно."""
        srcs = []
        if self._gps_on:
            srcs.append("экран")
        if self._service:
            srcs.append("фон")
        where = "+".join(srcs) or "нет источника"
        if not self._last_fix:
            return f"{where} · жду первую координату со спутников…"
        age = time.time() - self._last_fix
        acc = self.walk.last_acc or 0.0
        parts = [where]
        parts.append(f"±{acc:.0f} м" if acc else "точность неизвестна")
        parts.append("только что" if age < 5 else f"{age:.0f} с назад")
        if age > POLL_AFTER_S:
            parts.append("подписка молчит, опрашиваю")
        parts.append(f"точек {len(self.walk.points)}")
        if self.walk.skipped:
            parts.append(f"отброшено {self.walk.skipped}")
        return " · ".join(parts)

    def _heading(self):
        """Куда повёрнут человек: курс по треку, иначе компас.

        Курс по треку точнее компаса и не врёт рядом с железом, но
        существует только на ходу. Стоящему подставляется компас — он и
        нужен как раз тогда, когда человек остановился на развилке.
        """
        course = nav.course_over_ground(self.walk.points) if self.walk.points else None
        if course is not None:
            return course
        return self._compass.heading() if self._compass_on else None

    def _refresh(self):
        # Компас опрашивается каждый раз: сглаживание набирает историю, и к
        # моменту остановки стрелка уже показывает верно, а не с нуля.
        if self._compass_on:
            self._compass.read()
        self.map.set_heading(self._heading())
        self._nav_refresh()
        self.gps.text = self._gps_line() if (self.running or self._last_fix) else ""
        if self.running:
            state = self.walk.signal_state()
            if state:
                self.hint.text = state
        self.c_dist.set(f"{self.walk.distance:.0f}")
        mins = int(self.walk.duration // 60)
        h, m = divmod(mins, 60)
        self.c_time.set(f"{h} ч {m} мин" if h else f"{m} мин")
        self.c_finds.set(str(len(self.walk.finds)))
        self.b_undo.disabled = not self.walk.finds
        self._refresh_dusk()
        self._check_battery()

    def _check_battery(self):
        """Предупреждение о разряде: один раз на порог.

        Показывается только во время записи. До «Старта» человек ещё у
        машины, где есть зарядка, и пугать его там незачем.
        """
        if not self.running:
            return
        text, level = power.warning(power.level(), self._battery_warned)
        if not text:
            return
        self._battery_warned = level
        self.hint.text = text
        buzz.long()

    def _refresh_dusk(self):
        """Счётчик «до заката» и единственное предупреждение.

        Предупреждение показывается один раз: подсказка под картой одна на
        всё, и повторяясь каждую секунду, она затирала бы состояние приёма
        и сообщения о метках.
        """
        left = sun.seconds_to_sunset(*(self.map.here or self._start_at))
        self.c_sun.set(sun.text(left))
        dusk = left is not None and left <= sun.WARN_S
        self.c_sun.lbl.color = RED if dusk else INK
        if dusk and left > 0 and not self._dusk_warned:
            self._dusk_warned = True
            buzz.long()
            mins = int(left // 60)
            self.hint.text = (f"До заката {mins} мин. В лесу темнеет раньше — "
                              f"пора выходить к машине.")

    def show_service_log(self):
        """Диагностика: что именно происходит с фоновой записью."""
        st = tracklog.get_status()
        head = (f"Состояние: {'работает' if tracklog.service_alive() else 'не отвечает'}\n"
                f"Источник: {st.get('source', '—')}\n"
                f"Точек записано: {st.get('points', 0)}\n"
                f"Провайдеры: {st.get('providers', '—')}\n")
        if st.get("error"):
            head += f"Ошибка: {st['error']}\n"
        head += (f"Компас: {self._compass.kind or 'выключен'}"
                 + (f" — {self._compass.error}" if not self._compass_on else "")
                 + "\n"
                 f"Каталог данных: {tracklog.places_mod.data_dir()}\n")

        # Разрешение системы на работу в фоне и подсказка производителя.
        # Стоят выше лога: человек приходит сюда, когда запись оборвалась, и
        # ему нужен ответ, а не журнал событий.
        exempt = survival.is_exempt()
        if exempt is True:
            head += "Работа в фоне: разрешена системой\n"
        elif exempt is False:
            head += ("Работа в фоне: ОГРАНИЧЕНА системой — с погашенным "
                     "экраном запись может обрываться\n")
        broken = survival.report(self.walk)
        if broken:
            head += broken + "\n"

        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        _fill(box, CARD)
        sv = ScrollView()
        lbl = Label(text=head + "\n" + survival.advice() + "\n\n"
                    + tracklog.read_log(), color=INK,
                    font_size=sp(11), halign="left", valign="top",
                    size_hint_y=None, padding=(dp(8), dp(8)))
        lbl.bind(width=lambda w, x: setattr(w, "text_size", (x - dp(16), None)),
                 texture_size=lambda w, t: setattr(w, "height", t[1] + dp(16)))
        sv.add_widget(lbl)
        box.add_widget(sv)

        # Выключатель подсказок у старых мест стоит здесь, в окне «Приём и
        # сервис». Отдельного экрана настроек в приложении нет, а идут сюда
        # ровно тогда, когда что-то в походе мешает или ведёт себя не так, —
        # то есть в ту самую минуту, когда человек и хочет это отключить.
        b_near = Button(size_hint_y=None, height=dp(46), font_size=sp(13),
                        background_normal="",
                        background_color=hexc(palette.SOFT), color=INK)

        def near_label():
            on = prefs.get("near_buzz", True)
            b_near.text = ("Подсказки у старых мест: включены" if on
                           else "Подсказки у старых мест: выключены")

        def near_toggle(*_):
            prefs.save(near_buzz=not prefs.get("near_buzz", True))
            near_label()

        near_label()
        b_near.bind(on_release=near_toggle)
        box.add_widget(b_near)

        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        b_bat = Button(text="Батарея", font_size=sp(13), background_normal="",
                       background_color=hexc(palette.SOFT), color=INK)
        b_bat.bind(on_release=lambda *_: survival.open_battery_settings())
        b_auto = Button(text="Автозапуск", font_size=sp(13),
                        background_normal="",
                        background_color=hexc(palette.SOFT), color=INK)
        b_auto.bind(on_release=lambda *_: survival.open_vendor_settings())
        row.add_widget(b_bat)
        row.add_widget(b_auto)
        box.add_widget(row)

        Popup(title="Фоновая запись", content=box, size_hint=(0.94, 0.85),
              separator_color=BLUE, title_size=sp(14)).open()

    # --- завершение ---------------------------------------------------------
    def finish(self):
        self.running = False
        if self._tick:
            self._tick.cancel()
            self._tick = None
        self._stop_gps()
        self._keep_screen(False)
        if self._compass_on:
            self._compass.stop()
        saved = ""
        tracklog.clear_live()
        if self.walk.points:
            self.walk.stop()
            try:
                track_mod.save(self.walk)
                track_mod.export_gpx(self.walk)
                saved = "Поход сохранён, выгружен GPX."
            except OSError as e:
                saved = f"Не удалось сохранить: {e}"
            # Находки уходят в журнал калибровки: именно по нему calibrate.py
            # подгоняет модель под ваш лес. Пустой выход тоже записывается —
            # без промахов модель обучится только на удачных днях.
            try:
                n = walk2journal.export(self.walk)
                if n:
                    saved += f" В журнал: {walk2journal.summary(self.walk)}."
            except (OSError, ValueError) as e:
                saved += f" В журнал не записалось: {e}"
        # Уборка осиротевших снимков — строго ПОСЛЕ сохранения похода:
        # иначе load_all() ещё не видит текущий поход и его кадры будут
        # приняты за ничейные и удалены вместе со всей заметкой.
        self._sweep_photos()
        self.dismiss()
        if self.on_close:
            self.on_close(self.walk, saved)

    def _sweep_photos(self):
        try:
            keep = set(track_mod.all_photo_names()) | set(self.walk.photo_names())
            photos_mod.cleanup(keep)
        except (OSError, ValueError):
            pass
