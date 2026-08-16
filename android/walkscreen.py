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

import time

from kivy.clock import Clock, mainthread
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.utils import get_color_from_hex as hexc

import palette

import location as location_mod
import mushroom_forecast as engine
import compass as compass_mod
import nav
import walk2journal
import service_ctl
import track as track_mod
import tracklog
import photos as photos_mod
from finddialog import FindDialog
from mapview import TileMap
from navwidget import NavArrow

INK = hexc(palette.INK)
MUTED = hexc(palette.MUTED)
CARD = hexc(palette.CARD)
ACCENT = hexc(palette.ACCENT)
RED = hexc(palette.RED)
BLUE = hexc(palette.BLUE)

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

    def __init__(self, title, value="—", color=INK, **kw):
        super().__init__(orientation="vertical", **kw)
        self.lbl = Label(text=value, font_size=sp(22), bold=True, color=color)
        self.add_widget(self.lbl)
        self.add_widget(Label(text=title, font_size=sp(11), color=MUTED,
                              size_hint_y=None, height=dp(16)))

    def set(self, text):
        self.lbl.text = text


class WalkScreen(Popup):
    """Режим похода поверх основного экрана."""

    def __init__(self, lat, lon, biotope="смешанный", place="", on_close=None, **kw):
        self.walk = track_mod.Walk(place=place, biotope=biotope)
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
        for c in (self.c_dist, self.c_time, self.c_finds):
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
        self.map.set_here(lat, lon)
        root.add_widget(self.map)

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
        root.add_widget(btns)

        # Вспомогательные кнопки в два ряда. Пять штук в одну строку на экране
        # шириной 360 dp дают по 66 dp на кнопку — подписи не помещаются и
        # налезают друг на друга: «Слежение: вк.К машинОтменить мет».
        # Заодно каждая кнопка получает text_size: если надпись всё же длиннее
        # места, она обрежется многоточием внутри своей кнопки, а не поверх
        # соседней.
        def small(text, action, color=INK):
            b = Button(text=text, font_size=sp(12), background_normal="",
                       background_color=hexc(palette.SOFT), color=color,
                       halign="center", valign="middle", shorten=True,
                       shorten_from="right")
            b.bind(size=lambda w, v: setattr(w, "text_size", v))
            b.bind(on_release=lambda *_: action())
            return b

        row1 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.b_follow = small("Слежение: вкл", self.toggle_follow)
        self.b_nav = small("К машине", self.toggle_nav)
        row1.add_widget(self.b_follow)
        row1.add_widget(self.b_nav)
        row1.add_widget(small("Заметка и фото", self.edit_last_find))
        root.add_widget(row1)

        row2 = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        row2.add_widget(small("Приём и сервис", self.show_service_log, MUTED))
        row2.add_widget(small("Закрыть поход", self.finish))
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
        self._refresh()

    # --- управление ---------------------------------------------------------
    def toggle(self):
        self.running = not self.running
        self.b_start.text = "Пауза" if self.running else "Продолжить"
        self.b_start.background_color = MUTED if self.running else ACCENT
        self.b_find.disabled = not self.running
        if self.running:
            self._keep_screen(True)
            self._start_gps()
            self.hint.text = "Идёт запись. Кнопка «Нашёл!» ставит метку на карте."
        else:
            self._keep_screen(False)
            self.hint.text = "Пауза. Метры не считаются."

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
        else:
            self.walk.last_acc = acc
        self._last_fix = time.time()
        self.map.set_here(lat, lon)
        self._refresh()

    def mark_find(self):
        if not self.map.here:
            return
        self._species_dialog()

    def _species_dialog(self):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        _fill(box, CARD)
        sv = ScrollView()
        grid = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        grid.bind(minimum_height=grid.setter("height"))
        for key, sp_obj in engine.SPECIES.items():
            b = Button(text=sp_obj.name, size_hint_y=None, height=dp(46),
                       font_size=sp(15), background_normal="",
                       background_color=hexc(palette.SOFT), color=INK)
            b.bind(on_release=lambda _b, k=key: self._add_find(k, pop))
            grid.add_widget(b)
        other = Button(text="Просто метка", size_hint_y=None, height=dp(46),
                       font_size=sp(15), background_normal="",
                       background_color=hexc(palette.SOFT_ALT), color=MUTED)
        other.bind(on_release=lambda _b: self._add_find("", pop))
        grid.add_widget(other)
        sv.add_widget(grid)
        box.add_widget(sv)
        pop = Popup(title="Что нашли?", content=box, size_hint=(0.9, 0.8),
                    separator_color=RED, title_size=sp(15))
        pop.open()

    def _add_find(self, key, pop):
        """Метка ставится сразу, карточка открывается следом.

        Порядок важен: сначала запись, потом уточнения. Если человек
        передумает заполнять карточку или приложение закроют, метка с
        координатами уже сохранена — а координаты и есть самое ценное,
        их потом не восстановить.
        """
        pop.dismiss()
        lat, lon = self.map.here
        find = self.walk.add_find(lat, lon, key)
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
        box = BoxLayout(orientation="vertical", padding=dp(8))
        _fill(box, CARD)
        sv = ScrollView()
        lbl = Label(text=head + "\n" + tracklog.read_log(), color=INK,
                    font_size=sp(11), halign="left", valign="top",
                    size_hint_y=None, padding=(dp(8), dp(8)))
        lbl.bind(width=lambda w, x: setattr(w, "text_size", (x - dp(16), None)),
                 texture_size=lambda w, t: setattr(w, "height", t[1] + dp(16)))
        sv.add_widget(lbl)
        box.add_widget(sv)
        Popup(title="Фоновая запись", content=box, size_hint=(0.94, 0.8),
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
