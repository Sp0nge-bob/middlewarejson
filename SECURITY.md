# Безопасность

Не публикуйте и не коммитьте файл `.env` и каталог `data/`.

## Рекомендации на сервере

- `chmod 600 .env`
- агент слушает `127.0.0.1`, доступ снаружи — через nginx

## Встроенные меры

- агент не ходит в Panel API
- в логах upstream URL без секретов

## Сообщить об уязвимости

[GitHub Security Advisory](https://github.com/Sp0nge-bob/middlewarejson/security/advisories/new) или issue с пометкой «security». Не прикладывайте `sub_id` пользователей и дампы `.env`.
