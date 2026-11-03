#!/usr/bin/env bash
# shellcheck disable=SC2029  # remote commands are built on this side on purpose
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <user@host> [repo folder on the host, default garmin-coach]"
  echo "Copies the profiles, the research library and .env from this computer to the host."
  exit 1
fi

HOST=$1
REMOTE=${2:-garmin-coach}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${DATA_DIR:-$ROOT/data}"
STAMP=$(date +%Y%m%d-%H%M%S)
COACH_PROCESS='[c]oach (serve|sync|backfill)'

confirm() {
  local answer
  read -rp "$1 [y/N]: " answer
  [[ ${answer,,} == y* ]]
}

remote() { ssh "$HOST" "$@"; }

if pgrep -f "$COACH_PROCESS" >/dev/null; then
  echo "The coach is running on this computer:"
  pgrep -af "$COACH_PROCESS"
  echo "Stop it first, so the copy doesn't catch a database in the middle of a write:"
  echo "  systemctl --user stop garmin-coach, or Ctrl+C where you started it"
  exit 1
fi
if [[ ! -d $DATA/profiles ]]; then
  echo "There are no profiles in $DATA/profiles to copy."
  exit 1
fi

echo "Checking $HOST:$REMOTE"
if ! remote "test -x $REMOTE/scripts/install.sh"; then
  echo "Could not find $REMOTE/scripts/install.sh on $HOST. Clone or pull the repo there first."
  exit 1
fi
if remote "pgrep -f '$COACH_PROCESS'" >/dev/null; then
  echo "The coach is running on $HOST. Stop it there first with: systemctl --user stop garmin-coach"
  exit 1
fi

profiles=$(cd "$DATA/profiles" && ls)
echo "Profiles to copy: $(echo "$profiles" | tr '\n' ' ')"
echo "Research library: $(du -h "$DATA/research.db" | cut -f1)"
existing=$(remote "cd $REMOTE/data 2>/dev/null && ls -d research.db profiles/* 2>/dev/null" || true)
if [[ -n $existing ]]; then
  echo
  echo "$HOST already has this data, which the copy would replace:"
  while IFS= read -r line; do echo "  $line"; done <<<"$existing"
  echo "The script renames it with the suffix .old-$STAMP instead of deleting it."
  confirm "Replace it?" || exit 1
  for name in $profiles; do
    remote "cd $REMOTE/data && if [ -d profiles/$name ]; then mv profiles/$name profiles/$name.old-$STAMP; fi"
  done
  remote "cd $REMOTE/data && for f in research.db research.db-wal research.db-shm; do if [ -e \$f ]; then mv \$f \$f.old-$STAMP; fi; done"
fi

echo
echo "Copying $(du -sh "$DATA/profiles" | cut -f1) of profiles and the research library"
files=(profiles)
for name in research.db research.db-wal research.db-shm; do
  if [[ -e $DATA/$name ]]; then files+=("$name"); fi
done
tar -C "$DATA" -czf - "${files[@]}" |
  remote "mkdir -p $REMOTE/data && tar -C $REMOTE/data -xzf -"
echo "Copied."

if [[ -f $ROOT/.env ]]; then
  echo
  echo ".env holds the API key and the budget. The copy leaves out DATA_DIR and FRONTEND_DIR," \
    "because those paths belong to this computer."
  if remote "test -e $REMOTE/.env" && ! confirm "$HOST has a .env already. Replace it?"; then
    echo "Kept the .env on $HOST."
  else
    grep -vE '^(DATA_DIR|FRONTEND_DIR)=' "$ROOT/.env" | remote "umask 077 && cat >$REMOTE/.env"
    echo "Copied .env."
  fi
fi

echo
echo "Next, run the install script on $HOST. It installs what is missing, builds the" \
  "web UI and starts the coach with the copied profiles."
if confirm "Run it now over ssh?"; then
  ssh -t "$HOST" "cd $REMOTE && ./scripts/install.sh"
fi

echo
echo "To check the copy, open the app on $HOST, pick a profile and press Sync. That tests"
echo "the Garmin token there. Settings shows how far back the activities go."
echo "Leave the coach stopped on this computer from now on, so only one machine syncs."
