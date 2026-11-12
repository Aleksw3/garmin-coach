#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE=garmin-coach
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$SERVICE.service"
export PATH="$HOME/.local/bin:$PATH"
cd "$ROOT"
WEB_BUILT_FROM="$(git rev-parse --git-dir)/coach-web-built-from"

git fetch --quiet origin main
if [[ $(git rev-parse HEAD) != $(git rev-parse origin/main) ]] && git merge-base --is-ancestor HEAD origin/main; then
  echo "Updating $(git log -1 --format='%h %s') -> $(git log -1 --format='%h %s' origin/main)"
  git merge --ff-only --quiet origin/main
fi

# The checkout can be ahead of the build and the server after a pull or a reset by hand,
# so compare what is checked out with what was built and what is running.
checked_out=$(git log -1 --format=%h)
port=$(grep -oP -- '--port \K[0-9]+' "$UNIT" 2>/dev/null || echo 8000)
running=$(curl -fs --max-time 2 "http://127.0.0.1:$port/api/version" | grep -oP '"commit":"\K[^"]+' || true)

web_is_current() {
  [[ -f frontend/dist/index.html && -s $WEB_BUILT_FROM ]] &&
    git diff --quiet "$(cat "$WEB_BUILT_FROM")" HEAD -- frontend 2>/dev/null
}

if [[ $running == "$checked_out" ]] && web_is_current; then
  exit 0
fi

(cd backend && uv sync --frozen --quiet)
if ! web_is_current; then
  echo "Rebuilding the web UI"
  (cd frontend && npm ci --silent && npm run build --silent >/dev/null)
  git rev-parse HEAD >"$WEB_BUILT_FROM"
fi

if [[ $running != "$checked_out" ]]; then
  echo "Restarting the coach, which ran ${running:-nothing} and should run $checked_out"
  systemctl --user restart "$SERVICE"
fi
for _ in $(seq 1 30); do
  if curl -fs -o /dev/null --max-time 2 "http://127.0.0.1:$port/health"; then
    echo "The coach is running $checked_out"
    exit 0
  fi
  sleep 1
done
echo "The coach did not answer on port $port after the update. See: journalctl --user -u $SERVICE -n 50"
exit 1
