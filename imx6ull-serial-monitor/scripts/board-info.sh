#!/bin/sh
echo '=== Run on the physical board; no settings are changed ==='
uname -a
printf 'Model: '; tr '\000' ' ' < /proc/device-tree/model 2>/dev/null || true
echo
cat /proc/cmdline
cat /proc/partitions
mount
ls -l /dev/ttymxc* /dev/mon_* /sys/class/leds /dev/input/event* 2>/dev/null || true
cat /proc/bus/input/devices 2>/dev/null || true
cat /etc/inittab 2>/dev/null || true
ps
