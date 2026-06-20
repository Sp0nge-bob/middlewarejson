"""Общие элементы оформления интерактивного CLI."""

from __future__ import annotations

import locale
import sys

from rich.console import Console
from rich.panel import Panel

console = Console()

_YES = frozenset({"y", "yes", "д", "да"})
_NO = frozenset({"n", "no", "н", "нет"})


def _decode_stdin_line() -> str:
    line = sys.stdin.buffer.readline()
    if not line:
        return ""

    candidates: list[str] = []
    for encoding in (sys.stdin.encoding, locale.getpreferredencoding(False), "utf-8", "cp1251"):
        if encoding and encoding not in candidates:
            candidates.append(encoding)
    candidates.append("latin-1")

    for encoding in candidates:
        try:
            return line.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return line.decode("utf-8", errors="replace").strip()


def confirm_prompt(message: str, *, default: bool = False) -> bool:
    """Подтверждение без typer.confirm — совместимо с не-UTF-8 терминалами."""
    hint = "Y/n" if default else "y/N"
    console.print(f"{message} [{hint}]: ", end="")
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