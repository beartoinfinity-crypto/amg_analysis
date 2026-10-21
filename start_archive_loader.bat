@echo off
cd /d "%~dp0"
python -m amg gui
if errorlevel 1 pause
