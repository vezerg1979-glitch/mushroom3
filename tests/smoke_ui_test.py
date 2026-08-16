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

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "android")
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

    w._add_find("белый", _FakePopup())
    assert len(w.walk.finds) == 1
    assert not w.b_undo.disabled
    w.undo()
    assert not w.walk.finds

    w._add_find("лисичка", _FakePopup())
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
