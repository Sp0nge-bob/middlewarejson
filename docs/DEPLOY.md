# Развёртывание (production)

Руководство для VPS с nginx и systemd. Подходит для машин от 1 CPU / 1 GB RAM.

## 1. Установка

```bash
git clone https://github.com/Sp0nge-bob/middlewarejson.git ~/jsonscript
cd ~/jsonscript

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env   # см. docs/CONFIGURATION.md
chmod 600 .env
```

Создайте каталог данных:

```bash
mkdir -p data
```

Для балансировщиков:

```bash
cp config/rules.example.yaml config/rules.yaml
# TRANSFORM_MODE=rules в .env
```

## 2. Первичная настройка через CLI

```bash
source .venv/bin/activate
python -m app.cli
```

Рекомендуемый порядок:

1. **П. 1** — настройки панели (URL, web base path, token), если не всё в `.env`
2. **П. 3** — проверка Panel API
3. **П. 9** — синхронизация каталога и групп
4. **П. 8** — балансировщики (при `TRANSFORM_MODE=rules`)
5. **П. 10** — ручной запуск для проверки (`curl http://127.0.0.1:8085/health`)
6. **П. 5** — установка systemd

Или из командной строки:

```bash
python -m app.cli service install --start
```

### User vs system unit

- Запуск **без root** → user unit (`~/.config/systemd/user/middlewarejson.service`)
- Запуск **от root** → system unit (`/etc/systemd/system/middlewarejson.service`)

Для user unit без активной сессии:

```bash
loginctl enable-linger $USER
```

CLI подскажет эту команду после установки.

## 3. Nginx

Фрагмент для существующего `server { listen 443 ssl; ... }`:

```nginx
location /json/ {
    proxy_pass http://127.0.0.1:8085;   # AGENT_PORT из .env
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 30s;
    proxy_connect_timeout 10s;
}
```

Полный пример: [deploy/nginx.conf.example](../deploy/nginx.conf.example).

Клиенты должны получать подписку через **ваш домен** (nginx), а не напрямую на порт 3x-ui.

## 4. Управление службой

Через CLI (п. 4 в меню) или Typer:

```bash
python -m app.cli service status
python -m app.cli service start
python -m app.cli service restart
```

Прямо через systemctl (user unit):

```bash
systemctl --user status middlewarejson
systemctl --user restart middlewarejson
journalctl --user -u middlewarejson -f
```

## 5. Обновление

Скрипт [deploy/update.sh](../deploy/update.sh):

```bash
export APP_DIR=~/jsonscript   # путь к проекту
chmod +x deploy/update.sh
./deploy/update.sh
```

Или вручную:

```bash
cd ~/jsonscript
git pull
source .venv/bin/activate
pip install -r requirements.txt -q
systemctl --user restart middlewarejson   # или systemctl restart
```

После изменения `.env` всегда перезапускайте службу.

## 6. Ресурсы (1 GB VPS)

- Агент: ~50–80 MB RAM в покое
- SQLite: файл в `data/`, бэкапьте вместе с `.env`
- Синхронизация по расписанию — лёгкая; при проблемах увеличьте `PANEL_SYNC_INTERVAL`

## 7. Чеклист перед открытым доступом

- [ ] `.env` не в git, права `600`
- [ ] Panel API token ротирован после любых утечек
- [ ] `UPSTREAM_BASE_URL` — sub-сервер, не панель
- [ ] nginx проксирует только `/json/`
- [ ] `TRANSFORM_MODE=rules` если нужны балансировщики
- [ ] `/health` отвечает через loopback
- [ ] Тестовая подписка в HAPP открывается и содержит ожидаемые профили