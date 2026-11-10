#!/bin/sh
# Run FROM the board's serial login shell. Leaves getty's login shell alive but idle.
# The kernel console is only quieted temporarily; this is a development session.
set -eu
BASE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PORT=${MONITOR_PORT:-/dev/ttymxc0}
STATE=${MONITOR_STATE:-/var/lib/serial-monitor}
LIMIT=${MONITOR_SECONDS:-300}
case "$LIMIT" in ''|*[!0-9]*) echo 'MONITOR_SECONDS must be an integer'; exit 1;; esac
[ "$LIMIT" -ge 15 ] && [ "$LIMIT" -le 86400 ] || { echo 'Session range: 15..86400 seconds'; exit 1; }
[ "$(id -u)" = 0 ] || { echo 'Run as root on the BOARD'; exit 1; }
[ -c "$PORT" ] || { echo "No UART: $PORT"; exit 1; }
[ -x "$BASE/bin/monitor" ] || { echo 'Run install-board.sh first'; exit 1; }
CURRENT=$(tty)
[ "$CURRENT" = "$PORT" ] || { echo "Run from $PORT login shell, current tty=$CURRENT. Do not run from VM/WSL terminal."; exit 1; }
mkdir -p "$STATE"
OLD_STTY=$(stty -g < "$PORT")
OLD_PRINTK=$(cat /proc/sys/kernel/printk)
child=
timer=
restore() {
    trap - EXIT HUP INT TERM
    [ -z "$timer" ] || kill "$timer" 2>/dev/null || true
    if [ -n "$child" ]; then kill -TERM "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true; fi
    printf '%s\n' "$OLD_PRINTK" > /proc/sys/kernel/printk
    stty "$OLD_STTY" < "$PORT"
    echo 'Serial session ended. Reopen the terminal at 115200 8N1 and press Enter.'
}
trap restore EXIT HUP INT TERM
echo "Starting in 5 seconds; close SecureCRT/PuTTY, then connect the PC monitor. Auto-exit in $LIMIT seconds."
sleep 5
# Suppress non-emergency printk; emergency output can still interrupt the protocol.
dmesg -n 1
"$BASE/bin/monitor" --serial "$PORT" --state "$STATE" "$@" >> "$STATE/session.log" 2>&1 &
child=$!
( sleep "$LIMIT"; kill -TERM "$child" 2>/dev/null || true ) &
timer=$!
wait "$child" || true
child=
