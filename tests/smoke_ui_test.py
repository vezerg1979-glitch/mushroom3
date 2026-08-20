# -*- coding: utf-8 -*-
"""Дымовой прогон интерфейса на настоящем Kivy.

Зачем понадобился. Все остальные тесты проверяют арифметику и разбирают
исходники — это дёшево и ловит многое, но не трогает сам Kivy. Из-за этого
на телефон уехала кнопка, которая падала в конструкторе экрана похода:
значок отмены разбирался по номерам полей кортежа, и в одной ветке номер
был на единицу больше нужного. Геометрия при этом была правильной, тесты
были зелёными, а «В лес» открывал окно с трассировкой.

Поэтому здесь окна действительно создаются и рисуются. Нужен экран, поэтому
на машине без него тест пропускается, а в CI поднимается Xvfb.

Правило простое: всё, что человек может нажать, должно быть нажато хотя бы
раз до сборки APK.

Имя файла не «test_...» намеренно: обычный прогон в CI идёт через
`unittest discover`, а тот не умеет пропускать модуль целиком — отсутствие
экрана он засчитал бы как ошибку. Pytest подбирает и «..._test.py», поэтому
файл виден там, где его умеют запускать.
"""

import os
import sys
import tempfile
import time

import pytest

# Kivy наверху файла быть не должно: без него сбор тестов падает целиком, и
# машина без графики не может прогнать даже те тесты, которые окна не
# требуют. Импорты Kivy идут ниже — после importorskip — или внутри самих
# тестов. Один такой импорт я сюда уже заносил: на своей машине с Kivy всё
# проходило, а CI встал на сборе.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

ROOT = APP
sys.path.insert(0, ROOT)

kivy = pytest.importorskip("kivy", reason="Kivy не установлен")

if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    pytest.skip("нужен экран: запускать под xvfb-run", allow_module_level=True)

os.environ.setdefault("KIVY_NO_ARGS", "1")

import places  # noqa: E402


def _android_main():
    """Мобильный main.py, а не пусковой из корня репозитория.

    Их два, и оба называются main. Обычный импорт по имени приносит корневой,
    который только выбирает интерфейс и никакого MushroomApp не содержит.
    """
    import importlib.util

    path = os.path.join(ROOT, "main.py")
    spec = importlib.util.spec_from_file_location("android_main", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("android_main", mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module", autouse=True)
def data_dir():
    """Свой каталог данных на весь модуль.

    Две тонкости, обе стоили путаницы. Первая: не через MUSHROOM_DATA_DIR —
    эта переменная сильнее всего остального и, выставленная на процесс,
    уводила туда же соседние тесты. Вторая: MushroomApp.build() первым делом
    зовёт places.set_data_dir(user_data_dir) и тем самым выбирается из
    подменённого каталога наружу, в настоящие данные пользователя. Поэтому
    подменяется и сама функция — иначе дымовой прогон читает чужие настройки
    и оставляет свои, а следующий за ним тест модели падает на непонятном.
    """
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as mp:
        mp.setattr(places, "_DATA_DIR", tmp)
        mp.setattr(places, "set_data_dir", lambda path: tmp)
        yield tmp


@pytest.fixture(scope="module")
def app():
    main_mod = _android_main()
    a = main_mod.MushroomApp()
    a.build()
    a._module = main_mod
    return a


@pytest.fixture
def walk_screen():
    from walkscreen import WalkScreen

    w = WalkScreen(56.02, 38.28, "смешанный", "Тест")
    w.open()
    yield w
    w.dismiss()


# --------------------------------------------------------------------------- #
#  Значки
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", ["heart", "journal", "undo"])
def test_every_icon_actually_draws(name):
    """Именно этого теста не хватило: значок падал при отрисовке, не в расчёте."""
    import icons

    b = icons.IconButton(icon=name, size=(48, 48))
    b.redraw()
    assert len(b.canvas.children) > 2          # фон плюс сам значок


@pytest.mark.parametrize("name", ["heart", "journal", "undo"])
def test_disabled_icon_draws_too(name):
    import icons

    b = icons.IconButton(icon=name, size=(48, 48), disabled=True)
    b.redraw()


def test_plan_covers_every_primitive_of_every_icon():
    """Разбор примитивов — распаковкой, поэтому лишнее поле падает сразу."""
    import icons

    known = {"ellipse", "quad", "tri", "line"}
    for name in icons.ICONS:
        for item in icons.shapes(name, 0.0, 0.0, 48.0, 48.0):
            what, kwargs = icons.plan(item)
            assert what in known
            assert kwargs


def test_unknown_primitive_is_loud():
    import icons

    with pytest.raises(ValueError):
        icons.plan(("спираль", 1, 2))


# --------------------------------------------------------------------------- #
#  Эталонные изображения
# --------------------------------------------------------------------------- #

def _species_keys():
    import atlas

    return sorted(atlas.PICTURES)


@pytest.mark.parametrize("key", _species_keys())
def test_every_reference_picture_actually_draws(key):
    """Ровно то, что не поймала арифметика: заливка веером идёт через Mesh,
    и неверный набор аргументов падает при отрисовке, а не в расчёте."""
    import atlas

    pic = atlas.SpeciesPicture(key=key, size=(120, 120), pos=(0, 0))
    pic.redraw()
    assert len(pic.canvas.children) > 4         # плашка плюс сам гриб


@pytest.mark.parametrize("key", _species_keys())
def test_every_species_card_opens(key):
    """Карточка вида: крупный рисунок, признаки, двойники."""
    import atlas
    import mushroom_forecast as engine

    pop = atlas.card(key, engine.SPECIES[key])
    pop.dismiss()


def test_species_picker_opens_and_marks_a_find(walk_screen):
    """Окно «Что нашли?» строится и ставит метку нажатием на строку.

    Правило прежнее: всё, что человек может нажать, должно быть нажато хотя
    бы раз до сборки APK. Здесь этого правила не хватало дважды — сначала
    для значка отмены, теперь для строк с картинками.
    """
    import atlas

    w = walk_screen
    w.toggle()
    w.feed(56.02, 38.28, acc=8.0, t=w.walk.started + 1)
    w.mark_find()

    rows = [x for x in _walk(_window()) if isinstance(x, atlas.SpeciesRow)]
    assert len(rows) == len(_species_keys())

    rows[0].dispatch("on_release")
    assert len(w.walk.finds) == 1
    assert w.walk.finds[0].species == rows[0].key
    w.toggle()


def test_walk_carries_the_forecast_of_the_day():
    """Снимок прогноза должен доезжать до похода и переживать сохранение.

    Снимок задаётся здесь явно, а не берётся с главного экрана: на сборочной
    машине сети нет, прогноз пустой, и сравнение «пусто равно пусто» проходит
    при любом обрыве. Первая версия этого теста именно так и молчала.
    """
    import track as track_mod
    from walkscreen import WalkScreen

    snapshot = {"белый": 61.4, "лисичка": 22.0}
    w = WalkScreen(56.02, 38.28, "смешанный", "Тест", index=snapshot)
    w.open()
    try:
        assert w.walk.index == snapshot
        assert w.walk.index_stamp > 0
        w.feed(56.02, 38.28, acc=8.0, t=w.walk.started + 1)
        assert track_mod.save(w.walk)
        back = [x for x in track_mod.load_all()
                if abs(x.started - w.walk.started) < 1.0][0]
        assert back.index == snapshot
    finally:
        w.dismiss()


def test_main_screen_takes_the_snapshot_from_its_own_forecast(app):
    """Снимок собирается по ключам видов, а не по их названиям.

    В расчёте индексы разложены по названиям («Белый гриб»), а находки и
    эталоны живут по ключам («белый»). Перепутать их легко, а заметно это
    станет только через сезон, когда сравнивать окажется нечего.
    """
    import mushroom_forecast as engine

    class FakeRes:
        today = 0

        @staticmethod
        def value(name, _i):
            return 50.0 + len(name)

    before = app.res
    app.res = FakeRes()
    try:
        snap = app._index_today()
    finally:
        app.res = before
    assert set(snap) == set(engine.SPECIES)
    assert snap["белый"] == round(50.0 + len(engine.SPECIES["белый"].name), 1)


def test_snapshot_is_empty_without_a_forecast(app):
    before = app.res
    app.res = None
    try:
        assert app._index_today() == {}
    finally:
        app.res = before


def test_species_of_a_find_can_be_changed(walk_screen):
    """Сверился, понял, что ошибся, — и поправил, не теряя снимков.

    Проверяется весь путь целиком: карточка метки, карточка эталона,
    кнопка «Это другой вид», список, выбор. Разорвись он в любом месте,
    человеку останется только удалить метку вместе с фотографиями.
    """
    import atlas
    from finddialog import FindDialog

    w = walk_screen
    w.toggle()
    w.feed(56.02, 38.28, acc=8.0, t=w.walk.started + 1)
    find = w.walk.add_find(56.02, 38.28, "белый")
    find.note = "под елью"
    find.photos = ["snap.jpg"]

    w._edit_find(find)
    # Окно ищется по самой метке, а не «последнее открытое»: соседние тесты
    # оставляют свои карточки висеть, и поиск по типу цепляет чужую.
    dlg = _find_dialog_for(find)

    # Кнопки нажимаются настоящие: карточка эталона, собранная в тесте
    # вручную, проверяла бы саму себя, а не то, что окно метки её открывает
    # и связывает со сменой вида. Именно на этом тест однажды и промолчал.
    check = [b for b in _walk(dlg.ref_slot) if getattr(b, "text", "") == "Сверить"]
    assert check, "в карточке метки нет кнопки сверки с эталоном"
    check[0].dispatch("on_release")

    card = _popup_titled("Белый гриб")
    other = [b for b in _walk(card.content)
             if getattr(b, "text", "") == "Это другой вид"]
    assert other, "в карточке эталона нет кнопки смены вида"
    other[0].dispatch("on_release")

    picker = _popup_titled("Какой это вид?")
    rows = {r.key: r for r in _walk(picker.content)
            if isinstance(r, atlas.SpeciesRow)}
    assert "подберёзовик" in rows
    rows["подберёзовик"].dispatch("on_release")

    assert find.species == "подберёзовик"
    assert find.note == "под елью"
    assert find.photos == ["snap.jpg"]
    assert len(w.walk.finds) == 1
    dlg.dismiss()
    w.toggle()


def test_a_plain_mark_can_be_named_later(walk_screen):
    """Вид часто становится понятен дома, по снимку. Назвать его должно быть где."""
    from finddialog import FindDialog

    w = walk_screen
    find = w.walk.add_find(56.02, 38.28, "")
    w._edit_find(find)
    dlg = _find_dialog_for(find)
    labels = [b for b in _walk(dlg.ref_slot) if getattr(b, "text", "") == "Указать вид"]
    assert labels, "у метки без вида нет кнопки «Указать вид»"
    dlg._set_species("лисичка")
    assert find.species == "лисичка"
    assert dlg.title == "Лисичка"
    dlg.dismiss()


def _window():
    from kivy.core.window import Window

    return Window


def _find_dialog_for(find):
    """Карточка именно этой метки среди открытых окон."""
    from finddialog import FindDialog

    for x in _walk(_window()):
        if isinstance(x, FindDialog) and x.find is find:
            return x
    raise AssertionError("карточка метки не открылась")


def _popup_titled(title):
    from kivy.uix.popup import Popup

    for x in _walk(_window()):
        if isinstance(x, Popup) and x.title == title:
            return x
    raise AssertionError(f"окно «{title}» не открылось")


def _walk(root):
    yield root
    for child in getattr(root, "children", []):
        for node in _walk(child):
            yield node


# --------------------------------------------------------------------------- #
#  Слои, цвета и тесная шапка
# --------------------------------------------------------------------------- #

def test_repaint_does_not_cover_open_windows(app):
    """Пересобранный экран — нижний слой, а не верхний.

    Kivy рисует окна в порядке добавления на холст, а не по списку детей.
    Пересобранный главный экран добавлялся последним и ложился ПОВЕРХ
    открытого похода: карта и кнопки просвечивали сквозь прогноз.
    """
    from kivy.core.window import Window
    from kivy.clock import Clock
    from walkscreen import WalkScreen

    walk = WalkScreen(56.02, 38.28, "смешанный", "Тест")
    walk.open()
    Clock.tick()
    try:
        app._repaint()
        Clock.tick()
        # Главный экран уходит в группу before, окна остаются в основной:
        # before рисуется первой, то есть экран заведомо под ними. Проверять
        # порядок внутри одного списка нельзя — они лежат в разных.
        assert app.root.canvas in list(Window.canvas.before.children), (
            "главный экран не в нижнем слое")
        assert walk.canvas not in list(Window.canvas.before.children), (
            "окно уехало под главный экран")
    finally:
        walk.dismiss(animation=False)
        Clock.tick()


def test_map_buttons_stay_visible_in_the_dark(walk_screen):
    """«+» и «−» на карте пропадали ночью: белая плашка, светлая подпись."""
    import palette
    import theme
    from kivy.uix.button import Button

    было = palette.current()
    try:
        for тема in ("день", "ночь"):
            theme.set_mode(тема, 56.0, 38.0)
            экран = type(walk_screen)(56.02, 38.28, "смешанный", "Тест")
            кнопки = [b for b in _walk(экран.content)
                      if isinstance(b, Button) and b.text in ("+", "−")]
            assert len(кнопки) == 2, тема
            for b in кнопки:
                фон = b.background_color[:3]
                текст = b.color[:3]
                разница = sum(abs(a - c) for a, c in zip(фон, текст))
                assert разница > 0.9, f"{тема}: подпись сливается с плашкой"
            экран.dismiss(animation=False)
    finally:
        theme.set_mode(было, 56.0, 38.0)


def test_place_name_gets_room_on_a_narrow_phone(app):
    """На телефоне 360 точек «Фрязино» вставало в столбик по букве.

    Мелкие кнопки шапки съедали 290 точек из 340, названию оставалось
    полсотни. Поэтому в портрете шапка разделена на два ряда.
    """
    from kivy.clock import Clock
    from kivy.core.window import Window
    from kivy.metrics import dp

    было = Window.size
    try:
        Window.size = (360, 740)
        app._repaint()
        # Раскладка считается не сразу, и ждать «пока ширина станет не нулевой»
        # нельзя: у виджета Kivy размер по умолчанию 100×100, и цикл выходил
        # на первом же тике, намерив эту сотню вместо настоящей ширины.
        # Поэтому тиков просто отсчитывается с запасом.
        for _ in range(20):
            Clock.tick()
        assert app.btn_place.width > dp(150), (
            f"названию места осталось {app.btn_place.width:.0f} точек")
    finally:
        Window.size = было
        app._repaint()
        Clock.tick()


# --------------------------------------------------------------------------- #
#  Поворот экрана
# --------------------------------------------------------------------------- #

def test_main_screen_rebuilds_on_rotation(app):
    """Поворот и обратно: раскладка меняется, экран остаётся живым.

    Проверяется настоящая пересборка, а не расчёт по числам: части экрана
    расставляются заново, и забытая в одной из раскладок часть пропадёт
    именно здесь.
    """
    from kivy.clock import Clock
    from kivy.core.window import Window

    было = Window.size
    try:
        Window.size = (420, 880)
        Clock.tick()
        assert app._wide is False
        части_портрет = len(list(_walk(app.root)))

        Window.size = (960, 480)
        Clock.tick()
        assert app._wide is True, "на боку должны быть две колонки"
        части_бока = len(list(_walk(app.root)))
        assert abs(части_бока - части_портрет) <= 4, (
            "при повороте потерялись или удвоились части экрана")

        Window.size = (420, 880)
        Clock.tick()
        assert app._wide is False
    finally:
        Window.size = было
        Clock.tick()


def test_walk_screen_rebuilds_on_rotation(walk_screen):
    """На боку карта уходит влево, кнопки — в узкую колонку справа."""
    from kivy.clock import Clock
    from kivy.core.window import Window

    w = walk_screen
    было = Window.size
    try:
        Window.size = (420, 880)
        Clock.tick()
        w._on_window_size()
        assert w._wide is False

        Window.size = (960, 480)
        Clock.tick()
        w._on_window_size()
        assert w._wide is True
        карта = [x for x in _walk(w.content) if type(x).__name__ == "TileMap"]
        assert карта, "карта пропала при повороте"
        кнопки = [b.text for b in _walk(w.content)
                  if getattr(b, "text", "") == "Нашёл!"]
        assert кнопки, "«Нашёл!» пропала при повороте"
    finally:
        Window.size = было
        Clock.tick()
        w._on_window_size()


# --------------------------------------------------------------------------- #
#  Журнал: миниатюры и итог сезона
# --------------------------------------------------------------------------- #

def test_journal_row_shows_a_thumbnail_and_stays_tappable(data_dir):
    """Снимок лежит поверх кнопки, а не рядом: строка нажимается целиком.

    Соседний виджет съел бы полсотни точек, на которых нажатие не работает.
    Проверяется и то, и другое: картинка на месте, кнопка под ней.
    """
    from kivy.uix.button import Button
    from kivy.uix.image import AsyncImage

    import photos as photos_mod
    import track
    import walkjournal

    w = track.Walk(place="Ельник")
    w.add_point(56.0, 38.0, t=time.time() - 3600)
    find = w.add_find(56.0, 38.0, "белый")
    name = photos_mod.new_name()
    with open(photos_mod.path_for(name), "wb") as f:
        f.write(b"\xff\xd8\xff\xdb" + b"0" * 64)     # заглушка вместо кадра
    find.photos.append(name)

    journal = walkjournal.WalkJournal()
    try:
        row = journal._row(w)
        kids = list(_walk(row))
        assert any(isinstance(k, AsyncImage) for k in kids), "нет миниатюры"
        buttons = [k for k in kids if isinstance(k, Button)]
        assert buttons and list(buttons[0].size_hint) == [1, 1], "кнопка не во всю строку"
    finally:
        journal.dismiss()


def test_journal_row_without_photos_is_a_plain_button(data_dir):
    from kivy.uix.button import Button

    import track
    import walkjournal

    w = track.Walk(place="Гарь")
    w.add_point(56.0, 38.0, t=time.time() - 3600)
    journal = walkjournal.WalkJournal()
    try:
        assert isinstance(journal._row(w), Button)
    finally:
        journal.dismiss()


def test_missing_photo_file_does_not_leave_a_black_box(data_dir):
    """Снимок могли удалить из галереи, а ссылка на него осталась."""
    import track
    import walkjournal

    w = track.Walk(place="Просека")
    w.add_find(56.0, 38.0, "белый").photos.append("нет-такого.jpg")
    assert walkjournal.WalkJournal._first_photo(w) is None


# --------------------------------------------------------------------------- #
#  Мелочи, экономящие касания
# --------------------------------------------------------------------------- #

def test_last_species_comes_first(walk_screen):
    """Грибы растут семьями: вторая метка почти всегда того же вида."""
    import atlas

    w = walk_screen
    w.toggle()
    w.feed(56.02, 38.28, acc=8.0, t=w.walk.started + 1)
    w.walk.add_find(56.02, 38.28, "лисичка")
    w.mark_find()
    picker = _popup_titled("Что нашли?")
    rows = [r for r in _walk(picker.content) if isinstance(r, atlas.SpeciesRow)]
    # Строки идут сверху вниз, а children Kivy — снизу вверх.
    assert rows[-1].key == "лисичка"
    picker.dismiss()
    w.toggle()


def test_coordinates_can_be_copied(walk_screen):
    """«Стой там, я тебе точку скину» — обычный разговор в лесу."""
    from kivy.core.clipboard import Clipboard

    w = walk_screen
    find = w.walk.add_find(56.0206, 38.2807, "белый")
    w._edit_find(find)
    dlg = _find_dialog_for(find)
    try:
        dlg._copy_coords()
        assert "56.020600" in dlg.status.text
        assert Clipboard.paste() == "56.020600, 38.280700"
    finally:
        dlg.dismiss()


# --------------------------------------------------------------------------- #
#  Где машина
# --------------------------------------------------------------------------- #

def test_start_marks_the_car(walk_screen):
    """Старт у машины — самый частый случай, отметка ставится сама."""
    w = walk_screen
    w.feed(56.02, 38.28, acc=8.0, t=w.walk.started)
    assert w.walk.car is None
    w.toggle()
    assert w.walk.car is not None
    assert w.walk.car[0] == pytest.approx(56.02, abs=1e-4)
    w.toggle()


def test_the_car_mark_follows_a_drive(walk_screen):
    """Уехали после старта — отметка должна оказаться там, где вышли.

    Это тот же разрыв маршрута, что и в track.FAST_BREAK: точка разрыва
    едет вместе с машиной и останавливается на стоянке.
    """
    w = walk_screen
    t = w.walk.started
    w.feed(56.02, 38.28, acc=8.0, t=t)
    w.toggle()
    home = tuple(w.walk.car[:2])
    lat = 56.02
    for i in range(120):                      # десять минут по 60 км/ч
        t += 5
        lat += 0.00075
        w.feed(lat, 38.28, acc=8.0, t=t)
    assert "переехала" in w.hint.text
    for i in range(1, 4):                     # вышли и пошли пешком
        t += 20
        lat += 0.00018
        w.feed(lat, 38.28, acc=8.0, t=t)
    # Отметка стоит там, где человек вышел, а не там, где её последний раз
    # успела обновить дорога: разница между этими местами — сотни метров.
    assert w.walk.car[0] == pytest.approx(lat, abs=2e-4)
    assert w.walk.car[0] != pytest.approx(home[0], abs=1e-3)
    w.toggle()


def test_the_car_can_be_moved_by_hand(walk_screen):
    """Случаи, которые не угадать: шлагбаум, автобус, приехали с товарищем."""
    w = walk_screen
    w.feed(56.02, 38.28, acc=8.0, t=w.walk.started)
    w.toggle()
    w.feed(56.05, 38.30, acc=8.0, t=w.walk.started + 600)
    w.mark_car()
    assert w.walk.car[0] == pytest.approx(56.05, abs=1e-4)
    assert "Машина отмечена" in w.hint.text
    w.toggle()


def test_navigation_leads_to_the_car(walk_screen):
    w = walk_screen
    t = w.walk.started
    w.feed(56.02, 38.28, acc=8.0, t=t)
    w.toggle()
    for i in range(1, 6):                     # ушли на север
        w.feed(56.02 + i * 0.0005, 38.28, acc=8.0, t=t + i * 30)
    w.walk.set_car(56.00, 38.28)              # машина южнее
    w.toggle_nav()
    fix = w.arrow.fix
    assert fix is not None
    assert 150 < fix.bearing < 210, "стрелка должна показывать на юг"
    w.toggle_nav()
    w.toggle()


# --------------------------------------------------------------------------- #
#  Живучесть фоновой записи
# --------------------------------------------------------------------------- #

def test_service_popup_shows_advice_and_buttons(walk_screen):
    """Окно «Приём и сервис» — то место, куда человек идёт, когда запись
    оборвалась. Значит, в нём должны быть ответ и кнопки, а не только лог."""
    from kivy.uix.button import Button
    from kivy.uix.popup import Popup

    w = walk_screen
    w.show_service_log()
    pop = _popup_titled("Фоновая запись")
    try:
        texts = [b.text for b in _walk(pop.content) if isinstance(b, Button)]
        assert "Батарея" in texts and "Автозапуск" in texts
        labels = " ".join(getattr(x, "text", "") for x in _walk(pop.content))
        assert "Автозапуск" in labels or "Без ограничений" in labels
    finally:
        pop.dismiss()


def test_old_spot_hints_can_be_switched_off(walk_screen):
    """Кому-то вибрация в кармане помеха, и терпеть её незачем.

    Выключатель живёт в окне «Приём и сервис»: отдельного экрана настроек
    нет, а сюда человек приходит ровно тогда, когда что-то мешает.
    """
    from kivy.uix.button import Button

    import prefs

    w = walk_screen
    w.show_service_log()
    pop = _popup_titled("Фоновая запись")
    try:
        btn = next(b for b in _walk(pop.content)
                   if isinstance(b, Button)
                   and b.text.startswith("Подсказки у старых мест"))
        assert "включены" in btn.text
        btn.dispatch("on_release")
        assert prefs.get("near_buzz", True) is False
        assert "выключены" in btn.text

        # Проверяется молчание, а не надпись на кнопке: первая версия этого
        # теста смотрела только на текст и спокойно проходила, когда сам
        # выключатель переставал действовать.
        import history
        import proximity

        w.toggle()
        t = w.walk.started - 600
        w.walk.started = t
        w._near = proximity.Watcher(
            spots=[history.Spot(lat=56.02, lon=38.28, count=6, visits=2,
                                last_t=t - 380 * 86400, species="белый",
                                kinds={"белый": 6})], started=t)
        w.hint.text = "тишина"
        w.feed(56.0200, 38.28002, acc=8.0, t=t + 900)
        assert w.hint.text == "тишина", "выключатель не действует"
        w.toggle()

        btn.dispatch("on_release")
        assert prefs.get("near_buzz", True) is True
    finally:
        pop.dismiss()


def test_old_spot_alert_buzzes_once(walk_screen):
    """Полный путь: архив загрузился, человек подошёл, телефон дёрнулся."""
    import buzz
    import history
    import proximity

    w = walk_screen
    w.toggle()
    t = w.walk.started - 600            # обход молчания в начале похода
    w.walk.started = t
    spot = history.Spot(lat=56.02, lon=38.28, count=6, visits=2,
                        last_t=t - 380 * 86400, species="белый",
                        kinds={"белый": 6})
    w._near = proximity.Watcher(spots=[spot], started=t)
    buzz.reset()
    w.feed(56.0200, 38.28002, acc=8.0, t=t + 900)
    assert "здесь брали белый гриб" in w.hint.text
    said = w.hint.text
    w.feed(56.02001, 38.28003, acc=8.0, t=t + 1000)
    assert w.hint.text == said, "второй раз про то же место говорить нечего"
    w.toggle()


def test_pause_button_records_the_pause(walk_screen):
    """Перерыв должен попадать в поход, иначе его примут за обрыв записи."""
    w = walk_screen
    w.toggle()                                   # старт
    w.feed(56.02, 38.28, acc=8.0, t=w.walk.started + 1)
    w.toggle()                                   # пауза
    assert w.walk.pauses, "пауза не записана"
    assert w.walk.pauses[-1][1] <= w.walk.pauses[-1][0]
    w.toggle()                                   # продолжили
    assert w.walk.pauses[-1][1] > w.walk.pauses[-1][0]
    w.toggle()


# --------------------------------------------------------------------------- #
#  Резервная копия
# --------------------------------------------------------------------------- #

def test_backup_screen_builds_and_makes_an_archive(app, data_dir):
    """Окно копии открывается и собирает архив по-настоящему.

    На компьютере системного окна «Поделиться» нет, поэтому проверяется то,
    что от него не зависит: размеры посчитаны, файл собран, кнопки на время
    сборки заблокированы и разблокированы обратно.
    """
    import backup
    import backupscreen
    from kivy.clock import Clock

    scr = backupscreen.show()
    try:
        assert "Записей" in scr.info.text
        scr._make_records()
        for _ in range(80):                       # сборка идёт в потоке
            if not scr.b_records.disabled:
                break
            time.sleep(0.05)
            Clock.tick()
        assert not scr.b_records.disabled, "кнопки остались заблокированными"
        assert "Копия собрана" in scr.status.text or "Загрузк" in scr.status.text
        path = scr.status.text.split(" (")[0].replace("Копия собрана: ", "")
        assert os.path.exists(path), scr.status.text
        assert backup.inspect(path)["app"] == "navigator-gribnika"
    finally:
        scr.dismiss()


def test_backup_screen_refuses_a_foreign_archive(app, data_dir):
    """Чужой архив не должен разворачиваться поверх журнала."""
    import zipfile

    import backupscreen
    from kivy.clock import Clock

    alien = os.path.join(data_dir, "alien.zip")
    with zipfile.ZipFile(alien, "w") as z:
        z.writestr("море.jpg", "данные")
    scr = backupscreen.show()
    try:
        scr._picked(alien, "")
        Clock.tick()                              # ответ приходит через mainthread
        assert "не копия" in scr.status.text or "другого приложения" in scr.status.text
    finally:
        scr.dismiss()


# --------------------------------------------------------------------------- #
#  Главный экран
# --------------------------------------------------------------------------- #

def test_main_screen_builds(app):
    assert app.btn_place.text
    assert app.sp_kind.values


def test_help_and_donate_open(app):
    app.show_help()
    app.show_donate()


def test_place_picker_opens(app):
    from mapview import PlacePicker

    p = PlacePicker(56.0, 38.0, lambda *_: None)
    p.open()
    p.map.zoom_by(1)
    p.map.zoom_by(-1)
    p.dismiss()


def test_walk_journal_opens(app):
    app.show_walk_journal()


# --------------------------------------------------------------------------- #
#  Экран похода
# --------------------------------------------------------------------------- #

def test_walk_screen_opens(walk_screen):
    assert walk_screen.map is not None
    assert walk_screen.b_undo.disabled          # отменять пока нечего


def test_the_whole_walk_flow(walk_screen):
    """Старт, точки, метка, отмена, вписывание, слои, закрытие."""
    w = walk_screen
    w.toggle()                                  # старт
    # Время задаётся явно: без него все точки приходят одним мгновением,
    # и фильтр скорости справедливо считает их выбросом приёмника.
    t0 = w.walk.started
    for i in range(6):
        w.feed(56.02 + i * 0.0004, 38.28 + i * 0.0004, acc=8.0, t=t0 + i * 20)
    assert w.walk.distance > 0

    w._add_find("белый")
    assert len(w.walk.finds) == 1
    assert not w.b_undo.disabled
    w.undo()
    assert not w.walk.finds

    w._add_find("лисичка")
    w.fit_walk()
    w.toggle_follow()
    w.toggle_nav()
    w.toggle_history()
    w.toggle_history()
    w._refresh()
    w.toggle()                                  # пауза


def test_zoom_buttons_work(walk_screen):
    before = walk_screen.map.zoom
    walk_screen.map.zoom_by(-1)
    assert walk_screen.map.zoom == before - 1


def test_history_card_and_saving_a_place(walk_screen):
    import history

    spot = history.Spot(lat=56.02, lon=38.28, count=7, visits=2,
                        last_t=1_700_000_000.0, species="белый",
                        kinds={"белый": 7})
    walk_screen.map.history = history.History(trails=[], spots=[spot])
    walk_screen.map.redraw()
    walk_screen._show_spot(spot)                # карточка открывается
    walk_screen._keep_spot(spot)                # и место сохраняется
    assert any(s.lat == pytest.approx(56.02) for s in places.load())


def test_map_draws_a_full_history_layer(walk_screen):
    """Слой из нескольких походов должен пережить настоящую отрисовку."""
    import history

    trails = [history.Trail(points=[(56.0 + i * 0.001, 38.28 + j * 0.001)
                                    for j in range(20)], started=1_700_000_000.0)
              for i in range(5)]
    spots = [history.Spot(lat=56.0 + i * 0.002, lon=38.28, count=i * 3 + 1,
                          visits=1, last_t=1_700_000_000.0, species="лисичка")
             for i in range(8)]
    walk_screen.map.history = history.History(trails=trails, spots=spots)
    walk_screen.map.redraw()


def test_dusk_and_battery_do_not_break_the_refresh(walk_screen):
    walk_screen._refresh_dusk()
    walk_screen._check_battery()
    assert walk_screen.c_sun.lbl.text


def test_day_sheet_opens_with_real_numbers(app):
    """Разбор «почему такой индекс» — самый длинный текст в приложении."""
    import mushroom_forecast as engine

    place, days = engine.demo_weather(7)
    app.res = app._module.Result(place, days, len(days) - 8)
    app.refresh()
    app.show_day(app.res.today)


class _FakePopup:
    """Диалог выбора вида закрывается сам; тесту хватает заглушки."""

    def dismiss(self):
        pass


# --------------------------------------------------------------------------- #
#  Окно ошибки
# --------------------------------------------------------------------------- #

def test_error_dialog_starts_with_the_cause(app):
    """Суть — наверху, иначе на снимке экрана видно только пути внутрь Kivy."""
    main_mod = app._module
    tb = ('Traceback (most recent call last):\n'
          '  File "/data/kivy/base.py", line 339, in mainloop\n'
          '  File "/android/app/main.py", line 482, in <lambda>\n'
          '  File "/android/app/icons.py", line 209, in redraw\n'
          'IndexError: tuple index out of range\n')
    head = main_mod._Catcher._headline(tb)
    assert head.splitlines()[-1].startswith("IndexError")
    assert "icons.py" in head


def test_error_dialog_survives_an_empty_traceback(app):
    assert app._module._Catcher._headline("") == "Причина неизвестна"


def test_map_buttons_do_not_overlap(walk_screen):
    """Кнопки на карте расставлены столбиком, а не долями высоты.

    Доля от невысокой карты (маленький телефон, открытая полоса навигации)
    давала промежуток меньше самой кнопки, и они налезали друг на друга.
    """
    from kivy.base import EventLoop
    from kivy.clock import Clock
    from kivy.metrics import dp

    # Раскладка складывается на следующем кадре, а не в конструкторе.
    for _ in range(5):
        Clock.tick()
        EventLoop.idle()

    column = [c for c in walk_screen.map.parent.children
              if c is not walk_screen.map]
    assert len(column) == 1                      # именно столбик, а не россыпь
    boxes = sorted(column[0].children, key=lambda w: w.y)
    assert len(boxes) == 3
    for lower, upper in zip(boxes, boxes[1:]):
        assert lower.top <= upper.y + 0.5        # не налезают
        assert lower.height >= dp(40)            # и в них можно попасть пальцем


def test_labels_with_user_brackets_render(walk_screen):
    """Название вида «[size=x]» роняло отрисовку подписи целиком."""
    import markup
    from kivy.uix.label import Label

    lbl = Label(text=f"[b]{markup.esc('Ельник [size=x]')}[/b]", markup=True)
    lbl.texture_update()
    assert "Ельник" in lbl.text


# --------------------------------------------------------------------------- #
#  Утечка подписки на Window.size
# --------------------------------------------------------------------------- #

def test_walk_screen_unsubscribes_on_dismiss():
    """Открыл поход, закрыл, открыл снова — старый обработчик не должен
    оставаться в списке подписчиков Window.

    Без отписки за сессию с несколькими походами в списке накапливается по
    одному мёртвому обработчику на каждый закрытый экран, и каждый
    следующий поворот телефона исполняет их все впустую.
    """
    from kivy.core.window import Window
    from walkscreen import WalkScreen

    # Точное число подписчиков после open() не проверяется: Kivy сам
    # добавляет и убирает собственные временные обработчики вокруг
    # анимации попапа, и это не наша забота. Важно только одно: после
    # закрытия список должен вернуться к тому, что был до открытия.
    до = len(Window.get_property_observers("size"))
    w = WalkScreen(56.0, 38.0, "смешанный", "Тест")
    w.open(animation=False)
    assert len(Window.get_property_observers("size")) > до
    w.dismiss(animation=False)
    assert len(Window.get_property_observers("size")) == до, (
        "обработчик остался висеть после закрытия похода")


def test_repeated_walks_do_not_pile_up_listeners():
    from kivy.core.window import Window
    from walkscreen import WalkScreen

    до = len(Window.get_property_observers("size"))
    for i in range(4):
        w = WalkScreen(56.0, 38.0, "смешанный", f"поход{i}")
        w.open(animation=False)
        w.dismiss(animation=False)
    assert len(Window.get_property_observers("size")) == до
