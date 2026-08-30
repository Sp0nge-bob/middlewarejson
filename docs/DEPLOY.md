# Развёртывание (production)

Руководство для VPS с nginx и systemd. Подходит для машин от 1 CPU / 1 GB RAM.

## 1. Установка

```bash
sudo mkdir -p /opt
sudo git clone https://github.com/Sp0nge-bob/middlewarejson.git /opt/middlewarejson
cd /opt/middlewarejson

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

`TRANSFORM_MODE=ios-fix` — режим по умолчанию (совместимость HAPP iOS).

## 2. Первичная настройка через CLI

```bash
source .venv/bin/activate
python -m app.cli
```

1. Проверьте upstream в `.env` (`UPSTREAM_BASE_URL` = sub-сервер 3x-ui)
2. Превью подписки
3. Ручной запуск / systemd

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

## 3. Nginx

Фрагмент для существующего `server { listen 443 ssl; ... }`:

```nginx
location <AGENT_JSON_PATH>/ {
    proxy_pass http://127.0.0.1:8080;   # порт = AGENT_PORT из .env
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

```bash
python -m app.cli service status
python -m app.cli service start
python -m app.cli service restart
```

```bash
systemctl --user status middlewarejson
systemctl --user restart middlewarejson
journalctl --user -u middlewarejson -f
```

## 5. Обновление

Скрипт [deploy/update.sh](../deploy/update.sh):

```bash
chmod +x deploy/update.sh
./deploy/update.sh
```

Или вручную:

```bash
cd /opt/middlewarejson
git pull
source .venv/bin/activate
pip install -r requirements.txt -q
systemctl --user restart middlewarejson
```

После изменения `.env` всегда перезапускайте службу.

## 6. Чеклист

- [ ] `.env` не в git, права `600`
- [ ] `UPSTREAM_BASE_URL` — sub-сервер, не панель
- [ ] nginx проксирует `http://127.0.0.1:<AGENT_PORT>` (не https)
- [ ] `TRANSFORM_MODE=ios-fix`
- [ ] `/health` отвечает через loopback
- [ ] JSON-подписка в HAPP на iPhone открывается, Автовыбор — пул 3x-ui
