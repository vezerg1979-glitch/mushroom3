#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_unlock_code.py — считает код разблокировки по коду устройства.

Запускать у себя, после того как деньги пришли по СБП:

    python3 tools/make_unlock_code.py 7K4M-9PQR

Код должен совпадать с SECRET из android/licensecode.py — то есть запускать
это нужно из копии репозитория с ВАШИМ секретом, не с тем нулевым, что лежит
в исходниках по умолчанию.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "android"))

import licensecode  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("device_code", help="код устройства с экрана покупки")
    args = p.parse_args()

    if set(licensecode.SECRET) == {"0"}:
        print("SECRET в licensecode.py ещё нулевой — коды, посчитанные им,",
              "не совпадут с тем, что стоит в опубликованном APK.",
              file=sys.stderr)
        sys.exit(1)

    print(licensecode.unlock_code_for(args.device_code))


if __name__ == "__main__":
    main()
