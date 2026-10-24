# Откат технической подписи Happ

Перед реализацией создан и опубликован отдельный checkpoint-коммит **64c0391**.
Неизменяемый тег: **rollback-before-happ-subtitle-2026-10-24**.
Это версия с рабочим A/B-балансером и первым blackhole, до cf-description.
Ранее опубликованный тег v1 сохраняет другой, более ранний этап — до A/B-функции.

## Откат на сервере

Из каталога службы, при чистом рабочем дереве:

```bash
git fetch origin --tags
git switch --detach rollback-before-happ-subtitle-2026-10-24
sudo systemctl restart middlewarejson
```

После перезапуска обновить подписку в Happ, затем переподключить активный профиль:
старый JSON уже импортированного подключения сам по себе не заменяется кодом сервера.
Если Git сообщает о локальных изменениях, сначала сохранить их; не применять
принудительный reset. .env, SQLite и .venv не входят в коммит и сохраняются.

## Возврат к обновлениям

```bash
git switch main
git pull --ff-only origin main
sudo systemctl restart middlewarejson
```

Обновить подписку и переподключиться в Happ. Для user-службы использовать
соответствующий `systemctl --user restart middlewarejson` вместо system unit.
