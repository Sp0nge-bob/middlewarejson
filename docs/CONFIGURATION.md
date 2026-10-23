# Конфигурация

Все параметры задаются в файле `.env` в корне проекта. Шаблон: `.env.example`.

Режим трансформации и отдельную функцию БС-балансера можно переключать через CLI
в SQLite — значение из базы имеет приоритет над `.env` и действует без перезапуска.

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
| `TRANSFORM_MODE` | `ios-fix` | `ios-fix` — совместимость 3x-ui/Happ iOS; `ios-fix-dns` — те же исправления плюс DNS TCP/UDP:53 через прокси/балансер; `passthrough` — без iOS-исправлений. Старое имя `ios-fix-beta` принимается как алиас `ios-fix-dns`. Base64 передаётся без изменений. |
| `ALLOWLIST_BALANCER_ENABLED` | `true` | Независимая функция композиции пары `[A]`/`[B]` из remarks. Не новый TRANSFORM_MODE. Без однозначной пары композиция не применяется. |
| `ALLOWLIST_PROBE_URL` | `https://www.gstatic.com/generate_204` | Общий HTTPS endpoint для клиентских проб A/Б; без credentials и fragment. Должен быть доступен через все VPN-выходы. |
| `ALLOWLIST_PROBE_INTERVAL_SEC` | `20` | Пауза между раундами ordinary observatory, 1–3600 секунд. Время обнаружения включает длительность проб; переключение ровно за этот интервал не гарантируется. |
| `DB_PATH` | `data/middleware.db` | SQLite: режим трансформации и независимый переключатель БС-балансера |

Исходные два балансера создаются в панели. Агент выбирает их по меткам remarks
`[A]`/`[А]` и `[B]`/`[В]`, разрешает selectors в доступные подписчику outbounds
и заменяет пару одним составным профилем. Структура сервера не пересобирается;
все credentials, transport/path, TLS/SNI/ALPN сохраняются.

```bash
python -m app.cli settings transform-mode ios-fix-dns
python -m app.cli settings allowlist-balancer on
python -m app.cli settings allowlist-balancer off
```

В интерактивном меню переключатель находится в «Настройки → БС-балансер».
Выключение функции не меняет выбранный IOS-FIX. Для полностью неизменённого
JSON нужны одновременно passthrough и выключенный БС-балансер. В составном
профиле DNS TCP/UDP:53 всегда следует политике A → Б во всех трёх режимах;
DoH/DoT, Tunnel DNS и bootstrap проверяются отдельно.

Передаются HWID request headers панели и диагностические X-Hwid-* ответы,
ProviderID, Hide-Settings, DNS-From-JSON-Enable и URL обновления. Если используются
new-url/fallback-url/new-domain, они должны сохранять маршрут через middleware.

## Пример `.env` (типичный VPS)

```env
UPSTREAM_BASE_URL=https://127.0.0.1:2096
UPSTREAM_JSON_PATH=/json
UPSTREAM_VERIFY_SSL=false

AGENT_HOST=127.0.0.1
AGENT_PORT=8080

TRANSFORM_MODE=ios-fix
ALLOWLIST_BALANCER_ENABLED=true
ALLOWLIST_PROBE_URL=https://www.gstatic.com/generate_204
ALLOWLIST_PROBE_INTERVAL_SEC=20
DB_PATH=data/middleware.db
```

Скопируйте JSON URL из карточки клиента в 3x-ui:

```
https://example.com/<ваш-путь>/abcd1234efgh5678
  → UPSTREAM_BASE_URL=https://example.com
  → UPSTREAM_JSON_PATH=/<ваш-путь>
```
