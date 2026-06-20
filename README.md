# middlewarejson

Middleware between VPN clients and a 3x-ui panel. Proxies JSON subscriptions (`/json/{sub_id}`), preserves upstream headers, and applies configurable transforms.

## Features

- **Passthrough proxy** — transparent JSON relay
- **Rules engine** — YAML-based transforms (balancers, filters, tagging)
- **Panel API sync** — inbound catalog and client groups from 3x-ui
- **Per-group balancers** — apply transforms by client group, not globally

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env — upstream URL, panel token, paths
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Health check: `curl -s http://127.0.0.1:8080/health`

## Configuration

Copy `.env.example` to `.env`. Required values depend on your setup:

| Variable | Purpose |
|---|---|
| `UPSTREAM_BASE_URL` | 3x-ui subscription origin |
| `UPSTREAM_JSON_PATH` | JSON subscription path (default `/json`) |
| `PANEL_WEB_BASE_PATH` | Panel secret web path (from panel settings) |
| `PANEL_API_TOKEN` | Bearer token for Panel API |
| `TRANSFORM_MODE` | `passthrough` or `rules` |
| `DB_PATH` | SQLite database for catalog and groups |

Panel credentials can also be stored via CLI: `python -m app.cli settings set --panel-token <token>`

## CLI

```bash
python -m app.cli                          # interactive menu
python -m app.cli catalog sync             # sync inbounds from Panel API
python -m app.cli group sync               # sync client groups
python -m app.cli balancer create \
  --name "Pool" --members 1,7              # panel inbound IDs
python -m app.cli group assign \
  --group premium --balancer pool
```

Members accept panel inbound IDs (`1,7`) or fingerprints (`vless|host|...`).

## Rules (optional)

```bash
cp config/rules.example.yaml config/rules.yaml
# set TRANSFORM_MODE=rules in .env
```

## Deploy

See `deploy/nginx.conf.example` and `deploy/middlewarejson.service`. Update paths and ports for your environment.

```bash
chmod +x deploy/update.sh
./deploy/update.sh
```

## Docs

Technical spec: [`docs/TZ.md`](docs/TZ.md).