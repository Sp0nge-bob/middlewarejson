# Конфигурация

Все параметры задаются в файле `.env` в корне проекта. Шаблон: `.env.example`.

Настройки панели (URL, web base path, token) можно также сохранить через CLI в SQLite — но значения из `.env` **имеют приоритет**.

## Переменные окружения

### Upstream (JSON-подписка)

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `UPSTREAM_BASE_URL` | *(пусто)* | Базовый URL **sub-сервера** подписок 3x-ui. Не URL панели. |
| `UPSTREAM_JSON_PATH` | `/json` | Путь к JSON-эндпоинту upstream без `{sub_id}` |
| `UPSTREAM_VERIFY_SSL` | `true` | Проверка TLS-сертификата upstream |
| `UPSTREAM_HOST_HEADER` | *(пусто)* | Подмена заголовка `Host` при запросе к upstream |
| `REQUEST_TIMEOUT_SEC` | `15` | Таймаут HTTP-запроса к upstream (сек) |

Если `UPSTREAM_BASE_URL` пуст, используется URL панели из БД / `PANEL_API_BASE_URL` (fallback для совместимости; для production лучше задать явно).

### Агент (middleware)

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `AGENT_HOST` | `127.0.0.1` | Адрес bind uvicorn. На VPS обычно `127.0.0.1` (доступ через nginx). |
| `AGENT_PORT` | `8080` | Порт агента. Должен совпадать с `proxy_pass` в nginx. |
| `AGENT_JSON_PATH` | *(как upstream)* | Путь подписки на агенте. Пусто — берётся из `UPSTREAM_JSON_PATH`. |

### Трансформации

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `TRANSFORM_MODE` | `passthrough` | `passthrough` — без изменений; `rules` — балансировщики из SQLite |
| `DB_PATH` | `data/middleware.db` | SQLite: каталог, группы, балансировщики |

### Panel API (3x-ui)

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `PANEL_API_BASE_URL` | *(пусто)* | URL панели, напр. `https://127.0.0.1:9001` |
| `PANEL_WEB_BASE_PATH` | *(пусто)* | Web base path из настроек панели, напр. `/panel-path` |
| `PANEL_API_TOKEN` | *(пусто)* | Bearer token для Panel API |
| `PANEL_VERIFY_SSL` | *(наследует upstream)* | Проверка TLS при запросах к панели |

Panel API используется **только для чтения** (GET): список инбаундов, группы, клиенты.

### Синхронизация с панелью

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `PANEL_SYNC_ON_STARTUP` | `true` | Синхронизация каталога и групп при старте агента |
| `PANEL_SYNC_INTERVAL` | `24h` | Периодическая синхронизация: `30m`, `24h`, `7d`. Пустое значение — выкл. |

## Пример `.env` (типичный VPS)

```env
# Sub-сервер подписок (порт 2096, БЕЗ web base path)
UPSTREAM_BASE_URL=https://127.0.0.1:2096
UPSTREAM_JSON_PATH=/json
UPSTREAM_VERIFY_SSL=false

# Агент за nginx
AGENT_HOST=127.0.0.1
AGENT_PORT=8080

TRANSFORM_MODE=rules
DB_PATH=data/middleware.db

# Панель 3x-ui
PANEL_API_BASE_URL=https://127.0.0.1:9001
PANEL_WEB_BASE_PATH=/panel-path
PANEL_API_TOKEN=your-panel-api-token
PANEL_VERIFY_SSL=false

PANEL_SYNC_ON_STARTUP=true
PANEL_SYNC_INTERVAL=24h
```

## Приоритет настроек панели

1. `.env` (`PANEL_*`)
2. SQLite (через `python -m app.cli settings set`)
3. Fallback URL: `UPSTREAM_BASE_URL` → для Panel API base

В CLI при активном `.env` появится предупреждение, что значения из файла перекрывают базу.

## Маршрутизация запросов

```
Клиент HAPP
    → nginx (443) {AGENT_JSON_PATH}/{sub_id}
    → middlewarejson (AGENT_HOST:AGENT_PORT)
    → upstream (UPSTREAM_BASE_URL + UPSTREAM_JSON_PATH + sub_id)
    → трансформация (если TRANSFORM_MODE=rules)
    → ответ клиенту
```

## Troubleshooting

### DNS / connection error к upstream

- Проверьте `UPSTREAM_BASE_URL` — это должен быть **доступный** адрес sub-сервера
- Для localhost на VPS: `https://127.0.0.1:2096` + `UPSTREAM_VERIFY_SSL=false` при self-signed

### HTTP 404 от upstream

- Скорее всего `UPSTREAM_BASE_URL` указывает на **панель**, а не на sub-сервер
- В логах при старте: предупреждение, если upstream URL содержит `PANEL_WEB_BASE_PATH`
- Сверьте URL с JSON-ссылкой в карточке клиента 3x-ui

### Балансировщики не работают

- `TRANSFORM_MODE` должен быть `rules`
- Выполните синхронизацию каталога и групп
- Проверьте привязку балансировщика к группе / клиенту
- Перезапустите службу после изменения `.env`

### Panel API: 401 / connection refused

- П. 3 в CLI — диагностика с URL, кодом ответа и временем
- Проверьте token, `PANEL_WEB_BASE_PATH`, `PANEL_API_BASE_URL`

### Служба active, но /health не отвечает

- Порт в unit-файле должен совпадать с `AGENT_PORT`
- Переустановите службу: CLI п. 5 или `python -m app.cli service install`