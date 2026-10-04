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
git fetch origin main

local_sha="$(git rev-parse HEAD 2>/dev/null || true)"
remote_sha="$(git rev-parse origin/main 2>/dev/null || true)"
remote_short="$(git rev-parse --short origin/main 2>/dev/null || echo "${remote_sha:0:7}")"
commit_title="$(git log -1 --format='%s' origin/main 2>/dev/null | head -n 1 | tr -d '\r' || true)"

if [[ -n "$local_sha" && -n "$remote_sha" && "$local_sha" == "$remote_sha" ]]; then
  echo "Код уже актуален: ${remote_short}${commit_title:+ — $commit_title}"
  echo "Обновление и перезапуск службы не требуются"
  exit 0
fi

echo "Обновление: ${local_sha:0:7} → ${remote_short}${commit_title:+ — $commit_title}"
git merge --ff-only origin/main

if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -r requirements.txt -q
fi

if systemctl is-active --quiet middlewarejson 2>/dev/null; then
  systemctl restart middlewarejson
  echo "middlewarejson restarted (system unit) — ${remote_short}${commit_title:+: $commit_title}"
elif systemctl --user is-active --quiet middlewarejson 2>/dev/null; then
  systemctl --user restart middlewarejson
  echo "middlewarejson restarted (user unit) — ${remote_short}${commit_title:+: $commit_title}"
else
  echo "updated to ${remote_short}${commit_title:+ ($commit_title)} (service not running via systemd)"
fi