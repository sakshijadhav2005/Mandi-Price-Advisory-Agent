@echo off
rem Daily price ingestion + alert check. Registered by install-daily-task.ps1.
cd /d "%~dp0..\backend"
python manage.py daily >> daily.log 2>&1
