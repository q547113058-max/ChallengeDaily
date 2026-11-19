@echo off
setlocal
REM ChallengeDaily local collector (main.py) - long running, hidden window
REM Pure ASCII (system ANSI codepage)
set "ROOT=D:\project\daily\ChallengeDaily"
set "PY=%ROOT%\.venv312\Scripts\pythonw.exe"
set "MAIN=%ROOT%\main.py"
set "DATA=%ROOT%\data"

if not exist "%PY%" set "PY=%ROOT%\.venv312\Scripts\python.exe"

set "CHALLENGE_DAILY_DATA_DIR=%DATA%"
set "PORT=58888"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "ELECTRON_RUN_AS_NODE="

REM --- auto-todo bridge proxy (standalone node process on 127.0.0.1:58889) ---
REM Loopback listeners created INSIDE Electron are blocked by security software
REM on this machine, so the bridge must run as a separate node.exe process.
set "TODO_SYNC_URL=http://193.112.246.85:18766"
REM TODO_SYNC_TOKEN is supplied by the caller environment; never hardcode it here.
set "CD_BRIDGE_PORT=58889"
set "NODE_EXE=C:\Users\54711\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v24.16.0-win-x64\node.exe"
if not exist "%NODE_EXE%" set "NODE_EXE=node"
set "BRIDGE=%ROOT%\client\electron\bridge-proxy.cjs"
if exist "%BRIDGE%" (
  netstat -ano | findstr ":58889" | findstr "LISTENING" >nul 2>&1
  if errorlevel 1 wscript //nologo "%ROOT%\run-hidden-args.vbs" "%NODE_EXE%" "%BRIDGE%"
)

REM --- auto-todo candidate producer (long running, hidden window) ---
set "AUTO_TODO_INTERVAL=90"
set "AUTO_TODO_MAX_PER_HOUR=3"
set "PRODUCER=%ROOT%\auto_todo_producer.py"
set "PRODUCER_PY=%ROOT%\.venv312\Scripts\python.exe"
if not exist "%PRODUCER_PY%" set "PRODUCER_PY=%PY%"
if exist "%PRODUCER%" wscript //nologo "%ROOT%\run-hidden-args.vbs" "%PRODUCER_PY%" -u "%PRODUCER%"

cd /d "%ROOT%"
"%PY%" -u "%MAIN%"
endlocal
