#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE=garmin-coach
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$SERVICE.service"
export PATH="$HOME/.local/bin:$PATH"
cd "$ROOT"

git fetch --quiet origin main
old=$(git rev-parse HEAD)
new=$(git rev-parse origin/main)
[[ $old == "$new" ]] && exit 0

echo "Updating $(git log -1 --format='%h %s' "$old") -> $(git log -1 --format='%h %s' "$new")"
git merge --ff-only --quiet origin/main
changed=$(git diff --name-only "$old" "$new")

(cd backend && uv sync --frozen --quiet)
if grep -q '^frontend/' <<<"$changed"; then
  echo "Rebuilding the web UI"
  (cd frontend && npm ci --silent && npm run build --silent >/dev/null)
fi

systemctl --user restart "$SERVICE"
port=$(grep -oP -- '--port \K[0-9]+' "$UNIT" || echo 8000)
for _ in $(seq 1 30); do
  if curl -fs -o /dev/null --max-time 2 "http://127.0.0.1:$port/health"; then
    echo "The coach is running $(git log -1 --format='%h')"
    exit 0
  fi
  sleep 1
done
echo "The coach did not answer on port $port after the update. See: journalctl --user -u $SERVICE -n 50"
exit 1
