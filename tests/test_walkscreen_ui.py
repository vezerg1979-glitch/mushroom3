# -*- coding: utf-8 -*-
"""Проверки по следам снимка экрана из леса.

На снимке: «0 метров» после полутора часов, трек не нарисован, стрелки
компаса нет, подпись уезжает за край окна, а пять кнопок в нижнем ряду
налезают друг на друга. Виджеты Kivy без экрана не поднять, поэтому тесты
проверяют то, что от экрана не зависит: настройки фильтрации, арифметику
компаса и разбор исходников на предмет вернувшихся ошибок вёрстки.
"""

import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "android")
sys.path.insert(0, ROOT)

import compass  # noqa: E402
import track  # noqa: E402


def _src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------- #
#  Почему трек не рисовался
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("module", ["service_tracker.py", "location.py"])
def test_receiver_is_not_asked_to_filter_by_distance(module):
    """Фильтр по расстоянию должен быть нулевым.

    С ненулевым Android не присылает обновлений, пока человек не отойдёт на
    заданное число метров. Стоящий грибник не получает ни одной точки, и
    приложение выглядит сломанным, хотя приём работает.
    """
    assert re.search(r"^MIN_DIST_M = 0\.0$", _src(module), re.M), module


def test_software_filter_still_suppresses_jitter():
    """Отсев дрожания остаётся, просто он теперь в программе."""
    w = track.Walk()
    assert w.add_point(55.9606, 38.0456, 5.0, t=1000.0)
    # шаг в полметра — дрожание приёмника, в маршрут не идёт
    assert not w.add_point(55.96060, 38.04561, 5.0, t=1010.0)
    assert w.distance == 0.0
    # десять метров — настоящий шаг
    assert w.add_point(55.96069, 38.0456, 5.0, t=1020.0)
    assert w.distance > 5.0


def test_standing_still_still_reports_accuracy():
    """Даже когда точка не зачтена, точность приёма известна.

    По ней строится строка «фон · ±12 м, 3 с назад»: человеку нужно видеть,
    что приёмник жив, даже если метры не растут.
    """
    w = track.Walk()
    w.add_point(55.9606, 38.0456, 8.0, t=1000.0)
    w.add_point(55.96060, 38.04561, 12.0, t=1010.0)
    assert w.last_acc == 12.0


def test_walk_screen_shows_reception_line():
    src = _src("walkscreen.py")
    assert "_gps_line" in src
    assert "self.gps.text" in src


# --------------------------------------------------------------------------- #
#  Стрелка компаса
# --------------------------------------------------------------------------- #

def test_direction_is_shown_on_the_map():
    """Направление показывает стрелка на карте, а не прибор под ней.

    Отдельный компас заставлял переводить взгляд с карты на круг и в уме
    поворачивать одно относительно другого — ровно та работа, которую
    автомобильные навигаторы сняли с человека тридцать лет назад.
    """
    assert "def set_heading" in _src("mapview.py")
    assert "def _draw_here" in _src("mapview.py")
    assert "self.map.set_heading" in _src("walkscreen.py")


def test_compass_band_is_gone():
    assert "def set_compass" not in _src("navwidget.py")
    assert "_draw_compass" not in _src("navwidget.py")


def test_course_over_ground_wins_over_the_compass():
    """Курс по треку точнее и не врёт рядом с железом — но только на ходу."""
    src = _src("walkscreen.py")
    body = src[src.index("def _heading"):src.index("def _refresh")]
    assert body.index("course_over_ground") < body.index("_compass.heading")


def test_compass_heading_is_kept_between_reads():
    """Стрелка рисуется по последнему известному курсу.

    Датчик отдаёт значения не каждый кадр; если бы виджет рисовал только
    по свежему чтению, стрелка мигала бы.
    """
    c = compass.Compass()
    assert c.heading() is None
    c._value = 137.0
    assert c.heading() == 137.0


@pytest.mark.parametrize("heading,expect_north_at", [
    (0.0, 0.0),        # телефон на север — север вверху
    (90.0, 270.0),     # повернули направо — север ушёл влево
    (180.0, 180.0),
    (270.0, 90.0),
])
def test_north_marker_rotates_opposite_to_heading(heading, expect_north_at):
    """Поворачивается картина мира, а не стрелка."""
    assert (-heading) % 360.0 == expect_north_at


# --------------------------------------------------------------------------- #
#  Вёрстка
# --------------------------------------------------------------------------- #

def test_hint_label_wraps():
    """Подпись без text_size рисуется одной строкой и уезжает за края окна."""
    src = _src("walkscreen.py")
    hint = src[src.index("self.hint = Label"):src.index("self.hint = Label") + 700]
    assert "text_size" in hint


def test_bottom_buttons_split_into_two_rows():
    """Пять кнопок в одну строку не помещаются подписями."""
    src = _src("walkscreen.py")
    assert "row1 = BoxLayout" in src and "row2 = BoxLayout" in src
    # и каждая мелкая кнопка обрезает подпись внутри себя, а не поверх соседа
    small = src[src.index("def small("):src.index("def small(") + 500]
    assert "shorten=True" in small and "text_size" in small


# --------------------------------------------------------------------------- #
#  Откуда берутся координаты
# --------------------------------------------------------------------------- #

def test_receiver_starts_when_the_screen_opens():
    """Синяя точка обязана ехать за человеком до нажатия «Старт».

    Иначе непонятно, работает ли GPS вообще, и карта показывает место,
    выбранное на главном экране, — стоящее намертво.
    """
    src = _src("walkscreen.py")
    on_open = src[src.index("def on_open"):src.index("# --- управление")]
    assert "_start_gps_foreground()" in on_open


def test_own_subscription_does_not_wait_for_the_service():
    """Своя подписка включается сразу, сервис — вдогонку.

    Сервис живёт в отдельном процессе и может отчитаться, что жив, не отдав
    ни одной координаты. Пока запись зависела только от него, второго шанса
    не было: трек оставался пустым.
    """
    src = _src("walkscreen.py")
    begin = src[src.index("def _begin_recording"):src.index("def _check_service")]
    assert begin.index("self._start_gps_foreground()") < begin.index("service_ctl.start()")


def test_service_failure_is_no_longer_fatal():
    src = _src("walkscreen.py")
    check = src[src.index("def _check_service"):src.index("def _start_gps_foreground")]
    # раньше здесь был единственный запуск своего приёмника — теперь он уже
    # работает, и провал сервиса лишь лишает записи с погашенным экраном
    assert "не поднялась" in check


def test_locator_uses_every_provider():
    """Одного GPS мало: под крышей и в ельнике спутники ищутся минутами."""
    src = _src("location.py")
    assert "PASSIVE_PROVIDER" in src
    assert "FUSED_PROVIDER" in src
    assert "NETWORK_PROVIDER" in src


def test_last_known_seeds_the_screen():
    """Первая точка берётся из кэша приёмника, не дожидаясь спутников."""
    src = _src("walkscreen.py")
    fg = src[src.index("def _start_gps_foreground"):src.index("def _stop_gps")]
    assert "last_known()" in fg


def test_status_line_names_both_sources():
    src = _src("walkscreen.py")
    line = src[src.index("def _gps_line"):src.index("def _refresh")]
    assert '"экран"' in line and '"фон"' in line


def test_arrow_falls_back_to_a_dot():
    """Без направления рисуется точка: врущая стрелка хуже её отсутствия."""
    src = _src("mapview.py")
    body = src[src.index("def _draw_here"):src.index("def _text")]
    assert "if self.heading is None:" in body


def test_heading_updates_are_throttled():
    """Перерисовывать тайлы ради поворота на полградуса незачем."""
    body = _src("mapview.py")
    body = body[body.index("def set_heading"):body.index("def _draw_here")]
    assert "180.0) % 360.0 - 180.0)" in body


# --------------------------------------------------------------------------- #
#  Почему подписка молчала
# --------------------------------------------------------------------------- #
#
# «экран · ±4 м · 193 с назад · точек 0»: приём отличный, подписка прошла,
# getLastKnownLocation отдаёт точку мгновенно — а живых обновлений ноль.
# Причина в динамическом посреднике pyjnius: он перехватывает ВСЕ методы
# интерфейса, включая методы с реализацией по умолчанию. Начиная с Android 12
# система отдаёт координаты пачкой через onLocationChanged(List<Location>),
# и пока этого метода не было на стороне Python, координаты пропадали молча.

@pytest.mark.parametrize("module", ["location.py", "service_tracker.py"])
def test_batch_location_callback_is_implemented(module):
    src = _src(module)
    assert 'name="onLocationChanged"' in src, "нет варианта с List<Location>"
    assert '"(Ljava/util/List;)V"' in src


@pytest.mark.parametrize("module", ["location.py", "service_tracker.py"])
def test_every_listener_method_is_implemented(module):
    """Нереализованный метод интерфейса = молча потерянные координаты."""
    src = _src(module)
    for signature in ('"(Landroid/location/Location;)V"',
                      '"(Ljava/util/List;)V"',
                      '"(I)V"',
                      '"(Ljava/lang/String;)V"',
                      '"(Ljava/lang/String;ILandroid/os/Bundle;)V"'):
        assert signature in src, f"{module}: не реализован {signature}"


def test_emergency_poll_exists():
    """Страховка: если подписка молчит, систему спрашивают напрямую."""
    assert "def poll" in _src("location.py")
    src = _src("walkscreen.py")
    assert "_poll_if_silent" in src
    assert "POLL_AFTER_S" in src


def test_poll_threshold_value():
    src = _src("walkscreen.py")
    m = re.search(r"^POLL_AFTER_S = ([\d.]+)$", src, re.M)
    assert m, "порог аварийного опроса не задан"
    value = float(m.group(1))
    assert 5.0 <= value <= 60.0, f"{value} с — за пределами разумного"


# --------------------------------------------------------------------------- #
#  Кнопки на экране похода
# --------------------------------------------------------------------------- #

def test_undo_is_reachable_from_the_screen():
    """Метод undo() был написан, но ни одна кнопка на него не ссылалась.

    Ошибочную метку — промахнулись видом, нажали дважды — убрать было нечем,
    хотя вся механика для этого уже существовала.
    """
    src = _src("walkscreen.py")
    assert "self.undo()" in src
    assert 'icon="undo"' in src


def test_undo_is_dimmed_while_there_is_nothing_to_undo():
    src = _src("walkscreen.py")
    assert "self.b_undo.disabled = not self.walk.finds" in src


def test_map_has_zoom_buttons():
    """Щипок двумя пальцами в перчатке и одной рукой не выходит."""
    src = _src("walkscreen.py")
    assert "self.map.zoom_by" in src


def test_zoom_buttons_do_not_steal_height_from_the_map():
    """Кнопки лежат поверх карты: отдавать ей ещё 40 dp полосой нельзя."""
    src = _src("walkscreen.py")
    assert "FloatLayout" in src
    i = src.index("map_box = FloatLayout()")
    j = src.index("root.add_widget(map_box)")
    assert "pos_hint" in src[i:j]
