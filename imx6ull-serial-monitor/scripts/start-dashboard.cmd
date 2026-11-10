@echo off
cd /d "%~dp0.."
py -3 host\dashboard.py
if errorlevel 1 pause
