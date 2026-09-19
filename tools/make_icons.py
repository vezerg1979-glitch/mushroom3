# -*- coding: utf-8 -*-
"""Сборка значка и заставки из исходной картинки.

Значок и заставка делаются из одного файла, но по-разному, и причина не в
красоте. Значок на рабочем столе телефона занимает 48 dp — примерно ноготь
большого пальца. Надпись «НАВИГАТОР ГРИБНИКА» на таком размере не читается
даже как надпись: получается серая полоса, отъедающая четверть площади у
единственной картинки, которую там вообще можно узнать. Плюс лончеры
обрезают значок под свою форму — круг, скруглённый квадрат, каплю, — и
всё, что у краёв, срезается. Поэтому в значок идёт только гриб, вырезанный
с запасом от краёв.

Заставка показывается на весь экран и живёт полторы секунды: здесь надпись
как раз к месту — человек видит, что запустилось именно то, что он нажал.
"""

from PIL import Image, ImageFilter

import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "icon-source.jpg")      # исходная картинка, как прислана
OUT = os.path.join(HERE, "..", "android")

# Границы, найденные по яркости: рамка карточки занимает первые ~10 пикселей,
# белая надпись начинается на 545-й строке. Гриб с мхом лежит между ними.
CARD = (10, 11, 686, 690)
CONTENT_BOTTOM = 536
MUSHROOM_CX = 350          # центр гриба по горизонтали; звезда компаса правее


def build_icon(side, safe=0.88):
    """Квадратный значок: гриб с мхом, без надписи, с запасом от краёв.

    safe — доля стороны, внутри которой держится содержимое. Лончер,
    обрезающий значок в круг, съедает по краям примерно десятую часть; при
    полном вылете за край у шляпки отрезало бы бока.
    """
    im = Image.open(SRC).convert("RGB")
    box = CONTENT_BOTTOM - CARD[1]                 # сторона квадрата-исходника
    left = MUSHROOM_CX - box // 2
    crop = im.crop((left, CARD[1], left + box, CONTENT_BOTTOM))

    # Фон под запас по краям берётся из самой картинки: размытая и слегка
    # затемнённая копия. Заливка ровным цветом дала бы видимую рамку —
    # у исходника фон с виньеткой, а не плоский зелёный.
    bg = crop.resize((side, side), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(side * 0.06))
    bg = Image.blend(bg, Image.new("RGB", (side, side), (26, 34, 26)), 0.25)

    inner = int(side * safe)
    fg = crop.resize((inner, inner), Image.LANCZOS)
    fg = fg.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=3))

    # Мягкая маска: края вставки растворяются в фоне, стыка не видно.
    mask = Image.new("L", (inner, inner), 0)
    pad = max(2, inner // 40)
    mask.paste(255, (pad, pad, inner - pad, inner - pad))
    mask = mask.filter(ImageFilter.GaussianBlur(pad))

    off = (side - inner) // 2
    bg.paste(fg, (off, off), mask)
    return bg


def build_presplash(side=1024, bg=(23, 26, 31)):
    """Заставка: картинка целиком, вместе с надписью, на тёмном поле.

    Поле того же цвета, что углы исходника, и тем же цветом задаётся
    android.presplash_color: экран телефона вытянутый, а картинка
    квадратная, и полосы сверху и снизу иначе будут белыми.
    """
    im = Image.open(SRC).convert("RGB")
    scale = min(side / im.width, side / im.height)
    art = im.resize((round(im.width * scale), round(im.height * scale)),
                    Image.LANCZOS)
    canvas = Image.new("RGB", (side, side), bg)
    canvas.paste(art, ((side - art.width) // 2, (side - art.height) // 2))
    return canvas


if __name__ == "__main__":
    icon = build_icon(512)
    icon.save(os.path.join(OUT, "icon.png"))
    icon.resize((192, 192), Image.LANCZOS).save(os.path.join(OUT, "icon-192.png"))
    build_presplash().save(os.path.join(OUT, "presplash.png"))
    print("готово: icon.png, icon-192.png, presplash.png")
