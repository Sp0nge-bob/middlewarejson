from app.cli_ui import confirm_prompt, is_exit_choice, text_prompt


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


def test_decode_bytes_prefers_utf8_over_cp1251() -> None:
    from app.cli_ui import _decode_bytes

    assert _decode_bytes("Авто-подбор".encode("utf-8")) == "Авто-подбор"


def test_decode_bytes_reads_cp1251_terminal() -> None:
    from app.cli_ui import _decode_bytes

    assert _decode_bytes("Авто-подбор".encode("cp1251")) == "Авто-подбор"


def test_repair_mojibake_from_cp1251_misread_utf8() -> None:
    from app.cli_ui import _repair_mojibake

    broken = "Авто-подбор".encode("utf-8").decode("cp1251")
    assert _repair_mojibake(broken) == "Авто-подбор"


def test_text_prompt_preserves_cyrillic(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.cli_ui._decode_stdin_line",
        lambda: "Ближайший сервер",
    )
    assert text_prompt("Название") == "Ближайший сервер"


def test_text_prompt_empty_uses_default(monkeypatch) -> None:
    monkeypatch.setattr("app.cli_ui._decode_stdin_line", lambda: "")
    assert text_prompt("Название", default="Balance") == "Balance"


def test_is_exit_choice_recognizes_aliases() -> None:
    assert is_exit_choice("exit")
    assert is_exit_choice("EXIT")
    assert is_exit_choice(" выход ")
    assert is_exit_choice("отмена")
    assert is_exit_choice("quit")
    assert not is_exit_choice("0,1,2")
    assert not is_exit_choice("")