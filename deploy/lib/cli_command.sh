# shellcheck shell=bash
# Системная команда middlewarejson → deploy/middlewarejson-ctl.sh (или python -m app.cli)

MIDDLEWAREJSON_BIN="${MIDDLEWAREJSON_BIN:-/usr/local/bin/middlewarejson}"

install_middlewarejson_command() {
    : "${APP_DIR:?}"
    local ctl="$APP_DIR/deploy/middlewarejson-ctl.sh"
    if [[ ! -f "$ctl" ]]; then
        echo "WARN: Нет $ctl — команда middlewarejson не установлена" >&2
        return 1
    fi
    [[ -x "$ctl" ]] || chmod 755 "$ctl"

    mkdir -p "$(dirname "$MIDDLEWAREJSON_BIN")"
    cat >"$MIDDLEWAREJSON_BIN" <<EOF
#!/usr/bin/env bash
# CaelixFlow MiddlewareJSON — ярлык на CLI (создаётся install / update)
# Не редактируйте вручную: перезаписывается при установке.
set -euo pipefail
APP_DIR=$(printf '%q' "$APP_DIR")
CTL="\$APP_DIR/deploy/middlewarejson-ctl.sh"
if [[ ! -f "\$CTL" ]]; then
    echo "ERR: не найден \$CTL — middlewarejson перемещён или удалён" >&2
    exit 1
fi
exec bash "\$CTL" "\$@"
EOF
    chmod 755 "$MIDDLEWAREJSON_BIN"
    ln -sf "$MIDDLEWAREJSON_BIN" /usr/local/bin/mwjson 2>/dev/null || true
    echo "Команда: $MIDDLEWAREJSON_BIN (и mwjson) → middlewarejson"
    return 0
}

remove_middlewarejson_command() {
    if [[ -f "$MIDDLEWAREJSON_BIN" ]]; then
        rm -f "$MIDDLEWAREJSON_BIN"
        rm -f /usr/local/bin/mwjson 2>/dev/null || true
        echo "Удалена команда $MIDDLEWAREJSON_BIN"
    else
        echo "Команды middlewarejson уже нет"
    fi
}

ensure_middlewarejson_command() {
    : "${APP_DIR:?}"
    if [[ -x "$MIDDLEWAREJSON_BIN" ]]; then
        if ! grep -qF "$APP_DIR" "$MIDDLEWAREJSON_BIN" 2>/dev/null; then
            install_middlewarejson_command || true
        fi
        return 0
    fi
    install_middlewarejson_command || true
}
