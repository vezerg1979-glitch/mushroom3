# -*- coding: utf-8 -*-
"""
photos.py — снимки находок: хранение, съёмка, выбор из галереи.

Зачем снимок. Заметка «крупный, под елью, ножка сетчатая» через месяц ничего
не восстановит, а фотография восстановит всё. Кроме того, половина сомнений
грибника — определительские: снял, вечером посмотрел в определитель или
показал знающему человеку. Без снимка вопрос остаётся навсегда.

Где лежат. В приватном каталоге приложения, рядом с треками и журналом:
<данные>/photos/2026-08-16_142305_a1b2.jpg. Не в общей галерее — грибные
места это то, чем не делятся, и попадание координат в чужие руки через
синхронизацию галереи было бы неприятным сюрпризом. Имя содержит дату и
время съёмки: даже если база походов потеряется, снимки останутся
разложенными по времени.

Почему снимок пережимается. Телефон снимает 12 мегапикселей — это 4-6 МБ на
кадр и примерно 50 МБ оперативной памяти при показе. Десяток находок за
поход, и приложение вылетает по памяти, а карточка забивается. 1600 точек по
длинной стороне — это лист А4 при печати и полный экран телефона с запасом,
при весе около 300 КБ. Пережатие делает сам Android (BitmapFactory), никаких
дополнительных пакетов в сборку не тянется.

Съёмка сделана без FileProvider: снимок пишется в MediaStore, оттуда
читается и переносится к себе, а запись в галерее удаляется. FileProvider
требует правки манифеста, которую python-for-android не умеет, а
Uri.fromFile начиная с Android 7 бросает FileUriExposedException — на этом
ломается штатная реализация plyer.camera.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from datetime import datetime

import places as places_mod

PHOTOS_DIR = "photos"

# Длинная сторона после пережатия и качество JPEG.
MAX_SIDE = 1600
JPEG_QUALITY = 85

# Коды запросов к системе. Значения произвольные, лишь бы не пересекались
# с чужими: android.activity раздаёт результат всем подписчикам подряд.
REQUEST_CAPTURE = 0x6D31
REQUEST_PICK = 0x6D32


# --------------------------------------------------------------------------- #
#  Хранилище
# --------------------------------------------------------------------------- #

def photos_dir() -> str:
    d = os.path.join(places_mod.data_dir(), PHOTOS_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def new_name(when: float | None = None, suffix: str = ".jpg") -> str:
    """Имя нового файла: время съёмки плюс восемь случайных знаков.

    Случайная часть нужна на случай двух снимков в одну секунду — за этим
    в лесу никто не следит, а перезаписанный кадр не вернуть. Восемь знаков,
    а не четыре: при четырёх на две сотни кадров приходится примерно четверть
    вероятности совпадения — парадокс дней рождения, который на глаз кажется
    невозможным, а на практике съедает снимок раз в несколько сезонов.
    """
    stamp = datetime.fromtimestamp(when if when is not None else time.time())
    return f"{stamp:%Y-%m-%d_%H%M%S}_{uuid.uuid4().hex[:8]}{suffix}"


def path_for(name: str) -> str:
    """Полный путь по имени файла. Имя, а не путь, хранится в походе:
    каталог данных на Android меняется при переустановке."""
    return os.path.join(photos_dir(), os.path.basename(name or ""))


def exists(name: str) -> bool:
    return bool(name) and os.path.isfile(path_for(name))


def save_bytes(data: bytes, when: float | None = None) -> str:
    """Кладёт готовый JPEG и возвращает имя файла."""
    name = new_name(when)
    tmp = path_for(name) + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path_for(name))
    return name


def import_path(src: str, when: float | None = None) -> str:
    """Забирает снимок из чужого файла к себе, по пути пережимая."""
    if not os.path.isfile(src):
        raise OSError(f"нет файла {src}")
    name = new_name(when)
    dst = path_for(name)
    if not downscale(src, dst):
        shutil.copyfile(src, dst)
    return name


def remove(name: str) -> bool:
    try:
        os.remove(path_for(name))
        return True
    except OSError:
        return False


def list_all() -> list[str]:
    try:
        return sorted(n for n in os.listdir(photos_dir())
                      if n.lower().endswith((".jpg", ".jpeg", ".png")))
    except OSError:
        return []


def total_bytes() -> int:
    """Сколько места занято: карточка не бесконечная, а поход длинный."""
    total = 0
    for name in list_all():
        try:
            total += os.path.getsize(path_for(name))
        except OSError:
            continue
    return total


def size_text(nbytes: int = None) -> str:
    n = total_bytes() if nbytes is None else nbytes
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} КБ"
    return f"{n / 1024 / 1024:.1f} МБ"


def cleanup(keep) -> int:
    """Удаляет снимки, на которые никто не ссылается.

    Осиротеть снимок может законно: человек сфотографировал, передумал,
    отменил метку. Без уборки такие кадры остаются на карточке навсегда.
    """
    keep = {os.path.basename(k) for k in keep if k}
    removed = 0
    for name in list_all():
        if name not in keep:
            removed += int(remove(name))
    return removed


# --------------------------------------------------------------------------- #
#  Пережатие
# --------------------------------------------------------------------------- #

def _sample_size(width: int, height: int, max_side: int) -> int:
    """Во сколько раз уменьшать при декодировании: степень двойки.

    BitmapFactory умеет прореживать пиксели прямо при чтении файла, поэтому
    полный кадр в память вообще не попадает — иначе на слабом телефоне
    двенадцать мегапикселей укладывают приложение ещё до пережатия.

    Прореживание кратно только степеням двойки, поэтому точного попадания в
    max_side не будет. Берётся наибольшее прореживание, при котором снимок
    ещё НЕ меньше цели: 12000 точек при цели 1600 дают 3000, а не 1500.
    Лучше отдать чуть больше нужного, чем потерять детали, по которым потом
    определяют вид.
    """
    sample = 1
    while max(width, height) // (sample * 2) >= max_side:
        sample *= 2
    return sample


def downscale(src: str, dst: str, max_side: int = MAX_SIDE) -> bool:
    """Пережимает снимок средствами Android. False — не получилось."""
    try:
        from jnius import autoclass
    except ImportError:
        return False
    try:
        BitmapFactory = autoclass("android.graphics.BitmapFactory")
        Options = autoclass("android.graphics.BitmapFactory$Options")
        CompressFormat = autoclass("android.graphics.Bitmap$CompressFormat")
        FileOutputStream = autoclass("java.io.FileOutputStream")

        probe = Options()
        probe.inJustDecodeBounds = True
        BitmapFactory.decodeFile(src, probe)
        if probe.outWidth <= 0:
            return False

        opts = Options()
        opts.inSampleSize = _sample_size(probe.outWidth, probe.outHeight, max_side)
        bitmap = BitmapFactory.decodeFile(src, opts)
        if bitmap is None:
            return False
        out = FileOutputStream(dst)
        try:
            bitmap.compress(CompressFormat.JPEG, JPEG_QUALITY, out)
        finally:
            out.close()
            bitmap.recycle()
        return os.path.isfile(dst)
    except Exception:                                             # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
#  Съёмка и выбор из галереи
# --------------------------------------------------------------------------- #

class Photographer:
    """Съёмка и выбор снимка. Вне Android молча отвечает отказом.

        p = Photographer()
        p.capture(lambda name, err: ...)
        p.pick(lambda name, err: ...)

    Обратный вызов приходит из потока Android: в интерфейсе его надо
    оборачивать в @mainthread.
    """

    def __init__(self):
        self._callback = None
        self._uri = None
        self._bound = False
        self.error = ""

    # --- доступность --------------------------------------------------------
    @staticmethod
    def available() -> bool:
        try:
            from jnius import autoclass
            autoclass("org.kivy.android.PythonActivity")
            return True
        except Exception:                                         # noqa: BLE001
            return False

    @staticmethod
    def _sdk_int() -> int:
        try:
            from jnius import autoclass
            return autoclass("android.os.Build$VERSION").SDK_INT
        except Exception:                                         # noqa: BLE001
            return 0

    @staticmethod
    def needs_storage_permission() -> bool:
        """До Android 10 запись в MediaStore требует разрешения на память."""
        return 0 < Photographer._sdk_int() < 29

    @staticmethod
    def request_storage_permission(callback=None) -> bool:
        try:
            from android.permissions import Permission, request_permissions
        except ImportError:
            if callback:
                callback(True)
            return False
        perms = [Permission.WRITE_EXTERNAL_STORAGE]
        if callback is None:
            request_permissions(perms)
            return True
        request_permissions(perms,
                            lambda _p, results: callback(bool(results)
                                                         and any(results)))
        return True

    # --- подписка на ответ системы -----------------------------------------
    def _bind(self):
        if self._bound:
            return
        from android import activity as android_activity
        android_activity.bind(on_activity_result=self._on_result)
        self._bound = True

    def _finish(self, name, error=""):
        cb, self._callback = self._callback, None
        self.error = error
        if cb:
            cb(name, error)

    def _on_result(self, request, result, intent):
        if request not in (REQUEST_CAPTURE, REQUEST_PICK):
            return
        try:
            from jnius import autoclass
            Activity = autoclass("android.app.Activity")
            if result != Activity.RESULT_OK:
                self._drop_placeholder()
                self._finish(None, "")            # человек передумал — не ошибка
                return
            uri = self._uri if request == REQUEST_CAPTURE else (
                intent.getData() if intent is not None else None)
            if uri is None:
                self._finish(None, "система не вернула снимок")
                return
            name = self._store(uri)
            if request == REQUEST_CAPTURE:
                self._drop_placeholder()
            self._finish(name, "" if name else "снимок не прочитался")
        except Exception as e:                                    # noqa: BLE001
            self._finish(None, str(e)[:80])

    # --- перенос снимка к себе ---------------------------------------------
    def _store(self, uri) -> str | None:
        """Читает содержимое по content-ссылке и кладёт к себе, пережимая."""
        from jnius import autoclass
        BitmapFactory = autoclass("android.graphics.BitmapFactory")
        Options = autoclass("android.graphics.BitmapFactory$Options")
        CompressFormat = autoclass("android.graphics.Bitmap$CompressFormat")
        FileOutputStream = autoclass("java.io.FileOutputStream")
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        resolver = activity.getContentResolver()

        probe = Options()
        probe.inJustDecodeBounds = True
        stream = resolver.openInputStream(uri)
        try:
            BitmapFactory.decodeStream(stream, None, probe)
        finally:
            stream.close()
        if probe.outWidth <= 0:
            return None

        opts = Options()
        opts.inSampleSize = _sample_size(probe.outWidth, probe.outHeight, MAX_SIDE)
        stream = resolver.openInputStream(uri)
        try:
            bitmap = BitmapFactory.decodeStream(stream, None, opts)
        finally:
            stream.close()
        if bitmap is None:
            return None

        name = new_name()
        out = FileOutputStream(path_for(name))
        try:
            bitmap.compress(CompressFormat.JPEG, JPEG_QUALITY, out)
        finally:
            out.close()
            bitmap.recycle()
        return name if exists(name) else None

    def _drop_placeholder(self):
        """Убирает запись из галереи: снимок уже лежит у нас.

        Оставлять его в общей галерее нельзя — она синхронизируется в облако
        вместе с координатами съёмки, а грибные места на то и грибные.
        """
        if self._uri is None:
            return
        try:
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            activity.getContentResolver().delete(self._uri, None, None)
        except Exception:                                         # noqa: BLE001
            pass
        self._uri = None

    # --- действия -----------------------------------------------------------
    def capture(self, callback) -> bool:
        """Открывает камеру. callback(имя_файла|None, текст_ошибки)."""
        if not self.available():
            callback(None, "камера доступна только на телефоне")
            return False
        try:
            from jnius import autoclass, cast
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            Intent = autoclass("android.content.Intent")
            MediaStore = autoclass("android.provider.MediaStore")
            Images = autoclass("android.provider.MediaStore$Images$Media")
            ContentValues = autoclass("android.content.ContentValues")

            values = ContentValues()
            values.put("_display_name", new_name())
            values.put("mime_type", "image/jpeg")
            uri = activity.getContentResolver().insert(
                Images.EXTERNAL_CONTENT_URI, values)
            if uri is None:
                callback(None, "не удалось подготовить файл для снимка")
                return False
            self._uri = uri

            intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
            intent.putExtra(MediaStore.EXTRA_OUTPUT, cast("android.os.Parcelable", uri))
            self._callback = callback
            self._bind()
            activity.startActivityForResult(intent, REQUEST_CAPTURE)
            return True
        except Exception as e:                                    # noqa: BLE001
            self._callback = None
            callback(None, str(e)[:80])
            return False

    def pick(self, callback) -> bool:
        """Открывает выбор снимка из галереи."""
        if not self.available():
            callback(None, "галерея доступна только на телефоне")
            return False
        try:
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            Intent = autoclass("android.content.Intent")

            intent = Intent(Intent.ACTION_GET_CONTENT)
            intent.setType("image/*")
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            self._uri = None
            self._callback = callback
            self._bind()
            activity.startActivityForResult(intent, REQUEST_PICK)
            return True
        except Exception as e:                                    # noqa: BLE001
            self._callback = None
            callback(None, str(e)[:80])
            return False
