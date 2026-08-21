# -*- coding: utf-8 -*-
"""
legal.py — адреса опубликованных версий политики конфиденциальности и
условий использования.

Тексты живут в docs/privacy.md и docs/terms.md в репозитории; здесь —
только ссылки на их опубликованную веб-версию (см. docs/rustore.md,
раздел про GitHub Pages). Замените PRIVACY_URL и TERMS_URL на настоящий
адрес перед публикацией — плейсхолдер ниже собран по образцу из
rustore.md и рабочим не является, пока Pages не включены.
"""

from __future__ import annotations

PRIVACY_URL = "https://grezev.github.io/mushroom-forecast/privacy"
TERMS_URL = "https://grezev.github.io/mushroom-forecast/terms"


def both_ready() -> bool:
    """True, когда обе ссылки заменены с плейсхолдера на настоящие.

    Плейсхолдер узнаваем по логину grezev — если он остался, значит адрес
    ещё не проверен. Используется тестом, чтобы публикация без ссылок не
    проходила молча.
    """
    placeholder_login = "grezev"
    return placeholder_login not in PRIVACY_URL and placeholder_login not in TERMS_URL
