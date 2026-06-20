from typing import Literal

BalancerScope = Literal["disabled", "group", "all", "client"]
BalancerStrategy = Literal["roundRobin", "leastLoad", "leastPing", "random"]

BALANCER_SCOPES: dict[BalancerScope, str] = {
    "disabled": "Выключен",
    "group": "Группа",
    "all": "Все клиенты",
    "client": "Один клиент",
}

BALANCER_STRATEGIES: list[BalancerStrategy] = [
    "roundRobin",
    "leastLoad",
    "leastPing",
    "random",
]

STRATEGY_LABELS: dict[BalancerStrategy, str] = {
    "roundRobin": "По очереди",
    "leastLoad": "Меньше нагрузка",
    "leastPing": "Минимальный пинг",
    "random": "Случайный выбор",
}

STRATEGY_HINTS: dict[BalancerStrategy, str] = {
    "roundRobin": "каждый запрос — следующий инбаунд по кругу",
    "leastLoad": "выбор сервера с наименьшей нагрузкой",
    "leastPing": "ближайший по задержке",
    "random": "случайный инбаунд из состава",
}

SCOPE_PRIORITY: dict[BalancerScope, int] = {
    "client": 3,
    "group": 2,
    "all": 1,
    "disabled": 0,
}


def format_strategy(strategy: str) -> str:
    return STRATEGY_LABELS.get(strategy, strategy)  # type: ignore[arg-type]


def format_hide_members(hide_members: bool) -> str:
    return "да" if hide_members else "нет"


def format_scope(scope: str, scope_target: str) -> str:
    label = BALANCER_SCOPES.get(scope, scope)  # type: ignore[arg-type]
    if scope in ("group", "client") and scope_target:
        return f"{label}: {scope_target}"
    return label


def normalize_scope(scope: str) -> BalancerScope:
    value = scope.strip().lower()
    if value in BALANCER_SCOPES:
        return value  # type: ignore[return-value]
    raise ValueError(f"unknown scope: {scope}")


def normalize_strategy(strategy: str) -> BalancerStrategy:
    value = strategy.strip()
    if value in BALANCER_STRATEGIES:
        return value  # type: ignore[return-value]
    raise ValueError(f"unknown strategy: {strategy}")