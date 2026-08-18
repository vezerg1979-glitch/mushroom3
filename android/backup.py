# -*- coding: utf-8 -*-
"""
backup.py — резервная копия наблюдений: архив, отправка и восстановление.

Зачем. Журнал, треки, снимки находок и места живут только на телефоне и
больше нигде. Утонувший в болоте или потерянный телефон уносит с собой годы
наблюдений, и восстановить их нельзя ничем: это не переписка, которая лежит
на сервере, а единственный экземпляр. Причём ценность данных растёт со
временем — на пятый сезон журнал стоит дороже самого телефона.

Что кладётся в архив. Всё, что человек накопил: journal.csv, походы, места,
настройки и, по желанию, снимки. Не кладётся то, что восстановится само:
кэш погоды, кэш карты, служебный лог и незаконченный трек.

Почему два вида архива. Записи весят килобайты, снимки — сотни мегабайт.
Почтовое вложение обычно ограничено 25 МБ, поэтому «только записи» — не
экономия, а единственный вариант, доходящий по почте. Полный архив имеет
смысл сохранять на носитель или в облако.

Про «отправку на почту». Приложение НЕ отправляет письма само, и это
намеренно. Чтобы отправить письмо напрямую, нужен либо пароль от почтового
ящика человека на телефоне (Gmail и Яндекс такие входы давно закрыли, а
хранить чужой пароль — плохая идея сама по себе), либо свой сервер-ретранслятор,
через который пойдут чужие координаты грибных мест. Вместо этого архив
передаётся системе: открывается обычное окно «Поделиться», где человек
выбирает свою почтовую программу, облако или мессенджер. Письмо уходит из
его собственного ящика, приложение к нему не притрагивается.

Про ссылку на файл. FileProvider в сборке нет (см. photos.py — там та же
история), а Uri.fromFile начиная с Android 7 бросает FileUriExposedException.
Поэтому архив пишется в MediaStore, в общий каталог «Загрузки»: оттуда
система сама даёт content-ссылку, годную и для вложения в письмо, и для
файлового менеджера. Заодно это и есть «сохранение на носитель»: файл
лежит в «Загрузках», его видно из любого проводника и с компьютера по USB.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import zipfile

import places as places_mod

MANIFEST = "manifest.json"
FORMAT = 1

# Что переносим. Порядок важен только для читаемости архива.
RECORDS = ("journal.csv", "places.json", "prefs.json", "tilesource.json",
           "calibration.json")
RECORD_DIRS = ("tracks",)
PHOTO_DIR = "photos"

# Что НЕ переносим: восстановится само или относится к текущему моменту.
SKIP_DIRS = ("cache",)
SKIP_FILES = ("track_live.ndjson", "track_status.json", "service.log")

# Предел почтового вложения у большинства служб. Не запрет, а повод
# предупредить: архив со снимками обычно больше и по почте не уйдёт.
MAIL_LIMIT_MB = 25.0

# Код запроса к системе. Не должен совпадать с кодами photos.py, иначе один
# экран получит ответ, предназначенный другому.
REQUEST_PICK = 0x6247


def data_dir() -> str:
    return places_mod.data_dir()


# --------------------------------------------------------------------------- #
#  Что войдёт в архив
# --------------------------------------------------------------------------- #

def _walk_files(root: str):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name in SKIP_FILES:
                continue
            full = os.path.join(base, name)
            yield full, os.path.relpath(full, root).replace(os.sep, "/")


def contents(with_photos: bool = True, root: str = None) -> dict:
    """Что и сколько уйдёт в архив — до того, как его собирать.

    Считается заранее по той же причине, что и в tiles.py: человек должен
    видеть объём ДО нажатия, а не узнавать о двухстах мегабайтах из
    сообщения почтовой программы.
    """
    root = root or data_dir()
    records = photos = 0
    rbytes = pbytes = 0
    for full, rel in _walk_files(root):
        try:
            size = os.path.getsize(full)
        except OSError:
            continue
        if rel.startswith(PHOTO_DIR + "/"):
            photos += 1
            pbytes += size
        else:
            records += 1
            rbytes += size
    total = rbytes + (pbytes if with_photos else 0)
    return {"records": records, "record_bytes": rbytes,
            "photos": photos, "photo_bytes": pbytes,
            "files": records + (photos if with_photos else 0),
            "bytes": total, "megabytes": total / (1024.0 * 1024.0),
            "fits_mail": total / (1024.0 * 1024.0) <= MAIL_LIMIT_MB}


def size_text(nbytes: float) -> str:
    if nbytes < 1024:
        return f"{int(nbytes)} Б"
    if nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.0f} КБ"
    return f"{nbytes / (1024 * 1024):.1f} МБ".replace(".", ",")


def archive_name(when: float = None) -> str:
    """Имя файла архива. Латиницей и с датой.

    Латиницей намеренно: файл поедет в почту, на компьютер, во флешку, и на
    этом пути кириллица в имени превращается в кракозябры чаще, чем хочется.
    Дата в имени — чтобы копии не затирали друг друга и было видно, какая
    свежее.
    """
    stamp = time.strftime("%Y-%m-%d_%H%M", time.localtime(when or time.time()))
    return f"gribnik-backup-{stamp}.zip"


# --------------------------------------------------------------------------- #
#  Сборка
# --------------------------------------------------------------------------- #

def create(dst: str, with_photos: bool = True, root: str = None,
           on_progress=None) -> dict:
    """Собирает архив в dst. Возвращает то же, что contents().

    Пишется через временный файл: обрыв на середине (кончилось место,
    убили приложение) не должен оставить обрубок с правильным именем —
    человек примет его за копию и обнаружит правду, когда будет поздно.
    """
    root = root or data_dir()
    info = contents(with_photos, root)
    items = [(full, rel) for full, rel in _walk_files(root)
             if with_photos or not rel.startswith(PHOTO_DIR + "/")]
    tmp = dst + ".part"
    done = missing = 0
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(MANIFEST, json.dumps({
                "format": FORMAT,
                "created": time.time(),
                "app": "navigator-gribnika",
                "with_photos": bool(with_photos),
                "files": info["files"],
            }, ensure_ascii=False))
            for full, rel in items:
                try:
                    z.write(full, rel)
                except (OSError, ValueError):
                    # Разница принципиальная. Исчезнувший файл — мелочь:
                    # снимок могли удалить между подсчётом и записью, копия
                    # от этого не портится. Любая другая ошибка (кончилось
                    # место, отобрали доступ) означает НЕПОЛНУЮ копию, и
                    # проглотить её нельзя: человек получит архив, который
                    # выглядит целым, а недостачу обнаружит при
                    # восстановлении, когда исходников уже нет.
                    if not os.path.exists(full):
                        missing += 1
                        continue
                    raise
                done += 1
                if on_progress and done % 20 == 0:
                    on_progress(done, len(items))
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    info["path"] = dst
    info["missing"] = missing
    return info


# --------------------------------------------------------------------------- #
#  Восстановление
# --------------------------------------------------------------------------- #

class NotOurs(ValueError):
    """Файл не похож на копию этого приложения."""


def inspect(path: str) -> dict:
    """Что внутри архива, до распаковки.

    Открывать что попало нельзя: zip из интернета может содержать пути вида
    ../../ и разложить свои файлы куда угодно. Здесь заодно и проверка на
    «это вообще наша копия», чтобы человек не восстановил поверх журнала
    архив с фотографиями с отпуска.
    """
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if MANIFEST not in names:
                raise NotOurs("в архиве нет описания: это не копия наблюдений")
            man = json.loads(z.read(MANIFEST).decode("utf-8"))
    except zipfile.BadZipFile:
        raise NotOurs("файл не читается как архив")
    if man.get("app") != "navigator-gribnika":
        raise NotOurs("архив от другого приложения")
    if int(man.get("format", 0)) > FORMAT:
        raise NotOurs("копия от более новой версии — обновите приложение")
    walks = sum(1 for n in names if n.startswith("tracks/") and n.endswith(".json"))
    photos = sum(1 for n in names if n.startswith(PHOTO_DIR + "/"))
    man.update({"walks": walks, "photos": photos, "names": names})
    return man


def _safe(rel: str) -> bool:
    """Путь внутри архива, который не пытается вылезти наружу."""
    if not rel or rel.endswith("/"):
        return False
    if rel.startswith("/") or ".." in rel.split("/"):
        return False
    if os.path.isabs(rel) or ":" in rel:
        return False
    return rel == MANIFEST or rel in RECORDS or rel.startswith(
        tuple(d + "/" for d in RECORD_DIRS + (PHOTO_DIR,)))


def restore(path: str, root: str = None, replace: bool = False) -> dict:
    """Разворачивает копию в каталог данных.

    По умолчанию НИЧЕГО не затирает: файл, который уже есть, пропускается.
    Восстановление обычно идёт на новый телефон, но случается и поверх
    живых данных — и человек, нажавший не ту кнопку, не должен потерять
    сегодняшний поход из-за прошлогодней копии. Настройки и журнал при
    слиянии остаются те, что на телефоне: replace=True для случая, когда
    человек сознательно хочет вернуть всё как было.
    """
    root = root or data_dir()
    man = inspect(path)
    added = skipped = 0
    with zipfile.ZipFile(path) as z:
        for rel in man["names"]:
            if rel == MANIFEST or not _safe(rel):
                continue
            dst = os.path.join(root, *rel.split("/"))
            if os.path.exists(dst) and not replace:
                skipped += 1
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with z.open(rel) as src, open(dst, "wb") as out:
                out.write(src.read())
            added += 1
    return {"added": added, "skipped": skipped,
            "walks": man.get("walks", 0), "photos": man.get("photos", 0)}


# --------------------------------------------------------------------------- #
#  Android: сохранение в «Загрузки» и передача системе
# --------------------------------------------------------------------------- #

def on_android() -> bool:
    try:
        from jnius import autoclass
        autoclass("org.kivy.android.PythonActivity")
        return True
    except Exception:                                             # noqa: BLE001
        return False


def _sdk_int() -> int:
    try:
        from jnius import autoclass
        return autoclass("android.os.Build$VERSION").SDK_INT
    except Exception:                                             # noqa: BLE001
        return 0


def publish(path: str, mime: str = "application/zip"):
    """Кладёт файл в общие «Загрузки». Возвращает content-ссылку или None.

    Начиная с Android 10 это делается через MediaStore и не требует ни
    одного разрешения. На более старых нужен доступ к памяти, и там же
    неприятность посерьёзнее: ссылка вида file:// с Android 7 в чужую
    программу не передаётся, поэтому на таких аппаратах остаётся только
    сохранение — файл кладётся в «Загрузки», а отправить его человек может
    из проводника.
    """
    from jnius import autoclass, cast

    activity = autoclass("org.kivy.android.PythonActivity").mActivity
    if _sdk_int() >= 29:
        MediaStore = autoclass("android.provider.MediaStore")
        Downloads = autoclass("android.provider.MediaStore$Downloads")
        ContentValues = autoclass("android.content.ContentValues")
        values = ContentValues()
        values.put("_display_name", os.path.basename(path))
        values.put("mime_type", mime)
        values.put("relative_path", "Download")
        resolver = activity.getContentResolver()
        uri = resolver.insert(Downloads.EXTERNAL_CONTENT_URI, values)
        if uri is None:
            return None
        out = resolver.openOutputStream(uri)
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(262144)
                    if not chunk:
                        break
                    out.write(chunk)
        finally:
            out.close()
        return uri

    Environment = autoclass("android.os.Environment")
    folder = Environment.getExternalStoragePublicDirectory(
        Environment.DIRECTORY_DOWNLOADS).getAbsolutePath()
    dst = os.path.join(folder, os.path.basename(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "rb") as src, open(dst, "wb") as out:
        out.write(src.read())
    return None                     # ссылки нет: отправить сможет проводник


def pick(callback):
    """Просит систему дать файл копии. callback(path, error) — из потока Android.

    Файл копируется во временный каталог и уже оттуда читается: content-
    ссылка может указывать куда угодно, вплоть до облака, и открывать её
    как обычный путь нельзя.
    """
    try:
        from jnius import autoclass
        from android import activity as android_activity
    except ImportError:
        callback(None, "выбор файла доступен только на телефоне")
        return False

    Intent = autoclass("android.content.Intent")
    activity = autoclass("org.kivy.android.PythonActivity").mActivity

    def on_result(request, result, intent):
        if request != REQUEST_PICK:
            return
        android_activity.unbind(on_activity_result=on_result)
        try:
            Activity = autoclass("android.app.Activity")
            if result != Activity.RESULT_OK or intent is None:
                callback(None, "")               # передумал — не ошибка
                return
            uri = intent.getData()
            if uri is None:
                callback(None, "система не вернула файл")
                return
            stream = activity.getContentResolver().openInputStream(uri)
            dst = os.path.join(tempfile.gettempdir(), "restore.zip")
            with open(dst, "wb") as out:
                while True:
                    chunk = stream.read(262144)
                    if chunk is None or len(chunk) <= 0:
                        break
                    out.write(bytes(bytearray(chunk)))
            stream.close()
            callback(dst, "")
        except Exception as e:                                    # noqa: BLE001
            callback(None, str(e)[:80])

    android_activity.bind(on_activity_result=on_result)
    intent = Intent(Intent.ACTION_GET_CONTENT)
    intent.setType("application/zip")
    intent.addCategory(Intent.CATEGORY_OPENABLE)
    activity.startActivityForResult(intent, REQUEST_PICK)
    return True


def share(uri, subject: str = "Наблюдения грибника", text: str = "",
          mime: str = "application/zip", title: str = "Куда отправить") -> bool:
    """Отдаёт архив системе: почта, облако, мессенджер — на выбор человека.

    Именно выбор, а не «отправить на почту»: приложение не знает ни ящика
    человека, ни пароля от него, и знать не должно. Письмо уходит из его
    собственной почтовой программы, с его адреса, куда он сам укажет.
    """
    if uri is None:
        return False
    from jnius import autoclass, cast

    Intent = autoclass("android.content.Intent")
    String = autoclass("java.lang.String")
    activity = autoclass("org.kivy.android.PythonActivity").mActivity

    def chars(value):
        """Python-строка -> java.lang.CharSequence.

        Через java.lang.String, а не напрямую: cast превращает один Java-
        объект в другой и питоновскую строку не принимает вовсе —
        «Cannot convert str to jnius.JavaClass». Ошибка вылезает только на
        телефоне, потому что на компьютере jnius нет.
        """
        return cast("java.lang.CharSequence", String(value))

    intent = Intent(Intent.ACTION_SEND)
    intent.setType(mime)
    intent.putExtra(Intent.EXTRA_STREAM, cast("android.os.Parcelable", uri))
    intent.putExtra(Intent.EXTRA_SUBJECT, chars(subject))
    if text:
        intent.putExtra(Intent.EXTRA_TEXT, chars(text))
    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    chooser = Intent.createChooser(intent, chars(title))
    activity.startActivity(chooser)
    return True
