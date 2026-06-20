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

SCOPE_PRIORITY: dict[BalancerScope, int] = {
    "client": 3,
    "group": 2,
    "all": 1,
    "disabled": 0,
}


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