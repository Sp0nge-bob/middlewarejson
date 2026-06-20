"""Флаги стран для названий профилей в HAPP."""

from __future__ import annotations

import re

_REGIONAL_BASE = 0x1F1E6
_FLAG_PREFIX_RE = re.compile(r"^[\U0001F1E6-\U0001F1FF]{2}\s*")

CUSTOM_FLAG_MENU_KEY = "+"


class OtherFlagChoice:
    """Маркер: пользователь хочет ввести код страны вручную."""


OTHER_FLAG_CHOICE = OtherFlagChoice()


COMMON_COUNTRY_FLAGS: list[tuple[str, str]] = [
    ("NL", "Нидерланды"),
    ("US", "США"),
    ("DE", "Германия"),
    ("RU", "Россия"),
    ("GB", "Великобритания"),
    ("FR", "Франция"),
    ("FI", "Финляндия"),
    ("TR", "Турция"),
    ("AE", "ОАЭ"),
    ("SG", "Сингапур"),
    ("JP", "Япония"),
    ("KR", "Корея"),
    ("CA", "Канада"),
    ("PL", "Польша"),
    ("UA", "Украина"),
]


def country_code_to_flag(code: str) -> str | None:
    value = code.strip().upper()
    if len(value) != 2 or not value.isalpha():
        return None
    return "".join(chr(_REGIONAL_BASE + ord(char) - ord("A")) for char in value)


def strip_leading_flag(text: str) -> str:
    return _FLAG_PREFIX_RE.sub("", text).strip()


def extract_country_code(text: str) -> str | None:
    match = _FLAG_PREFIX_RE.match(text)
    if not match:
        return None
    flag = match.group(0).strip()
    if len(flag) != 2:
        return None
    letters = []
    for char in flag:
        offset = ord(char) - _REGIONAL_BASE
        if offset < 0 or offset > 25:
            return None
        letters.append(chr(ord("A") + offset))
    return "".join(letters)


def apply_flag_prefix(name: str, country_code: str | None) -> str:
    base = strip_leading_flag(name)
    if not country_code:
        return base
    flag = country_code_to_flag(country_code)
    if not flag:
        return base
    return f"{flag} {base}" if base else flag


def resolve_flag_choice(
    choice: str,
) -> str | None | bool | OtherFlagChoice:
    """Разобрать выбор флага.

    True — без флага, str — код страны, OTHER_FLAG_CHOICE — ввести код вручную,
    None — неверный ввод.
    """
    value = choice.strip()
    if not value or value == "0":
        return True

    if value.casefold() in {CUSTOM_FLAG_MENU_KEY, "другой", "other", "*"}:
        return OTHER_FLAG_CHOICE

    try:
        index = int(value) - 1
        if 0 <= index < len(COMMON_COUNTRY_FLAGS):
            return COMMON_COUNTRY_FLAGS[index][0]
    except ValueError:
        pass

    if country_code_to_flag(value):
        return value.upper()[:2]
    return None