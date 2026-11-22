@echo off
rem Double-click to start the backend and the mobile app's dev server (see start-mobile.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-mobile.ps1" %*
