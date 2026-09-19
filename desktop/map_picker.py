#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
map_picker.py — выбор точки на карте без QtWebEngine.

Растровые тайлы OpenStreetMap рисуются средствами QPainter, скачиваются через
QNetworkAccessManager и кэшируются на диск. Если сети нет, карта остаётся
работоспособной как координатная сетка: щелчок всё равно даёт широту и долготу.

Данные карты © OpenStreetMap contributors, ODbL.
"""

from __future__ import annotations

import math
import os

from PySide6.QtCore import (QByteArray, QPoint, QPointF, QRect, QStandardPaths,
                            Qt, QUrl, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtNetwork import (QNetworkAccessManager, QNetworkReply,
                               QNetworkRequest)
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

TILE = 256
MIN_Z, MAX_Z = 3, 17
UA = b"mushroom-forecast/1.6 (personal use; https://open-meteo.com)"
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


# --------------------------------------------------------------------------- #
#  Проекция Web Mercator
# --------------------------------------------------------------------------- #

def deg2num(lat: float, lon: float, z: int) -> tuple[float, float]:
    n = 2.0 ** z
    lat = max(-85.0511, min(85.0511, lat))
    r = math.radians(lat)
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n
    return x, y


def num2deg(x: float, y: float, z: int) -> tuple[float, float]:
    n = 2.0 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return lat, lon


# --------------------------------------------------------------------------- #
#  Карта
# --------------------------------------------------------------------------- #

class SlippyMap(QWidget):
    """Панорамируемая карта с меткой. Щелчок ставит метку."""

    picked = Signal(float, float)

    def __init__(self, lat=55.9606, lon=38.0456, zoom=11):
        super().__init__()
        self.zoom = zoom
        self.cx, self.cy = deg2num(lat, lon, zoom)
        self.marker = (lat, lon)
        self.setMinimumSize(520, 380)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)

        self._mem: dict[tuple, QPixmap] = {}
        self._pending: set[tuple] = set()
        self._drag = None
        self._moved = False
        self._offline = False

        base = QStandardPaths.writableLocation(QStandardPaths.CacheLocation)
        self._dir = os.path.join(base or ".", "osm-tiles")
        os.makedirs(self._dir, exist_ok=True)

        self._net = QNetworkAccessManager(self)
        self._net.finished.connect(self._on_tile)

    # --- координаты <-> экран ---------------------------------------------
    def _screen(self, lat, lon) -> QPointF:
        x, y = deg2num(lat, lon, self.zoom)
        return QPointF((x - self.cx) * TILE + self.width() / 2,
                       (y - self.cy) * TILE + self.height() / 2)

    def _latlon(self, px, py) -> tuple[float, float]:
        x = self.cx + (px - self.width() / 2) / TILE
        y = self.cy + (py - self.height() / 2) / TILE
        return num2deg(x, y, self.zoom)

    def center_on(self, lat, lon, zoom=None):
        if zoom is not None:
            self.zoom = max(MIN_Z, min(MAX_Z, zoom))
        self.cx, self.cy = deg2num(lat, lon, self.zoom)
        self.update()

    def set_marker(self, lat, lon):
        self.marker = (lat, lon)
        self.picked.emit(lat, lon)
        self.update()

    # --- тайлы -------------------------------------------------------------
    def _path(self, z, x, y):
        return os.path.join(self._dir, f"{z}_{x}_{y}.png")

    def _tile(self, z, x, y) -> QPixmap | None:
        key = (z, x, y)
        if key in self._mem:
            return self._mem[key]
        fn = self._path(z, x, y)
        if os.path.exists(fn):
            pm = QPixmap(fn)
            if not pm.isNull():
                self._mem[key] = pm
                return pm
        if key not in self._pending and len(self._pending) < 24:
            self._pending.add(key)
            req = QNetworkRequest(QUrl(TILE_URL.format(z=z, x=x, y=y)))
            req.setRawHeader(QByteArray(b"User-Agent"), QByteArray(UA))
            req.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                             QNetworkRequest.NoLessSafeRedirectPolicy)
            reply = self._net.get(req)
            reply.setProperty("key", f"{z}/{x}/{y}")
        return None

    def _on_tile(self, reply: QNetworkReply):
        raw = reply.property("key") or ""
        try:
            z, x, y = (int(v) for v in raw.split("/"))
        except ValueError:
            reply.deleteLater()
            return
        self._pending.discard((z, x, y))
        if reply.error() == QNetworkReply.NoError:
            data = reply.readAll()
            pm = QPixmap()
            if pm.loadFromData(data):
                self._mem[(z, x, y)] = pm
                try:
                    with open(self._path(z, x, y), "wb") as f:
                        f.write(bytes(data))
                except OSError:
                    pass
                self._offline = False
                self.update()
        else:
            self._offline = True
            self.update()
        reply.deleteLater()

    # --- ввод --------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.position()
            self._moved = False

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        d = e.position() - self._drag
        if abs(d.x()) + abs(d.y()) > 3:
            self._moved = True
        self.cx -= d.x() / TILE
        self.cy -= d.y() / TILE
        self._drag = e.position()
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and not self._moved:
            lat, lon = self._latlon(e.position().x(), e.position().y())
            self.set_marker(lat, lon)
        self._drag = None

    def wheelEvent(self, e):
        step = 1 if e.angleDelta().y() > 0 else -1
        z = max(MIN_Z, min(MAX_Z, self.zoom + step))
        if z == self.zoom:
            return
        lat, lon = self._latlon(e.position().x(), e.position().y())
        self.zoom = z
        self.cx, self.cy = deg2num(lat, lon, z)
        # сохраняем точку под курсором на месте
        self.cx += (self.width() / 2 - e.position().x()) / TILE
        self.cy += (self.height() / 2 - e.position().y()) / TILE
        self.update()

    def zoom_by(self, step: int):
        lat, lon = self._latlon(self.width() / 2, self.height() / 2)
        self.zoom = max(MIN_Z, min(MAX_Z, self.zoom + step))
        self.center_on(lat, lon)

    # --- отрисовка ---------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#E9E5DC"))
        n = 2 ** self.zoom
        x0 = int(math.floor(self.cx - self.width() / 2 / TILE))
        y0 = int(math.floor(self.cy - self.height() / 2 / TILE))
        x1 = int(math.ceil(self.cx + self.width() / 2 / TILE))
        y1 = int(math.ceil(self.cy + self.height() / 2 / TILE))
        missing = 0
        for tx in range(x0, x1 + 1):
            for ty in range(y0, y1 + 1):
                if not (0 <= ty < n):
                    continue
                sx = (tx - self.cx) * TILE + self.width() / 2
                sy = (ty - self.cy) * TILE + self.height() / 2
                pm = self._tile(self.zoom, tx % n, ty)
                if pm is not None:
                    p.drawPixmap(QPoint(int(sx), int(sy)), pm)
                else:
                    missing += 1
                    p.setPen(QPen(QColor("#D5D0C4"), 1))
                    p.setBrush(Qt.NoBrush)
                    p.drawRect(QRect(int(sx), int(sy), TILE, TILE))

        # координатная сетка, если тайлов нет
        if missing and self._offline:
            p.setPen(QColor("#8A8578"))
            p.setFont(QFont("", 8))
            for tx in range(x0, x1 + 1):
                for ty in range(y0, y1 + 1):
                    if not (0 <= ty < n):
                        continue
                    lat, lon = num2deg(tx, ty, self.zoom)
                    sx = (tx - self.cx) * TILE + self.width() / 2
                    sy = (ty - self.cy) * TILE + self.height() / 2
                    p.drawText(QPoint(int(sx) + 5, int(sy) + 14),
                               f"{lat:.2f}, {lon:.2f}")

        # метка
        if self.marker:
            s = self._screen(*self.marker)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor("#FFFFFF"), 3))
            p.drawLine(int(s.x()), int(s.y()) - 16, int(s.x()), int(s.y()))
            p.setPen(QPen(QColor("#C0392B"), 1.6))
            p.setBrush(QColor("#E74C3C"))
            p.drawEllipse(QPointF(s.x(), s.y() - 18), 8, 8)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#C0392B"), 2))
            p.drawLine(int(s.x()), int(s.y()) - 12, int(s.x()), int(s.y()))

        # атрибуция и подсказки
        p.setFont(QFont("", 8))
        txt = "© OpenStreetMap contributors"
        p.setPen(QColor(255, 255, 255, 200))
        p.fillRect(QRect(self.width() - 178, self.height() - 18, 178, 18),
                   QColor(255, 255, 255, 190))
        p.setPen(QColor("#4A5142"))
        p.drawText(QRect(self.width() - 174, self.height() - 18, 170, 18),
                   Qt.AlignRight | Qt.AlignVCenter, txt)
        if self._offline and missing:
            p.fillRect(QRect(0, 0, self.width(), 22), QColor(255, 246, 230, 235))
            p.setPen(QColor("#8A5A1A"))
            p.drawText(QRect(8, 0, self.width() - 16, 22), Qt.AlignLeft | Qt.AlignVCenter,
                       "Тайлы карты не загружаются — координаты по щелчку всё равно верны")
        p.end()


# --------------------------------------------------------------------------- #
#  Диалог
# --------------------------------------------------------------------------- #

class MapPicker(QDialog):
    """Выбор точки: щелчок по карте, поиск по названию или ручной ввод."""

    def __init__(self, parent=None, lat=55.9606, lon=38.0456, zoom=11, first_run=False):
        super().__init__(parent)
        self.setWindowTitle("Выбор места")
        self.resize(760, 600)
        self.lat, self.lon = lat, lon

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        if first_run:
            hint = QLabel("Укажите, для какого места считать прогноз: щёлкните по карте, "
                          "найдите населённый пункт или впишите координаты вручную. "
                          "Выбор запомнится — при следующем запуске диалог не появится.")
            hint.setWordWrap(True)
            hint.setStyleSheet("background:#F0F3EA; border:1px solid #DFE1D8;"
                               "border-radius:6px; padding:8px 10px; color:#4A5142;")
            lay.addWidget(hint)

        top = QHBoxLayout()
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Населённый пункт, например: Щёлково")
        self.ed_search.returnPressed.connect(self._search)
        top.addWidget(self.ed_search, 1)
        b_find = QPushButton("Найти")
        b_find.clicked.connect(self._search)
        top.addWidget(b_find)
        b_out = QPushButton("–")
        b_out.setFixedWidth(36)
        b_out.setFont(QFont("", 12, QFont.Bold))
        b_out.clicked.connect(lambda: self.map.zoom_by(-1))
        b_in = QPushButton("+")
        b_in.setFixedWidth(36)
        b_in.setFont(QFont("", 12, QFont.Bold))
        b_in.clicked.connect(lambda: self.map.zoom_by(1))
        top.addWidget(b_out)
        top.addWidget(b_in)
        lay.addLayout(top)

        self.map = SlippyMap(lat, lon, zoom)
        self.map.picked.connect(self._on_pick)
        lay.addWidget(self.map, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Координаты:"))
        self.ed_coords = QLineEdit(f"{lat:.5f}, {lon:.5f}")
        self.ed_coords.setMaximumWidth(220)
        self.ed_coords.editingFinished.connect(self._from_text)
        bottom.addWidget(self.ed_coords)
        self.lbl_note = QLabel("Перетаскивайте карту мышью, колесо — масштаб")
        self.lbl_note.setStyleSheet("color:#7B8272;")
        bottom.addWidget(self.lbl_note, 1)
        lay.addLayout(bottom)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("Использовать это место")
        box.button(QDialogButtonBox.Cancel).setText("Отмена")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    # --- события ------------------------------------------------------------
    def _on_pick(self, lat, lon):
        self.lat, self.lon = lat, lon
        self.ed_coords.setText(f"{lat:.5f}, {lon:.5f}")
        self.lbl_note.setText("Точка выбрана")

    def _from_text(self):
        parts = [p.strip().replace(",", ".") for p in
                 self.ed_coords.text().replace(";", ",").split(",")]
        if len(parts) == 2:
            try:
                lat, lon = float(parts[0]), float(parts[1])
            except ValueError:
                return
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                self.lat, self.lon = lat, lon
                self.map.set_marker(lat, lon)
                self.map.center_on(lat, lon)

    def _search(self):
        name = self.ed_search.text().strip()
        if not name:
            return
        try:
            import mushroom_forecast as engine
            place = engine.geocode(name)
        except Exception as e:                                    # noqa: BLE001
            self.lbl_note.setText(str(e)[:90])
            return
        self.lat, self.lon = place.lat, place.lon
        self.map.center_on(place.lat, place.lon, max(self.map.zoom, 10))
        self.map.set_marker(place.lat, place.lon)
        self.lbl_note.setText(f"Найдено: {place.name}")

    def result_coords(self) -> tuple[float, float, int]:
        return self.lat, self.lon, self.map.zoom
