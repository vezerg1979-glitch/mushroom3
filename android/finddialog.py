# -*- coding: utf-8 -*-
"""
finddialog.py — карточка метки: заметка и снимки.

Открывается сразу после выбора вида и второй раз — при правке уже
поставленной метки. Устроена так, чтобы её можно было закрыть, ничего не
заполняя: в лесу чаще всего достаточно самой метки, а подписывать её будут
далеко не всегда. Поэтому кнопка «Готово» есть всегда, а поля пустые.

Порядок элементов выбран по частоте использования: сверху снимки (снял и
пошёл дальше), ниже заметка (набирать текст в лесу неудобно и делают это
реже), в самом низу — количество и удаление.

Снимки показываются миниатюрами в ряд. Полный кадр открывается касанием:
на маленькой картинке не разобрать, годится она для определения или смазана,
а переснять можно только пока стоишь на месте.
"""

from __future__ import annotations

from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import AsyncImage, Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.utils import get_color_from_hex as hexc
from kivy.clock import mainthread
from kivy.graphics import Color, Rectangle

import atlas
import mushroom_forecast as engine
import palette
import theme
import photos as photos_mod

def _apply_palette():
    """Перечитывает цвета после смены темы.

    Цвета копируются в константы модуля при загрузке — так быстрее, но
    после переключения копии остаются прежними. theme вызывает эту функцию
    и пересобирает экран: у виджета цвет выставлен в момент создания, и
    задним числом палитра его не изменит.
    """
    global INK, MUTED, CARD, ACCENT, RED, SOFT
    INK = hexc(palette.INK)
    MUTED = hexc(palette.MUTED)
    CARD = hexc(palette.CARD)
    ACCENT = hexc(palette.ACCENT)
    RED = hexc(palette.RED)
    SOFT = hexc(palette.SOFT)


_apply_palette()
theme.register(_apply_palette)

THUMB = dp(84)


def _fill(widget, color):
    with widget.canvas.before:
        Color(*color)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(pos=lambda w, v: setattr(rect, "pos", v),
                size=lambda w, v: setattr(rect, "size", v))


def show_photo(name: str):
    """Снимок во весь экран. Касание закрывает."""
    path = photos_mod.path_for(name)
    box = BoxLayout(orientation="vertical", padding=dp(4), spacing=dp(4))
    _fill(box, CARD)
    box.add_widget(Image(source=path, fit_mode="contain"))
    pop = Popup(title=name, content=box, size_hint=(0.98, 0.9),
                title_size=sp(11), separator_color=ACCENT)
    close = Button(text="Закрыть", size_hint_y=None, height=dp(44),
                   font_size=sp(14), background_normal="",
                   background_color=SOFT, color=INK)
    close.bind(on_release=lambda *_: pop.dismiss())
    box.add_widget(close)
    pop.open()
    return pop


class FindDialog(Popup):
    """Карточка одной метки.

    on_done(find) вызывается после «Готово», on_delete(find) — после удаления.
    Снимки складываются в find.photos сразу, как только приходят с камеры:
    если приложение упадёт на следующем шаге, кадр не пропадёт.
    """

    def __init__(self, find, title="Метка", on_done=None, on_delete=None, **kw):
        self.find = find
        self._on_done = on_done
        self._on_delete = on_delete
        self._camera = photos_mod.Photographer()

        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        _fill(box, CARD)

        self.status = Label(text="", font_size=sp(11), color=MUTED,
                            halign="left", valign="middle", size_hint_y=None,
                            height=dp(18))
        self.status.bind(
            width=lambda w, x: setattr(w, "text_size", (x, None)),
            texture_size=lambda w, t: setattr(w, "height", max(dp(18), t[1])))

        # --- эталон ---
        # Сверять снимок с эталоном имеет смысл ровно здесь: гриб ещё в
        # руках, а не в корзине вперемешку с остальными, и ошибку видом
        # можно исправить, пока стоишь на месте. Строка узкая: главное в
        # карточке — свои снимки, эталон только подсказка.
        #
        # Полоска пересобирается на месте, поэтому она в отдельном
        # контейнере: вид у метки может смениться прямо отсюда.
        self.ref_slot = BoxLayout(size_hint_y=None, height=dp(46))
        box.add_widget(self.ref_slot)

        # --- снимки ---
        self.strip = BoxLayout(size_hint=(None, None), height=THUMB,
                               spacing=dp(6))
        self.strip.bind(minimum_width=self.strip.setter("width"))
        strip_sv = ScrollView(size_hint_y=None, height=THUMB, do_scroll_y=False,
                              bar_width=0)
        strip_sv.add_widget(self.strip)
        box.add_widget(strip_sv)

        cams = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        b_shot = Button(text="Снять фото", font_size=sp(14), bold=True,
                        background_normal="", background_color=ACCENT)
        b_shot.bind(on_release=lambda *_: self._capture())
        b_pick = Button(text="Из галереи", font_size=sp(13),
                        background_normal="", background_color=SOFT, color=INK)
        b_pick.bind(on_release=lambda *_: self._pick())
        cams.add_widget(b_shot)
        cams.add_widget(b_pick)
        box.add_widget(cams)

        # --- заметка ---
        box.add_widget(Label(text="Заметка", font_size=sp(11), color=MUTED,
                             halign="left", valign="middle", size_hint_y=None,
                             height=dp(18),
                             text_size=(dp(300), None)))
        self.note = TextInput(text=find.note or "", font_size=sp(14),
                              size_hint_y=None, height=dp(96),
                              hint_text="под елью у просеки, ножка сетчатая",
                              padding=(dp(8), dp(8)))
        box.add_widget(self.note)

        # --- количество ---
        cnt = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        cnt.add_widget(Label(text="Штук", font_size=sp(12), color=MUTED,
                             size_hint_x=None, width=dp(56)))
        self.count = Label(text=str(max(1, find.count)), font_size=sp(17),
                           bold=True, color=INK)

        def stepper(label, delta):
            b = Button(text=label, font_size=sp(20), bold=True, size_hint_x=None,
                       width=dp(52), background_normal="", background_color=SOFT,
                       color=INK)
            b.bind(on_release=lambda *_: self._bump(delta))
            return b

        cnt.add_widget(stepper("−", -1))
        cnt.add_widget(self.count)
        cnt.add_widget(stepper("+", 1))
        # Координаты рядом со счётчиком, а не отдельной строкой: место в
        # карточке дорогое, а нажимают эту кнопку редко — зато метко.
        # «Стой там, я тебе точку скину» — обычный разговор в лесу, а до
        # сих пор передать точку было нечем.
        b_coord = Button(text="Координаты", size_hint_x=None, width=dp(104),
                         font_size=sp(12), background_normal="",
                         background_color=SOFT, color=INK)
        b_coord.bind(on_release=lambda *_: self._copy_coords())
        cnt.add_widget(b_coord)
        box.add_widget(cnt)

        box.add_widget(self.status)

        # --- кнопки ---
        btns = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        b_del = Button(text="Удалить метку", font_size=sp(13),
                       background_normal="", background_color=SOFT, color=RED)
        b_del.bind(on_release=lambda *_: self._delete())
        b_ok = Button(text="Готово", font_size=sp(16), bold=True,
                      background_normal="", background_color=ACCENT)
        b_ok.bind(on_release=lambda *_: self._done())
        btns.add_widget(b_del)
        btns.add_widget(b_ok)
        box.add_widget(btns)

        super().__init__(title=title, content=box, size_hint=(0.94, 0.9),
                         separator_color=RED, title_size=sp(15),
                         auto_dismiss=False, **kw)
        self._fill_reference()
        self._redraw_strip()

    # --- эталон -------------------------------------------------------------
    def _fill_reference(self):
        """Строка вида: эталон и кнопка сверки. Без вида — приглашение указать.

        Метка «просто метка» тоже получает эту строку. Часто вид становится
        понятен позже — дома, по снимку, — а раньше назвать его было негде:
        карточка показывала эталон только тем, у кого вид уже выбран.
        """
        self.ref_slot.clear_widgets()
        species = engine.SPECIES.get(self.find.species)
        if species is None:
            lab = Label(text="Вид не указан", font_size=sp(12), color=MUTED,
                        halign="left", valign="middle")
            lab.bind(width=lambda w, x: setattr(w, "text_size", (x, None)))
            b = Button(text="Указать вид", size_hint_x=None, width=dp(120),
                       font_size=sp(12), background_normal="",
                       background_color=SOFT, color=INK)
            b.bind(on_release=lambda *_: self._ask_species())
            self.ref_slot.add_widget(lab)
            self.ref_slot.add_widget(b)
            return
        key = self.find.species
        self.ref_slot.spacing = dp(6)
        self.ref_slot.add_widget(atlas.SpeciesPicture(key=key, size_hint_x=None,
                                                      width=dp(46)))
        lab = Label(text=f"Эталон: {species.name}", font_size=sp(12),
                    color=MUTED, halign="left", valign="middle")
        lab.bind(width=lambda w, x: setattr(w, "text_size", (x, None)))
        self.ref_slot.add_widget(lab)
        b = Button(text="Сверить", size_hint_x=None, width=dp(88),
                   font_size=sp(12), background_normal="",
                   background_color=SOFT, color=INK)
        # Смена вида живёт внутри карточки эталона, а не рядом с кнопкой
        # «Сверить»: две кнопки в одной узкой строке — это промахи, а
        # сомнение в виде возникает как раз при взгляде на признаки.
        b.bind(on_release=lambda *_: atlas.card(key, species,
                                                on_change=self._ask_species))
        self.ref_slot.add_widget(b)

    def _copy_coords(self):
        """Координаты метки в буфер обмена.

        Формат «55.960600, 38.045600» намеренно самый скучный: его понимают
        и карты Яндекса, и Google, и OsmAnd, и человек на том конце может
        просто вставить строку в поиск. Красивые градусы с минутами
        выглядят солиднее, но их половина программ не разбирает.
        """
        text = f"{self.find.lat:.6f}, {self.find.lon:.6f}"
        try:
            from kivy.core.clipboard import Clipboard
            Clipboard.copy(text)
        except Exception as e:                                    # noqa: BLE001
            self.status.text = f"Не удалось скопировать: {text}"
            return
        self.status.text = f"Скопировано: {text}"

    def _ask_species(self):
        atlas.picker(self._set_species, title="Какой это вид?")

    def _set_species(self, key):
        """Меняет вид у метки, ничего больше не трогая.

        Раньше исправить ошибку можно было только удалением метки, а вместе
        с ней уходили снимки, заметка и координаты — то есть всё, ради чего
        метку и ставили. Снимки тут особенно жаль: переснять гриб, который
        уже в корзине или срезан, нельзя.
        """
        if key == self.find.species:
            return
        self.find.species = key
        species = engine.SPECIES.get(key)
        self.title = species.name if species else "Метка"
        self._fill_reference()
        self.status.text = (f"Вид изменён: {species.name}" if species
                            else "Вид снят: осталась просто метка")

    # --- снимки -------------------------------------------------------------
    def _redraw_strip(self):
        self.strip.clear_widgets()
        if not self.find.photos:
            hint = Label(text="Снимков пока нет", font_size=sp(11), color=MUTED,
                         size_hint=(None, None), size=(dp(160), THUMB))
            self.strip.add_widget(hint)
            return
        for name in list(self.find.photos):
            cell = BoxLayout(orientation="vertical", size_hint=(None, None),
                             size=(THUMB, THUMB), spacing=dp(2))
            img = AsyncImage(source=photos_mod.path_for(name),
                             fit_mode="contain")
            img.bind(on_touch_down=lambda w, touch, n=name:
                     bool(w.collide_point(*touch.pos)) and show_photo(n))
            cell.add_widget(img)
            drop = Button(text="убрать", font_size=sp(9), size_hint_y=None,
                          height=dp(18), background_normal="",
                          background_color=SOFT, color=MUTED)
            drop.bind(on_release=lambda _b, n=name: self._drop(n))
            cell.add_widget(drop)
            self.strip.add_widget(cell)

    def _capture(self):
        self.status.text = "Открываю камеру…"
        self._camera.capture(self._got_photo)

    def _pick(self):
        self.status.text = "Открываю галерею…"
        self._camera.pick(self._got_photo)

    @mainthread
    def _got_photo(self, name, error):
        """Ответ от камеры приходит из потока Android."""
        if name:
            self.find.photos.append(name)
            self.status.text = (f"Снимков: {len(self.find.photos)}, "
                                f"занято {photos_mod.size_text()}")
            self._redraw_strip()
        elif error:
            self.status.text = f"Не вышло: {error}"
        else:
            self.status.text = "Съёмка отменена"

    def _drop(self, name):
        """Убирает снимок из метки и удаляет файл.

        Файл удаляется сразу: снимок, который человек забраковал, хранить
        незачем, а место на карточке в лесу не появится.
        """
        if name in self.find.photos:
            self.find.photos.remove(name)
        photos_mod.remove(name)
        self.status.text = "Снимок удалён"
        self._redraw_strip()

    # --- количество ---------------------------------------------------------
    def _bump(self, delta):
        value = max(1, min(999, int(self.count.text) + delta))
        self.count.text = str(value)

    # --- завершение ---------------------------------------------------------
    def _done(self):
        self.find.note = self.note.text.strip()
        self.find.count = max(1, int(self.count.text))
        self.dismiss()
        if self._on_done:
            self._on_done(self.find)

    def _delete(self):
        for name in list(self.find.photos):
            photos_mod.remove(name)
        self.find.photos = []
        self.dismiss()
        if self._on_delete:
            self._on_delete(self.find)
