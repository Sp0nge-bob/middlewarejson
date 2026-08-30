# Конфигурация

Все параметры задаются в файле `.env` в корне проекта. Шаблон: `.env.example`.

Режим трансформации можно также переключить через CLI в SQLite — значение из базы имеет приоритет над `.env`.

## Переменные окружения

### Upstream (JSON-подписка)

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `UPSTREAM_BASE_URL` | *(пусто)* | Базовый URL **sub-сервера** подписок 3x-ui. Не URL панели. |
| `UPSTREAM_JSON_PATH` | `/json` | Путь к JSON-эндпоинту upstream без `{sub_id}` |
| `UPSTREAM_VERIFY_SSL` | `true` | Проверка TLS-сертификата upstream |
| `UPSTREAM_HOST_HEADER` | *(пусто)* | Подмена заголовка `Host` при запросе к upstream |
| `REQUEST_TIMEOUT_SEC` | `15` | Таймаут HTTP-запроса к upstream (сек) |

### Агент (middleware)

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `AGENT_HOST` | `127.0.0.1` | Адрес bind uvicorn. На VPS обычно `127.0.0.1` (доступ через nginx). |
| `AGENT_PORT` | `8080` | Порт агента. Должен совпадать с `proxy_pass` в nginx. |
| `AGENT_JSON_PATH` | *(как upstream)* | Путь подписки на агенте. Пусто — берётся из `UPSTREAM_JSON_PATH`. |

### Трансформации

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `TRANSFORM_MODE` | `ios-fix` | `ios-fix` — `mixed` → `socks`, балансер 3x-ui под iOS (leastPing/leastLoad/roundRobin/random); `passthrough` — без изменений. JSON обрабатывается, base64 уходит навылет. |
| `DB_PATH` | `data/middleware.db` | SQLite: только режим трансформации |

Балансировщики 3x-ui не создаются скриптом — их отдаёт панель. Агент только правит JSON для HAPP iOS.

## Пример `.env` (типичный VPS)

```env
UPSTREAM_BASE_URL=https://127.0.0.1:2096
UPSTREAM_JSON_PATH=/json
UPSTREAM_VERIFY_SSL=false

AGENT_HOST=127.0.0.1
AGENT_PORT=8080

TRANSFORM_MODE=ios-fix
DB_PATH=data/middleware.db
```

Скопируйте JSON URL из карточки клиента в 3x-ui:

```
https://example.com/<ваш-путь>/abcd1234efgh5678
  → UPSTREAM_BASE_URL=https://example.com
  → UPSTREAM_JSON_PATH=/<ваш-путь>
```
