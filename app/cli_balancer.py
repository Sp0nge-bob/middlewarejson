from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from app.db.repository import CatalogRepository
from app.models.balancer import (
    BALANCER_SCOPES,
    BALANCER_STRATEGIES,
    format_scope,
    normalize_scope,
    normalize_strategy,
)
from app.services.profile_builder import default_balancer_tag

console = Console()

SCOPE_CHOICES = list(BALANCER_SCOPES.keys())


_STRATEGY_HINTS = {
    "roundRobin": "по очереди",
    "leastLoad": "меньше нагрузка на сервере",
    "leastPing": "минимальный пинг (ближайший по задержке)",
    "random": "случайный выбор",
}


def prompt_strategy(default: str = "roundRobin") -> str:
    console.print("[bold]Стратегия[/bold]")
    for index, strategy in enumerate(BALANCER_STRATEGIES, start=1):
        mark = " (default)" if strategy == default else ""
        hint = _STRATEGY_HINTS.get(strategy, "")
        suffix = f" — {hint}" if hint else ""
        console.print(f"  {index}. {strategy}{suffix}{mark}")
    choice = typer.prompt("Выбор", default="1").strip()
    try:
        selected = int(choice) - 1
        if 0 <= selected < len(BALANCER_STRATEGIES):
            return BALANCER_STRATEGIES[selected]
    except ValueError:
        pass
    try:
        return normalize_strategy(choice)
    except ValueError:
        return default


def prompt_scope(repo: CatalogRepository) -> tuple[str, str]:
    console.print("[bold]Назначение[/bold]")
    for index, scope in enumerate(SCOPE_CHOICES, start=1):
        console.print(f"  {index}. {BALANCER_SCOPES[scope]}")
    choice = typer.prompt("Выбор", default="1").strip()
    try:
        scope = SCOPE_CHOICES[int(choice) - 1]
    except (ValueError, IndexError):
        try:
            scope = normalize_scope(choice)
        except ValueError:
            scope = "disabled"

    if scope == "group":
        groups = repo.list_groups()
        if not groups:
            console.print("[yellow]Групп нет. Сначала: group sync[/yellow]")
            return "disabled", ""
        for index, group_name in enumerate(groups):
            console.print(f"  {index}. {group_name}")
        group_choice = typer.prompt("Номер группы").strip()
        try:
            return "group", groups[int(group_choice)]
        except (ValueError, IndexError):
            return "group", typer.prompt("Имя группы").strip()

    if scope == "client":
        clients = repo.list_all_clients()
        if not clients:
            console.print("[yellow]Клиентов нет. Сначала: group sync[/yellow]")
            return "disabled", ""
        for index, client in enumerate(clients):
            label = client.email or client.sub_id
            group_hint = f" [{client.group_name}]" if client.group_name else ""
            console.print(f"  {index}. {label}{group_hint}  sub_id={client.sub_id}")
        client_choice = typer.prompt("Номер клиента").strip()
        try:
            return "client", clients[int(client_choice)].sub_id
        except (ValueError, IndexError):
            return "client", typer.prompt("sub_id").strip()

    return scope, ""


def print_balancer_table(balancers: list, *, catalog_by_fp: dict | None = None) -> None:
    table = Table(title="Balancers")
    table.add_column("#", style="dim")
    table.add_column("Tag")
    table.add_column("Name")
    table.add_column("Strategy")
    table.add_column("Scope")
    table.add_column("Members", justify="right")

    for index, balancer in enumerate(balancers):
        table.add_row(
            str(index),
            balancer.tag,
            balancer.remarks,
            balancer.strategy,
            format_scope(balancer.scope, balancer.scope_target),
            str(len(balancer.member_fingerprints)),
        )
    console.print(table)

    if catalog_by_fp is None:
        return

    for balancer in balancers:
        console.print(
            f"\n[bold]{balancer.tag}[/bold] — {balancer.remarks} "
            f"({balancer.strategy}, {format_scope(balancer.scope, balancer.scope_target)})"
        )
        for fingerprint in balancer.member_fingerprints:
            row = catalog_by_fp.get(fingerprint)
            if row and row.get("panel_inbound_id") is not None:
                panel_info = f"id={row['panel_inbound_id']} ep={row.get('endpoint_index', 0)}"
            else:
                panel_info = "id=?"
            console.print(f"  [{panel_info}] {fingerprint}")


def configure_balancer_interactive(
    repo: CatalogRepository,
    balancer_tag: str,
    *,
    list_inbounds,
    resolve_member_fingerprints,
) -> None:
    balancer = repo.get_balancer_by_tag(balancer_tag)
    if balancer is None:
        console.print(f"[red]Балансировщик '{balancer_tag}' не найден[/red]")
        return

    while True:
        console.print()
        console.print(
            f"[bold]{balancer.tag}[/bold] — {balancer.remarks}\n"
            f"  strategy: {balancer.strategy}\n"
            f"  scope: {format_scope(balancer.scope, balancer.scope_target)}\n"
            f"  members: {len(balancer.member_fingerprints)}"
        )
        console.print("  1. Изменить назначение (scope)")
        console.print("  2. Изменить стратегию")
        console.print("  3. Изменить имя (remarks)")
        console.print("  4. Изменить members")
        console.print("  0. Назад")

        choice = typer.prompt("Выбор", default="0").strip()
        if choice == "0":
            return

        if choice == "1":
            scope, target = prompt_scope(repo)
            repo.set_balancer_scope(balancer.tag, scope, target)
            console.print(
                f"[green]Назначение: {format_scope(scope, target)}[/green]"
            )
        elif choice == "2":
            strategy = prompt_strategy(default=balancer.strategy)
            repo.update_balancer(balancer.tag, strategy=strategy)
            console.print(f"[green]Стратегия: {strategy}[/green]")
        elif choice == "3":
            remarks = typer.prompt("Имя в HAPP", default=balancer.remarks).strip()
            repo.update_balancer(balancer.tag, remarks=remarks)
            console.print(f"[green]Имя: {remarks}[/green]")
        elif choice == "4":
            rows = list_inbounds(active_only=True)
            if not rows:
                continue
            selection = typer.prompt("Номера строк (например 0,2,5)")
            try:
                indices = [int(part.strip()) for part in selection.split(",") if part.strip()]
                fingerprints = [str(rows[i]["fingerprint"]) for i in indices]
            except (ValueError, IndexError):
                console.print("[red]Неверные индексы[/red]")
                continue
            repo.update_balancer(balancer.tag, member_fingerprints=fingerprints)
            console.print(f"[green]Members обновлены ({len(fingerprints)})[/green]")
        else:
            console.print("[yellow]Неизвестный пункт[/yellow]")

        refreshed = repo.get_balancer_by_tag(balancer_tag)
        if refreshed is not None:
            balancer = refreshed


def create_balancer_interactive(
    repo: CatalogRepository,
    *,
    list_inbounds,
    resolve_member_fingerprints,
) -> None:
    rows = list_inbounds(active_only=True)
    if not rows:
        return

    selection = typer.prompt("Номера строк из каталога (например 0,6,9)")
    try:
        indices = [int(part.strip()) for part in selection.split(",") if part.strip()]
        fingerprints = [str(rows[i]["fingerprint"]) for i in indices]
    except (ValueError, IndexError):
        console.print("[red]Неверные индексы[/red]")
        return

    name = typer.prompt("Имя балансировщика (для HAPP)", default="Balance")
    tag = default_balancer_tag(name)
    strategy = prompt_strategy()
    scope, scope_target = prompt_scope(repo)

    repo.create_balancer(
        tag=tag,
        remarks=name.strip(),
        strategy=strategy,
        member_fingerprints=fingerprints,
        scope=scope,
        scope_target=scope_target,
    )
    console.print(
        f"[green]Балансировщик '{tag}' создан "
        f"({format_scope(scope, scope_target)}, {strategy})[/green]"
    )


def list_balancers_interactive(
    repo: CatalogRepository,
    *,
    list_inbounds,
    resolve_member_fingerprints,
) -> None:
    balancers = repo.list_balancers()
    if not balancers:
        console.print("[yellow]Балансировщиков нет[/yellow]")
        return

    catalog_by_fp = {
        str(row["fingerprint"]): row for row in repo.list_inbounds(active_only=False)
    }
    print_balancer_table(balancers, catalog_by_fp=catalog_by_fp)

    choice = typer.prompt(
        "Номер балансировщика для настройки (Enter — пропустить)",
        default="",
    ).strip()
    if not choice:
        return

    try:
        index = int(choice)
        configure_balancer_interactive(
            repo,
            balancers[index].tag,
            list_inbounds=list_inbounds,
            resolve_member_fingerprints=resolve_member_fingerprints,
        )
    except (ValueError, IndexError):
        configure_balancer_interactive(
            repo,
            choice,
            list_inbounds=list_inbounds,
            resolve_member_fingerprints=resolve_member_fingerprints,
        )