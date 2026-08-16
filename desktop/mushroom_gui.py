#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mushroom_gui.py — графический интерфейс к mushroom_forecast.py (PySide6).

Запуск:
    pip install PySide6
    python mushroom_gui.py

Файл mushroom_forecast.py должен лежать рядом — он используется как расчётное ядро.
"""

from __future__ import annotations

import csv
import math
import sys
import urllib.error
from datetime import datetime

try:
    import mushroom_forecast as engine
except ImportError:
    sys.exit("Рядом с mushroom_gui.py должен лежать mushroom_forecast.py")

from PySide6.QtCore import (QObject, QPoint, QRect, QSettings, Qt, QThread,
                            QTimer, Signal, QSize)
from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QFontMetrics, QIcon,
                           QPainter, QPainterPath, QPen, QPixmap, QPolygonF)
import ensemble as ensemble_mod
import places as places_mod
from map_picker import MapPicker
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                               QComboBox, QDialog, QFileDialog, QFrame, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QPushButton, QSizePolicy, QSpinBox,
                               QSplitter, QTabWidget, QTableWidget,
                               QInputDialog, QTableWidgetItem, QTextBrowser,
                               QTextEdit, QToolButton,
                               QVBoxLayout, QWidget)

# --------------------------------------------------------------------------- #
#  Оформление
# --------------------------------------------------------------------------- #

LEVEL_COLORS = [
    (85, QColor("#2E7D32"), QColor("#FFFFFF")),
    (68, QColor("#66A63C"), QColor("#FFFFFF")),
    (50, QColor("#A6CC72"), QColor("#1B2E10")),
    (33, QColor("#CFE3A3"), QColor("#1B2E10")),
    (18, QColor("#E6EDCB"), QColor("#42502C")),
    (8,  QColor("#F0F1EA"), QColor("#77806B")),
    (0,  QColor("#F7F7F5"), QColor("#9AA093")),
]

SPECIES_COLORS = {
    "Белый гриб":      "#8B5A2B",
    "Подберёзовик":    "#A9744F",
    "Подосиновик":     "#D2601A",
    "Лисичка":         "#E8A317",
    "Маслёнок":        "#B8860B",
    "Опёнок осенний":  "#7B4B2A",
    "Груздь настоящий": "#9AA05C",
    "Сыроежка":        "#C0504D",
    "Вешенка":         "#6B8E9E",
    "Сморчок":         "#7A6A55",
}

BG = "#FAFAF7"
GRID = "#DFE1D8"
INK = "#2B2F27"

STYLE = f"""
QMainWindow, QWidget {{ background: {BG}; color: {INK}; }}
QGroupBox {{
    border: 1px solid {GRID}; border-radius: 6px; margin-top: 10px;
    padding-top: 8px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 9px; padding: 0 4px; color: #5A6152; }}
QLineEdit, QSpinBox, QComboBox {{
    background: #FFFFFF; border: 1px solid {GRID}; border-radius: 5px;
    padding: 5px 7px; selection-background-color: #A6CC72;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid #66A63C; }}
QPushButton {{
    background: #FFFFFF; border: 1px solid {GRID}; border-radius: 5px; padding: 6px 14px;
}}
QPushButton:hover {{ border-color: #66A63C; }}
QPushButton:disabled {{ color: #A8AEA0; }}
QPushButton#primary {{ background: #3E7D2C; color: white; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: #4A9134; }}
QPushButton#primary:disabled {{ background: #B9C6B2; }}
QTableWidget {{
    background: #FFFFFF; border: 1px solid {GRID}; border-radius: 6px;
    gridline-color: #ECEDE6; selection-background-color: #E6EDCB; selection-color: {INK};
}}
QHeaderView::section {{
    background: #F2F3EE; border: none; border-right: 1px solid {GRID};
    border-bottom: 1px solid {GRID}; padding: 5px 6px; font-weight: 600; color: #5A6152;
}}
QTabWidget::pane {{ border: 1px solid {GRID}; border-radius: 6px; top: -1px; background: #FFFFFF; }}
QTabBar::tab {{
    background: transparent; padding: 7px 16px; margin-right: 2px;
    border: 1px solid transparent; border-top-left-radius: 6px; border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{ background: #FFFFFF; border-color: {GRID}; border-bottom-color: #FFFFFF; }}
QListWidget {{ background: #FFFFFF; border: 1px solid {GRID}; border-radius: 6px; padding: 3px; }}
QTextEdit {{ background: #FFFFFF; border: 1px solid {GRID}; border-radius: 6px; padding: 8px; }}
QStatusBar {{ color: #6B7263; }}
"""


def level_style(v: float):
    for th, bg, fg in LEVEL_COLORS:
        if v >= th:
            return bg, fg
    return LEVEL_COLORS[-1][1], LEVEL_COLORS[-1][2]


def mono(size: int = 10, bold: bool = False) -> QFont:
    f = QFont("DejaVu Sans Mono")
    f.setStyleHint(QFont.Monospace)
    f.setPointSize(size)
    f.setBold(bold)
    return f


# --------------------------------------------------------------------------- #
#  Результат расчёта
# --------------------------------------------------------------------------- #

class Result:
    def __init__(self, place, days, today_idx):
        self.place = place
        self.days = days
        self.today = today_idx
        self.m = engine.water_balance(days)
        self.ts = engine.soil_temperature(days)
        self.idx = {sp.name: engine.species_index(sp, days, self.m, self.ts)
                    for sp in engine.SPECIES.values()}
        self.stamp = datetime.now()
        self.stale = None

    def value(self, name: str, i: int) -> float:
        v = self.idx[name][i]
        return 0.0 if (v is None or math.isnan(v)) else v

    def best(self, names: list[str], i: int):
        if not names:
            return 0.0, None
        pairs = [(self.value(n, i), n) for n in names]
        return max(pairs)


class Worker(QObject):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, place_text, fdays, demo):
        super().__init__()
        self.place_text, self.fdays, self.demo = place_text, fdays, demo
        self.stale = None

    def run(self):
        try:
            if self.demo:
                place, days = engine.demo_weather(self.fdays)
            else:
                txt = self.place_text.strip()
                parts = [p.strip().replace(",", ".") for p in txt.replace(";", ",").split(",")]
                if len(parts) == 2 and all(_isnum(p) for p in parts):
                    lat, lon = float(parts[0]), float(parts[1])
                    place = engine.Place(f"{lat:.3f}, {lon:.3f}", lat, lon)
                else:
                    place = engine.geocode(txt)
                try:
                    days = engine.fetch_weather(place, self.fdays)
                    places_mod.cache_forecast(
                        places_mod.Spot(place.name, place.lat, place.lon), days)
                except (urllib.error.URLError, TimeoutError, OSError):
                    got = places_mod.cached_forecast(
                        places_mod.Spot(place.name, place.lat, place.lon))
                    if got is None:
                        raise
                    days, stamp = got
                    self.stale = stamp
            today = datetime.now().date()
            ti = next((i for i, d in enumerate(days) if d.d >= today), len(days) - self.fdays)
            res = Result(place, days, ti)
            res.stale = self.stale
            self.done.emit(res)
        except BaseException as e:                                # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}" if not str(e) else str(e))


def _isnum(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
#  График
# --------------------------------------------------------------------------- #

class ChartWidget(QWidget):
    """Индекс плодоношения по дням + столбики осадков. Наведение — подсказка."""

    ML, MR, MT, MB = 46, 50, 16, 38

    def __init__(self):
        super().__init__()
        self.res: Result | None = None
        self.names: list[str] = []
        self.hover = -1
        self.show_drivers = False
        self.band: dict = {}
        self.setMouseTracking(True)
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, res: Result | None, names: list[str]):
        self.res, self.names, self.hover = res, names, -1
        self.update()

    # --- геометрия ---------------------------------------------------------
    def _legend_rows(self) -> int:
        fm = QFontMetrics(QFont("", 8))
        rows, x = 1, self.ML
        for n in self.names:
            w = fm.horizontalAdvance(n) + 18
            if x + w > self.width() - self.MR:
                rows, x = rows + 1, self.ML
            x += w
        return rows

    def _range(self):
        r = self.res
        lo = max(0, r.today - 7)
        hi = len(r.days)
        return lo, hi

    def _x(self, i: int) -> float:
        lo, hi = self._range()
        n = max(1, hi - lo - 1)
        return self.ML + (self.width() - self.ML - self.MR) * (i - lo) / n

    def _y(self, v: float) -> float:
        h = self.height() - self.MT - self.MB
        return self.MT + h * (1 - max(0.0, min(100.0, v)) / 100.0)

    def mouseMoveEvent(self, e):
        if not self.res:
            return
        lo, hi = self._range()
        best, bi = 1e9, -1
        for i in range(lo, hi):
            d = abs(self._x(i) - e.position().x())
            if d < best:
                best, bi = d, i
        self.hover = bi if best < 40 else -1
        self.update()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    # --- отрисовка ---------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#FFFFFF"))
        if not self.res:
            p.setPen(QColor("#A8AEA0"))
            p.drawText(self.rect(), Qt.AlignCenter, "Нажмите «Рассчитать»")
            return

        r, lo, hi = self.res, *self._range()
        legend_rows = self._legend_rows()
        self.MT = 10 + legend_rows * 15
        plot = QRect(self.ML, self.MT, self.width() - self.ML - self.MR,
                     self.height() - self.MT - self.MB)

        # зоны уровней
        for th, col, _fg in reversed(LEVEL_COLORS):
            if th == 0:
                continue
            y0, y1 = self._y(min(100, th + 17)), self._y(th)
            c = QColor(col)
            c.setAlpha(28)
            p.fillRect(QRect(plot.left(), int(y0), plot.width(), int(y1 - y0)), c)

        # сетка
        p.setFont(QFont("", 8))
        for v in range(0, 101, 20):
            y = self._y(v)
            p.setPen(QPen(QColor(GRID), 1, Qt.DotLine))
            p.drawLine(plot.left(), int(y), plot.right(), int(y))
            p.setPen(QColor("#8A9180"))
            p.drawText(QRect(0, int(y) - 8, self.ML - 8, 16),
                       Qt.AlignRight | Qt.AlignVCenter, str(v))

        p.setPen(QColor("#8A9180"))
        p.setFont(QFont("", 8))
        p.save()
        p.translate(11, plot.center().y())
        p.rotate(-90)
        p.drawText(QRect(-70, -8, 140, 14), Qt.AlignCenter, "индекс плодоношения")
        p.restore()

        # осадки (правая ось)
        pmax = max(8.0, max(r.days[i].precip for i in range(lo, hi)) * 1.25)
        bw = max(3.0, (plot.width() / max(1, hi - lo)) * 0.42)
        for i in range(lo, hi):
            pr = r.days[i].precip
            if pr <= 0.05:
                continue
            h = plot.height() * (pr / pmax) * 0.55
            x = self._x(i) - bw / 2
            p.fillRect(QRect(int(x), int(plot.bottom() - h), int(bw), int(h)),
                       QColor(90, 150, 200, 70))
        p.setPen(QColor("#7392AB"))
        for k in (0.0, 0.5, 1.0):
            y = plot.bottom() - plot.height() * 0.55 * k
            p.drawLine(plot.right(), int(y), plot.right() + 4, int(y))
            lbl = f"{pmax * k:.0f}" + (" мм" if k == 1.0 else "")
            p.drawText(QRect(plot.right() + 7, int(y) - 8, self.MR, 16),
                       Qt.AlignLeft | Qt.AlignVCenter, lbl)

        # коридор сценариев P10-P90
        if self.band:
            top, bot = [], []
            for i in range(lo, hi):
                v = self.band.get(r.days[i].d)
                if not v:
                    continue
                top.append(QPoint(int(self._x(i)), int(self._y(v[2]))))
                bot.append(QPoint(int(self._x(i)), int(self._y(v[0]))))
            if len(top) >= 2:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(74, 116, 168, 60))
                p.drawPolygon(QPolygonF(top + bot[::-1]))
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(74, 116, 168, 170), 1.1, Qt.DotLine))
                p.drawPolyline(QPolygonF(top))
                p.drawPolyline(QPolygonF(bot))
                p.setPen(QPen(QColor(48, 86, 134, 210), 1.5, Qt.DashLine))
                med = QPolygonF()
                for i in range(lo, hi):
                    v = self.band.get(r.days[i].d)
                    if v:
                        med.append(QPoint(int(self._x(i)), int(self._y(v[1]))))
                p.drawPolyline(med)
                # подпись у правого края коридора
                if top:
                    p.setFont(QFont("", 8))
                    p.setPen(QColor(48, 86, 134))
                    p.drawText(QPoint(top[-1].x() - 96, top[-1].y() - 6),
                               "коридор сценариев")

        # огибающая «лучший вид»
        if self.names:
            path = QPolygonF()
            for i in range(lo, hi):
                path.append(QPoint(int(self._x(i)), int(self._y(r.best(self.names, i)[0]))))
            fill = QPolygonF(path)
            fill.append(QPoint(int(self._x(hi - 1)), plot.bottom()))
            fill.append(QPoint(int(self._x(lo)), plot.bottom()))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(62, 125, 44, 26))
            p.drawPolygon(fill)

        # кривые по видам
        for n in self.names:
            col = QColor(SPECIES_COLORS.get(n, "#555555"))
            p.setPen(QPen(col, 2.0))
            p.setBrush(Qt.NoBrush)
            pts = QPolygonF()
            for i in range(lo, hi):
                v = r.idx[n][i]
                if v is None or math.isnan(v):
                    continue
                pts.append(QPoint(int(self._x(i)), int(self._y(v))))
            p.drawPolyline(pts)

        # драйверы модели: влага подстилки и температура почвы
        if self.show_drivers:
            for key, col, conv in (("m", "#4E86B5", lambda j: r.m[j] * 100),
                                   ("ts", "#C98A2E", lambda j: r.ts[j] * 100 / 30.0)):
                pen = QPen(QColor(col), 1.4, Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                poly = QPolygonF()
                for i in range(lo, hi):
                    poly.append(QPoint(int(self._x(i)), int(self._y(conv(i)))))
                p.drawPolyline(poly)
                p.setFont(QFont("", 8))
                lbl = "влага, %" if key == "m" else "T почвы (0–30 °C)"
                p.setPen(QColor(col))
                p.drawText(QPoint(int(self._x(hi - 1)) - 108,
                                  int(self._y(conv(hi - 1))) - 5), lbl)

        # линия «сегодня»
        xt = self._x(r.today)
        p.setPen(QPen(QColor("#3E7D2C"), 1.5, Qt.DashLine))
        p.drawLine(int(xt), plot.top(), int(xt), plot.bottom())
        p.setFont(QFont("", 8, QFont.Bold))
        p.setPen(QColor("#3E7D2C"))
        p.drawText(QPoint(int(xt) + 4, plot.top() + 11), "сегодня")

        # даты
        p.setFont(QFont("", 8))
        p.setPen(QColor("#6B7263"))
        step = max(1, (hi - lo) // 12)
        for i in range(lo, hi, step):
            p.drawText(QRect(int(self._x(i)) - 22, plot.bottom() + 5, 44, 14),
                       Qt.AlignCenter, r.days[i].d.strftime("%d.%m"))

        # легенда (в верхнем поле, над областью графика)
        p.setFont(QFont("", 8))
        fm = QFontMetrics(p.font())
        x, y = self.ML, 0
        for n in self.names:
            w = fm.horizontalAdvance(n) + 18
            if x + w > self.width() - self.MR:
                x, y = self.ML, y + 15
            p.setBrush(QColor(SPECIES_COLORS.get(n, "#555")))
            p.setPen(Qt.NoPen)
            p.drawRect(QRect(x, y + 3, 9, 9))
            p.setPen(QColor("#4A5142"))
            p.drawText(QPoint(x + 13, y + 12), n)
            x += w

        # подсказка под курсором
        if lo <= self.hover < hi:
            i = self.hover
            p.setPen(QPen(QColor("#9AA093"), 1, Qt.DotLine))
            p.drawLine(int(self._x(i)), plot.top(), int(self._x(i)), plot.bottom())
            lines = [r.days[i].d.strftime("%d.%m.%Y"),
                     f"осадки {r.days[i].precip:.1f} мм   влага {r.m[i]*100:.0f}%",
                     f"T воздуха {r.days[i].tmean:.1f}   T почвы {r.ts[i]:.1f} °C", ""]
            for n in sorted(self.names, key=lambda n: -r.value(n, i))[:5]:
                lines.append(f"{n}: {r.value(n, i):.0f}")
            f = QFont("", 8)
            p.setFont(f)
            fm = QFontMetrics(f)
            w = max(fm.horizontalAdvance(s) for s in lines) + 16
            h = len(lines) * 14 + 10
            bx = self._x(i) + 12
            if bx + w > plot.right():
                bx = self._x(i) - w - 12
            by = min(plot.bottom() - h, max(plot.top(), plot.top() + 20))
            p.setBrush(QColor(255, 255, 255, 244))
            p.setPen(QPen(QColor("#C9CDBF")))
            p.drawRoundedRect(QRect(int(bx), int(by), int(w), int(h)), 5, 5)
            p.setPen(QColor(INK))
            for k, s in enumerate(lines):
                p.drawText(QPoint(int(bx) + 8, int(by) + 16 + k * 14), s)
        p.end()


# --------------------------------------------------------------------------- #
#  Пояснительные виджеты
# --------------------------------------------------------------------------- #

LEVEL_NAMES = [(0, 8, "нет"), (8, 18, "почти нет"), (18, 33, "единично"),
               (33, 50, "умеренно"), (50, 68, "хорошо"), (68, 85, "обильно"),
               (85, 100, "массовый слой")]


class LevelLegend(QWidget):
    """Цветовая шкала индекса с расшифровкой словами."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(52)
        self.setToolTip("Индекс — условная оценка шансов застать плодоношение, 0…100")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(QFont("", 8))
        w = self.width() - 8
        p.setPen(QColor("#6B7263"))
        p.drawText(QRect(4, 0, w, 13), Qt.AlignLeft | Qt.AlignVCenter,
                   "Шкала индекса — насколько вероятно застать плодоношение:")
        for lo, hi, name in LEVEL_NAMES:
            x0 = 4 + w * lo / 100.0
            x1 = 4 + w * hi / 100.0
            bg, fg = level_style(lo + 1)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRect(QRect(int(x0), 15, int(x1 - x0) - 1, 20))
            p.setPen(fg)
            if x1 - x0 > 44:
                p.drawText(QRect(int(x0), 15, int(x1 - x0), 20), Qt.AlignCenter, name)
        p.setPen(QColor("#8A9180"))
        for v in (0, 33, 68, 100):
            x = 4 + w * v / 100.0
            r = QRect(int(x) - 16, 36, 32, 13)
            if v == 0:
                r.moveLeft(4)
            elif v == 100:
                r.moveRight(int(4 + w))
            p.drawText(r, Qt.AlignCenter, str(v))
        p.end()


class FactorBars(QWidget):
    """Разложение индекса на сомножители: видно, что именно тормозит."""

    ROW = 46

    def __init__(self):
        super().__init__()
        self.rows: list[tuple[str, float, str]] = []
        self.setMinimumHeight(self.ROW * 5)

    def set_rows(self, rows):
        self.rows = rows
        self.setMinimumHeight(self.ROW * max(1, len(rows)) + 8)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.rows:
            p.setPen(QColor("#A8AEA0"))
            p.drawText(self.rect(), Qt.AlignCenter, "Нет данных")
            return
        name_w, val_w = 168, 46
        bar_x = name_w + 10
        bar_w = max(60, self.width() - bar_x - val_w - 14)
        for k, (name, val, why) in enumerate(self.rows):
            y = 6 + k * self.ROW
            p.setFont(QFont("", 9, QFont.Bold))
            p.setPen(QColor(INK))
            p.drawText(QRect(6, y, name_w, 18), Qt.AlignLeft | Qt.AlignVCenter, name)
            # шкала
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#EFF0EA"))
            p.drawRoundedRect(QRect(bar_x, y + 3, bar_w, 13), 6, 6)
            col = QColor("#C0504D") if val < 0.35 else (
                QColor("#E8A317") if val < 0.7 else QColor("#66A63C"))
            p.setBrush(col)
            p.drawRoundedRect(QRect(bar_x, y + 3, max(4, int(bar_w * val)), 13), 6, 6)
            p.setFont(mono(9, True))
            p.setPen(QColor(INK))
            p.drawText(QRect(bar_x + bar_w + 6, y, val_w, 18),
                       Qt.AlignLeft | Qt.AlignVCenter, f"{val * 100:.0f}%")
            # пояснение
            p.setFont(QFont("", 8))
            p.setPen(QColor("#7B8272"))
            p.drawText(QRect(6, y + 20, self.width() - 14, 22),
                       Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, why)
        p.end()


class SchemeWidget(QWidget):
    """Схема расчёта: от дождя до плодового тела."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(224)

    def _box(self, p, r, title, sub, fill, border):
        p.setBrush(QColor(fill))
        p.setPen(QPen(QColor(border), 1.4))
        p.drawRoundedRect(r, 7, 7)
        p.setPen(QColor(INK))
        p.setFont(QFont("", 9, QFont.Bold))
        p.drawText(QRect(r.x(), r.y() + 7, r.width(), 18),
                   Qt.AlignCenter | Qt.TextWordWrap, title)
        p.setFont(QFont("", 8))
        p.setPen(QColor("#6B7263"))
        p.drawText(QRect(r.x() + 5, r.y() + 26, r.width() - 10, r.height() - 30),
                   Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, sub)

    def _arrow(self, p, x0, y0, x1, y1):
        p.setPen(QPen(QColor("#9AA093"), 1.6))
        p.drawLine(int(x0), int(y0), int(x1), int(y1))
        ang = math.atan2(y1 - y0, x1 - x0)
        for s in (-0.45, 0.45):
            p.drawLine(int(x1), int(y1),
                       int(x1 - 8 * math.cos(ang + s)), int(y1 - 8 * math.sin(ang + s)))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n, gap = 5, 16
        w = max(96, (self.width() - 20 - gap * (n - 1)) // n)
        y = 22
        h = 74
        boxes = [
            ("1. Осадки", "приход воды за вычетом задержки кронами"),
            ("2. Влага подстилки", "резервуар 55 мм: приход минус испарение"),
            ("3. Закладка", "влага × температура × толчок дождя"),
            ("4. Лаг вида", "3–16 суток от стимула до плодового тела"),
            ("5. Индекс 0–100", "с поправками на сезон и сохранность"),
        ]
        xs = []
        for k, (t, s) in enumerate(boxes):
            x = 10 + k * (w + gap)
            xs.append(x)
            self._box(p, QRect(x, y, w, h), t, s,
                      "#F4F7EE" if k < 4 else "#EAF2E0", "#C7D3B6")
            if k:
                self._arrow(p, x - gap + 2, y + h / 2, x - 3, y + h / 2)
        # боковые входы
        y2 = y + h + 34
        self._box(p, QRect(xs[2] - 8, y2, w + 16, 60), "Температура почвы",
                  "сглаженная температура воздуха, лаг ~3 суток", "#FBF4E6", "#E3D2AC")
        self._arrow(p, xs[2] + w / 2, y2 - 4, xs[2] + w / 2, y + h + 4)
        self._box(p, QRect(xs[4] - 8, y2, w + 16, 60), "Сезон и погода дня",
                  "месяц вида, заморозки, жара, пересыхание", "#FBF4E6", "#E3D2AC")
        self._arrow(p, xs[4] + w / 2, y2 - 4, xs[4] + w / 2, y + h + 4)
        p.end()


class HowItWorks(QWidget):
    """Вкладка «Как это работает»."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.addWidget(SchemeWidget())
        txt = QTextBrowser()
        txt.setOpenExternalLinks(True)
        txt.setHtml(f"""
<div style='font-family:sans-serif; font-size:10pt; color:{INK}'>

<h3 style='margin:2px 0 4px'>Что показывает индекс</h3>
<p style='margin:0 0 8px'>Индекс 0–100 — это оценка шансов застать плодоношение в
типичном для вида лесу. Не количество грибов и не гарантия: программа знает погоду,
но не знает ваш конкретный лес, возраст древостоя и грибные места.</p>

<h3 style='margin:8px 0 4px'>Откуда данные</h3>
<p style='margin:0 0 8px'>Погода берётся с сервиса Open-Meteo: 31 сутки назад и
до 16 суток вперёд для указанной точки. История нужна не меньше прогноза —
гриб, который вылезет послезавтра, заложился неделю назад.</p>

<h3 style='margin:8px 0 4px'>Как считается</h3>
<ol style='margin:0 0 8px -20px'>
<li><b>Влага почвы.</b> Берётся прямо из погодной модели — объёмная влажность
слоя 0–7 см, пересчитанная в долю доступной влаги между влажностью завядания
и полевой влагоёмкостью. Если модель этот слой не отдаёт, включается резерв:
резервуар подстилки ёмкостью {engine.CAPACITY_MM:.0f} мм, где дождь пополняет,
а испарение опустошает, причём сухая подстилка сохнет медленнее сырой.</li>
<li><b>Температура почвы.</b> Тоже из модели, слой 0–7 см. Резерв при её отсутствии —
сглаживание температуры воздуха с задержкой около трёх суток. Какой источник
сработал, видно во вкладке «Сводка по погоде».</li>
<li><b>Закладка примордиев.</b> Перемножаются влага и температура, а сверху —
импульс дождя. Ключевая идея: плодоношение это <i>реакция на событие</i> увлажнения,
а не на ровную сырость. Поэтому после ливня будет волна, а под непрерывной моросью —
умеренный ровный фон.</li>
<li><b>Лаг вида.</b> Заложенное сегодня вылезает через 3–16 суток в зависимости от вида:
маслёнок отзывается за 3–7 суток, белый за 6–12, опёнок за 8–16. Итог за день —
свёртка закладки за все подходящие предыдущие дни.</li>
<li><b>Поправки.</b> Сезонный вес месяца; гибель уже выросших грибов от заморозка,
жары и пересыхания; для осеннего опёнка — обязательный триггер похолодания.</li>
</ol>

<h3 style='margin:8px 0 4px'>Как этим пользоваться</h3>
<ul style='margin:0 0 8px -20px'>
<li>Смотрите не на абсолютное число, а на <b>форму волны</b>: где подъём, где пик.
Модель точнее в сроках, чем в амплитуде.</li>
<li>Вкладка <b>«Почему такой прогноз»</b> показывает, какой сомножитель тормозит:
сухо, холодно, не сезон или дождь был слишком недавно.</li>
<li>Разные виды идут в разное время — сравнивайте строки в матрице.</li>
</ul>

<h3 style='margin:8px 0 4px'>Чего программа не умеет</h3>
<p style='margin:0 0 8px'>Она не знает тип леса и почвы, экспозицию склона, микроклимат
низин, прошлогодний урожай и состояние мицелия. Модель эвристическая: константы
подобраны по литературным представлениям о сроках слоёв, а не по вашим наблюдениям.
Если вести журнал выездов, параметры можно подогнать под конкретные места.</p>
</div>""")
        lay.addWidget(txt, 1)


# --------------------------------------------------------------------------- #
#  Главное окно
# --------------------------------------------------------------------------- #

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Прогноз плодоношения грибов  v{engine.VERSION}")
        self.resize(1180, 760)
        self.settings = QSettings("grezev", "mushroom-forecast")
        self.res: Result | None = None
        self.members: list = []
        self.thread: QThread | None = None
        self._first = True
        self._build()
        self._reload_spots()
        self._restore()

    # --- построение UI -----------------------------------------------------
    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 10, 10, 6)
        outer.setSpacing(8)

        # верхняя панель
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(QLabel("Место:"))
        self.cb_spots = QComboBox()
        self.cb_spots.setMinimumWidth(150)
        self.cb_spots.setToolTip("Сохранённые места: у каждого свои координаты и тип леса")
        self.cb_spots.currentIndexChanged.connect(self._spot_selected)
        bar.addWidget(self.cb_spots)
        b_save = QPushButton("Запомнить")
        b_save.setToolTip("Сохранить текущую точку и тип леса как место")
        b_save.clicked.connect(self._save_spot)
        bar.addWidget(b_save)
        b_del = QPushButton("Удалить")
        b_del.clicked.connect(self._delete_spot)
        bar.addWidget(b_del)
        self.ed_place = QLineEdit("Фрязино")
        self.ed_place.setPlaceholderText("населённый пункт или «широта, долгота»")
        self.ed_place.setMinimumWidth(260)
        self.ed_place.returnPressed.connect(self.calculate)
        bar.addWidget(self.ed_place)

        bar.addWidget(QLabel("Прогноз, сут:"))
        self.sp_days = QSpinBox()
        self.sp_days.setRange(3, 16)
        self.sp_days.setValue(10)
        bar.addWidget(self.sp_days)

        bar.addWidget(QLabel("Лес:"))
        self.cb_biotope = QComboBox()
        for b in engine.BIOTOPES.values():
            self.cb_biotope.addItem(b.name, b.key)
            self.cb_biotope.setItemData(self.cb_biotope.count() - 1, b.note, Qt.ToolTipRole)
        self.cb_biotope.setToolTip("Тип леса задаёт почвенные константы, затенение\n"
                                   "и пригодность для каждого вида")
        self.cb_biotope.currentIndexChanged.connect(self._biotope_changed)
        bar.addWidget(self.cb_biotope)

        self.cb_demo = QCheckBox("Демо-режим (без сети)")
        bar.addWidget(self.cb_demo)

        self.btn_map = QPushButton("На карте…")
        self.btn_map.setToolTip("Выбрать точку щелчком по карте")
        self.btn_map.clicked.connect(self.pick_on_map)
        bar.addWidget(self.btn_map)

        self.btn_help = QPushButton("Как это работает")
        self.btn_help.setToolTip("Как работает программа")
        self.btn_help.clicked.connect(
            lambda: self.tabs.setCurrentIndex(self.tabs.count() - 1))
        bar.addWidget(self.btn_help)

        bar.addStretch(1)
        self.btn_calc = QPushButton("Рассчитать")
        self.btn_calc.setObjectName("primary")
        self.btn_calc.clicked.connect(self.calculate)
        bar.addWidget(self.btn_calc)
        self.btn_csv = QPushButton("Экспорт CSV")
        self.btn_csv.clicked.connect(self.export_csv)
        self.btn_csv.setEnabled(False)
        bar.addWidget(self.btn_csv)
        self.btn_json = QPushButton("Экспорт JSON")
        self.btn_json.clicked.connect(self.export_json)
        self.btn_json.setEnabled(False)
        bar.addWidget(self.btn_json)
        outer.addLayout(bar)

        # карточка вывода
        self.card = QFrame()
        self.card.setObjectName("verdict")
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(13, 9, 13, 10)
        cl.setSpacing(3)
        self.verdict = QLabel("Данные не загружены")
        self.verdict.setFont(QFont("", 13, QFont.Bold))
        self.explain_lbl = QLabel("Укажите место и нажмите «Рассчитать». "
                                  "Кнопка «?» — как работает программа.")
        self.explain_lbl.setWordWrap(True)
        self.explain_lbl.setFont(QFont("", 9))
        cl.addWidget(self.verdict)
        cl.addWidget(self.explain_lbl)
        outer.addWidget(self.card)
        self._card_style("#F0F3EA", INK, "#5A6152")

        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split, 1)

        # левая колонка — виды
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        gb = QGroupBox("Виды")
        gl = QVBoxLayout(gb)
        self.lst = QListWidget()
        self.lst.setSelectionMode(QAbstractItemView.NoSelection)
        for sp in engine.SPECIES.values():
            it = QListWidgetItem(sp.name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, sp.name)
            px = QPixmap(10, 10)
            px.fill(QColor(SPECIES_COLORS.get(sp.name, "#555")))
            it.setIcon(QIcon(px))
            it.setToolTip(f"{sp.latin}\nT опт {sp.t_opt:.0f} °C, лаг {sp.lag_min}–{sp.lag_max} сут"
                          + (f"\n{sp.note}" if sp.note else ""))
            self.lst.addItem(it)
        self.lst.itemChanged.connect(lambda *_: self.refresh())
        gl.addWidget(self.lst)
        row = QHBoxLayout()
        b1 = QPushButton("Все")
        b1.clicked.connect(lambda: self._check_all(True))
        b2 = QPushButton("Снять")
        b2.clicked.connect(lambda: self._check_all(False))
        b3 = QPushButton("По сезону")
        b3.clicked.connect(self._check_season)
        for b in (b1, b2, b3):
            row.addWidget(b)
        gl.addLayout(row)
        lv.addWidget(gb)
        left.setMaximumWidth(280)
        split.addWidget(left)

        # правая колонка
        right = QSplitter(Qt.Vertical)
        top_box = QWidget()
        tv = QVBoxLayout(top_box)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(4)
        self.chart = ChartWidget()
        tv.addWidget(self.chart, 1)
        under = QHBoxLayout()
        self.legend = LevelLegend()
        under.addWidget(self.legend, 1)
        self.cb_band = QCheckBox("Разброс сценариев")
        self.cb_band.setToolTip("Коридор P10–P90 по ансамблю погодных сценариев:\n"
                                "видно, до какого дня прогнозу можно верить")
        self.cb_band.toggled.connect(self._toggle_band)
        under.addWidget(self.cb_band, 0, Qt.AlignBottom)
        self.cb_drivers = QCheckBox("Показать влагу и T почвы")
        self.cb_drivers.setToolTip("Пунктиром — от чего зависит индекс:\n"
                                   "влагозапас подстилки и температура почвы")
        self.cb_drivers.toggled.connect(self._toggle_drivers)
        under.addWidget(self.cb_drivers, 0, Qt.AlignBottom)
        tv.addLayout(under)
        right.addWidget(top_box)

        self.tabs = QTabWidget()
        self.tbl_days = QTableWidget()
        self.tbl_days.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_days.setAlternatingRowColors(False)
        self.tabs.addTab(self.tbl_days, "Прогноз по дням")

        self.tbl_sp = QTableWidget()
        self.tbl_sp.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_sp.setToolTip("Строка — вид, столбец — дата. Видно, кто когда идёт.")
        self.tabs.addTab(self.tbl_sp, "Все виды")

        # вкладка «Почему такой прогноз»
        why = QWidget()
        wl = QVBoxLayout(why)
        wl.setContentsMargins(10, 8, 10, 8)
        wl.setSpacing(6)
        pick = QHBoxLayout()
        pick.addWidget(QLabel("День:"))
        self.cb_day = QComboBox()
        self.cb_day.setMinimumWidth(150)
        self.cb_day.currentIndexChanged.connect(lambda *_: self._fill_why())
        pick.addWidget(self.cb_day)
        pick.addSpacing(12)
        pick.addWidget(QLabel("Вид:"))
        self.cb_species = QComboBox()
        self.cb_species.setMinimumWidth(190)
        self.cb_species.currentIndexChanged.connect(lambda *_: self._fill_why())
        pick.addWidget(self.cb_species)
        pick.addStretch(1)
        wl.addLayout(pick)
        self.why_head = QLabel()
        self.why_head.setWordWrap(True)
        self.why_head.setFont(QFont("", 10))
        self.why_head.setStyleSheet("background:#F4F6EF; border:1px solid #DFE1D8;"
                                    "border-radius:6px; padding:8px 10px;")
        wl.addWidget(self.why_head)
        wl.addWidget(QLabel("Индекс — произведение этих сомножителей. "
                            "Самый короткий столбик и есть причина:"))
        self.bars = FactorBars()
        wl.addWidget(self.bars)
        wl.addStretch(1)
        self.tabs.addTab(why, "Почему такой прогноз")

        cmp_w = QWidget()
        cl = QVBoxLayout(cmp_w)
        cl.setContentsMargins(10, 8, 10, 8)
        cl.setSpacing(6)
        row = QHBoxLayout()
        b_cmp = QPushButton("Сравнить мои места")
        b_cmp.setObjectName("primary")
        b_cmp.clicked.connect(self.compare_spots)
        row.addWidget(b_cmp)
        row.addStretch(1)
        cl.addLayout(row)
        self.cmp_head = QLabel("Нажмите «Сравнить мои места», чтобы понять, куда ехать.")
        self.cmp_head.setWordWrap(True)
        self.cmp_head.setFont(QFont("", 11, QFont.Bold))
        self.cmp_head.setStyleSheet("background:#F4F6EF; border:1px solid #DFE1D8;"
                                    "border-radius:6px; padding:8px 10px;")
        cl.addWidget(self.cmp_head)
        self.tbl_cmp = QTableWidget()
        self.tbl_cmp.setEditTriggers(QAbstractItemView.NoEditTriggers)
        cl.addWidget(self.tbl_cmp, 1)
        self.tabs.addTab(cmp_w, "Куда ехать")

        self.txt = QTextEdit()
        self.txt.setReadOnly(True)
        self.tabs.addTab(self.txt, "Сводка по погоде")
        self.tabs.addTab(HowItWorks(), "Как это работает")

        right.addWidget(self.tabs)
        right.setSizes([330, 360])
        split.addWidget(right)
        split.setSizes([250, 930])

        self.statusBar().showMessage("Источник погоды: Open-Meteo (CC-BY). "
                                     "Модель эвристическая — вкладка «Как это работает».")

    def _check_all(self, on: bool):
        self.lst.blockSignals(True)
        for i in range(self.lst.count()):
            self.lst.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.lst.blockSignals(False)
        self.refresh()

    def _check_season(self):
        month = (self.res.days[self.res.today].d.month if self.res else datetime.now().month)
        self.lst.blockSignals(True)
        for i in range(self.lst.count()):
            name = self.lst.item(i).data(Qt.UserRole)
            sp = next(s for s in engine.SPECIES.values() if s.name == name)
            self.lst.item(i).setCheckState(
                Qt.Checked if sp.months.get(month, 0) > 0 else Qt.Unchecked)
        self.lst.blockSignals(False)
        self.refresh()

    def selected(self) -> list[str]:
        return [self.lst.item(i).data(Qt.UserRole) for i in range(self.lst.count())
                if self.lst.item(i).checkState() == Qt.Checked]

    # --- сохранённые места --------------------------------------------------
    def _reload_spots(self, select: str | None = None):
        self.cb_spots.blockSignals(True)
        self.cb_spots.clear()
        self.cb_spots.addItem("— текущая точка —", None)
        for sp in places_mod.load():
            self.cb_spots.addItem(sp.name, sp.name)
        if select:
            k = self.cb_spots.findData(select)
            if k >= 0:
                self.cb_spots.setCurrentIndex(k)
        self.cb_spots.blockSignals(False)

    def _current_coords(self) -> tuple[float, float] | None:
        parts = [p.strip().replace(",", ".") for p in
                 self.ed_place.text().replace(";", ",").split(",")]
        if len(parts) == 2:
            try:
                return float(parts[0]), float(parts[1])
            except ValueError:
                return None
        if self.res is not None:
            return self.res.place.lat, self.res.place.lon
        return None

    def _spot_selected(self):
        name = self.cb_spots.currentData()
        if not name:
            return
        sp = next((x for x in places_mod.load() if x.name == name), None)
        if sp is None:
            return
        self.ed_place.setText(sp.coords)
        k = self.cb_biotope.findData(sp.biotope)
        if k >= 0:
            self.cb_biotope.blockSignals(True)
            self.cb_biotope.setCurrentIndex(k)
            self.cb_biotope.blockSignals(False)
            engine.set_biotope(sp.biotope)
        self.calculate()

    def _save_spot(self):
        coords = self._current_coords()
        if coords is None:
            QMessageBox.information(self, "Место не определено",
                                    "Сначала рассчитайте прогноз или выберите точку "
                                    "на карте — тогда её можно будет запомнить.")
            return
        default = self.res.place.name if self.res else "Новое место"
        name, ok = QInputDialog.getText(self, "Запомнить место",
                                        "Название места:", text=default)
        if not ok or not name.strip():
            return
        spot = places_mod.Spot(name.strip(), coords[0], coords[1],
                               self.cb_biotope.currentData() or "смешанный")
        places_mod.add(spot)
        self._reload_spots(select=spot.name)
        self.statusBar().showMessage(f"Место сохранено: {spot.name} ({spot.coords})")

    def _delete_spot(self):
        name = self.cb_spots.currentData()
        if not name:
            return
        if QMessageBox.question(self, "Удалить место", f"Удалить «{name}»?") \
                == QMessageBox.Yes:
            places_mod.remove(name)
            self._reload_spots()

    # --- сравнение мест -----------------------------------------------------
    def compare_spots(self):
        spots = places_mod.load()
        if not spots:
            self.cmp_head.setText("Нет сохранённых мест. Выберите точку и нажмите "
                                  "«Запомнить» — тогда их можно будет сравнивать.")
            self.tbl_cmp.setRowCount(0)
            return
        self.cmp_head.setText("Считаю по всем местам…")
        QApplication.processEvents()
        fdays = self.sp_days.value()
        forecasts = places_mod.compare(spots, fdays)
        names = places_mod.season_names()

        cols = 0
        for f in forecasts:
            if f.days:
                cols = max(cols, min(fdays, len(f.days) - f.today))
        t = self.tbl_cmp
        t.clear()
        t.setRowCount(len(forecasts))
        t.setColumnCount(cols + 2)
        ref = next((f for f in forecasts if f.days), None)
        heads = ["Место", "Тип леса"] + ([ref.days[i].d.strftime("%d.%m")
                                          for i in range(ref.today, ref.today + cols)]
                                         if ref else [])
        t.setHorizontalHeaderLabels(heads)
        t.verticalHeader().setVisible(False)
        for row, f in enumerate(forecasts):
            it = QTableWidgetItem(f.spot.name + (" ⟳" if f.stale else ""))
            if f.stale:
                it.setToolTip(f"Данные из кэша, {places_mod.cache_age_text(f.stale)}")
            t.setItem(row, 0, it)
            bio = engine.BIOTOPES.get(f.spot.biotope)
            t.setItem(row, 1, QTableWidgetItem(bio.name if bio else f.spot.biotope))
            if f.error:
                cell = QTableWidgetItem(f"нет данных: {f.error[:40]}")
                cell.setForeground(QBrush(QColor("#A8564F")))
                t.setItem(row, 2, cell)
                continue
            for c in range(cols):
                i = f.today + c
                if i >= len(f.days):
                    continue
                v, who = f.best(i, names)
                cell = QTableWidgetItem(f"{v:.0f}")
                cell.setTextAlignment(Qt.AlignCenter)
                cell.setFont(mono(9, v >= 50))
                bg, fg = level_style(v)
                cell.setBackground(QBrush(bg))
                cell.setForeground(QBrush(fg))
                cell.setToolTip(f"{f.spot.name}, {f.days[i].d.strftime('%d.%m')}: "
                                f"{engine.level(v)}" + (f", {who.lower()}" if who else ""))
                t.setItem(row, c + 2, cell)
        t.resizeColumnsToContents()
        self.cmp_head.setText(places_mod.recommend(forecasts, names))

    # --- выбор места на карте ----------------------------------------------
    def pick_on_map(self, first_run: bool = False):
        s = self.settings
        lat = float(s.value("lat", 55.9606))
        lon = float(s.value("lon", 38.0456))
        zoom = int(s.value("zoom", 11))
        dlg = MapPicker(self, lat, lon, zoom, first_run=first_run)
        if dlg.exec() != QDialog.Accepted:
            return False
        lat, lon, zoom = dlg.result_coords()
        s.setValue("lat", lat)
        s.setValue("lon", lon)
        s.setValue("zoom", zoom)
        s.setValue("picked", True)
        self.ed_place.setText(f"{lat:.5f}, {lon:.5f}")
        self.calculate()
        return True

    # --- расчёт ------------------------------------------------------------
    def calculate(self):
        if self.thread is not None:
            return
        self.btn_calc.setEnabled(False)
        self.btn_calc.setText("Загрузка…")
        self.statusBar().showMessage("Запрос погодных данных…")
        self.thread = QThread(self)
        self.worker = Worker(self.ed_place.text(), self.sp_days.value(), self.cb_demo.isChecked())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.done.connect(self._ok)
        self.worker.failed.connect(self._err)
        self.thread.start()

    def _stop(self):
        if self.thread:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
        self.btn_calc.setEnabled(True)
        self.btn_calc.setText("Рассчитать")

    def _ok(self, res: Result):
        self._stop()
        self.res = res
        self.btn_csv.setEnabled(True)
        self.btn_json.setEnabled(True)
        if res.stale:
            self.statusBar().showMessage(
                f"{res.place.name} · НЕТ СЕТИ, данные из кэша "
                f"({places_mod.cache_age_text(res.stale)})")
        else:
            self.statusBar().showMessage(
                f"{res.place.name} · обновлено {res.stamp:%H:%M} · Open-Meteo (CC-BY) · "
                f"наведите курсор на график для детализации по дню")
        if self._first:
            self._first = False
            self._check_season()
        self.refresh()

    def _err(self, msg: str):
        self._stop()
        QMessageBox.warning(self, "Не удалось получить данные",
                            f"{msg}\n\nПроверьте название места и подключение к сети "
                            f"или включите демо-режим.")
        self.statusBar().showMessage("Ошибка загрузки")

    # --- вывод -------------------------------------------------------------
    def refresh(self):
        names = self.selected()
        self.chart.set_data(self.res, names)
        if not self.res:
            return
        r = self.res
        self._fill_days(r, names)
        self._fill_matrix(r, names)
        self._fill_diag(r, names)

        v, who = r.best(names, r.today)
        hi = len(r.days)
        fut = [(r.best(names, i)[0], i) for i in range(r.today, hi)]
        bv, bi = max(fut) if fut else (0.0, r.today)
        txt = f"Сегодня: {v:.0f} из 100 — {engine.level(v)}"
        if who and v >= 18:
            txt += f" ({who.lower()})"
        if bi != r.today and bv > v + 6:
            txt += f"   ·   пик {r.days[bi].d.strftime('%d.%m')}: {bv:.0f} — {engine.level(bv)}"
        elif bv < 18:
            txt += "   ·   выхода в ближайшие дни не ожидается"
        self.verdict.setText(txt)
        bg, fg = level_style(v)
        self._card_style(bg.name(), fg.name(), fg.name())

        if who:
            spec = next(s for s in engine.SPECIES.values() if s.name == who)
            self.explain_lbl.setText(
                engine.plain_summary(spec, r.today, r.days, r.m, r.ts, v))
        else:
            self.explain_lbl.setText("Не выбрано ни одного вида — отметьте их слева.")

        self._sync_why_pickers(r, names, who, bi)
        if getattr(self, "members", None):
            self._update_band()

    def _card_style(self, bg: str, fg: str, sub: str):
        self.card.setStyleSheet(
            f"QFrame#verdict {{ background:{bg}; border:1px solid #DFE1D8; border-radius:6px; }}")
        self.verdict.setStyleSheet(f"color:{fg}; background:transparent;")
        self.explain_lbl.setStyleSheet(f"color:{sub}; background:transparent;")

    def _biotope_changed(self):
        key = self.cb_biotope.currentData()
        if not key:
            return
        engine.set_biotope(key)
        self.settings.setValue("biotope", key)
        if self.res is not None:
            self.res = Result(self.res.place, self.res.days, self.res.today)
            self.refresh()

    def _toggle_band(self, on: bool):
        if not on:
            self.members = []
            self.chart.band = {}
            self.chart.update()
            return
        if self.res is None:
            return
        self.cb_band.setEnabled(False)
        self.statusBar().showMessage("Загружаю ансамбль погодных сценариев…")
        QApplication.processEvents()
        try:
            self.members = ensemble_mod.fetch_members(self.res.place,
                                                      self.sp_days.value())
        except Exception as e:                                    # noqa: BLE001
            self.members = []
            self.statusBar().showMessage(f"Ансамбль недоступен: {e}")
        self.cb_band.setEnabled(True)
        if not self.members:
            self.cb_band.blockSignals(True)
            self.cb_band.setChecked(False)
            self.cb_band.blockSignals(False)
            if not self.statusBar().currentMessage().startswith("Ансамбль"):
                self.statusBar().showMessage("Ансамблевые данные для этой точки "
                                             "не отдаются.")
            return
        self._update_band()

    def _update_band(self):
        if not getattr(self, "members", None) or self.res is None:
            self.chart.band = {}
            self.chart.update()
            return
        names = self.selected()
        lead = self.res.best(names, self.res.today)[1] if names else None
        if lead is None:
            return
        spec = next(s for s in engine.SPECIES.values() if s.name == lead)
        self.chart.band = ensemble_mod.band(self.res.days, self.members, spec)
        self.chart.update()
        self.statusBar().showMessage(
            f"{len(self.members)} сценариев · "
            + ensemble_mod.reliability(self.chart.band, self.res.days, self.res.today))

    def _toggle_drivers(self, on: bool):
        self.chart.show_drivers = on
        self.chart.update()

    def _sync_why_pickers(self, r: Result, names: list[str], who: str | None, peak: int):
        blocked = (self.cb_day.blockSignals(True), self.cb_species.blockSignals(True))
        cur_d = self.cb_day.currentData()
        cur_s = self.cb_species.currentText()
        self.cb_day.clear()
        for i in range(max(0, r.today - 3), len(r.days)):
            mark = " (сегодня)" if i == r.today else (" (пик)" if i == peak else "")
            self.cb_day.addItem(r.days[i].d.strftime("%d.%m.%Y") + mark, i)
        k = self.cb_day.findData(cur_d if cur_d is not None else r.today)
        self.cb_day.setCurrentIndex(k if k >= 0 else self.cb_day.findData(r.today))
        self.cb_species.clear()
        self.cb_species.addItems(names or [s.name for s in engine.SPECIES.values()])
        j = self.cb_species.findText(cur_s if cur_s else (who or ""))
        self.cb_species.setCurrentIndex(max(0, j))
        self.cb_day.blockSignals(False)
        self.cb_species.blockSignals(False)
        del blocked
        self._fill_why()

    def _fill_why(self):
        r = self.res
        if not r or self.cb_day.currentIndex() < 0 or not self.cb_species.currentText():
            return
        i = self.cb_day.currentData()
        if i is None:
            return
        spec = next(s for s in engine.SPECIES.values()
                    if s.name == self.cb_species.currentText())
        v = r.value(spec.name, i)
        self.why_head.setText(
            f"<b>{spec.name}, {r.days[i].d.strftime('%d.%m.%Y')}: "
            f"{v:.0f} из 100 — {engine.level(v)}.</b><br>"
            + engine.plain_summary(spec, i, r.days, r.m, r.ts, v))
        self.bars.set_rows(engine.explain(spec, i, r.days, r.m, r.ts))

    def _fill_days(self, r: Result, names: list[str]):
        cols = ["Дата", "Осадки, мм", "T возд., °C", "T почвы, °C", "Влага, %",
                "Индекс", "Оценка", "Лидирующий вид"]
        lo, hi = max(0, r.today - 3), len(r.days)
        t = self.tbl_days
        t.clear()
        t.setColumnCount(len(cols))
        t.setRowCount(hi - lo)
        t.setHorizontalHeaderLabels(cols)
        t.verticalHeader().setVisible(False)
        for row, i in enumerate(range(lo, hi)):
            d = r.days[i]
            v, who = r.best(names, i)
            vals = [d.d.strftime("%d.%m.%Y  ") + engine.RU_WD[d.d.weekday()],
                    f"{d.precip:.1f}", f"{d.tmean:.1f}", f"{r.ts[i]:.1f}",
                    f"{r.m[i]*100:.0f}", f"{v:.0f}", engine.level(v),
                    (who or "") if v >= 8 else ""]
            for c, s in enumerate(vals):
                it = QTableWidgetItem(s)
                if c:
                    it.setTextAlignment(Qt.AlignCenter)
                if c in (1, 2, 3, 4, 5):
                    it.setFont(mono(9))
                if c in (5, 6):
                    bg, fg = level_style(v)
                    it.setBackground(QBrush(bg))
                    it.setForeground(QBrush(fg))
                    if c == 5:
                        it.setFont(mono(10, True))
                if i == r.today:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                if i < r.today:
                    it.setForeground(QBrush(QColor("#9AA093"))) if c not in (5, 6) else None
                t.setItem(row, c, it)
        t.resizeColumnsToContents()
        t.horizontalHeader().setStretchLastSection(True)
        if hi - lo:
            t.scrollToItem(t.item(min(3, t.rowCount() - 1), 0))

    def _fill_matrix(self, r: Result, names: list[str]):
        lo, hi = r.today, len(r.days)
        t = self.tbl_sp
        t.clear()
        t.setRowCount(len(names))
        t.setColumnCount(hi - lo)
        t.setHorizontalHeaderLabels([r.days[i].d.strftime("%d.%m") for i in range(lo, hi)])
        t.setVerticalHeaderLabels(names)
        for row, n in enumerate(names):
            for col, i in enumerate(range(lo, hi)):
                v = r.value(n, i)
                it = QTableWidgetItem(f"{v:.0f}")
                it.setTextAlignment(Qt.AlignCenter)
                it.setFont(mono(9, v >= 50))
                bg, fg = level_style(v)
                it.setBackground(QBrush(bg))
                it.setForeground(QBrush(fg))
                it.setToolTip(f"{n}, {r.days[i].d.strftime('%d.%m')}: {engine.level(v)}")
                t.setItem(row, col, it)
        t.resizeColumnsToContents()
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def _fill_diag(self, r: Result, names: list[str]):
        i = r.today
        dsr = engine.days_since_rain(i, r.days)
        p14 = sum(r.days[j].precip for j in range(max(0, i - 13), i + 1))
        rows = "".join(
            f"<tr><td style='padding:2px 14px 2px 0'>{k}</td>"
            f"<td style='padding:2px 0'><b>{v}</b></td></tr>"
            for k, v in [
                ("Влагозапас подстилки",
                 f"{r.m[i]*100:.0f}% ёмкости ({r.m[i]*engine.CAPACITY_MM:.0f} мм из "
                 f"{engine.CAPACITY_MM:.0f})"),
                ("Осадки за 14 суток", f"{p14:.1f} мм"),
                ("Последний дождь ≥5 мм",
                 f"{dsr} сут назад" if dsr is not None else "не было за месяц"),
                ("Температура почвы (5–10 см)", f"{r.ts[i]:.1f} °C"),
                ("Источник влаги", engine.sources(r.days)[0]),
                ("Источник T почвы", engine.sources(r.days)[1]),
                ("Настройка модели", engine.calibration_info()),
                ("Тип леса", f"{engine.CURRENT_BIOTOPE.name} · влага "
                             f"{engine.THETA_WILT:.2f}–{engine.THETA_FC:.2f} м³/м³"),
                ("Температура воздуха", f"{r.days[i].tmean:.1f} °C "
                                        f"(мин {r.days[i].tmin:.1f} / макс {r.days[i].tmax:.1f})"),
            ])
        band_row = ""
        if getattr(self, "members", None) and self.chart.band:
            band_row = (f"<p style='margin:6px 0'><b>Разброс сценариев:</b> "
                        f"{ensemble_mod.spread_text(self.chart.band, r.days[i].d)}. "
                        f"{ensemble_mod.reliability(self.chart.band, r.days, i)}</p>")
        lim = "".join(
            f"<tr><td style='padding:2px 14px 2px 0'>{n}</td>"
            f"<td style='padding:2px 12px 2px 0'><b>{r.value(n, i):.0f}</b></td>"
            f"<td style='padding:2px 0;color:#5A6152'>"
            f"{engine.limiting_factor(next(s for s in engine.SPECIES.values() if s.name == n), i, r.days, r.m, r.ts)}"
            f"</td></tr>" for n in names)
        notes = "".join(
            f"<li><b>{sp.name}.</b> {sp.note}</li>"
            for sp in engine.SPECIES.values() if sp.note and sp.name in names)
        self.txt.setHtml(f"""
        <div style='font-family:sans-serif; font-size:10pt'>
        <h3 style='margin:0 0 6px'>Состояние на {r.days[i].d.strftime('%d.%m.%Y')}</h3>
        <table>{rows}</table>
        {band_row}
        <h3 style='margin:14px 0 6px'>Что ограничивает</h3>
        <table>{lim}</table>
        <h3 style='margin:14px 0 6px'>Заметки</h3>
        <ul style='margin:0 0 0 -18px'>{notes}</ul>
        <p style='color:#7B8272; margin-top:14px'>Модель эвристическая: водный баланс подстилки,
        температура почвы, импульсный отклик на дождь и лаг плодообразования.
        Калибровочные константы — в начале mushroom_forecast.py.</p>
        </div>""")

    # --- экспорт -----------------------------------------------------------
    def export_csv(self):
        if not self.res:
            return
        fn, _ = QFileDialog.getSaveFileName(self, "Сохранить CSV", "mushroom_forecast.csv",
                                            "CSV (*.csv)")
        if not fn:
            return
        r, names = self.res, self.selected()
        with open(fn, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["дата", "осадки_мм", "T_возд", "T_почвы", "влага_доля", "индекс", "оценка"]
                       + names)
            for i in range(r.today, len(r.days)):
                v = r.best(names, i)[0]
                w.writerow([r.days[i].d.isoformat(), f"{r.days[i].precip:.1f}",
                            f"{r.days[i].tmean:.1f}", f"{r.ts[i]:.1f}", f"{r.m[i]:.3f}",
                            f"{v:.0f}", engine.level(v)]
                           + [f"{r.value(n, i):.0f}" for n in names])
        self.statusBar().showMessage(f"Сохранено: {fn}")

    def export_json(self):
        if not self.res:
            return
        fn, _ = QFileDialog.getSaveFileName(self, "Сохранить JSON", "mushroom_forecast.json",
                                            "JSON (*.json)")
        if not fn:
            return
        r = self.res
        chosen = [sp for sp in engine.SPECIES.values() if sp.name in self.selected()]
        data = engine.as_json(r.place, r.days, len(r.days) - r.today, chosen, r.today)
        with open(fn, "w", encoding="utf-8") as f:
            f.write(data)
        self.statusBar().showMessage(f"Сохранено: {fn}")

    # --- настройки ---------------------------------------------------------
    def _restore(self):
        s = self.settings
        self.ed_place.setText(s.value("place", "Фрязино"))
        bio = s.value("biotope", "смешанный")
        k = self.cb_biotope.findData(bio)
        if k >= 0:
            self.cb_biotope.blockSignals(True)
            self.cb_biotope.setCurrentIndex(k)
            self.cb_biotope.blockSignals(False)
            engine.set_biotope(bio)
        if s.value("picked") in (None, "", False, "false"):
            QTimer.singleShot(60, lambda: self.pick_on_map(first_run=True))
        self.sp_days.setValue(int(s.value("days", 10)))
        g = s.value("geometry")
        if g:
            self.restoreGeometry(g)

    def closeEvent(self, e):
        s = self.settings
        s.setValue("place", self.ed_place.text())
        s.setValue("biotope", self.cb_biotope.currentData())
        s.setValue("days", self.sp_days.value())
        s.setValue("geometry", self.saveGeometry())
        self._stop()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Прогноз плодоношения грибов")
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
