# middlewarejson

Middleware между VPN-клиентами (HAPP и др.) и панелью **3x-ui**. Проксирует JSON-подписки по настраиваемому пути (`UPSTREAM_JSON_PATH`), сохраняет заголовки upstream и применяет трансформации: балансировщики по группам клиентов, теги, фильтры.

**English:** JSON subscription proxy and transform layer for 3x-ui — passthrough or rules-based balancers per client group.

## Возможности

- **Прозрачный прокси** — relay JSON без изменений (`TRANSFORM_MODE=passthrough`)
- **Балансировщики** — объединение нескольких инбаундов в один профиль HAPP по группе клиента
- **Синхронизация с панелью** — каталог инбаундов и группы клиентов через Panel API (только GET)
- **CLI** — интерактивное меню на русском: настройки, синхронизация, балансировщики, systemd
- **Systemd** — установка и управление службой из CLI

## Требования

- Python 3.11+
- Linux (для production и systemd; разработка возможна на Windows)
- Панель 3x-ui с JSON-подписками и Panel API token

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

Частая ошибка — указать в `UPSTREAM_BASE_URL` URL **панели** вместо **sub-сервера** подписок.

| Что | Порт / путь | Переменные |
|-----|-------------|------------|
| JSON-подписка (upstream) | Отдельный порт (часто `2096`), **без** web base path | `UPSTREAM_BASE_URL`, `UPSTREAM_JSON_PATH` |
| Panel API | Порт панели + web base path | `PANEL_API_BASE_URL`, `PANEL_WEB_BASE_PATH`, `PANEL_API_TOKEN` |

Скопируйте JSON URL из карточки клиента в 3x-ui и разбейте на base + path:

```
https://node1.example.com/<ваш-путь>/abcd1234efgh5678
  → UPSTREAM_BASE_URL=https://node1.example.com
  → UPSTREAM_JSON_PATH=/<ваш-путь>
```

Подробнее: [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Меню CLI

```bash
python -m app.cli
```

| # | Раздел | Действие |
|---|--------|----------|
| 1 | Настройки | Показать / изменить настройки панели |
| 2 | Настройки | Показать настройки скрипта (.env) |
| 3 | Настройки | Проверить подключение к Panel API |
| 4 | Настройки | Состояние systemd-службы |
| 5 | Настройки | Установить службу systemd |
| 6–7 | Данные панели | Список инбаундов / групп |
| 8 | Настройка JSON | Балансировщики |
| 9 | Синхронизация | Каталог + группы клиентов |
| 10 | Отладка | Запуск uvicorn вручную |

Команды Typer (без меню):

```bash
python -m app.cli settings show
python -m app.cli catalog sync
python -m app.cli group sync
python -m app.cli service status
python -m app.cli service install --start
python -m app.cli balancer create --name "Pool" --members 1,7
```

## Балансировщики

1. Установите `TRANSFORM_MODE=rules` в `.env`
2. Синхронизируйте каталог (п. 9 в меню)
3. Создайте балансировщик (п. 8) — выберите инбаунды, стратегию, область (группа / клиент)
4. Перезапустите службу

Балансировщики хранятся в SQLite (`data/middleware.db`). Правила YAML (`config/rules.yaml`) — опционально для тегирования; скопируйте из `config/rules.example.yaml`.

## Деплой

Production-развёртывание (nginx, systemd, обновление):

- [docs/DEPLOY.md](docs/DEPLOY.md)

Кратко:

```bash
chmod 600 .env
python -m app.cli          # п. 5 — установить systemd
# nginx: см. deploy/nginx.conf.example
```

## Документация

| Файл | Содержание |
|------|------------|
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Все переменные `.env`, приоритеты, troubleshooting |
| [docs/DEPLOY.md](docs/DEPLOY.md) | VPS, nginx, systemd, обновление |
| [docs/TZ.md](docs/TZ.md) | Техническое задание |
| [SECURITY.md](SECURITY.md) | Секреты, ротация токенов, отчёт об уязвимостях |

## Безопасность

- Файл `.env` **не коммитится** — см. `.env.example`
- Токен панели маскируется в CLI (`abcd...wxyz`)
- После публикации репозитория **ротируйте** Panel API token в 3x-ui
- `chmod 600 .env` на сервере

## Разработка

```bash
pip install -r requirements.txt
pytest -q
```

## Лицензия

MIT — см. [LICENSE](LICENSE).