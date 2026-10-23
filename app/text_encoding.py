"""Repair reversible UTF-8 terminal decoding errors without changing valid text."""


def _cyrillic_letter_count(text: str) -> int:
    return sum(1 for char in text if "\u0400" <= char <= "\u04ff")


def _looks_like_mojibake(text: str) -> bool:
    return any(marker in text for marker in ("Рђ", "РІ", "Рѕ", "СЂ", "С‡", "СЏ"))


def repair_mojibake(text: str) -> str:
    """Undo strict, reversible cp1251/Latin decoding of UTF-8, at most 3 times.

    Invalid byte sequences are left intact: missing characters cannot be
    reconstructed safely. Only accept candidates with Cyrillic or an explicit
    mojibake signature; ASCII and correctly decoded Unicode stay unchanged.
    """
    for _ in range(3):
        original = text
        for encoding in ("cp1251", "latin-1", "cp1252"):
            try:
                repaired = text.encode(encoding).decode("utf-8")
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
            if repaired == text:
                continue
            if _looks_like_mojibake(text) or _cyrillic_letter_count(repaired) > _cyrillic_letter_count(text):
                text = repaired
                break
        if text == original:
            break
    return text
