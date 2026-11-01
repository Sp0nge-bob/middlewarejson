#!/usr/bin/env bash
# CaelixFlow MiddlewareJSON — запуск и управление CLI прослойки
#
#   middlewarejson
#   mwjson
#   bash deploy/middlewarejson-ctl.sh [args...]

set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(cd "$DEPLOY_DIR/.." && pwd)}"
export APP_DIR

# Подключаем функцию управления системным ярлыком
if [[ -f "$DEPLOY_DIR/lib/cli_command.sh" ]]; then
    # shellcheck source=lib/cli_command.sh
    source "$DEPLOY_DIR/lib/cli_command.sh"
    ensure_middlewarejson_command 2>/dev/null || true
fi

cd "$APP_DIR"

PYTHON=""
if [[ -x "$APP_DIR/.venv/bin/python" ]]; then
    PYTHON="$APP_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PYTHON="$(command -v python)"
else
    echo "ERR: Python не найден ни в $APP_DIR/.venv, ни в системе PATH" >&2
    exit 1
fi

exec "$PYTHON" -m app.cli "$@"
