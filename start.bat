@echo off
cd /d "%~dp0"
start "スクショトリマー サーバー" cmd /k python server.py
timeout /t 2 /nobreak >nul
start "" "http://localhost:8321/"
