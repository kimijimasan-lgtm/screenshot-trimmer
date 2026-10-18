@echo off
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found. Install Python and try again.
    pause
    exit /b 1
)

if not exist server.py (
    echo [ERROR] server.py not found in this folder.
    pause
    exit /b 1
)

echo Starting server...
start "Screenshot Trimmer" cmd /c "python server.py & pause"
timeout /t 3 /nobreak >nul
start "" "http://localhost:8321/"
