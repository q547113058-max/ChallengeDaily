@echo off
setlocal

REM ============================================================
REM  ChallengeDaily source debug launcher (double-click to run)
REM  Pure ASCII: cmd.exe parses .cmd with the system ANSI codepage,
REM  so any non-ASCII text gets garbled and executed as commands.
REM  Equivalent to: node scripts/dev-launch.cjs
REM
REM  Args:
REM    (none)   build frontend + launch source Electron
REM    fast     skip build, launch directly (when only .cjs changed)
REM    browser  build and open browser shell on 5173
REM ============================================================

set "CLIENT=D:\project\daily\ChallengeDaily\client"
cd /d "%CLIENT%"

if /i "%~1"=="fast"    goto FAST
if /i "%~1"=="browser" goto BROWSER

echo [1/1] Building frontend and launching source Electron ...
node scripts\dev-launch.cjs
goto DONE

:FAST
echo [skip build] Launching source Electron ...
node scripts\dev-launch.cjs --no-build
goto DONE

:BROWSER
echo Building and opening browser shell ...
node scripts\dev-launch.cjs --no-build
start "" "http://127.0.0.1:5173/"
goto DONE

:DONE
echo.
echo If the window flashes and closes, send me this log:
echo   %%APPDATA%%\challenge-daily\logs\electron-main.log
timeout /t 3 >nul
endlocal
