@echo off
setlocal
cd /d "%~dp0"

REM === スクショトリマー ビルドスクリプト ===
REM 出力先: F:\Claude学習\_dist\スクショトリマー\スクショトリマー\

set DIST_BASE=F:\Claude学習\_dist\スクショトリマー
set BUILD_DIR=%DIST_BASE%\_build
set DIST_DIR=%DIST_BASE%
set OUT_DIR=%DIST_DIR%\スクショトリマー
set YTDLP_SRC=%DIST_BASE%\yt-dlp.exe

REM --- 前提チェック ---
where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo [ERROR] pyinstaller が見つかりません。
    pause
    exit /b 1
)

if not exist "%YTDLP_SRC%" (
    echo [ERROR] yt-dlp.exe が見つかりません: %YTDLP_SRC%
    echo https://github.com/yt-dlp/yt-dlp/releases からダウンロードしてください。
    pause
    exit /b 1
)

REM --- ビルド ---
echo Building...
pyinstaller スクショトリマー.spec --noconfirm --workpath "%BUILD_DIR%" --distpath "%DIST_DIR%"

if errorlevel 1 (
    echo [ERROR] ビルドに失敗しました。
    pause
    exit /b 1
)

REM --- yt-dlp.exe を出力フォルダにコピー ---
copy /y "%YTDLP_SRC%" "%OUT_DIR%\yt-dlp.exe" >nul

echo.
echo === ビルド完了 ===
echo 出力先: %OUT_DIR%
echo.
pause
