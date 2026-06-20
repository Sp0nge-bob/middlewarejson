"""Общие элементы оформления интерактивного CLI."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

console = Console()


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