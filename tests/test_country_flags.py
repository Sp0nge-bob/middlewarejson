from app.country_flags import (
    apply_flag_prefix,
    country_code_to_flag,
    extract_country_code,
    resolve_flag_choice,
    strip_leading_flag,
)


def test_country_code_to_flag_nl() -> None:
    assert country_code_to_flag("nl") == "🇳🇱"


def test_strip_and_apply_flag() -> None:
    assert strip_leading_flag("🇳🇱 Balance") == "Balance"
    assert apply_flag_prefix("Balance", "US") == "🇺🇸 Balance"
    assert apply_flag_prefix("🇳🇱 Old", "US") == "🇺🇸 Old"


def test_extract_country_code() -> None:
    assert extract_country_code("🇳🇱 Balance") == "NL"
    assert extract_country_code("Balance") is None


def test_resolve_flag_choice() -> None:
    assert resolve_flag_choice("0") is True
    assert resolve_flag_choice("1") == "NL"
    assert resolve_flag_choice("us") == "US"
    assert resolve_flag_choice("zzz") is None