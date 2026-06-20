from app.cli_balancer import _prompt_member_indices


def test_prompt_member_indices_exit_cancels(monkeypatch) -> None:
    monkeypatch.setattr("app.cli_balancer.typer.prompt", lambda *_a, **_k: "exit")
    rows = [{"fingerprint": "fp0"}, {"fingerprint": "fp1"}]
    assert _prompt_member_indices(rows) is None


def test_prompt_member_indices_parses_numbers(monkeypatch) -> None:
    monkeypatch.setattr("app.cli_balancer.typer.prompt", lambda *_a, **_k: "0, 2")
    rows = [
        {"fingerprint": "fp0"},
        {"fingerprint": "fp1"},
        {"fingerprint": "fp2"},
    ]
    assert _prompt_member_indices(rows) == ["fp0", "fp2"]


def test_prompt_member_indices_empty_catalog() -> None:
    assert _prompt_member_indices([]) is None