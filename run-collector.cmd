@echo off
setlocal
REM ChallengeDaily local collector (main.py) - long running, hidden window
REM Pure ASCII (system ANSI codepage)
set "ROOT=D:\project\daily\ChallengeDaily"
set "PY=%ROOT%\.venv312\Scripts\python.exe"
set "MAIN=%ROOT%\main.py"
set "DATA=%ROOT%\data"

REM pythonw.exe is killed by local policy here (starts then dies ~1 min later),
REM which made the watchdog see DOWN and spawn duplicates every minute.
REM Use python.exe; callers already hide the window via run-hidden.vbs.
if not exist "%PY%" set "PY=%ROOT%\.venv312\Scripts\pythonw.exe"

set "CHALLENGE_DAILY_DATA_DIR=%DATA%"
set "PORT=58888"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "ELECTRON_RUN_AS_NODE="

REM --- auto-todo bridge proxy (standalone node process on 127.0.0.1:58889) ---
REM Loopback listeners created INSIDE Electron are blocked by security software
REM on this machine, so the bridge must run as a separate node.exe process.
REM It is launched here (before main.py) so it shares the collector's lifetime
REM and auto-starts at logon via the ChallengeDailyCollector scheduled task.
set "TODO_SYNC_URL=http://193.112.246.85:18766"
set "TODO_SYNC_TOKEN=51500b289da5acb9419adc0580c2a4e22e76c34dc057f250"
set "CD_BRIDGE_PORT=58889"
set "NODE_EXE=C:\Users\54711\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v24.16.0-win-x64\node.exe"
if not exist "%NODE_EXE%" set "NODE_EXE=node"
set "BRIDGE=%ROOT%\client\electron\bridge-proxy.cjs"
if exist "%BRIDGE%" (
  netstat -ano | findstr ":58889" | findstr "LISTENING" >nul 2>&1
  if errorlevel 1 wscript //nologo "%ROOT%\run-hidden-args.vbs" "%NODE_EXE%" "%BRIDGE%"
)

REM --- auto-todo candidate producer (long running, hidden window) ---
REM Reads the collector's own activities table and pushes low-noise candidates
REM to todo-sync so the approval popup has something to show while app is open.
set "AUTO_TODO_INTERVAL=90"
set "AUTO_TODO_MAX_PER_HOUR=3"
set "PRODUCER=%ROOT%\auto_todo_producer.py"
REM pythonw.exe gets blocked by policy here; use python.exe with a hidden window.
set "PRODUCER_PY=%ROOT%\.venv312\Scripts\python.exe"
if not exist "%PRODUCER_PY%" set "PRODUCER_PY=%PY%"
if exist "%PRODUCER%" wscript //nologo "%ROOT%\run-hidden-args.vbs" "%PRODUCER_PY%" -u "%PRODUCER%"

cd /d "%ROOT%"
"%PY%" -u "%MAIN%"
endlocal
