#!/usr/bin/env bash
# ==============================================================================
# CaelixFlow MiddlewareJSON — Быстрая автоматическая установка на чистый Linux
#
#   bash <(curl -Ls https://raw.githubusercontent.com/Sp0nge-bob/middlewarejson/main/install.sh)
#   или
#   bash <(wget -qO- https://raw.githubusercontent.com/Sp0nge-bob/middlewarejson/main/install.sh)
# ==============================================================================

set -euo pipefail

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PLAIN='\033[0m'

info() {
    echo -e "${CYAN}[INFO]${PLAIN} $*"
}

success() {
    echo -e "${GREEN}[OK]${PLAIN} $*"
}

warn() {
    echo -e "${YELLOW}[WARN]${PLAIN} $*"
}

error() {
    echo -e "${RED}[ERROR]${PLAIN} $*" >&2
}

# 1. Проверка прав root
if [[ $EUID -ne 0 ]]; then
    error "Этот скрипт должен быть запущен с правами root (sudo)."
    echo "Запустите команду: sudo bash <(curl -Ls https://raw.githubusercontent.com/Sp0nge-bob/middlewarejson/main/install.sh)"
    exit 1
fi

echo -e "${BLUE}"
echo "================================================================"
echo "          CaelixFlow MiddlewareJSON — Quick Installer           "
echo "   Прослойка JSON-подписок 3x-ui для iOS/Happ и БС-балансер     "
echo "================================================================"
echo -e "${PLAIN}"

# 2. Установка системных зависимостей (Debian/Ubuntu/CentOS/Alma/Rocky/Arch)
info "Проверка и установка системных пакетов (git, python3, venv, curl)..."

if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y -q
    apt-get install -y -q git curl wget python3 python3-venv python3-pip
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y -q git curl wget python3 python3-pip
elif command -v yum >/dev/null 2>&1; then
    yum install -y -q git curl wget python3 python3-pip
elif command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm git curl wget python python-pip
elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache git curl wget python3 py3-pip bash
else
    warn "Не удалось определить пакетный менеджер. Убедитесь, что git, python3 и python3-venv установлены."
fi

# Проверка наличия Python 3.11+
if ! command -v python3 >/dev/null 2>&1; then
    error "python3 не найден в системе даже после установки пакетов."
    exit 1
fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
info "Обнаружен Python версии: $PY_VER"

# 3. Определение директории установки (дефолт: /opt/middlewarejson)
DEFAULT_DIR="/opt/middlewarejson"
LEGACY_ROOT_DIR="/root/middlewarejson"

if [[ -f "$(pwd)/app/main.py" && -f "$(pwd)/requirements.txt" ]]; then
    APP_DIR="$(pwd)"
    info "Установка в текущую директорию: $APP_DIR"
elif [[ -d "$DEFAULT_DIR" ]]; then
    APP_DIR="$DEFAULT_DIR"
    info "Директория установки: $APP_DIR"
elif [[ -d "$LEGACY_ROOT_DIR" && ! -L "$LEGACY_ROOT_DIR" ]]; then
    # Мягкая миграция из /root/middlewarejson в /opt/middlewarejson
    warn "Обнаружена существующая установка в $LEGACY_ROOT_DIR."
    info "Выполняется мягкая миграция в $DEFAULT_DIR с сохранением симлинка $LEGACY_ROOT_DIR..."
    systemctl stop middlewarejson 2>/dev/null || true
    mkdir -p /opt
    cp -a "$LEGACY_ROOT_DIR" "$DEFAULT_DIR"
    rm -rf "$DEFAULT_DIR/.venv"
    backup_legacy="${LEGACY_ROOT_DIR}.bak.$(date +%s)"
    mv "$LEGACY_ROOT_DIR" "$backup_legacy"
    ln -s "$DEFAULT_DIR" "$LEGACY_ROOT_DIR"
    APP_DIR="$DEFAULT_DIR"
    success "Проект успешно перенесен в $DEFAULT_DIR (для обратной совместимости оставлен симлинк $LEGACY_ROOT_DIR)"
else
    APP_DIR="${APP_DIR:-$DEFAULT_DIR}"
    info "Директория установки: $APP_DIR"
fi

# 4. Клонирование или обновление репозитория
if [[ -d "$APP_DIR/.git" ]]; then
    info "Директория уже существует, обновляем репозиторий..."
    cd "$APP_DIR"
    git fetch origin main -q
    git reset --hard origin/main -q
else
    info "Клонирование репозитория из GitHub..."
    mkdir -p "$APP_DIR"
    git clone https://github.com/Sp0nge-bob/middlewarejson.git "$APP_DIR" -q
    cd "$APP_DIR"
fi

# 5. Создание виртуального окружения Python
info "Настройка виртуального окружения Python (.venv)..."
if [[ ! -f "$APP_DIR/.venv/bin/python" ]]; then
    python3 -m venv "$APP_DIR/.venv"
fi

# 6. Установка Python-зависимостей
info "Установка зависимостей из requirements.txt..."
"$APP_DIR/.venv/bin/pip" install --upgrade pip -q
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q
success "Зависимости успешно установлены."

# 7. Инициализация .env и директорий
mkdir -p "$APP_DIR/data"

if [[ ! -f "$APP_DIR/.env" ]]; then
    info "Создание файла конфигурации .env из .env.example..."
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    success "Файл .env создан."
else
    info "Файл .env уже существует, сохранён без изменений."
fi

# 8. Создание глобального системного ярлыка команды (middlewarejson и mwjson)
info "Установка системной команды middlewarejson в /usr/local/bin..."
if [[ -f "$APP_DIR/deploy/lib/cli_command.sh" ]]; then
    # shellcheck source=deploy/lib/cli_command.sh
    source "$APP_DIR/deploy/lib/cli_command.sh"
    install_middlewarejson_command
fi

# 9. Установка и запуск системной службы systemd
info "Настройка и запуск службы systemd (middlewarejson.service)..."
"$APP_DIR/.venv/bin/python" -m app.cli service install --start >/dev/null 2>&1 || true

# 10. Проверка работоспособности (/health)
info "Проверка статуса службы (/health)..."
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
if [[ "$HEALTH_OK" == "true" ]]; then
    echo -e "${GREEN}  ✔ MiddlewareJSON успешно установлен и запущен! (HTTP 200 OK)  ${PLAIN}"
else
    echo -e "${YELLOW}  ✔ MiddlewareJSON установлен. Проверьте запуск через меню.     ${PLAIN}"
fi
echo -e "${GREEN}================================================================${PLAIN}"
echo
echo -e "  ${CYAN}Путь к приложению:${PLAIN}    $APP_DIR"
echo -e "  ${CYAN}Управление из консоли:${PLAIN} ${GREEN}middlewarejson${PLAIN} (или ${GREEN}mwjson${PLAIN})"
echo -e "  ${CYAN}Локальный адрес:${PLAIN}      http://127.0.0.1:8080"
echo -e "  ${CYAN}Служба systemd:${PLAIN}       systemctl status middlewarejson"
echo
echo -e "${YELLOW}ВАЖНО:${PLAIN} Обязательно укажите адрес вашей панели 3x-ui!"
echo "Вы можете отредактировать $APP_DIR/.env или сделать это прямо в меню:"
echo "  1) Введите команду: middlewarejson"
echo "  2) Перейдите в раздел настроек и проверьте параметры."
echo "================================================================"
echo

# 11. Предложение сразу запустить интерактивное меню CLI
RUN_MENU=false
if [[ -t 0 ]]; then
    read -r -p "Запустить интерактивное меню настройки прямо сейчас? [Y/n]: " choice
    [[ "$choice" =~ ^[YyДд]$ || -z "$choice" ]] && RUN_MENU=true
elif [[ -c /dev/tty ]]; then
    read -r -p "Запустить интерактивное меню настройки прямо сейчас? [Y/n]: " choice </dev/tty
    [[ "$choice" =~ ^[YyДд]$ || -z "$choice" ]] && RUN_MENU=true
fi

if [[ "$RUN_MENU" == "true" ]]; then
    exec "$APP_DIR/.venv/bin/python" -m app.cli
fi
