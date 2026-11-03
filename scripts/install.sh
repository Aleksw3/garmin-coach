#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
SLUG_PATTERN='^[a-z0-9][a-z0-9-]{0,31}$'

bold=$(tput bold 2>/dev/null || true)
plain=$(tput sgr0 2>/dev/null || true)

step() { printf '\n%s== %s ==%s\n' "$bold" "$1" "$plain"; }
info() { printf '%s\n' "$@"; }

ask() {
  local prompt=$1 default=${2:-} answer
  if [[ -n $default ]]; then
    read -rp "$prompt [$default]: " answer
  else
    read -rp "$prompt: " answer
  fi
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

env_get() {
  [[ -f $ENV_FILE ]] || return 0
  grep -m1 "^$1=" "$ENV_FILE" | cut -d= -f2- | tr -d "\"'" || true
}

env_set() {
  local tmp
  tmp=$(mktemp "$ENV_FILE.XXXXXX")
  if [[ -f $ENV_FILE ]]; then
    grep -v "^$1=" "$ENV_FILE" >"$tmp" || true
  fi
  printf '%s=%s\n' "$1" "$2" >>"$tmp"
  mv "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

coach() { (cd "$ROOT/backend" && uv run --quiet coach "$@"); }

server_running() { curl -fs -o /dev/null --max-time 2 http://127.0.0.1:8000/health; }

key_status() {
  curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://api.anthropic.com/v1/models \
    -H "x-api-key: $1" -H 'anthropic-version: 2023-06-01' || true
}

info "${bold}Garmin coach setup${plain}" \
  "This script installs what the app needs, writes the settings to $ENV_FILE" \
  "and creates a profile for each person. You can run it again later to add a" \
  "profile or change the key and budget. Press Ctrl+C to stop at any time."

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
if ! command -v npm >/dev/null || [[ $(node -p 'process.versions.node.split(".")[0]') -lt 20 ]]; then
  info "Node 20 or newer is missing. On Debian or Raspberry Pi OS, install it from" \
    "https://nodejs.org or with your package manager, then run this script again."
  exit 1
fi
info "uv $(uv --version | cut -d' ' -f2) and Node $(node --version) are installed."

step "2. Anthropic API key"
info "The coach talks to Claude through the Anthropic API. The API is prepaid and" \
  "separate from a Claude.ai Pro or Max subscription, so it needs its own credits:" \
  "" \
  "  1. Sign in or create an account at https://platform.claude.com" \
  "  2. Open Settings > Billing and press Buy credits. Without credits every coach" \
  "     call fails. Credits expire after a year. Leave auto-reload off to make the" \
  "     credits you bought the most you can ever spend." \
  "  3. Open Settings > API keys and press Create key. Copy the key right away," \
  "     the console shows it only once. It starts with sk-ant-." \
  ""
api_key=$(env_get ANTHROPIC_API_KEY)
if [[ -n $api_key ]] && ! confirm "A key is already saved. Replace it?" n; then
  info "Keeping the saved key."
else
  while true; do
    read -rsp "Paste the API key (hidden), or press Enter to skip: " api_key
    echo
    if [[ -z $api_key ]]; then
      info "Skipped. The app works without a key, but the coach is off until you add one."
      break
    fi
    status=$(key_status "$api_key")
    if [[ $status == 200 ]]; then
      env_set ANTHROPIC_API_KEY "$api_key"
      info "The key works and is saved. This check is free and doesn't test the credits."
      break
    elif [[ $status == 401 ]]; then
      info "Anthropic rejected the key. Check that you copied all of it."
    else
      info "Could not check the key (HTTP $status)."
      if confirm "Save it anyway?"; then
        env_set ANTHROPIC_API_KEY "$api_key"
        break
      fi
    fi
  done
fi

step "3. Monthly budget"
info "The budget caps what the app spends on the API each month, for all profiles and" \
  "the research library together. When the month's spending reaches it, the coach" \
  "stops until the 1st. Settings in the app shows what you have spent." \
  "Chat, plans and the daily messages for two people fit in about 5 to 10 dollars."
while true; do
  current=$(env_get MONTHLY_BUDGET_USD)
  budget=$(ask "Monthly budget in US dollars" "${current:-5}")
  budget=${budget:-5}
  if [[ $budget =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    env_set MONTHLY_BUDGET_USD "$budget"
    info "Saved a budget of $budget dollars."
    break
  fi
  info "Write a number, for example 5 or 7.5."
done

step "4. Install and build"
info "Installing the Python packages and building the web UI. This takes a minute or two."
(cd "$ROOT/backend" && uv sync --quiet)
(cd "$ROOT/frontend" && npm ci --silent && npm run build --silent >/dev/null)
info "Done. The web UI is in frontend/dist."

step "5. Profiles"
info "Each person gets a profile with their own Garmin login, data, plan and coach." \
  "Everyone shares the research library. There is no app login, so anyone who can" \
  "open the app can see every profile."
if server_running; then
  info "" "The server is running on port 8000. Stop it before you add a profile, so its" \
    "hourly sync and the backfill below don't talk to Garmin at the same time."
  confirm "Continue anyway?" n || exit 1
fi
profiles=$(coach profile list)
if [[ -n $profiles ]]; then
  info "" "Profiles you have:" "$profiles"
elif [[ -f ${DATA_DIR:-$ROOT/data}/coach.db ]]; then
  info "" "There is data in the old single-person layout. Move it into a profile with:" \
    "  cd backend && uv run coach profile adopt <name>" "and run this script again."
  exit 1
fi

add_default=y
[[ -n $profiles ]] && add_default=n
while confirm $'\n'"Add a profile?" "$add_default"; do
  add_default=n
  while true; do
    slug=$(ask "Short name, lowercase letters, digits and dashes, used in paths (for example kari)")
    [[ $slug =~ $SLUG_PATTERN ]] && break
    info "Use lowercase letters, digits and dashes, for example kari or ola-n."
  done
  name=$(ask "Name shown in the app" "${slug^}")

  info "" "TRIMP turns heart rate into training load for activities where Garmin has" \
    "none. The standard factor is 1.92 for men and 1.67 for women. You can change it" \
    "later on the Goals page."
  while true; do
    trimp=$(ask "Enter m, w or a factor" "m")
    case ${trimp,,} in
      m*) trimp=1.92 ;;
      w* | f*) trimp=1.67 ;;
    esac
    [[ $trimp =~ ^[0-9]+([.][0-9]+)?$ ]] && break
    info "Enter m, w or a number such as 1.8."
  done
  coach profile add "$slug" --name "$name" --trimp "$trimp" || continue

  info "" "Next, log in to Garmin Connect as $name. The password goes to Garmin only." \
    "The app keeps a login token in data/profiles/$slug/ and uses it for every sync." \
    "If two-step verification is on, Garmin sends a code to enter here."
  logged_in=n
  while confirm "Log in to Garmin now?"; do
    if coach -p "$slug" login; then
      logged_in=y
      break
    fi
    info "The login failed. Check the email and password and try again."
  done
  if [[ $logged_in == n ]]; then
    info "Log in later with: cd backend && uv run coach -p $slug login"
    continue
  fi

  info "" "The backfill fetches past activities, sleep, HRV and other daily data. The" \
    "coach uses it for baselines and trends, so more history gives better advice." \
    "It waits 2 seconds between requests to stay friendly with Garmin, so two years" \
    "can take a couple of hours. Enter 0 to skip it and let the hourly sync fetch" \
    "the last 14 days."
  while true; do
    days=$(ask "Days of history to fetch" 730)
    [[ $days =~ ^[0-9]+$ ]] && break
    info "Write a whole number of days."
  done
  if [[ $days -gt 0 ]]; then
    resume="cd backend && uv run coach -p $slug backfill --days $days"
    info "If you stop it with Ctrl+C, this command continues where it stopped:" "  $resume"
    coach -p "$slug" backfill --days "$days" || info "The backfill stopped. Continue it with: $resume"
  fi
done

step "6. Start"
info "Start the app with:" "  cd backend && uv run coach serve" "" \
  "It runs on http://127.0.0.1:8000 and syncs every profile with Garmin each hour" \
  "from 05:00 to 23:00. Add --host 0.0.0.0 to reach it from your phone over the VPN." \
  "Restart it after adding a profile." "" \
  "In the app, pick your profile, then:" \
  "  - on Goals, add your goals" \
  "  - on Trends, add your LT1 and LT2 heart rates to get your zones" \
  "  - on Settings, enter an ntfy topic to get the coach's messages on your phone" \
  "  - on Research, press Fetch now and approve the papers the coach may use"
if server_running; then
  info "" "The server is already running. Restart it to pick up new profiles."
elif confirm $'\n'"Start the app now?" n; then
  host=127.0.0.1
  confirm "Reach it from other devices on the network or VPN?" n && host=0.0.0.0
  cd "$ROOT/backend"
  exec uv run coach serve --host "$host"
fi
