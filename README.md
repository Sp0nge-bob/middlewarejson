# middlewarejson

Прослойка между VPN-клиентами (HAPP и др.) и панелью **3x-ui**. Проксирует JSON-подписки, правит их для iOS/HAPP и пропускает base64 без изменений.

Пулы серверов задаются в 3x-ui. Отдельная функция БС-балансера объединяет
помеченные пулы A/Б в один профиль с клиентским переключением.

## Возможности

- **JSON-прокси** — relay подписки 3x-ui с заголовками (`Subscription-Userinfo` и др.)
- **ios-fix** — `mixed` → `socks`, балансер панели под LibXray iOS (leastPing / leastLoad / roundRobin / random)
- **ios-fix-dns** — все исправления ios-fix плюс TCP/UDP DNS на порт 53 через прокси/балансер (прежнее имя: ios-fix-beta)
- **БС-балансер** — отдельный переключатель: `[A]` обычные серверы + `[B]` БС-серверы → один профиль; fastest A, Б только при отказе всех A
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
| 2 | Настройки агента / режим ios-fix, ios-fix-dns или passthrough |
| 3 | Служба systemd |
| 4 | Проверить подписку |
| 5 | Запуск uvicorn вручную |

```bash
python -m app.cli settings show
python -m app.cli settings transform-mode ios-fix
python -m app.cli settings transform-mode ios-fix-dns
python -m app.cli settings allowlist-balancer on
python -m app.cli settings allowlist-balancer off
python -m app.cli settings allowlist-balancer-name "Мой VPN"
python -m app.cli settings allowlist-balancer-flag RU
python -m app.cli settings allowlist-balancer-description "VLESS / WS / TLS | JSON"
python -m app.cli settings allowlist-balancer-description auto
python -m app.cli service status
python -m app.cli service install --start
```

## Деплой

- [docs/DEPLOY.md](docs/DEPLOY.md)

## БС-балансер

В панели создайте два балансера с названиями `[A] Обычные сервера` и
`[B] БС сервера`. Поддерживаются кириллические `[А]`/`[В]` и любой регистр.
Функция включена по умолчанию, но без корректной пары меток подписка не объединяется.
Режим совместимости выбирается отдельно: `ios-fix`, `ios-fix-dns`, `passthrough`.
Для полностью неизменённого JSON выберите passthrough и выключите БС-балансер.

Пара заменяется одним профилем «Автовыбор — A → Б»; остальные профили сохраняются.
Название можно изменить через `ALLOWLIST_BALANCER_NAME` или CLI. Отдельный
`ALLOWLIST_BALANCER_FLAG=RU` добавит `🇷🇺` перед названием; код `off` убирает
добавляемый флаг. В интерактивных настройках есть пункты имени и флага.
После изменения обновите подписку в Happ. Метки `[A]`/`[B]` остаются только
в названиях исходных балансеров панели.
Обратимые ошибки кодировки UTF-8/Windows-1251 в имени исправляются при вводе
через CLI, чтении .env и ранее сохранённого значения SQLite. Если при вводе
символы потеряны или заменены, имя нужно задать заново.
Для терминала с повреждённым вводом есть явный флаг `--unicode-escaped`:
`python -m app.cli settings allowlist-balancer-name --unicode-escaped '\u0410\u0432\u0442\u043e'`
задаёт имя «Авто», используя только ASCII в команде. Без этого флага escape-последовательности
в имени не интерпретируются.

Для стандартной технической подписи первым стоит служебный VLESS/WS/TLS
`cf-description`: он направляет любые соединения в `cf-unavailable` через
`sockopt.dialerProxy` и исключён из реальных пулов и observatory. Это статическая
подпись, а не информация о текущем выбранном узле или его транспорте. Работа
подтверждена на upstream Xray 26.9.9; UI Android 4.7.1(1999) и iPhone ещё требуют
проверки. См. [исследование JSON](docs/HAPP_JSON_SUBTITLE_RESEARCH.md).

Свой текст под названием передаётся через `meta.serverDescription`.
**Отображение кастомного текста зависит от возможностей подписки Happ/ProviderID**;
отправка этого поля сама по себе его не обеспечивает.

По умолчанию `ALLOWLIST_BALANCER_DESCRIPTION=auto`: сохраняется описание исходного профиля A,
а если его нет — формируется техническая подпись первого узла A, например
`VLESS / WS / TLS | JSON`. Это статическая подпись профиля, не индикатор текущего
выбранного сервера. Свой текст задаётся командой `settings allowlist-balancer-description`
или в «Настройки → 6. БС-балансер — описание профиля»; `auto` возвращает автоматическую
подпись. Для этой команды также доступен `--unicode-escaped`. SQLite имеет приоритет
над .env; изменение видно после обновления подписки в Happ.

Точка отката перед служебным выходом: `rollback-before-happ-subtitle-2026-10-24`
(коммит `64c0391`). [Инструкция отката](docs/ROLLBACK_HAPP_SUBTITLE.md).

leastPing выбирает минимальную измеренную задержку внутри активного пула.
Даже медленный живой A имеет приоритет перед Б. На запуске непроверенные A
остаются кандидатами; переключение происходит после результатов клиентских проб,
а уже открытые соединения не мигрируют. DNS TCP/UDP:53 следует той же схеме.

При дубликатах меток, неполной паре, пересечении узлов или несовместимых шаблонах
профили остаются отдельными; причина пишется в журнал. Генератор поддерживает
штатный профиль с одним балансером на документ; нестандартные цепочки outbounds
и несколько балансеров в одном исходном документе требуют отдельной обработки.

В Happ импортируйте URL middleware. Штатная кнопка Happ/crypt5 панели использует
`subURI`, поэтому изменение только `subJsonURI` не гарантирует нужный URL импорта.
Подробнее: [конфигурация](docs/CONFIGURATION.md),
[план и статус реализации](docs/PRIORITY_FAILOVER_DESIGN.md),
[аудит iPhone](docs/IPHONE_COMPATIBILITY_AUDIT.md).

## Тесты

```bash
python -m pytest -q
```

Для проверки реального upstream ядра задайте `XRAY_TEST_BINARY` — путь к
официальному Xray v26.9.9 — и повторите команду. Эти тесты работают только с
локальными тестовыми узлами, включая DNS TCP/UDP и состояния отказа/восстановления.
Без переменной проверки ядра пропускаются. CI скачивает закреплённую версию.
Проверка upstream Windows/Linux не заменяет проверку LibXray внутри Happ на iPhone.

## Версия для отката

GitHub Release / тег `v1` сохраняет состояние до реализации БС-балансера,
включая переименование `ios-fix-beta` в `ios-fix-dns`. Старые значения режима
в `.env` и БД принимаются как алиасы нового имени.
