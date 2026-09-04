#!/usr/bin/env bash
# Restart the app for development, without corrupting Proton's caches.
#
# Killing the app mid-write leaves a truncated ~/.cache/Proton/VPN/serverlist.json
# (24 MB, written in one go). Their code recovers by refetching, but it is our
# mess to avoid: stop the process politely and wait for it to actually exit.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${1:-/tmp/unofficial-protonvpn-dev}"
mkdir -p "$STATE_DIR"
PID_FILE="$STATE_DIR/app.pid"
LOG="$STATE_DIR/launch.log"

# Find every running instance, not just the one this script started. Two
# instances race for the same tray DBus name and the loser segfaults, so a
# stale pid file must not lead to a second one being launched.
# Only real app processes: a plain pgrep -f also matches this script's own
# shell (its command line contains the pattern), which makes the script kill
# itself.
mapfile -t RUNNING < <(
    pgrep -f "python3 -sP -m unofficial_protonvpn" 2>/dev/null | while read -r candidate; do
        [[ "$candidate" == "$$" ]] && continue
        [[ "$(cat "/proc/$candidate/comm" 2>/dev/null)" == "python3" ]] && echo "$candidate"
    done || true
)
if [[ -f "$PID_FILE" ]]; then
    RUNNING+=("$(cat "$PID_FILE")")
fi

for OLD in "${RUNNING[@]}"; do
    [[ -n "$OLD" ]] || continue
    if kill -0 "$OLD" 2>/dev/null; then
        kill -TERM "$OLD" 2>/dev/null || true
        # Up to 20s: a cache write must be allowed to finish.
        for _ in $(seq 1 40); do
            kill -0 "$OLD" 2>/dev/null || break
            sleep 0.5
        done
        if kill -0 "$OLD" 2>/dev/null; then
            echo "warning: pid $OLD did not exit; leaving it alone rather than" >&2
            echo "         forcing a kill that could truncate a cache write." >&2
            exit 1
        fi
    fi
done

: > "$LOG"
env PYTHONPATH="$REPO/src" /usr/bin/python3 -sP -m unofficial_protonvpn >"$LOG" 2>&1 &
echo $! > "$PID_FILE"

for _ in $(seq 1 40); do
    sleep 0.5
    grep -q "WIDGET_READY" "$LOG" && break
done

PID="$(cat "$PID_FILE")"
echo "running pid $PID"
echo "errors: $(grep -cE 'Traceback|falling back' "$LOG" || true)"

# Proton's cache must still be readable after every restart.
python3 - <<'PY'
import json
from pathlib import Path
cache = Path.home() / ".cache" / "Proton" / "VPN" / "serverlist.json"
if not cache.exists():
    print("cache: absent (Proton will refetch)")
else:
    try:
        json.loads(cache.read_text())
        print("cache: valid")
    except Exception as error:
        print(f"cache: CORRUPT - {str(error)[:60]}")
PY
