from app.cli_balancer import (
    _prompt_client_sub_id,
    _prompt_member_indices,
    filter_clients,
    prompt_happ_remarks,
)
from app.services.profile_builder import default_balancer_tag, suggest_balancer_tag
from app.db.repository import ClientRecord


def _client(email: str, *, sub_id: str = "sub1", group: str = "G1") -> ClientRecord:
    return ClientRecord(sub_id=sub_id, group_name=group, email=email, enable=True)


def test_default_balancer_tag_from_cyrillic_name() -> None:
    assert default_balancer_tag("Авто-подбор") == "авто-подбор"


def test_suggest_balancer_tag_skips_existing() -> None:
    assert suggest_balancer_tag() == "tag-1"
    assert suggest_balancer_tag({"tag-1"}) == "tag-2"
    assert suggest_balancer_tag({"tag-1", "tag-2"}) == "tag-3"


def test_prompt_member_indices_exit_cancels(monkeypatch) -> None:
    monkeypatch.setattr("app.cli_balancer.text_prompt", lambda *_a, **_k: "exit")
    rows = [{"fingerprint": "fp0"}, {"fingerprint": "fp1"}]
    assert _prompt_member_indices(rows) is None


def test_prompt_member_indices_parses_numbers(monkeypatch) -> None:
    monkeypatch.setattr("app.cli_balancer.text_prompt", lambda *_a, **_k: "0, 2")
    rows = [
        {"fingerprint": "fp0"},
        {"fingerprint": "fp1"},
        {"fingerprint": "fp2"},
    ]
    assert _prompt_member_indices(rows) == ["fp0", "fp2"]


def test_prompt_member_indices_empty_catalog() -> None:
    assert _prompt_member_indices([]) is None


def test_filter_clients_matches_email_group_and_sub_id() -> None:
    clients = [
        _client("Andrey_NL", sub_id="uzhp1975", group="Платные"),
        _client("Werash_NL", sub_id="ao44hvpk", group="Платные"),
        _client("Mom", sub_id="u3x9a2sl", group="Бесплатные"),
    ]
    assert len(filter_clients(clients, "andrey")) == 1
    assert len(filter_clients(clients, "платные")) == 2
    assert len(filter_clients(clients, "u3x9a2sl")) == 1


def test_prompt_client_sub_id_exit_cancels(monkeypatch) -> None:
    monkeypatch.setattr("app.cli_balancer.text_prompt", lambda *_a, **_k: "exit")
    clients = [_client("Andrey_NL")]
    assert _prompt_client_sub_id(clients) is None


def test_prompt_client_sub_id_exact_sub_id(monkeypatch) -> None:
    prompts = iter(["uzhp1975wixbxwj1"])
    monkeypatch.setattr(
        "app.cli_balancer.text_prompt",
        lambda *_a, **_k: next(prompts),
    )
    monkeypatch.setattr("app.cli_balancer.confirm_prompt", lambda *_a, **_k: True)
    clients = [_client("Andrey_NL", sub_id="uzhp1975wixbxwj1")]
    assert _prompt_client_sub_id(clients) == "uzhp1975wixbxwj1"


def test_prompt_happ_remarks_custom_flag_code(monkeypatch) -> None:
    prompts = iter(["ch", "Swiss Pool"])
    monkeypatch.setattr(
        "app.cli_balancer.text_prompt",
        lambda *_a, **_k: next(prompts),
    )
    assert prompt_happ_remarks(default="Balance") == "🇨🇭 Swiss Pool"


def test_prompt_happ_remarks_other_menu_flag(monkeypatch) -> None:
    prompts = iter(["+", "br", "Brazil"])
    monkeypatch.setattr(
        "app.cli_balancer.text_prompt",
        lambda *_a, **_k: next(prompts),
    )
    assert prompt_happ_remarks(default="Balance") == "🇧🇷 Brazil"


def test_prompt_happ_remarks_with_flag(monkeypatch) -> None:
    prompts = iter(["1", "NL Pool"])
    monkeypatch.setattr(
        "app.cli_balancer.text_prompt",
        lambda *_a, **_k: next(prompts),
    )
    assert prompt_happ_remarks(default="Balance") == "🇳🇱 NL Pool"


def test_prompt_happ_remarks_exit(monkeypatch) -> None:
    monkeypatch.setattr("app.cli_balancer.text_prompt", lambda *_a, **_k: "exit")
    assert prompt_happ_remarks() is None


def test_prompt_client_sub_id_search_then_pick(monkeypatch) -> None:
    prompts = iter(["andrey", "1"])
    monkeypatch.setattr(
        "app.cli_balancer.text_prompt",
        lambda *_a, **_k: next(prompts),
    )
    clients = [
        _client("Andrey_NL", sub_id="sub-a"),
        _client("Andrey_Woman", sub_id="sub-b"),
        _client("Mom", sub_id="sub-c"),
    ]
    assert _prompt_client_sub_id(clients) == "sub-b"