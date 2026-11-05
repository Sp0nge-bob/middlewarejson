#!/usr/bin/env bash
# ==============================================================================
# CaelixFlow MiddlewareJSON — Миграция проекта из /root/middlewarejson в /opt/middlewarejson
# ==============================================================================

set -euo pipefail

SRC="/root/middlewarejson"
DEST="/opt/middlewarejson"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
PLAIN='\033[0m'

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}[ERROR]${PLAIN} Скрипт миграции должен быть запущен от root (sudo)." >&2
    exit 1
fi

echo -e "${CYAN}================================================================${PLAIN}"
echo -e "   Миграция CaelixFlow MiddlewareJSON: $SRC → $DEST             "
echo -e "${CYAN}================================================================${PLAIN}"

# Проверка: возможно, миграция уже выполнена
if [[ -L "$SRC" ]]; then
    target="$(readlink -f "$SRC" || true)"
    if [[ "$target" == "$DEST" ]]; then
        echo -e "${GREEN}[OK]${PLAIN} Проект уже находится в $DEST ($SRC — активный симлинк)."
        exit 0
    fi
fi

if [[ ! -d "$SRC" ]]; then
    echo -e "${RED}[ERROR]${PLAIN} Исходная директория $SRC не найдена." >&2
    exit 1
fi

if [[ "$SRC" == "$DEST" ]]; then
    echo -e "${YELLOW}[WARN]${PLAIN} Исходная и целевая директории совпадают ($SRC)."
    exit 0
fi

# 1. Остановка службы systemd
echo -e "${CYAN}[1/6]${PLAIN} Остановка службы middlewarejson..."
systemctl stop middlewarejson 2>/dev/null || true

# 2. Подготовка целевой папки /opt/middlewarejson
echo -e "${CYAN}[2/6]${PLAIN} Копирование данных в $DEST..."
mkdir -p /opt
if [[ -d "$DEST" ]]; then
    backup_dest="${DEST}.bak.$(date +%s)"
    echo -e "${YELLOW}[WARN]${PLAIN} Папка $DEST уже существовала. Создана резервная копия: $backup_dest"
    mv "$DEST" "$backup_dest"
fi

cp -a "$SRC" "$DEST"

# 3. Пересоздание виртуального окружения (пути в .venv жестко привязаны к старому пути)
echo -e "${CYAN}[3/6]${PLAIN} Пересоздание виртуального окружения Python (.venv)..."
rm -rf "$DEST/.venv"
if ! command -v python3 >/dev/null 2>&1; then
    apt-get update -y -q && apt-get install -y -q python3 python3-venv python3-pip
fi

python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install --upgrade pip -q
"$DEST/.venv/bin/pip" install -r "$DEST/requirements.txt" -q

# 4. Мягкая обратная совместимость: создание симлинка /root/middlewarejson -> /opt/middlewarejson
echo -e "${CYAN}[4/6]${PLAIN} Настройка мягкой обратной совместимости ($SRC → $DEST)..."
backup_root="${SRC}.bak.$(date +%s)"
mv "$SRC" "$backup_root"
ln -s "$DEST" "$SRC"

# 5. Обновление системного ярлыка
echo -e "${CYAN}[5/6]${PLAIN} Обновление системных команд /usr/local/bin/middlewarejson и mwjson..."
APP_DIR="$DEST"
if [[ -f "$DEST/deploy/lib/cli_command.sh" ]]; then
    # shellcheck source=deploy/lib/cli_command.sh
    source "$DEST/deploy/lib/cli_command.sh"
    install_middlewarejson_command
fi

# 6. Обновление unit-файла systemd и запуск службы
echo -e "${CYAN}[6/6]${PLAIN} Обновление и запуск службы systemd..."
"$DEST/.venv/bin/python" -m app.cli service install --start >/dev/null 2>&1 || true

# Проверка health
HEALTH_OK=false
for _ in {1..10}; do
    if curl -s http://127.0.0.1:8080/health | grep -q '"status":"ok"'; then
        HEALTH_OK=true
        break
    fi
    sleep 0.5
done

echo
echo -e "${GREEN}================================================================${PLAIN}"
echo -e "${GREEN}  ✔ Миграция в $DEST успешно завершена!                         ${PLAIN}"
echo -e "${GREEN}================================================================${PLAIN}"
echo -e "  Статус службы:        $([ "$HEALTH_OK" == "true" ] && echo -e "${GREEN}работает (HTTP 200 OK)${PLAIN}" || echo -e "${YELLOW}проверьте через systemctl${PLAIN}")"
echo -e "  Новый путь:           ${CYAN}$DEST${PLAIN}"
echo -e "  Симлинк совместимости:${CYAN}$SRC → $DEST${PLAIN}"
echo -e "  Резервная копия:      ${CYAN}$backup_root${PLAIN}"
echo -e "  Команда управления:   ${GREEN}middlewarejson${PLAIN} (или ${GREEN}mwjson${PLAIN})"
echo -e "${GREEN}================================================================${PLAIN}"
