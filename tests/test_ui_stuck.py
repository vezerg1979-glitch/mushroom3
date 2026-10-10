# -*- coding: utf-8 -*-
"""
Защита интерфейса от залипания.

Случай из леса: после работы в окне похода кнопки «Пауза» и «Нашёл!»
перестали нажиматься. Приложение при этом живо — счётчики обновлялись.
Два механизма, способных дать ровно такую картину, и проверяются здесь.

Первый: исключение в такте, который идёт раз в секунду. Общий обработчик
показывает окно на каждое, за минуту их набирается шестьдесят, и стопка
модальных окон перехватывает касания.

Второй: потерянное событие «отпустили». Палец лежит на карте, открывается
окно или падает обработчик — и uid остаётся в учёте карты навсегда. Дальше
одиночный тап складывается со старым касанием, код принимает его за
пинч-зум, и карта вместе с соседними кнопками откликается неверно.

Проверяется поведение кода, а не Android: на сборочной машине окон нет.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

sys.path.insert(0, APP)


def _src(name: str) -> str:
    with open(os.path.join(APP, name), encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------- #
#  Окно с ошибкой показывается один раз
# --------------------------------------------------------------------------- #

def test_pokaz_oshibki_ogranichen():
    """Одно окно за раз: повторная ошибка не должна плодить модальные окна."""
    src = _src("main.py")
    assert "_showing" in src
    body = src[src.index("def handle_exception"):]
    body = body[:body.find("\n    def ", 1)]
    assert "_showing" in body, "показ не ограничивается"
    assert "SILENCE" in body, "повтор той же ошибки не подавляется"


def test_okno_oshibki_snimaet_zapret_pri_zakrytii():
    """Иначе после первой же ошибки о следующих не узнаем никогда."""
    src = _src("main.py")
    assert "on_dismiss" in src
    assert "_released" in src


def test_neudavsheesya_okno_ne_blokiruet_navsegda():
    """Если окно не построилось, запрет снимается сразу."""
    body = _src("main.py")
    i = body.index("def handle_exception")
    tail = body[i:]
    tail = tail[:tail.find("\n    def ", 1)]
    assert "popup is None" in tail or "_showing = False" in tail


def test_sheet_vozvrashchaet_okno():
    """Обработчику ошибок нужно само окно, чтобы поймать его закрытие."""
    src = _src("main.py")
    i = src.index("def _sheet")
    body = src[i:i + 900]
    assert "return popup" in body


def test_oshibki_popadayut_v_protokol():
    """Подавленный показ обязан оставлять след: иначе разбирать нечего."""
    src = _src("main.py")
    assert "tracklog.log" in src
    assert "подавлен показ" in src


# --------------------------------------------------------------------------- #
#  Такт записи не роняет себя
# --------------------------------------------------------------------------- #

def test_takt_obernut_perekhvatom():
    """Сбой в счётчике не должен останавливать поход."""
    src = _src("walkscreen.py")
    i = src.index("def _pump(self)")
    body = src[i:i + 1200]
    assert "try:" in body
    assert "_pump_once" in body
    assert "except" in body


def test_takt_ne_spamit_v_protokol():
    """Ошибка раз в секунду — это 3600 строк в час; пишем только вехи."""
    src = _src("walkscreen.py")
    i = src.index("def _pump(self)")
    body = src[i:i + 1200]
    assert re.search(r"in \(1, 10, 100\)", body), "нет ограничения на запись"


# --------------------------------------------------------------------------- #
#  Потерянные касания
# --------------------------------------------------------------------------- #

def test_protukhshie_kasaniya_snimayutsya():
    src = _src("mapview.py")
    assert "_drop_stale" in src
    assert "STALE_S" in src


def test_proverka_pered_novym_kasaniem():
    """Чистка должна идти до того, как новое касание сложится со старым."""
    src = _src("mapview.py")
    i = src.index("def on_touch_down")
    body = src[i:i + 600]
    assert body.index("_drop_stale") < body.index("len(self._touches) == 2")


def test_uid_ubiraetsya_v_lyubom_prokhode():
    """«Отпустили» может прийти и обычным проходом диспетчера."""
    src = _src("mapview.py")
    i = src.index("def on_touch_up")
    body = src[i:i + 700]
    head = body[:body.index("touch.ungrab")]
    assert "_touches.pop" in head, "в раннем возврате uid остаётся навсегда"


def test_srok_protukhaniya_razumnyy():
    """Слишком мало — порвём настоящий долгий жест, слишком много — не вылечим.

    Читается из исходника, а не импортом: Kivy на сборочной машине может
    отсутствовать, а проверка нужна и там.
    """
    m = re.search(r"STALE_S\s*=\s*([\d.]+)", _src("mapview.py"))
    assert m, "порог протухания не задан"
    assert 3.0 <= float(m.group(1)) <= 20.0


def test_sbros_chistit_ves_uchet():
    """reset_touches() обязан снимать и отметки времени, иначе они накапливаются."""
    src = _src("mapview.py")
    i = src.index("def reset_touches")
    body = src[i:i + 1400]
    assert "_touch_seen" in body
    assert "_pinch = None" in body
