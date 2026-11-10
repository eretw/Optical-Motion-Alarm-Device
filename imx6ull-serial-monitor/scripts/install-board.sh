#!/bin/sh
# Application deployment only. Does not format partitions or modify bootloader/getty.
set -eu
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST=${1:-/opt/serial-monitor}
[ "$(id -u)" = 0 ] || { echo 'Run as root on the board'; exit 1; }
case "$DEST" in /opt/*) ;; *) echo 'Destination must be under /opt'; exit 1;; esac
case "$(uname -m)" in arm*) ;; *) echo 'This installer is for the ARM board, not the PC/VM/WSL'; exit 1;; esac
[ -f "$SOURCE/release/arm/monitor" ] || { echo 'ARM binary missing; build first'; exit 1; }
mkdir -p "$DEST/bin" "$DEST/scripts" /var/lib/serial-monitor
[ ! -f "$DEST/bin/monitor" ] || cp "$DEST/bin/monitor" "$DEST/bin/monitor.previous"
cp "$SOURCE/release/arm/monitor" "$DEST/bin/monitor.new"
chmod 755 "$DEST/bin/monitor.new"
mv "$DEST/bin/monitor.new" "$DEST/bin/monitor"
cp "$SOURCE/scripts/run-session.sh" "$SOURCE/scripts/board-info.sh" "$DEST/scripts/"
chmod 755 "$DEST/scripts/"*.sh
sync
echo "Installed to $DEST; start: sh $DEST/scripts/run-session.sh --mock"
