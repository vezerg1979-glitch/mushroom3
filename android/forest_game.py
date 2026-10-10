"""Небольшая автономная игра «Тихая охота» для Kivy.

Никакой сети, GPS, рекламы и доступа к данным пользователя.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle, Triangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget
from kivy.uix.togglebutton import ToggleButton


@dataclass
class Mushroom:
    x: float
    y: float
    kind: str
    radius: float
    picked: bool = False


FOREST_PALETTES = (
    ((.11,.21,.19), (.19,.35,.29), (.20,.32,.21)),  # утренний хвойный лес
    ((.17,.24,.22), (.30,.39,.29), (.29,.35,.20)),  # золотистый просвет
    ((.10,.18,.20), (.17,.29,.31), (.15,.28,.24)),  # туманный ельник
)

FOREST_NOTES = (
    "Сквозь ветви пробивается мягкий солнечный свет.",
    "Вдали слышится дятел. Под ногами тихо шуршат листья.",
    "Между елями стелется лёгкий туман.",
    "Ветер качает верхушки берёз. На мху блестит роса.",
    "У старого пня пахнет влажной древесиной.",
)

KINDS = (("Белый", 3), ("Подберёзовик", 2), ("Лисичка", 2), ("Мухомор", 0))


def make_clearing(seed=0, count=11):
    """Детерминированное размещение, без перекрытий, в долях экрана."""
    rng = random.Random(seed)
    result = []
    for _ in range(count):
        for _attempt in range(150):
            x, y = rng.uniform(.10, .90), rng.uniform(.12, .82)
            if all((x-m.x)**2 + (y-m.y)**2 > .010 for m in result):
                result.append(Mushroom(x, y, rng.choices(
                    [k for k, _ in KINDS], weights=[4, 4, 4, 2])[0], .042))
                break
    return result


def find_mushroom(mushrooms, x, y, width, height):
    """Координаты касания относительно поля; допускается 44dp зона."""
    for mushroom in reversed(mushrooms):
        if mushroom.picked:
            continue
        px, py = mushroom.x * width, mushroom.y * height
        if math.hypot(x-px, y-py) <= max(dp(23), mushroom.radius * min(width, height) * 1.6):
            return mushroom
    return None


class ForestScene(Widget):
    def __init__(self, on_pick, **kwargs):
        super().__init__(**kwargs)
        self.on_pick = on_pick
        self.mushrooms = make_clearing(1)
        self.seed = 1
        self.light_phase = 0.0
        self.ambient_particles = True
        self.animation = None
        self.bind(pos=lambda *_: self.paint(), size=lambda *_: self.paint())

    def new_clearing(self, seed):
        self.seed = seed
        self.mushrooms = make_clearing(seed)
        self.paint()

    def paint(self):
        self.canvas.clear()
        x, y = self.pos
        w, h = self.size
        if w < 1 or h < 1:
            return
        with self.canvas:
            background, haze, ground = FOREST_PALETTES[self.seed % len(FOREST_PALETTES)]
            Color(*background, 1)
            Rectangle(pos=self.pos, size=self.size)
            # Дальний лес: мягкая дымка и разная глубина планов.
            Color(*haze, .58)
            Ellipse(pos=(x+w*.12, y+h*.43), size=(w*.80, h*.49))
            for i in range(14):
                tx = x + w * ((i*.173 + .023) % 1)
                depth = .55 + .45 * ((i*7) % 11)/10
                tw = max(dp(3), w*.012*depth)
                Color(.12,.22,.19, .40)
                Rectangle(pos=(tx, y+h*.38), size=(tw, h*(.30+.28*depth)))
                Color(.12,.25,.20,.35)
                Triangle(points=[tx-w*.055*depth,y+h*.48,tx+tw/2,y+h*(.82+.1*depth),tx+w*.06*depth,y+h*.48])
            # Тёплые солнечные просветы, без анимации каждого пикселя.
            shimmer = .025*math.sin(self.light_phase)
            Color(.88,.77,.47,.065+shimmer)
            Ellipse(pos=(x+w*.47,y+h*.54), size=(w*.39,h*.41))
            Color(*ground, 1)
            Ellipse(pos=(x-w*.16,y-h*.14),size=(w*1.32,h*.69))
            rng = random.Random(self.seed + 71)
            # Солнечные лучи между стволами: полупрозрачные треугольники.
            glow = .045 + .018 * math.sin(self.light_phase)
            for beam in range(3):
                bx = x + w * (.28 + beam*.22)
                Color(.96, .86, .57, glow)
                Triangle(points=[bx, y+h*.94, bx-w*.19, y+h*.20, bx+w*.14, y+h*.20])
            # Слои глубины и ближние деревья, мох, папоротники, листва.
            for i in range(7):
                tx = x+w*(i+.25)/7
                trunk = w*(.014 + .015*(i%3)/2)
                Color(.09,.15,.12,1)
                Rectangle(pos=(tx,y+h*.32),size=(trunk,h*.72))
                Color(.10,.23,.16,1)
                Triangle(points=[tx-w*.095,y+h*.46,tx+trunk/2,y+h*.98,tx+w*.10,y+h*.46])
            # Кочки и камни добавляют фактуру почвы и визуальную глубину.
            for i in range(22):
                px=x+w*rng.random()
                py=y+h*(.025+.31*rng.random())
                size=dp(4)+dp(13)*rng.random()
                Color(.18,.29,.18,.50)
                Ellipse(pos=(px-size/2,py-size/3),size=(size*1.8,size*.65))
                Color(.31,.43,.24,.43)
                Ellipse(pos=(px-size/3,py),size=(size*1.15,size*.38))
            for i in range(100):
                px=x+w*rng.random()
                py=y+h*(.035+.34*rng.random())
                if i%5==0:
                    Color(.52,.36,.19,.55)
                    Ellipse(pos=(px,py),size=(dp(4),dp(2)))
                else:
                    Color(.32,.48,.27,.45)
                    Line(points=[px,py,px+w*(rng.random()-.5)*.018,py+h*.018],width=1)
            for i in range(12):
                px=x+w*rng.random()
                py=y+h*(.05+.25*rng.random())
                Color(.23,.43,.26,.6)
                for side in (-1,1):
                    Line(points=[px,py,px+side*w*.025,py+h*.045],width=1)
            for m in self.mushrooms:
                if m.picked:
                    continue
                mx, my = x+m.x*w, y+m.y*h
                r = max(dp(12), m.radius*min(w, h))
                Color(.84, .75, .56, 1)
                RoundedRectangle(pos=(mx-r*.24, my-r*.9), size=(r*.48, r*1.1), radius=[r*.16])
                if m.kind == "Мухомор":
                    Color(.83, .24, .18, 1)
                elif m.kind == "Лисичка":
                    Color(.93, .63, .19, 1)
                elif m.kind == "Подберёзовик":
                    Color(.62, .43, .27, 1)
                else:
                    Color(.49, .29, .16, 1)
                Ellipse(pos=(mx-r, my-r*.15), size=(2*r, r*1.12))
                # Светлый кант шляпки и мягкая тень под грибом.
                Color(.12,.12,.08,.24)
                Ellipse(pos=(mx-r*.85,my-r*.98),size=(r*1.7,r*.33))
                Color(.95,.84,.61,.46)
                Line(ellipse=(mx-r*.78,my+r*.13,r*1.56,r*.58,18,165),width=1)
                if m.kind == "Мухомор":
                    Color(.98, .91, .76, 1)
                    for ox, oy in [(-.45,.28),(.13,.47),(.48,.19)]:
                        Ellipse(pos=(mx+r*ox, my+r*oy), size=(r*.22,r*.17))
            # Светлячки/пылинки на дальнем плане; лёгкая, отключаемая анимация.
            if self.ambient_particles:
                for i in range(9):
                    phase = self.light_phase*.22 + i*1.93
                    px=x+w*(.08+((i*.137 + .018*math.sin(phase)) % .84))
                    py=y+h*(.39 + (i*.073 % .45) + .012*math.cos(phase))
                    Color(.98,.91,.64,.10+.10*(.5+.5*math.sin(phase)))
                    Ellipse(pos=(px,py),size=(dp(2.5),dp(2.5)))

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        m = find_mushroom(self.mushrooms, touch.x-self.x, touch.y-self.y, self.width, self.height)
        if m:
            m.picked = True
            self.paint()
            self.on_pick(m.kind)
        return True


class ForestGame:
    """Тихая охота: три полянки, ограниченное время, без проигрыша от ошибок."""
    def __init__(self):
        self.score = 0
        self.collected = 0
        self.round = 0
        self.deadline = 0
        self.event = None
        self.popup = None
        self.relaxed = True
        self.found_kinds = set()
        self.note_index = 0

    def open(self):
        self.score = self.collected = self.round = 0
        root = BoxLayout(orientation='vertical', spacing=dp(7), padding=dp(9))
        self.status = Label(size_hint_y=None, height=dp(46), font_size=sp(15),
                            color=(.93,.94,.85,1), bold=True)
        self.scene = ForestScene(self.pick)
        self.message = Label(size_hint_y=None, height=dp(54), font_size=sp(13),
                             color=(.88,.89,.75,1), halign='center')
        self.message.bind(size=lambda obj, val: setattr(obj, 'text_size', (val[0], None)))
        modes = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        self.relax_button = ToggleButton(text='Прогулка без времени', group='forest_mode', state='down',
                                         background_normal='', background_color=(.22,.43,.31,1))
        self.timer_button = ToggleButton(text='Поиск на время', group='forest_mode',
                                         background_normal='', background_color=(.25,.38,.33,1))
        self.relax_button.bind(on_release=lambda *_: self.set_mode(True))
        self.timer_button.bind(on_release=lambda *_: self.set_mode(False))
        modes.add_widget(self.relax_button)
        modes.add_widget(self.timer_button)
        atmosphere = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(8))
        self.ambient_button = ToggleButton(text='Свет и лесная дымка', state='down',
                                           background_normal='', background_color=(.23,.39,.29,1))
        self.ambient_button.bind(on_release=lambda *_: self.toggle_ambient())
        atmosphere.add_widget(self.ambient_button)
        actions = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        hint = Button(text='Подсказка', background_normal='', background_color=(.34,.42,.27,1))
        hint.bind(on_release=lambda *_: self.hint())
        advance = Button(text='Дальше в лес', background_normal='', background_color=(.25,.42,.35,1))
        advance.bind(on_release=lambda *_: self.next_clearing())
        actions.add_widget(hint)
        actions.add_widget(advance)
        buttons = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        again = Button(text='Новая прогулка', background_normal='', background_color=(.23,.46,.31,1))
        close = Button(text='Выйти', background_normal='', background_color=(.35,.38,.35,1))
        again.bind(on_release=lambda *_: self.restart())
        close.bind(on_release=lambda *_: self.popup.dismiss())
        buttons.add_widget(again)
        buttons.add_widget(close)
        for item in (self.status,modes,self.scene,self.message,atmosphere,actions,buttons):
            root.add_widget(item)
        self.scene.animation = Clock.schedule_interval(self.animate_forest, 1/8)
        self.popup = Popup(title='Тихая охота — лесная прогулка', content=root,
                           size_hint=(.96,.92), auto_dismiss=True,
                           background_color=(.08,.15,.12,1))
        self.popup.bind(on_dismiss=lambda *_: self.close_game())
        self.popup.open()
        self.restart()

    def toggle_ambient(self):
        self.scene.ambient_particles = self.ambient_button.state == 'down'
        self.scene.paint()

    def animate_forest(self, dt):
        if self.scene and self.scene.parent:
            self.scene.light_phase += dt * .55
            self.scene.paint()

    def restart(self):
        self.stop()
        self.score = self.collected = 0
        self.found_kinds = set()
        self.round = 1
        self.deadline = time.monotonic() + 90
        self.scene.new_clearing(random.randrange(1, 1000000))
        self.message.text = FOREST_NOTES[0] + ' Ищите грибы среди мха.'
        if not self.relaxed:
            self.event = Clock.schedule_interval(self.tick, .25)
        self.tick(0)

    def close_game(self):
        self.stop()
        if self.scene.animation is not None:
            self.scene.animation.cancel()
            self.scene.animation = None

    def stop(self):
        if self.event is not None:
            self.event.cancel()
            self.event = None

    def pick(self, kind):
        if self.round > 3 or (not self.relaxed and self.event is None):
            return
        if kind == 'Мухомор':
            self.message.text = 'Мухомор оставляем расти. В настоящем лесу незнакомые грибы не собираем.'
        else:
            value = dict(KINDS)[kind]
            self.score += value
            self.collected += 1
            self.found_kinds.add(kind)
            self.message.text = f'{kind} найден! +{value} очка. Прислушайтесь к тишине леса.'
        if not any(not m.picked and m.kind != 'Мухомор' for m in self.scene.mushrooms):
            self.next_clearing()
        self.tick(0)

    def next_clearing(self):
        if self.round >= 3:
            if self.relaxed:
                self.round = 0
            else:
                self.finish()
                return
        self.round += 1
        self.scene.new_clearing(random.randrange(1, 1000000))
        self.note_index += 1
        self.message.text = FOREST_NOTES[self.note_index % len(FOREST_NOTES)]

    def set_mode(self, relaxed):
        self.relaxed = relaxed
        self.restart()

    def hint(self):
        remaining = [m for m in self.scene.mushrooms if not m.picked and m.kind != 'Мухомор']
        if not remaining:
            self.message.text = 'На этой полянке всё найдено. Можно идти дальше.'
            return
        target = remaining[0]
        side = 'слева' if target.x < .38 else ('справа' if target.x > .62 else 'в центре')
        depth = 'ближе к краю поляны' if target.y > .55 else 'среди травы и мха'
        self.message.text = f'Присмотритесь {side}, {depth}. Здесь что-то прячется.'

    def finish(self):
        self.stop()
        self.round = 4
        self.message.text = (f'Прогулка завершена! В корзинке {self.collected} грибов, '
                             f'{self.score} очков. Найдено видов: {len(self.found_kinds)}.')
        self.tick(0)

    def tick(self, _dt):
        left = max(0, math.ceil(self.deadline-time.monotonic()))
        if not self.relaxed and self.round <= 3 and left == 0:
            self.finish()
            return
        if self.relaxed and self.round <= 3:
            self.status.text = (f'Полянка {self.round}/3   Корзинка: {self.collected}   '
                                f'Видов: {len(self.found_kinds)}   Без спешки')
            return
        self.status.text = (f'Полянка {min(self.round,3)}/3    '
                            f'Корзинка: {self.collected}    Очки: {self.score}    '
                            f'Время: {left} с' if self.round <= 3 else
                            f'Прогулка завершена · {self.score} очков')


def open_game():
    ForestGame().open()
