# -*- coding: utf-8 -*-
"""
atlas.py — эталонные изображения грибов и признаки, по которым их узнают.

Зачем. В окне «Что нашли?» одиннадцать одинаковых кнопок с подписями. В лесу
человек читает их сквозь блики, в перчатке, с корзиной в другой руке — и
промахивается видом. Картинка узнаётся быстрее слова, поэтому у каждой строки
слева стоит эталон, а по кнопке «крупно» открывается карточка вида: рисунок
во весь экран, признаки и двойники.

Почему рисунок, а не фотография. Фотография в APK — это чужое авторское право
и лишние мегабайты, а главное — одна фотография всё равно не покрывает
разброс: тот же белый бывает и светлым колосовиком, и почти чёрным
листопадником. Схематичный силуэт с честным цветом на такое не претендует и
не создаёт ложной уверенности: он отвечает на вопрос «на какую кнопку жать»,
а не «съедобно ли это». Определяют гриб по признакам из карточки, не по
картинке — поэтому текст рядом с рисунком обязателен, а не украшение.

Свои фотографии подставляются без правки кода: положите файл в
`assets/species/<slug>.jpg` (slug — из таблицы SLUG ниже), и виджет покажет
его вместо рисунка. Имена латиницей намеренно: кириллица в путях внутри APK
и на разных прошивках ведёт себя по-разному.

Геометрия отделена от Kivy, как в icons.py: так её проверяет тест на
компьютере, где ни экрана, ни OpenGL нет. Все примитивы задаются в квадрате
0..1 (начало отсчёта — левый нижний угол) и переносятся в пиксели функцией
shapes().
"""

from __future__ import annotations

import os

# --------------------------------------------------------------------------- #
#  Примитивы
# --------------------------------------------------------------------------- #
#
#   ("poly", цвет, (x1, y1, ... xn, yn))   — залитый ВЫПУКЛЫЙ многоугольник
#   ("dome", цвет, cx, cy, rx, ry)         — верхняя половина эллипса (шляпка)
#   ("ellipse", цвет, cx, cy, rx, ry)      — залитый эллипс
#   ("line", цвет, (x1, y1, ... ), lw)     — ломаная толщиной lw
#
# Многоугольники рисуются веером треугольников из центра тяжести, поэтому они
# обязаны быть выпуклыми: у невыпуклого веер вылезет за контур. Это проверяет
# тест, а не глаз — на телефоне такая ошибка выглядит как лишний угол у
# шляпки, и её легко принять за задуманное.

# Цвета не берутся из palette: там цвета интерфейса, а здесь — окраска гриба.
# Совпадать им не обязательно, а вот меняться вместе (правишь кнопку — уехал
# цвет шляпки) точно не нужно.

GROUND = "#D9DCCC"      # подстилка под грибом
WOOD = "#6B5A45"        # древесина: пни и стволы
WOOD_DARK = "#4E4133"

FLESH = "#F1EDE0"       # светлая ножка
FLESH_WARM = "#EDE3C8"  # ножка с кремовым оттенком
SCALE = "#3D3C36"       # чешуйки на ножке подберёзовика и подосиновика
PORE_WHITE = "#F0EAD6"  # трубчатый слой белых грибов
PORE_YELLOW = "#E2C765"  # трубчатый слой маслёнка
GILL = "#EFEADB"        # пластинки
EDGE = "#C0BAA1"        # контур светлой мякоти на светлой подложке


def _dome(color, cx, cy, rx, ry):
    return ("dome", color, cx, cy, rx, ry)


def _stem(color, cx, w_bot, w_top, y0, y1):
    """Ножка-трапеция. Выпуклая при любых ширинах."""
    return ("poly", color, (cx - w_bot / 2, y0, cx + w_bot / 2, y0,
                            cx + w_top / 2, y1, cx - w_top / 2, y1))


def _barrel(color, cx, w_bot, w_mid, w_top, y0, y1, at=0.45):
    """Ножка бочонком: шестиугольник с утолщением на высоте at.

    Выпуклый, пока w_mid не меньше обеих крайних ширин — за этим следит тест.
    """
    ym = y0 + (y1 - y0) * at
    return ("poly", color, (cx - w_bot / 2, y0, cx + w_bot / 2, y0,
                            cx + w_mid / 2, ym, cx + w_top / 2, y1,
                            cx - w_top / 2, y1, cx - w_mid / 2, ym))


def _funnel(color, tip_x, tip_top, tip_bot, mid_top, mid_bot, cx=0.5):
    """Половина воронки: клин от середины гриба к приподнятому краю.

    Воронку нельзя задать одним многоугольником: провал посередине делает
    контур невыпуклым, и веер треугольников вылез бы наружу. Поэтому она
    склеена из двух клиньев, левого и правого, а функция возвращает один.

    У края клин не сходится в точку: острый край читается как лист или
    птица, а у гриба мякоть имеет толщину.
    """
    return ("poly", color, (tip_x, tip_top, cx, mid_top, cx, mid_bot,
                            tip_x, tip_bot))


def _ribs(tip_x, tip_top, tip_bot, mid_top, mid_bot, color, cx=0.5,
          count=4, lw=0.012):
    """Складки поперёк клина: отрезки между верхней и нижней кромками."""
    out = []
    for i in range(1, count + 1):
        t = i / (count + 1.0)
        out.append(("line", color,
                    (cx + (tip_x - cx) * t, mid_top + (tip_top - mid_top) * t,
                     cx + (tip_x - cx) * t, mid_bot + (tip_bot - mid_bot) * t),
                    lw))
    return out


def _outline(item, color=EDGE, lw=0.010):
    """Контур многоугольника.

    Нужен светлым ножкам: цвет мякоти почти совпадает с подложкой кнопки, и
    без контура у гриба в карточке видна одна шляпка, висящая в воздухе.
    """
    pts = item[2]
    return ("line", color, tuple(pts) + (pts[0], pts[1]), lw)


def _scales(cx, y_list, half, color=SCALE, lw=0.018):
    """Чешуйки на ножке: короткие штрихи парами по бокам."""
    out = []
    for y in y_list:
        out.append(("line", color, (cx - half, y, cx - half * 0.25, y), lw))
        out.append(("line", color, (cx + half * 0.25, y, cx + half, y), lw))
    return out


def _ground():
    return [("line", GROUND, (0.10, 0.085, 0.90, 0.085), 0.022)]


# --------------------------------------------------------------------------- #
#  Виды
# --------------------------------------------------------------------------- #
#
# Порядок примитивов = порядок рисования. Ножка идёт первой: её верх должна
# закрыть шляпка, иначе светлый прямоугольник торчит из тёмной шапки.

def _belyi():
    """Белый гриб: толстый бочонок и тяжёлая полушаровидная шляпка."""
    stem = _barrel(FLESH_WARM, 0.5, 0.30, 0.34, 0.22, 0.10, 0.56)
    return _ground() + [
        stem, _outline(stem),
        ("ellipse", PORE_WHITE, 0.5, 0.545, 0.40, 0.065),
        _dome("#8B5A2B", 0.5, 0.55, 0.42, 0.27),
        _dome("#A2703C", 0.42, 0.57, 0.24, 0.18),          # блик сверху слева
    ]


def _podberezovik():
    """Подберёзовик: длинная тонкая ножка в тёмных штрихах."""
    stem = _stem(FLESH, 0.5, 0.21, 0.13, 0.10, 0.66)
    return _ground() + [
        stem, _outline(stem),
    ] + _scales(0.5, (0.20, 0.31, 0.42, 0.53), 0.075) + [
        ("ellipse", PORE_WHITE, 0.5, 0.645, 0.31, 0.055),
        _dome("#A9744F", 0.5, 0.65, 0.33, 0.24),
        _dome("#BC8A66", 0.43, 0.67, 0.19, 0.15),
    ]


def _podosinovik():
    """Подосиновик: оранжевая шляпка напёрстком, ножка книзу толще."""
    stem = _stem(FLESH, 0.5, 0.28, 0.19, 0.10, 0.56)
    return _ground() + [
        stem, _outline(stem),
    ] + _scales(0.5, (0.19, 0.29, 0.39, 0.49), 0.105) + [
        ("ellipse", PORE_WHITE, 0.5, 0.545, 0.36, 0.06),
        _dome("#D2601A", 0.5, 0.55, 0.38, 0.31),
        _dome("#E0762F", 0.43, 0.57, 0.22, 0.21),
    ]


def _lisichka():
    """Лисичка: воронка одного цвета с ножкой, складки сбегают вниз.

    Воронка склеена из двух треугольников — левого и правого. Одним
    многоугольником её не задать: провал в середине делает контур
    невыпуклым, и веер треугольников вылез бы за край.
    """
    body = "#E8A317"
    fold = "#C0800F"
    top, bot = 0.54, 0.30
    return _ground() + [
        _stem("#EFB63A", 0.5, 0.19, 0.36, 0.10, 0.40),
        _funnel(body, 0.14, 0.72, 0.56, top, bot),
        _funnel(body, 0.86, 0.72, 0.56, top, bot),
    ] + _ribs(0.14, 0.72, 0.56, top, bot, fold) \
      + _ribs(0.86, 0.72, 0.56, top, bot, fold) + [
        # Складки не обрываются у шляпки, а сбегают на ножку — по этому
        # признаку лисичку и отличают от ложной.
        ("line", fold, (0.45, 0.36, 0.47, 0.13), 0.012),
        ("line", fold, (0.55, 0.36, 0.53, 0.13), 0.012),
    ]


def _maslenok():
    """Маслёнок: плоская блестящая шляпка и кольцо на ножке."""
    stem = _stem(FLESH_WARM, 0.5, 0.21, 0.23, 0.10, 0.50)
    return _ground() + [
        stem, _outline(stem),
        ("ellipse", "#C7AE6E", 0.5, 0.40, 0.135, 0.032),   # кольцо
        ("ellipse", PORE_YELLOW, 0.5, 0.505, 0.38, 0.065),
        _dome("#B8860B", 0.5, 0.51, 0.40, 0.22),
        _dome("#D3A52A", 0.41, 0.53, 0.20, 0.14),          # слизистый блеск
    ]


def _openok():
    """Опёнок осенний: пучок на валеже, у каждого кольцо на ножке.

    Пучок и древесина — половина признака. Одиночный гриб в этом рисунке был
    бы неотличим от десятка других мелких шляпочных, а на пне рядом друг с
    другом их узнают с трёх шагов.
    """
    cap = "#7B4B2A"
    out = [
        ("poly", WOOD, (0.06, 0.10, 0.94, 0.10, 0.94, 0.24, 0.06, 0.24)),
        ("line", WOOD_DARK, (0.10, 0.155, 0.90, 0.145), 0.014),
    ]
    for cx, top, scale in ((0.28, 0.62, 0.9), (0.50, 0.78, 1.0), (0.71, 0.56, 0.8)):
        rx = 0.155 * scale
        out += [
            _stem(FLESH_WARM, cx, 0.055, 0.045, 0.20, top),
            ("line", "#CBB78E", (cx - 0.055, top - 0.12, cx + 0.055, top - 0.12),
             0.022),                                        # кольцо
            ("ellipse", GILL, cx, top + 0.005, rx * 0.92, 0.028),
            _dome(cap, cx, top, rx, 0.115 * scale),
            _dome("#96613B", cx - rx * 0.28, top + 0.012, rx * 0.5, 0.075 * scale),
        ]
    return out


def _gruzd():
    """Груздь: белая воронка с мохнатым краем, ножка короткая и толстая.

    Бахрома по краю — то, чем настоящий груздь отличается от прочих белых
    млечников, поэтому она нарисована зубцами, а не намёком.
    """
    body = "#E9E4C6"
    edge = "#8E9370"          # белое на светлом фоне без обводки не видно
    top, bot = 0.52, 0.33
    stem = _stem(body, 0.5, 0.28, 0.32, 0.10, 0.40)
    left = _funnel(body, 0.07, 0.62, 0.54, top, bot)
    right = _funnel(body, 0.93, 0.62, 0.54, top, bot)
    out = _ground() + [
        stem, _outline(stem, edge, 0.012),
        left, right,
        _outline(left, edge, 0.012), _outline(right, edge, 0.012),
    ]
    # Бахрома по краю: ею настоящий груздь и отличается от прочих млечников,
    # поэтому она нарисована зубцами, а не намёком.
    for dist in (0.41, 0.35, 0.29, 0.23):
        for side in (-1.0, 1.0):
            x = 0.5 + side * dist
            y = top + (0.62 - top) * (dist / 0.43)
            out.append(("line", edge, (x, y, x + side * 0.015, y + 0.055), 0.014))
    return out


def _syroezhka():
    """Сыроежка: плоская цветная шляпка, белая ломкая ножка, пластинки."""
    stem = _stem("#F4F2E9", 0.5, 0.19, 0.20, 0.10, 0.52)
    return _ground() + [
        stem, _outline(stem),
        ("ellipse", GILL, 0.5, 0.525, 0.38, 0.055),
    ] + [
        ("line", "#C9C2AC", (0.5, 0.495, 0.5 + dx, 0.495), 0.012)
        for dx in (-0.34, -0.24, -0.14, 0.14, 0.24, 0.34)
    ] + [
        _dome("#C0504D", 0.5, 0.545, 0.40, 0.19),
        _dome("#CE6663", 0.41, 0.56, 0.20, 0.12),
    ]


def _veshenka():
    """Вешенка: черепица боковых шляпок на стволе, ножки почти нет."""
    body = "#6B8E9E"
    out = [
        ("poly", WOOD, (0.06, 0.06, 0.24, 0.06, 0.24, 0.94, 0.06, 0.94)),
        ("line", WOOD_DARK, (0.16, 0.10, 0.16, 0.90), 0.014),
    ]
    for y, w, h in ((0.74, 0.50, 0.11), (0.48, 0.64, 0.135), (0.24, 0.44, 0.10)):
        left = 0.24
        right = left + w
        # Шляпка веером: у ствола почти без ножки, к краю широкая и обвисает.
        out.append(("poly", body, (left, y - h * 0.35, left + w * 0.35, y - h * 0.95,
                                   right - w * 0.20, y - h * 1.05,
                                   right, y - h * 0.50, right, y + h * 0.50,
                                   right - w * 0.25, y + h * 0.95,
                                   left + w * 0.30, y + h * 0.85,
                                   left, y + h * 0.35)))
        # Пластинки сбегают к точке прикрепления — этим вешенка и узнаётся.
        for k in (-0.5, 0.5):
            out.append(("line", "#8FA9B6",
                        (left + w * 0.30, y + k * h * 0.20,
                         right - 0.03, y + k * h * 0.75), 0.009))
    return out


def _smorchok():
    """Сморчок: ячеистая шляпка-конус, приросшая к светлой ножке."""
    head = "#7A6A55"
    pit = "#57493A"
    stem = _stem("#EFE8D3", 0.5, 0.28, 0.24, 0.10, 0.40)
    out = _ground() + [
        stem, _outline(stem),
        _dome(head, 0.5, 0.36, 0.21, 0.52),
    ]
    # Соты: три вертикальных ребра и четыре поперечных, сужаются кверху.
    out.append(("line", pit, (0.50, 0.40, 0.50, 0.86), 0.012))
    out.append(("line", pit, (0.40, 0.40, 0.44, 0.80), 0.012))
    out.append(("line", pit, (0.60, 0.40, 0.56, 0.80), 0.012))
    for y, half in ((0.46, 0.185), (0.57, 0.165), (0.68, 0.125), (0.78, 0.07)):
        out.append(("line", pit, (0.5 - half, y, 0.5 + half, y), 0.012))
    return out


def _strochok():
    """Строчок: бесформенная мозговидная шляпка, складки без ячеек.

    Мозг вместо сот — единственное, что отличает его от сморчка на глаз,
    поэтому силуэт нарочно комковатый и несимметричный.
    """
    body = "#9B7B5A"
    fold = "#7C6046"
    stem = _stem("#EFE8D3", 0.5, 0.30, 0.26, 0.10, 0.36)
    out = _ground() + [stem, _outline(stem)]
    # Каждая доля — светлое пятно с тенью, сдвинутой вниз-вправо. Так масса
    # получается комковатой сама по себе. Тени и блики отдельными пятнами
    # пробовал: симметричная пара сразу читается как глаза, а тень под ними
    # как улыбка, и гриб превращается в смайлик.
    lobes = ((0.50, 0.72, 0.17, 0.125), (0.31, 0.62, 0.16, 0.125),
             (0.70, 0.60, 0.155, 0.12), (0.44, 0.56, 0.18, 0.135),
             (0.62, 0.72, 0.13, 0.10), (0.50, 0.47, 0.21, 0.13))
    for cx, cy, rx, ry in lobes:
        out.append(("ellipse", fold, cx + 0.012, cy - 0.020, rx, ry))
        out.append(("ellipse", body, cx, cy, rx, ry))
    return out


PICTURES = {
    "белый": _belyi,
    "подберёзовик": _podberezovik,
    "подосиновик": _podosinovik,
    "лисичка": _lisichka,
    "маслёнок": _maslenok,
    "опёнок": _openok,
    "груздь": _gruzd,
    "сыроежка": _syroezhka,
    "вешенка": _veshenka,
    "сморчок": _smorchok,
    "строчок": _strochok,
}

# Латинские имена файлов для своих фотографий: см. photo_path().
SLUG = {
    "белый": "belyi",
    "подберёзовик": "podberezovik",
    "подосиновик": "podosinovik",
    "лисичка": "lisichka",
    "маслёнок": "maslenok",
    "опёнок": "openok",
    "груздь": "gruzd",
    "сыроежка": "syroezhka",
    "вешенка": "veshenka",
    "сморчок": "smorchok",
    "строчок": "strochok",
}


# --------------------------------------------------------------------------- #
#  Признаки и двойники
# --------------------------------------------------------------------------- #
#
# marks  — по чему узнают вид в руках, а не по общему виду издалека.
# twins  — с чем путают и чем двойник выдаёт себя. Пусто не бывает: если
#          опасных двойников нет, так и написано — молчание читается как
#          «никто не проверял».
# care   — что делать с грибом до сковороды, если это не очевидно.

WARNING = ("Рисунок схематичный: силуэт и цвет, а не фотография. "
           "Определяют гриб по признакам, а не по картинке. "
           "Сомневаетесь — не берите.")

FEATURES = {
    "белый": {
        "marks": [
            "Низ шляпки губчатый: белый, с возрастом жёлто-зеленоватый",
            "Ножка бочонком, по верху светлая сетка",
            "Мякоть на срезе остаётся белой",
        ],
        "twins": [
            "Жёлчный гриб: сетка на ножке тёмная, губка розовеет, "
            "мякоть горькая — крупинка на язык не оставляет сомнений",
        ],
    },
    "подберёзовик": {
        "marks": [
            "Шляпка серо-бурая, подушкой",
            "Ножка светлая, в тёмных продольных чешуйках",
            "Трубочки белые, при надавливании сереют",
        ],
        "twins": [
            "Жёлчный гриб: вместо чешуек тёмная сетка, губка розовеет, горчит",
        ],
        "care": "Мякоть рыхлая: старые экземпляры в корзине превращаются в кашу.",
    },
    "подосиновик": {
        "marks": [
            "Шляпка оранжево-красная, кожица нависает над краем",
            "Ножка белая с тёмными чешуйками, книзу толще",
            "Срез быстро синеет и чернеет — это нормально",
        ],
        "twins": [
            "Опасных двойников нет. Путают с подберёзовиком — ошибка без "
            "последствий",
        ],
    },
    "лисичка": {
        "marks": [
            "Весь гриб одного яично-жёлтого цвета, шляпка переходит в ножку",
            "Вместо пластинок толстые складки, сбегающие на ножку",
            "Мякоть плотная, рвётся волокнами; почти никогда не червивая",
        ],
        "twins": [
            "Ложная лисичка: окраска ярче, к центру рыжая, пластинки "
            "настоящие — тонкие и частые; растёт на подстилке и гнилой "
            "древесине. Не смертельна, но невкусна",
        ],
    },
    "маслёнок": {
        "marks": [
            "Шляпка слизистая, кожица снимается лоскутом",
            "На ножке кольцо — остаток покрывала",
            "Трубчатый слой мелкий, жёлтый",
        ],
        "twins": [
            "Перечный гриб: поры красно-бурые, кольца нет, вкус жгучий",
        ],
        "care": "Кожицу снимают до мытья, иначе гриб не удержать в руках.",
    },
    "опёнок": {
        "marks": [
            "Растёт пучками на древесине: пни, валеж, корни",
            "На ножке плёнчатое кольцо",
            "Шляпка в мелких чешуйках, пластинки кремовые, споровый порошок белый",
        ],
        "twins": [
            "Ложноопёнок серно-жёлтый и кирпично-красный: кольца нет, "
            "пластинки зеленовато- или серо-оливковые, вкус горький",
            "Галерина окаймлённая — смертельно ядовита. Мелкая, с кольцом, "
            "на гниющей хвойной древесине; отличается от опёнка мало",
        ],
        "care": "Берут только пучок с кольцом на ножке. Одиночный мелкий гриб "
                "с кольцом на трухлявом дереве оставляют на месте.",
    },
    "груздь": {
        "marks": [
            "Белая воронка, край подвёрнут и мохнатый — бахрома по кромке",
            "На изломе обильный белый млечный сок, на воздухе желтеет",
            "Растёт колониями, часто целиком под подстилкой",
        ],
        "twins": [
            "Скрипица и другие белые млечники: край голый, сок не желтеет. "
            "Не опасны, но и не грузди",
        ],
        "care": "Сок едкий: только в засол, после вымачивания в нескольких водах.",
    },
    "сыроежка": {
        "marks": [
            "Мякоть ломкая, как мел: ножка переламывается, а не гнётся",
            "Пластинки и ножка белые, шляпка любого цвета",
            "Ни кольца на ножке, ни мешочка у основания",
        ],
        "twins": [
            "Бледная поганка — смертельно ядовита: у неё кольцо на ножке и "
            "мешочек-вольва в земле. Светлую сыроежку выкапывают целиком и "
            "смотрят на основание, а не срезают",
        ],
    },
    "вешенка": {
        "marks": [
            "Черепица шляпок на стволах и пнях лиственных деревьев",
            "Ножка боковая или почти отсутствует",
            "Пластинки далеко сбегают на ножку, серовато-белые",
        ],
        "twins": [
            "Опасных двойников в средней полосе нет",
        ],
    },
    "сморчок": {
        "marks": [
            "Шляпка ячеистая, как соты, приросшая краем к ножке",
            "Гриб полый насквозь — проверяется разрезом вдоль",
            "Апрель-май: гари, старые сады, осинники",
        ],
        "twins": [
            "Строчок: шляпка складчатая и мозговидная, без правильных ячеек, "
            "внутри с перегородками",
        ],
        "care": "Отваривать 10-15 минут, отвар слить.",
    },
    "строчок": {
        "marks": [
            "Шляпка бесформенная, мозговидно-складчатая, ячеек нет",
            "Внутри камеры с перегородками, а не пустота",
            "Идёт раньше сморчка, у кромки сошедшего снега",
        ],
        "twins": [
            "Сморчок: правильные соты и сплошная полость внутри",
        ],
        "care": "Содержит гиромитрин. Яд не разрушается сушкой и не уходит "
                "с отваром полностью; во многих справочниках гриб числится "
                "ядовитым. Незнакомым его брать не стоит.",
    },
}


# --------------------------------------------------------------------------- #
#  Разбор примитивов
# --------------------------------------------------------------------------- #

def shapes(key: str, x: float, y: float, w: float, h: float) -> list:
    """Примитивы вида key, вписанные в прямоугольник (x, y, w, h).

    Пропорции квадратные: картинка вписывается по меньшей стороне и садится
    по центру. Иначе на широкой строке гриб растянуло бы в блин.
    """
    try:
        draw = PICTURES[key]
    except KeyError:
        raise ValueError(f"нет картинки для {key!r}; "
                         f"есть: {', '.join(sorted(PICTURES))}")
    side = min(w, h)
    ox = x + (w - side) / 2.0
    oy = y + (h - side) / 2.0

    def px(v):
        return ox + v * side

    def py(v):
        return oy + v * side

    out = []
    for item in draw():
        kind = item[0]
        if kind == "poly":
            _, color, pts = item
            moved = []
            for i in range(0, len(pts), 2):
                moved += [px(pts[i]), py(pts[i + 1])]
            out.append((kind, color, tuple(moved)))
        elif kind in ("dome", "ellipse"):
            _, color, cx, cy, rx, ry = item
            out.append((kind, color, px(cx), py(cy), rx * side, ry * side))
        elif kind == "line":
            _, color, pts, lw = item
            moved = []
            for i in range(0, len(pts), 2):
                moved += [px(pts[i]), py(pts[i + 1])]
            out.append((kind, color, tuple(moved), lw * side))
        else:
            raise ValueError(f"неизвестный примитив {kind!r}")
    return out


def plan(item: tuple) -> tuple:
    """Примитив -> (что рисовать, аргументы). Чистая функция, без Kivy.

    Прослойка сделана по тем же граблям, что и в icons.py: разбор кортежей
    по номерам полей однажды уже уронил экран похода в конструкторе. Здесь
    разбор идёт распаковкой, а тот же вызов делает тест на компьютере.

    Многоугольник превращается в веер треугольников из центра тяжести:
    Mesh с mode='triangle_fan' — единственный способ залить произвольную
    фигуру в Kivy без картинки.

    Толщина линии в Kivy задаётся половиной: width=1 рисует два пикселя.
    """
    kind = item[0]
    if kind == "poly":
        _, color, pts = item
        xs = pts[0::2]
        ys = pts[1::2]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        verts = [cx, cy, 0, 0]
        for i in range(0, len(pts), 2):
            verts += [pts[i], pts[i + 1], 0, 0]
        verts += [pts[0], pts[1], 0, 0]          # замыкающая вершина веера
        return ("mesh", color, {"vertices": verts,
                                "indices": list(range(len(verts) // 4)),
                                "mode": "triangle_fan"})
    if kind == "dome":
        _, color, cx, cy, rx, ry = item
        return ("ellipse", color, {"pos": (cx - rx, cy - ry),
                                   "size": (2 * rx, 2 * ry),
                                   "angle_start": -90, "angle_end": 90})
    if kind == "ellipse":
        _, color, cx, cy, rx, ry = item
        return ("ellipse", color, {"pos": (cx - rx, cy - ry),
                                   "size": (2 * rx, 2 * ry)})
    if kind == "line":
        _, color, pts, lw = item
        return ("line", color, {"points": list(pts), "width": lw / 2.0,
                                "cap": "round", "joint": "round"})
    raise ValueError(f"неизвестный примитив {kind!r}")


# --------------------------------------------------------------------------- #
#  Свои фотографии
# --------------------------------------------------------------------------- #

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "assets", "species")
EXTS = (".jpg", ".jpeg", ".png")


def photo_path(key: str):
    """Путь к своей фотографии вида или None, если её не положили.

    Проверка идёт файловой системой, а не списком в коде: человек кладёт
    файл в assets/species и пересобирает APK, ничего не правя.
    """
    slug = SLUG.get(key)
    if not slug:
        return None
    for ext in EXTS:
        path = os.path.join(ASSETS, slug + ext)
        if os.path.exists(path):
            return path
    return None


# --------------------------------------------------------------------------- #
#  Виджет
# --------------------------------------------------------------------------- #

try:                                                  # pragma: no cover
    from kivy.graphics import Color, Ellipse, Line, Mesh, RoundedRectangle
    from kivy.metrics import dp, sp
    from kivy.uix.behaviors import ButtonBehavior
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.image import AsyncImage
    from kivy.uix.label import Label
    from kivy.uix.popup import Popup
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.widget import Widget
    from kivy.utils import get_color_from_hex as hexc
except ImportError:                                   # тесты геометрии без Kivy
    Widget = object
else:
    import palette

    class SpeciesPicture(Widget):
        """Эталон вида: своя фотография, если она есть, иначе рисунок.

        Виджет намеренно не кнопка: в окне выбора по нему уже нельзя
        промахнуться — нажатие ловит вся строка целиком.
        """

        def __init__(self, key="белый", bg=palette.SOFT, radius=None, **kw):
            super().__init__(**kw)
            self.key = key
            self.bg = hexc(bg) if isinstance(bg, str) else bg
            self.radius = dp(6) if radius is None else radius
            self._photo = None
            path = photo_path(key)
            if path:
                self._photo = AsyncImage(source=path, fit_mode="cover")
                self.add_widget(self._photo)
            self.bind(pos=self.redraw, size=self.redraw)
            self.redraw()

        def redraw(self, *_):
            if self._photo is not None:
                self._photo.pos = self.pos
                self._photo.size = self.size
                return
            self.canvas.clear()
            with self.canvas:
                Color(*self.bg)
                RoundedRectangle(pos=self.pos, size=self.size,
                                 radius=[self.radius])
                for item in shapes(self.key, self.x, self.y,
                                   self.width, self.height):
                    what, color, kwargs = plan(item)
                    Color(*hexc(color))
                    if what == "mesh":
                        Mesh(**kwargs)
                    elif what == "ellipse":
                        Ellipse(**kwargs)
                    else:
                        Line(**kwargs)

    def _line(text, color, size=12, bold=False):
        lab = Label(text=text, font_size=sp(size), bold=bold,
                    color=hexc(color), halign="left", valign="top",
                    size_hint_y=None)
        lab.bind(width=lambda w, x: setattr(w, "text_size", (x, None)),
                 texture_size=lambda w, t: setattr(w, "height", t[1] + dp(4)))
        return lab

    def card(key: str, species=None, on_change=None) -> "Popup":
        """Карточка вида: крупный эталон, признаки, двойники, предостережение.

        Открывается там, где спешить уже не надо: гриб в руках, а кнопка
        выбора никуда не денется. Поэтому текста здесь много, а в самом
        окне выбора — только картинка и название.

        on_change — что делать, если человек сверился и понял, что вид не
        тот. Кнопка стоит именно здесь, а не в карточке метки: сомнение
        возникает в ту секунду, когда смотришь на эталон и признаки, и
        отправлять человека закрывать карточку и искать нужную кнопку
        где-то ещё — верный способ оставить метку с неверным видом.
        """
        title = species.name if species is not None else key
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        with box.canvas.before:
            Color(*hexc(palette.CARD))
            rect = RoundedRectangle(pos=box.pos, size=box.size)
        box.bind(pos=lambda w, v: setattr(rect, "pos", v),
                 size=lambda w, v: setattr(rect, "size", v))

        pic = SpeciesPicture(key=key, size_hint_y=None, height=dp(200))
        box.add_widget(pic)

        sv = ScrollView()
        col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2),
                        padding=(dp(2), dp(4)))
        col.bind(minimum_height=col.setter("height"))

        if species is not None and getattr(species, "latin", ""):
            col.add_widget(_line(species.latin, palette.MUTED, 11))

        info = FEATURES.get(key, {})
        col.add_widget(_line("Как узнать", palette.MUTED, 11))
        for mark in info.get("marks", []):
            col.add_widget(_line("·  " + mark, palette.INK, 13))

        twins = info.get("twins", [])
        if twins:
            col.add_widget(_line("С чем путают", palette.MUTED, 11))
            for twin in twins:
                col.add_widget(_line("·  " + twin, palette.INK, 13))

        if info.get("care"):
            col.add_widget(_line("Перед готовкой", palette.MUTED, 11))
            col.add_widget(_line(info["care"], palette.RED, 13))

        if species is not None and getattr(species, "note", ""):
            col.add_widget(_line("Когда искать", palette.MUTED, 11))
            col.add_widget(_line(species.note, palette.INK, 13))

        col.add_widget(_line("", palette.MUTED, 8))
        sv.add_widget(col)
        box.add_widget(sv)

        # Предупреждение стоит вне прокрутки: у длинных карточек оно
        # оказывалось ниже края, а это единственная строка, которую нельзя
        # ставить в зависимость от того, докрутил человек до конца или нет.
        warn = _line(WARNING, palette.MUTED, 11)
        box.add_widget(warn)

        pop = Popup(title=title, content=box, size_hint=(0.94, 0.9),
                    title_size=sp(15), separator_color=hexc(palette.ACCENT))
        btns = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        close = Button(text="Закрыть", font_size=sp(15), background_normal="",
                       background_color=hexc(palette.SOFT),
                       color=hexc(palette.INK))
        close.bind(on_release=lambda *_: pop.dismiss())
        btns.add_widget(close)
        if on_change is not None:
            other = Button(text="Это другой вид", font_size=sp(14),
                           background_normal="",
                           background_color=hexc(palette.SOFT_ALT),
                           color=hexc(palette.INK))

            def switch(*_):
                pop.dismiss()
                on_change()

            other.bind(on_release=switch)
            btns.add_widget(other)
        box.add_widget(btns)
        pop.open()
        return pop


    class SpeciesRow(ButtonBehavior, BoxLayout):
        """Строка выбора вида: эталон, название, латынь. Нажимается целиком.

        Своей отрисовкой фона, а не готовой кнопкой: Button рисует надпись
        внутри себя и вложить в него картинку нельзя, а класть картинку поверх
        кнопки — значит получить два разных обработчика касания на одной
        площадке и промахи между ними.
        """

        def __init__(self, key, species, **kw):
            super().__init__(orientation="horizontal", spacing=dp(8),
                             padding=(dp(6), dp(4)), **kw)
            self.key = key
            with self.canvas.before:
                self._color = Color(*hexc(palette.SOFT))
                self._rect = RoundedRectangle(pos=self.pos, size=self.size,
                                              radius=[dp(8)])
            self.bind(pos=self._redraw, size=self._redraw, state=self._redraw)

            self.add_widget(SpeciesPicture(key=key, bg=palette.CARD,
                                           size_hint_x=None, width=dp(54)))
            text = BoxLayout(orientation="vertical")
            name = Label(text=species.name, font_size=sp(15), bold=True,
                         color=hexc(palette.INK), halign="left", valign="bottom")
            latin = Label(text=species.latin, font_size=sp(10),
                          color=hexc(palette.MUTED), halign="left", valign="top")
            for lab in (name, latin):
                lab.bind(width=lambda w, x: setattr(w, "text_size", (x, None)))
            text.add_widget(name)
            text.add_widget(latin)
            self.add_widget(text)

        def _redraw(self, *_):
            self._rect.pos = self.pos
            self._rect.size = self.size
            # Нажатая строка темнеет: без отклика палец жмёт второй раз.
            self._color.rgba = hexc(palette.SOFT_ALT if self.state == "down"
                                    else palette.SOFT)

    def picker(on_pick, title="Что нашли?", plain="Просто метка", recent=""):
        """Список видов с эталонами. on_pick(key) — выбранный вид, "" — без вида.

        recent — вид, отмеченный последним: он поднимается наверх списка.
        Грибы идут сериями: нашёл белый — через десять шагов ещё белый, и
        мокрым пальцем в перчатке до него каждый раз прокручивать.

        Живёт здесь, а не в экране похода, потому что мест, где вид
        выбирают, стало два: постановка метки и исправление уже поставленной.
        Разошедшиеся списки — классика: в одном одиннадцать видов, в другом
        девять, и никто этого не замечает до жалобы.

        Нажатие ловит вся строка целиком, а не картинка отдельно: маленькая
        мишень рядом с большой — верный промах в перчатке. Узкая кнопка
        «крупно» вынесена в конец строки и отделена зазором. Ошибка в ней
        стоит дёшево: откроется карточка вида, её закрывают одним касанием.
        """
        import mushroom_forecast as engine

        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        with box.canvas.before:
            Color(*hexc(palette.CARD))
            rect = RoundedRectangle(pos=box.pos, size=box.size)
        box.bind(pos=lambda w, v: setattr(rect, "pos", v),
                 size=lambda w, v: setattr(rect, "size", v))

        sv = ScrollView()
        grid = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        grid.bind(minimum_height=grid.setter("height"))

        def choose(key):
            pop.dismiss()
            if on_pick:
                on_pick(key)

        order = list(engine.SPECIES.items())
        if recent in engine.SPECIES:
            order.sort(key=lambda kv: kv[0] != recent)
        for key, sp_obj in order:
            line = BoxLayout(size_hint_y=None, height=dp(62), spacing=dp(6))
            row = SpeciesRow(key, sp_obj)
            row.bind(on_release=lambda _r, k=key: choose(k))
            zoom = Button(text="крупно", size_hint_x=None, width=dp(62),
                          font_size=sp(11), background_normal="",
                          background_color=hexc(palette.SOFT_ALT),
                          color=hexc(palette.MUTED))
            zoom.bind(on_release=lambda _b, k=key, s=sp_obj: card(k, s))
            line.add_widget(row)
            line.add_widget(zoom)
            grid.add_widget(line)

        if plain:
            other = Button(text=plain, size_hint_y=None, height=dp(52),
                           font_size=sp(15), background_normal="",
                           background_color=hexc(palette.SOFT_ALT),
                           color=hexc(palette.MUTED))
            other.bind(on_release=lambda _b: choose(""))
            grid.add_widget(other)

        sv.add_widget(grid)
        box.add_widget(sv)
        pop = Popup(title=title, content=box, size_hint=(0.9, 0.85),
                    separator_color=hexc(palette.RED), title_size=sp(15))
        pop.open()
        return pop
