# middlewarejson

Прослойка между VPN-клиентами (HAPP и др.) и панелью **3x-ui**. Проксирует JSON-подписки, правит их для iOS/HAPP и пропускает base64 без изменений.

Балансировщики теперь в 3x-ui — скрипт их не собирает.

## Возможности

- **JSON-прокси** — relay подписки 3x-ui с заголовками (`Subscription-Userinfo` и др.)
- **ios-fix** — `mixed` → `socks`, балансер панели под LibXray iOS (leastPing / leastLoad / roundRobin / random)
- **base64 навылет** — обычная подписка 3x-ui не трогается
- **CLI** — режим, превью подписки, systemd
- **Systemd** — установка и управление службой из CLI

## Требования

- Python 3.11+
- Linux (для production и systemd; разработка возможна на Windows)
- Панель 3x-ui с JSON-подписками

## Быстрый старт

```bash
git clone https://github.com/Sp0nge-bob/middlewarejson.git
cd middlewarejson

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Отредактируйте .env — см. docs/CONFIGURATION.md

python -m app.cli                  # интерактивное меню
```

Проверка агента:

```bash
curl -s http://127.0.0.1:8080/health
# {"status":"ok"}
```

## Важно: upstream ≠ панель

`UPSTREAM_BASE_URL` — это **sub-сервер** подписок, не URL панели.

| Что | Порт / путь | Переменные |
|-----|-------------|------------|
| JSON-подписка (upstream) | Отдельный порт, **без** web base path | `UPSTREAM_BASE_URL`, `UPSTREAM_JSON_PATH` |

```
https://example.com/<ваш-путь>/abcd1234efgh5678
  → UPSTREAM_BASE_URL=https://example.com
  → UPSTREAM_JSON_PATH=/<ваш-путь>
```

Подробнее: [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Меню CLI

```bash
python -m app.cli
```

| # | Действие |
|---|----------|
| 1 | Обзор состояния |
| 2 | Настройки агента / режим ios-fix или passthrough |
| 3 | Служба systemd |
| 4 | Проверить подписку |
| 5 | Запуск uvicorn вручную |

```bash
python -m app.cli settings show
python -m app.cli settings transform-mode ios-fix
python -m app.cli service status
python -m app.cli service install --start
```

## Деплой

- [docs/DEPLOY.md](docs/DEPLOY.md)
