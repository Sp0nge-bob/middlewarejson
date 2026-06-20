# Безопасность

## Конфиденциальные данные

Не публикуйте и не коммитьте:

- `PANEL_API_TOKEN` — Bearer token Panel API 3x-ui
- `PANEL_WEB_BASE_PATH` — web base path панели
- файл `.env` и каталог `data/` (SQLite с настройками и привязками)

В репозитории используйте только плейсхолдеры: `example.com`, `/panel-path`, `your-panel-api-token`.

## Рекомендации на сервере

- `chmod 600 .env`
- агент слушает `127.0.0.1`, доступ снаружи — через nginx
- после установки **смените** Panel API token в 3x-ui

## Встроенные меры

- токен маскируется в CLI (`abcd...wxyz`)
- Panel API — только GET (чтение каталога и групп)
- в логах upstream URL **без** token

## Сообщить об уязвимости

[GitHub Security Advisory](https://github.com/Sp0nge-bob/middlewarejson/security/advisories/new) или issue с пометкой «security». Не прикладывайте рабочие токены, `sub_id` пользователей и дампы `.env`.