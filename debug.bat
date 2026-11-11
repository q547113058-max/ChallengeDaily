@echo off
setlocal

REM ============================================================
REM  ChallengeDaily source debug (no packaging, no install)
REM  Pure ASCII only - cmd.exe uses system ANSI codepage.
REM  All env/token handling lives in scripts/dev-launch.cjs.
REM
REM  Usage:
REM    debug.bat           build frontend + launch source Electron
REM    debug.bat build     rebuild frontend only (then refresh)
REM    debug.bat electron  launch source Electron without rebuild
REM    debug.bat browser   build + open browser shell
REM ============================================================

set "CLIENT=D:\project\daily\ChallengeDaily\client"
cd /d "%CLIENT%"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=all"

if /i "%MODE%"=="browser" goto BROWSER
if /i "%MODE%"=="electron" goto ELECTRON
if /i "%MODE%"=="build" goto BUILD_ONLY

echo.
echo [1/1] Building frontend and launching source Electron ...
node scripts\dev-launch.cjs
goto END

:BUILD_ONLY
echo Building frontend only (then refresh browser or Ctrl+R in Electron) ...
node scripts\dev-launch.cjs --build-only
goto END

:ELECTRON
echo Launching source Electron without rebuild ...
node scripts\dev-launch.cjs --no-build
goto END

:BROWSER
echo Building frontend (browser shell refresh) ...
node scripts\dev-launch.cjs --no-build
start "" "http://127.0.0.1:5173/"

:END
echo.
echo If the window flashes and closes, send this log:
echo   %%APPDATA%%\challenge-daily\logs\electron-main.log
timeout /t 3 >nul
endlocal
