#!/usr/bin/env bash
# Deploys the latest main to this LXC. Run as root: sudo deploy/deploy.sh
# Credentials in /etc/diary-app/diary-app.env are outside the checkout and
# are never touched by the git reset below.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/diary-app}"
APP_USER="${APP_USER:-diary}"
SERVICE="${SERVICE:-diary-app}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"

run_as_app() { runuser -u "$APP_USER" -- "$@"; }

echo "==> Fetching latest main"
run_as_app git -C "$APP_DIR" fetch --prune origin
run_as_app git -C "$APP_DIR" reset --hard origin/main

echo "==> Syncing dependencies"
(cd "$APP_DIR" && run_as_app uv sync --frozen --no-dev)

echo "==> Restarting $SERVICE"
systemctl restart "$SERVICE"

echo "==> Waiting for $HEALTH_URL"
for _ in $(seq 1 15); do
  if curl --fail --silent --show-error "$HEALTH_URL" >/dev/null 2>&1; then
    echo "==> Healthy: $(git -C "$APP_DIR" rev-parse --short HEAD)"
    exit 0
  fi
  sleep 1
done

echo "!! Health check failed; recent logs:" >&2
journalctl -u "$SERVICE" -n 30 --no-pager >&2
exit 1
