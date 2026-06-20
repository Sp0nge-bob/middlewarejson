#!/usr/bin/env bash
# Update middlewarejson on the server and restart systemd service.
#
# Usage:
#   ./deploy/update.sh
#   export APP_DIR=/path/to/project && ./deploy/update.sh

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/middlewarejson}"

if [[ ! -d "$APP_DIR" ]]; then
  echo "APP_DIR not found: $APP_DIR" >&2
  echo "Set APP_DIR to your project path, e.g. export APP_DIR=/opt/middlewarejson" >&2
  exit 1
fi

cd "$APP_DIR"
git pull --ff-only origin main

if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -r requirements.txt -q
fi

if systemctl is-active --quiet middlewarejson 2>/dev/null; then
  systemctl restart middlewarejson
  echo "middlewarejson restarted (system unit)"
elif systemctl --user is-active --quiet middlewarejson 2>/dev/null; then
  systemctl --user restart middlewarejson
  echo "middlewarejson restarted (user unit)"
else
  echo "updated (service not running via systemd)"
fi