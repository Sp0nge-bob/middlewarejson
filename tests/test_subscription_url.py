import pytest

from app.models.subscription import parse_subscription_reference

EXAMPLE_SUB_ID = "abcd1234efgh5678"


def test_parse_full_url() -> None:
    assert (
        parse_subscription_reference(
            f"https://example.com/json/{EXAMPLE_SUB_ID}"
        )
        == EXAMPLE_SUB_ID
    )


def test_parse_sub_id_only() -> None:
    assert parse_subscription_reference(EXAMPLE_SUB_ID) == EXAMPLE_SUB_ID


def test_parse_domain_url() -> None:
    assert (
        parse_subscription_reference(
            f"https://example.com/json/{EXAMPLE_SUB_ID}"
        )
        == EXAMPLE_SUB_ID
    )


def test_parse_invalid_raises() -> None:
    with pytest.raises(ValueError):
        parse_subscription_reference("bad!")