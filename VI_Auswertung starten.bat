@echo off
cd /d "%~dp0"
python vi_auswertung.py
if errorlevel 1 pause
