#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/middlewarejson}"

cd "$APP_DIR"
git pull --ff-only origin main

if [[ -d .venv ]]; then
  source .venv/bin/activate
  pip install -r requirements.txt -q
fi

if systemctl is-active --quiet middlewarejson 2>/dev/null; then
  systemctl restart middlewarejson
  echo "middlewarejson restarted"
else
  echo "updated (service not running via systemd)"
fi