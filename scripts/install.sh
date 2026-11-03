#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE=garmin-coach
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
export PATH="$HOME/.local/bin:$PATH"

bold=$(tput bold 2>/dev/null || true)
plain=$(tput sgr0 2>/dev/null || true)

step() { printf '\n%s== %s ==%s\n' "$bold" "$1" "$plain"; }
info() { printf '%s\n' "$@"; }

ask() {
  local prompt=$1 default=$2 answer
  read -rp "$prompt [$default]: " answer
  printf '%s' "${answer:-$default}"
}

confirm() {
  local prompt=$1 default=${2:-y} answer
  if [[ $default == y ]]; then
    read -rp "$prompt [Y/n]: " answer
  else
    read -rp "$prompt [y/N]: " answer
  fi
  answer=${answer:-$default}
  [[ ${answer,,} == y* ]]
}

node_major() {
  if command -v node >/dev/null; then
    node -p 'process.versions.node.split(".")[0]'
  else
    echo 0
  fi
}

install_node() {
  local version=24 arch base name tmp
  case $(uname -m) in
    x86_64) arch=x64 ;;
    aarch64 | arm64) arch=arm64 ;;
    armv7l) arch=armv7l version=22 ;;
    *) return 1 ;;
  esac
  base=https://nodejs.org/dist/latest-v$version.x
  tmp=$(mktemp -d)
  curl -fsSL "$base/SHASUMS256.txt" -o "$tmp/SHASUMS256.txt" || return 1
  name=$(grep -o "node-v[0-9.]*-linux-$arch\.tar\.gz" "$tmp/SHASUMS256.txt" | head -1)
  [[ -n $name ]] || return 1
  info "Downloading $name"
  curl -fL --progress-bar "$base/$name" -o "$tmp/$name" || return 1
  (cd "$tmp" && grep " $name\$" SHASUMS256.txt | sha256sum -c --quiet -) || return 1
  mkdir -p "$HOME/.local/opt" "$HOME/.local/bin"
  tar -xzf "$tmp/$name" -C "$HOME/.local/opt" || return 1
  for tool in node npm npx; do
    ln -sf "$HOME/.local/opt/${name%.tar.gz}/bin/$tool" "$HOME/.local/bin/$tool"
  done
  rm -rf "$tmp"
  hash -r
}

user_systemd() { command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; }

info "${bold}Garmin coach install${plain}" \
  "This script installs what the app needs, builds it and starts it. Everything" \
  "else, like the Claude key and the Garmin login, happens in the app afterwards." \
  "Run it again after a git pull to rebuild and restart. Press Ctrl+C to stop."

step "1. Tools"
info "The backend needs uv, which installs Python and the packages. The web UI needs Node 20 or newer."
if ! command -v uv >/dev/null; then
  if confirm "uv is missing. Install it from astral.sh now?"; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  else
    info "Install uv from https://docs.astral.sh/uv/ and run this script again."
    exit 1
  fi
fi
if [[ $(node_major) -lt 20 ]] || ! command -v npm >/dev/null; then
  if command -v node >/dev/null; then
    info "Node $(node --version) is too old, the web UI needs 20 or newer."
  else
    info "Node is missing."
  fi
  info "The script can download the current Node LTS from nodejs.org into" \
    "$HOME/.local/opt and link it from $HOME/.local/bin. It needs no sudo and leaves the" \
    "system's Node alone."
  if confirm "Install Node now?" && install_node && [[ $(node_major) -ge 20 ]]; then
    info "Installed Node $(node --version)."
  else
    info "Install Node 20 or newer from https://nodejs.org and run this script again."
    exit 1
  fi
fi
info "uv $(uv --version | cut -d' ' -f2) and Node $(node --version) are installed."

step "2. Build"
info "Installing the Python packages and building the web UI. This takes a minute or two."
(cd "$ROOT/backend" && uv sync --quiet)
(cd "$ROOT/frontend" && npm ci --silent && npm run build --silent >/dev/null)
info "Done."
if [[ -f ${DATA_DIR:-$ROOT/data}/coach.db && ! -d ${DATA_DIR:-$ROOT/data}/profiles ]]; then
  info "" "There is data in the old single-person layout. Move it into a profile with:" \
    "  cd backend && uv run coach profile adopt <name>" "and run this script again."
  exit 1
fi

step "3. Start on boot"
if ! user_systemd; then
  info "systemd isn't available for your user here, so start the app yourself:" \
    "  cd $ROOT/backend && uv run coach serve --host 0.0.0.0"
  exit 0
fi
info "The app runs as a systemd service for your user. It starts when the machine" \
  "boots, restarts if it crashes, and syncs with Garmin every hour."
host=127.0.0.1
if confirm "Reach it from other devices on the network or VPN? The app has no login."; then
  host=0.0.0.0
fi
port=$(ask "Port" 8000)
if systemctl --user is-active --quiet "$SERVICE"; then
  systemctl --user stop "$SERVICE"
fi
if curl -fs -o /dev/null --max-time 2 "http://127.0.0.1:$port/health"; then
  info "Something already answers on port $port, probably a coach you started by hand." \
    "Stop it with Ctrl+C where it runs, then run this script again."
  exit 1
fi
mkdir -p "$UNIT_DIR"
cat >"$UNIT_DIR/$SERVICE.service" <<EOF
[Unit]
Description=Garmin coach

[Service]
WorkingDirectory=$ROOT/backend
ExecStart=$(command -v uv) run --frozen coach serve --host $host --port $port
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE"

if [[ $(loginctl show-user "$USER" -p Linger --value 2>/dev/null) != yes ]]; then
  info "" "Right now the service only runs while you are logged in. To start it at boot" \
    "without logging in, systemd needs 'lingering' for your user, which takes sudo once."
  if confirm "Turn it on with sudo now?"; then
    sudo loginctl enable-linger "$USER"
  else
    info "Turn it on later with: sudo loginctl enable-linger $USER"
  fi
fi

for _ in $(seq 1 30); do
  curl -fs -o /dev/null --max-time 2 "http://127.0.0.1:$port/health" && break
  sleep 1
done
if ! curl -fs -o /dev/null --max-time 2 "http://127.0.0.1:$port/health"; then
  info "" "The app did not start. See what went wrong with:" "  journalctl --user -u $SERVICE -n 50"
  exit 1
fi

address="http://127.0.0.1:$port"
[[ $host == 0.0.0.0 ]] && address="http://$(hostname).local:$port"
step "4. Open the app"
info "The coach is running. Open $address in a browser." \
  "The first visit walks you through the Claude key, your profile, the Garmin login" \
  "and fetching your history." "" \
  "Useful commands:" \
  "  systemctl --user status $SERVICE     is it running?" \
  "  journalctl --user -u $SERVICE -f     follow the log" \
  "  systemctl --user restart $SERVICE    restart it" \
  "  systemctl --user stop $SERVICE       stop it"
