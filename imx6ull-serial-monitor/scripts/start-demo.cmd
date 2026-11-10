@echo off
cd /d "%~dp0.."
py -3 host\monitor.py --simulate --seconds 12
pause
