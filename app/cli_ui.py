"""Общие элементы оформления интерактивного CLI."""

from __future__ import annotations

import locale
import sys

from rich.console import Console
from rich.panel import Panel

console = Console()

_YES = frozenset({"y", "yes", "д", "да"})
_NO = frozenset({"n", "no", "н", "нет"})
_EXIT_ALIASES = frozenset({"exit", "выход", "quit", "q", "отмена", "cancel"})
CANCEL_HINT = "exit — отмена"


def is_exit_choice(value: str) -> bool:
    return value.strip().casefold() in _EXIT_ALIASES


def _decode_bytes(data: bytes) -> str:
    if not data:
        return ""

    candidates: list[str] = []
    for encoding in (sys.stdin.encoding, locale.getpreferredencoding(False), "utf-8", "cp1251"):
        if encoding and encoding not in candidates:
            candidates.append(encoding)
    candidates.append("latin-1")

    for encoding in candidates:
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").strip()


def _decode_stdin_line() -> str:
    line = sys.stdin.buffer.readline()
    if not line:
        return ""
    return _decode_bytes(line.rstrip(b"\r\n"))


def text_prompt(
    message: str,
    *,
    default: str = "",
    hide_input: bool = False,
) -> str:
    """Текстовый ввод без typer.prompt — кириллица в терминалах с нестандартной кодировкой."""
    if hide_input:
        return secret_prompt(message)

    if default:
        console.print(f"{message} [{default}]: ", end="")
    else:
        console.print(f"{message}: ", end="")
    sys.stdout.flush()

    try:
        value = _decode_stdin_line()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return default
    if not value and default:
        return default
    return value


def secret_prompt(message: str) -> str:
    """Скрытый ввод без typer.prompt (API token и т.п.)."""
    if not sys.stdin.isatty():
        console.print(f"{message}: ", end="")
        sys.stdout.flush()
        try:
            return _decode_stdin_line()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return ""

    try:
        import termios
        import tty

        console.print(f"{message}: ", end="")
        sys.stdout.flush()
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            chunks: list[bytes] = []
            while True:
                ch = sys.stdin.buffer.read(1)
                if ch in (b"\n", b"\r"):
                    console.print()
                    break
                if ch in (b"\x7f", b"\x08"):
                    if chunks:
                        chunks.pop()
                        console.print("\b \b", end="")
                        sys.stdout.flush()
                    continue
                if ch == b"\x03":
                    raise KeyboardInterrupt
                chunks.append(ch)
                console.print("*", end="")
                sys.stdout.flush()
            return _decode_bytes(b"".join(chunks))
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except ImportError:
        import getpass

        try:
            return getpass.getpass(f"{message}: ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""
    except (EOFError, KeyboardInterrupt, OSError):
        console.print()
        return ""


def confirm_prompt(message: str, *, default: bool = False) -> bool:
    """Подтверждение без typer.confirm — совместимо с не-UTF-8 терминалами."""
    hint = "(Y/n)" if default else "(y/N)"
    console.print(f"{message} {hint}: ", end="")
    sys.stdout.flush()

    try:
        value = _decode_stdin_line().casefold()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return default

    if not value:
        return default
    if value in _YES:
        return True
    if value in _NO:
        return False
    return default


def print_header(title: str, *, subtitle: str = "") -> None:
    body = f"[bold]{title}[/bold]"
    if subtitle:
        body += f"\n[dim]{subtitle}[/dim]"
    console.print(Panel.fit(body, border_style="cyan"))


def print_section(title: str) -> None:
    console.print()
    console.print(f"[bold cyan]{title}[/bold cyan]")


def print_menu_item(number: str | int, text: str, *, indent: int = 2) -> None:
    prefix = " " * indent
    console.print(f"{prefix}{number}. {text}")


def print_step(step: int, total: int, title: str) -> None:
    console.print()
    console.print(f"[bold]Шаг {step}/{total}. {title}[/bold]")


def print_success(message: str) -> None:
    console.print(f"[green]{message}[/green]")


def print_error(message: str) -> None:
    console.print(f"[red]{message}[/red]")


def print_warning(message: str) -> None:
    console.print(f"[yellow]{message}[/yellow]")


def print_info(message: str) -> None:
    console.print(f"[dim]{message}[/dim]")


def print_field(label: str, value: str) -> None:
    console.print(f"  [dim]{label}:[/dim] {value}")


def print_cancelled() -> None:
    print_info("Отменено")


def prompt_line(label: str = "Выбор") -> str:
    """Строка ввода без typer — без пустых скобок [] в приглашении."""
    console.print(f"{label}: ", end="")
    sys.stdout.flush()
    try:
        return _decode_stdin_line().casefold()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return ""