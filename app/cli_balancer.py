from __future__ import annotations

import typer
from rich.table import Table

from app.cli_ui import (
    confirm_prompt,
    console,
    print_error,
    print_field,
    print_info,
    print_menu_item,
    print_section,
    print_step,
    print_success,
    print_warning,
    prompt_line,
)
from app.db.repository import CatalogRepository
from app.models.balancer import (
    BALANCER_SCOPES,
    BALANCER_STRATEGIES,
    STRATEGY_HINTS,
    format_scope,
    format_strategy,
    normalize_scope,
    normalize_strategy,
)
from app.services.profile_builder import default_balancer_tag

SCOPE_CHOICES = list(BALANCER_SCOPES.keys())


def prompt_strategy(default: str = "roundRobin") -> str:
    console.print("[bold]Стратегия балансировки[/bold]")
    for index, strategy in enumerate(BALANCER_STRATEGIES, start=1):
        label = format_strategy(strategy)
        hint = STRATEGY_HINTS.get(strategy, "")
        suffix = f" — {hint}" if hint else ""
        mark = " [dim](по умолчанию)[/dim]" if strategy == default else ""
        console.print(f"  {index}. {label}{suffix}{mark}")
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
    console.print("[bold]Область применения[/bold]")
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
            print_warning("Групп нет. Сначала выполните синхронизацию (п. 6 в меню).")
            return "disabled", ""
        console.print("[bold]Выберите группу[/bold]")
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
            print_warning("Клиентов нет. Сначала выполните синхронизацию (п. 6 в меню).")
            return "disabled", ""
        console.print("[bold]Выберите клиента[/bold]")
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


def _prompt_member_indices(rows: list) -> list[str] | None:
    if not rows:
        print_warning("Каталог инбаундов пуст. Сначала выполните синхронизацию.")
        return None

    selection = typer.prompt("Номера из колонки # (например 0,2,5)")
    try:
        indices = [int(part.strip()) for part in selection.split(",") if part.strip()]
        return [str(rows[i]["fingerprint"]) for i in indices]
    except (ValueError, IndexError):
        print_error("Неверные номера строк")
        return None


def print_balancer_table(balancers: list, *, catalog_by_fp: dict | None = None) -> None:
    table = Table(title="Балансировщики")
    table.add_column("#", style="dim")
    table.add_column("Идентификатор")
    table.add_column("Название")
    table.add_column("Стратегия")
    table.add_column("Область применения")
    table.add_column("Инбаундов", justify="right")

    for index, balancer in enumerate(balancers):
        table.add_row(
            str(index),
            balancer.tag,
            balancer.remarks,
            format_strategy(balancer.strategy),
            format_scope(balancer.scope, balancer.scope_target),
            str(len(balancer.member_fingerprints)),
        )
    console.print(table)

    if catalog_by_fp is None:
        return

    for balancer in balancers:
        console.print(
            f"\n[bold]{balancer.tag}[/bold] — {balancer.remarks} "
            f"({format_strategy(balancer.strategy)}, "
            f"{format_scope(balancer.scope, balancer.scope_target)})"
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
        print_error(f"Балансировщик «{balancer_tag}» не найден")
        return

    while True:
        console.print()
        console.print(f"[bold]{balancer.remarks}[/bold]")
        print_field("Идентификатор", balancer.tag)
        print_field("Стратегия балансировки", format_strategy(balancer.strategy))
        print_field(
            "Область применения",
            format_scope(balancer.scope, balancer.scope_target),
        )
        print_field("Состав инбаундов", f"{len(balancer.member_fingerprints)} шт.")
        console.print()
        console.print("  1. Область применения")
        console.print("  2. Стратегия балансировки")
        console.print("  3. Название в HAPP")
        console.print("  4. Состав инбаундов")
        console.print("  0. Назад")

        choice = typer.prompt("Выбор", default="0").strip()
        if choice == "0":
            return

        if choice == "1":
            scope, target = prompt_scope(repo)
            repo.set_balancer_scope(balancer.tag, scope, target)
            print_success(f"Область применения: {format_scope(scope, target)}")
        elif choice == "2":
            strategy = prompt_strategy(default=balancer.strategy)
            repo.update_balancer(balancer.tag, strategy=strategy)
            print_success(f"Стратегия: {format_strategy(strategy)}")
        elif choice == "3":
            remarks = typer.prompt("Название в HAPP", default=balancer.remarks).strip()
            repo.update_balancer(balancer.tag, remarks=remarks)
            print_success(f"Название: {remarks}")
        elif choice == "4":
            rows = list_inbounds(active_only=True, for_selection=True)
            fingerprints = _prompt_member_indices(rows)
            if fingerprints is None:
                continue
            repo.update_balancer(balancer.tag, member_fingerprints=fingerprints)
            print_success(f"Состав обновлён ({len(fingerprints)} инбаундов)")
        else:
            print_warning("Неизвестный пункт")

        refreshed = repo.get_balancer_by_tag(balancer_tag)
        if refreshed is not None:
            balancer = refreshed


def create_balancer_interactive(
    repo: CatalogRepository,
    *,
    list_inbounds,
    resolve_member_fingerprints,
) -> None:
    print_step(1, 4, "Состав инбаундов")
    rows = list_inbounds(active_only=True, for_selection=True)
    fingerprints = _prompt_member_indices(rows)
    if not fingerprints:
        return

    print_step(2, 4, "Название в HAPP")
    name = typer.prompt("Название", default="Balance").strip()
    tag = default_balancer_tag(name)
    print_info(f"Идентификатор будет: {tag}")

    print_step(3, 4, "Стратегия балансировки")
    strategy = prompt_strategy()

    print_step(4, 4, "Область применения")
    scope, scope_target = prompt_scope(repo)

    repo.create_balancer(
        tag=tag,
        remarks=name,
        strategy=strategy,
        member_fingerprints=fingerprints,
        scope=scope,
        scope_target=scope_target,
    )
    print_success(
        f"Балансировщик «{tag}» создан — "
        f"{format_scope(scope, scope_target)}, {format_strategy(strategy)}, "
        f"{len(fingerprints)} инбаундов"
    )


def _resolve_balancer_tag(
    repo: CatalogRepository,
    balancers: list,
    choice: str,
) -> str | None:
    value = choice.strip()
    if not value:
        return None

    try:
        return balancers[int(value)].tag
    except (ValueError, IndexError):
        if repo.get_balancer_by_tag(value) is not None:
            return value
        print_error(f"Балансировщик «{value}» не найден")
        return None


def delete_balancer_interactive(repo: CatalogRepository, balancers: list) -> None:
    if not balancers:
        print_warning("Балансировщиков нет")
        return

    choice = typer.prompt(
        "Номер или идентификатор для удаления (Enter — отмена)",
        default="",
    ).strip()
    tag = _resolve_balancer_tag(repo, balancers, choice)
    if tag is None:
        return

    if not confirm_prompt(f"Удалить балансировщик «{tag}»?", default=False):
        return

    if repo.delete_balancer(tag):
        print_success(f"Удалён балансировщик «{tag}»")
    else:
        print_error(f"Балансировщик «{tag}» не найден")


def run_balancers_menu(
    repo: CatalogRepository,
    *,
    list_inbounds,
    resolve_member_fingerprints,
) -> None:
    while True:
        console.print()
        print_section("Балансировщики")
        balancers = repo.list_balancers()
        if balancers:
            print_balancer_table(balancers)
        else:
            print_warning("Балансировщиков нет")

        console.print()
        print_menu_item(1, "Создать")
        print_menu_item(2, "Настроить")
        print_menu_item(3, "Удалить")
        print_menu_item(0, "Назад")

        choice = prompt_line("Выбор [0 — назад]")
        if choice == "0" or not choice:
            return

        if choice == "1":
            create_balancer_interactive(
                repo,
                list_inbounds=list_inbounds,
                resolve_member_fingerprints=resolve_member_fingerprints,
            )
        elif choice == "2":
            if not balancers:
                print_warning("Сначала создайте балансировщик")
                continue
            pick = typer.prompt(
                "Номер или идентификатор (Enter — отмена)",
                default="",
            ).strip()
            tag = _resolve_balancer_tag(repo, balancers, pick)
            if tag is None:
                continue
            configure_balancer_interactive(
                repo,
                tag,
                list_inbounds=list_inbounds,
                resolve_member_fingerprints=resolve_member_fingerprints,
            )
        elif choice == "3":
            delete_balancer_interactive(repo, balancers)
        else:
            print_warning("Неизвестный пункт")