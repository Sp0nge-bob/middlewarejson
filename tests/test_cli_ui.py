from app.cli_ui import confirm_prompt


def test_confirm_prompt_accepts_no(monkeypatch) -> None:
    monkeypatch.setattr("app.cli_ui._decode_stdin_line", lambda: "n")
    assert confirm_prompt("Test?", default=True) is False


def test_confirm_prompt_accepts_cyrillic_no(monkeypatch) -> None:
    monkeypatch.setattr("app.cli_ui._decode_stdin_line", lambda: "нет")
    assert confirm_prompt("Test?", default=True) is False


def test_confirm_prompt_empty_uses_default(monkeypatch) -> None:
    monkeypatch.setattr("app.cli_ui._decode_stdin_line", lambda: "")
    assert confirm_prompt("Test?", default=False) is False
    assert confirm_prompt("Test?", default=True) is True