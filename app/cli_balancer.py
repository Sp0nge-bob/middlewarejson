from __future__ import annotations

from rich.table import Table

from app.country_flags import (
    COMMON_COUNTRY_FLAGS,
    CUSTOM_FLAG_MENU_KEY,
    OTHER_FLAG_CHOICE,
    apply_flag_prefix,
    country_code_to_flag,
    extract_country_code,
    resolve_flag_choice,
    strip_leading_flag,
)
from app.cli_ui import (
    CANCEL_HINT,
    confirm_prompt,
    console,
    is_exit_choice,
    print_cancelled,
    print_error,
    print_field,
    print_info,
    print_menu_item,
    print_section,
    print_step,
    print_success,
    print_warning,
    prompt_line,
    text_prompt,
)
from app.db.repository import CatalogRepository, ClientRecord
from app.models.balancer import (
    BALANCER_SCOPES,
    BALANCER_STRATEGIES,
    STRATEGY_HINTS,
    format_hide_members,
    format_scope,
    format_strategy,
    normalize_scope,
    normalize_strategy,
)
from app.services.profile_builder import suggest_balancer_tag

SCOPE_CHOICES = list(BALANCER_SCOPES.keys())
MAX_CLIENT_RESULTS = 20
MIN_CLIENT_SEARCH_LEN = 2


def _client_display_label(client: ClientRecord) -> str:
    label = client.email or client.sub_id
    group_hint = f" [{client.group_name}]" if client.group_name else ""
    return f"{label}{group_hint}  sub_id={client.sub_id}"


def filter_clients(clients: list[ClientRecord], query: str) -> list[ClientRecord]:
    needle = query.strip().casefold()
    if not needle:
        return clients

    by_group = [client for client in clients if client.group_name.casefold() == needle]
    if by_group:
        return by_group

    matches: list[ClientRecord] = []
    for client in clients:
        if needle in client.email.casefold() or needle in client.sub_id.casefold():
            matches.append(client)
    return matches


def _find_client_by_sub_id(
    clients: list[ClientRecord],
    sub_id: str,
) -> ClientRecord | None:
    value = sub_id.strip()
    if not value:
        return None
    for client in clients:
        if client.sub_id == value:
            return client
    return None


def _prompt_client_sub_id(clients: list[ClientRecord]) -> str | None:
    total = len(clients)
    print_info(
        f"Клиентов в базе: {total}. "
        f"Введите часть имени, email или sub_id (от {MIN_CLIENT_SEARCH_LEN} символов), "
        f"или sub_id целиком."
    )

    while True:
        query = text_prompt(f"Поиск, {CANCEL_HINT}", default="").strip()
        if is_exit_choice(query):
            print_cancelled()
            return None

        exact = _find_client_by_sub_id(clients, query)
        if exact is not None:
            console.print(f"  {_client_display_label(exact)}")
            if confirm_prompt("Выбрать этого клиента?", default=True):
                return exact.sub_id
            continue

        if len(query) < MIN_CLIENT_SEARCH_LEN:
            print_warning(
                f"Слишком короткий запрос — минимум {MIN_CLIENT_SEARCH_LEN} символа "
                "или полный sub_id"
            )
            continue

        matches = filter_clients(clients, query)
        if not matches:
            print_warning("Ничего не найдено — уточните запрос")
            continue

        if len(matches) == 1:
            client = matches[0]
            console.print(f"  {_client_display_label(client)}")
            if confirm_prompt("Выбрать этого клиента?", default=True):
                return client.sub_id
            continue

        shown = matches[:MAX_CLIENT_RESULTS]
        if len(matches) > MAX_CLIENT_RESULTS:
            print_info(
                f"Найдено {len(matches)}, показаны первые {MAX_CLIENT_RESULTS}. "
                "Уточните поиск."
            )
        else:
            print_info(f"Найдено {len(matches)}")

        console.print("[bold]Выберите клиента[/bold]")
        for index, client in enumerate(shown):
            console.print(f"  {index}. {_client_display_label(client)}")

        choice = text_prompt(f"Номер клиента, {CANCEL_HINT}").strip()
        if is_exit_choice(choice):
            print_cancelled()
            return None
        try:
            return shown[int(choice)].sub_id
        except (ValueError, IndexError):
            print_error("Неверный номер")
            continue


def prompt_strategy(default: str = "roundRobin") -> str:
    console.print("[bold]Стратегия балансировки[/bold]")
    for index, strategy in enumerate(BALANCER_STRATEGIES, start=1):
        label = format_strategy(strategy)
        hint = STRATEGY_HINTS.get(strategy, "")
        suffix = f" — {hint}" if hint else ""
        mark = " [dim](по умолчанию)[/dim]" if strategy == default else ""
        console.print(f"  {index}. {label}{suffix}{mark}")
    choice = text_prompt("Выбор", default="1").strip()
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


def prompt_balancer_tag(repo: CatalogRepository) -> str | None:
    taken = {balancer.tag for balancer in repo.list_balancers()}
    suggested = suggest_balancer_tag(taken)
    while True:
        raw = text_prompt("Идентификатор", default=suggested).strip()
        if is_exit_choice(raw):
            print_cancelled()
            return None
        if not raw:
            print_warning("Идентификатор не может быть пустым")
            continue
        if repo.get_balancer_by_tag(raw) is not None:
            print_warning(f"Идентификатор «{raw}» уже занят — выберите другой")
            continue
        return raw


def prompt_hide_members(*, default: bool = True) -> bool:
    console.print("[bold]Скрывать сервера в подписке?[/bold]")
    print_info("Да — в HAPP только профиль балансировщика (серверы внутри него)")
    print_info("Нет — балансировщик и каждый сервер отдельными строками")
    return confirm_prompt("Скрывать добавленные сервера?", default=default)


def prompt_scope(repo: CatalogRepository) -> tuple[str, str] | None:
    console.print("[bold]Область применения[/bold]")
    for index, scope in enumerate(SCOPE_CHOICES, start=1):
        console.print(f"  {index}. {BALANCER_SCOPES[scope]}")
    choice = text_prompt(f"Выбор, {CANCEL_HINT}", default="1").strip()
    if is_exit_choice(choice):
        print_cancelled()
        return None
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
        group_choice = text_prompt(f"Номер группы, {CANCEL_HINT}").strip()
        if is_exit_choice(group_choice):
            print_cancelled()
            return None
        try:
            return "group", groups[int(group_choice)]
        except (ValueError, IndexError):
            group_name = text_prompt(f"Имя группы, {CANCEL_HINT}").strip()
            if is_exit_choice(group_name):
                print_cancelled()
                return None
            return "group", group_name

    if scope == "client":
        clients = repo.list_all_clients()
        if not clients:
            print_warning("Клиентов нет. Сначала выполните синхронизацию (п. 6 в меню).")
            return "disabled", ""
        sub_id = _prompt_client_sub_id(clients)
        if sub_id is None:
            return None
        return "client", sub_id

    return scope, ""


def prompt_happ_remarks(*, default: str = "Balance", current: str | None = None) -> str | None:
    default_name = strip_leading_flag(current or default)
    default_flag_code = extract_country_code(current) if current else None

    console.print("[bold]Название в HAPP[/bold]")
    print_info("Флаг в начале названия отображается в HAPP как иконка профиля")
    console.print("  0. Без флага")
    for index, (code, label) in enumerate(COMMON_COUNTRY_FLAGS, start=1):
        flag = country_code_to_flag(code) or ""
        mark = " [dim](текущий)[/dim]" if code == default_flag_code else ""
        console.print(f"  {index}. {flag} {code} — {label}{mark}")
    console.print(
        f"  {CUSTOM_FLAG_MENU_KEY}. Другой код "
        "(любые 2 буквы ISO: ch, se, kz, br…)"
    )
    print_info("Можно сразу ввести код (например ch), не только номер из списка")

    flag_default = "0"
    if default_flag_code:
        for index, (code, _) in enumerate(COMMON_COUNTRY_FLAGS, start=1):
            if code == default_flag_code:
                flag_default = str(index)
                break
        else:
            flag_default = default_flag_code.lower()

    country_code: str | None = None
    while True:
        flag_choice = text_prompt(
            f"Флаг (номер, код ch/se или {CUSTOM_FLAG_MENU_KEY} — другой), {CANCEL_HINT}",
            default=flag_default,
        ).strip()
        if is_exit_choice(flag_choice):
            print_cancelled()
            return None

        resolved = resolve_flag_choice(flag_choice)
        if resolved is None:
            print_warning("Неверный выбор — номер, 2-буквенный код или +")
            continue
        if resolved is True:
            country_code = None
            break
        if resolved is OTHER_FLAG_CHOICE:
            while True:
                custom_code = text_prompt(
                    f"Код страны (2 буквы, например ch), {CANCEL_HINT}",
                ).strip()
                if is_exit_choice(custom_code):
                    print_cancelled()
                    return None
                custom_resolved = resolve_flag_choice(custom_code)
                if isinstance(custom_resolved, str):
                    country_code = custom_resolved
                    preview = country_code_to_flag(custom_resolved) or ""
                    print_info(f"Выбран флаг: {preview} {custom_resolved}")
                    break
                print_warning("Нужен код из 2 латинских букв (ISO 3166-1)")
            break
        country_code = resolved
        break

    name = text_prompt("Название", default=default_name).strip()
    if is_exit_choice(name):
        print_cancelled()
        return None
    if not name:
        print_warning("Название не может быть пустым")
        return None

    remarks = apply_flag_prefix(name, country_code)
    print_info(f"В HAPP: {remarks}")
    return remarks


def _prompt_member_indices(rows: list) -> list[str] | None:
    if not rows:
        print_warning("Каталог инбаундов пуст. Сначала выполните синхронизацию.")
        return None

    selection = text_prompt(
        f"Номера из колонки # (например 0,2,5), {CANCEL_HINT}"
    ).strip()
    if is_exit_choice(selection):
        print_cancelled()
        return None
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
    table.add_column("Скрывает сервера")

    for index, balancer in enumerate(balancers):
        table.add_row(
            str(index),
            balancer.tag,
            balancer.remarks,
            format_strategy(balancer.strategy),
            format_scope(balancer.scope, balancer.scope_target),
            str(len(balancer.member_fingerprints)),
            format_hide_members(balancer.hide_members),
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
        print_field(
            "Скрывает сервера",
            format_hide_members(balancer.hide_members),
        )
        console.print()
        console.print("  1. Область применения")
        console.print("  2. Стратегия балансировки")
        console.print("  3. Название в HAPP")
        console.print("  4. Состав инбаундов")
        console.print("  5. Скрывать сервера в подписке")
        console.print("  0. Назад")

        choice = text_prompt("Выбор", default="0").strip()
        if choice == "0":
            return

        if choice == "1":
            scope_result = prompt_scope(repo)
            if scope_result is None:
                continue
            scope, target = scope_result
            repo.set_balancer_scope(balancer.tag, scope, target)
            print_success(f"Область применения: {format_scope(scope, target)}")
        elif choice == "2":
            strategy = prompt_strategy(default=balancer.strategy)
            repo.update_balancer(balancer.tag, strategy=strategy)
            print_success(f"Стратегия: {format_strategy(strategy)}")
        elif choice == "3":
            remarks = prompt_happ_remarks(current=balancer.remarks)
            if remarks is None:
                continue
            repo.update_balancer(balancer.tag, remarks=remarks)
            print_success(f"Название: {remarks}")
        elif choice == "4":
            rows = list_inbounds(active_only=True, for_selection=True)
            fingerprints = _prompt_member_indices(rows)
            if fingerprints is None:
                continue
            repo.update_balancer(balancer.tag, member_fingerprints=fingerprints)
            print_success(f"Состав обновлён ({len(fingerprints)} инбаундов)")
        elif choice == "5":
            hide_members = prompt_hide_members(default=balancer.hide_members)
            repo.update_balancer(balancer.tag, hide_members=hide_members)
            print_success(
                f"Скрывать сервера: {format_hide_members(hide_members)}"
            )
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
    print_step(1, 6, "Состав инбаундов")
    rows = list_inbounds(active_only=True, for_selection=True)
    fingerprints = _prompt_member_indices(rows)
    if not fingerprints:
        return

    print_step(2, 6, "Название в HAPP")
    name = prompt_happ_remarks(default="Balance")
    if name is None:
        return

    print_step(3, 6, "Идентификатор")
    tag = prompt_balancer_tag(repo)
    if tag is None:
        return

    print_step(4, 6, "Стратегия балансировки")
    strategy = prompt_strategy()

    print_step(5, 6, "Область применения")
    scope_result = prompt_scope(repo)
    if scope_result is None:
        return
    scope, scope_target = scope_result

    print_step(6, 6, "Видимость серверов в подписке")
    hide_members = prompt_hide_members(default=True)

    repo.create_balancer(
        tag=tag,
        remarks=name,
        strategy=strategy,
        member_fingerprints=fingerprints,
        scope=scope,
        scope_target=scope_target,
        hide_members=hide_members,
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

    choice = text_prompt(
        f"Номер или идентификатор для удаления (Enter — отмена, {CANCEL_HINT})",
        default="",
    ).strip()
    if is_exit_choice(choice):
        print_cancelled()
        return
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
            pick = text_prompt(
                f"Номер или идентификатор (Enter — отмена, {CANCEL_HINT})",
                default="",
            ).strip()
            if is_exit_choice(pick):
                print_cancelled()
                continue
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