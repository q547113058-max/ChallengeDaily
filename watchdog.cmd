@echo off
setlocal
REM ============================================================
REM  ChallengeDaily watchdog - runs every minute via Task Scheduler
REM  Ensures collector (port 58888) and sync agent are running.
REM  Pure ASCII. Detection logic lives in watchdog-check.ps1 so that
REM  PowerShell $_ is not eaten by cmd.exe (the old inline -Command
REM  broke on "$_.Name" -> ".Name", always misreported DOWN and
REM  spawned duplicate main.py processes every minute).
REM ============================================================

set "ROOT=D:\project\daily\ChallengeDaily"
set "DEPLOY=D:\project\daily\deploy"
set "PS=powershell -NoProfile -ExecutionPolicy Bypass -File"
set "CHECK=%ROOT%\watchdog-check.ps1"
set "RUNHIDDEN=%ROOT%\run-hidden.vbs"

REM ---- collector: any python process running main.py? ----
%PS% "%CHECK%" collector >nul 2>&1
if errorlevel 1 (
  echo [%DATE% %TIME%] collector DOWN - starting
  wscript //nologo "%RUNHIDDEN%" "%ROOT%\run-collector.cmd"
) else (
  echo [%DATE% %TIME%] collector OK
)

REM ---- sync agent: any python process running sync_agent.py? ----
%PS% "%CHECK%" sync >nul 2>&1
if errorlevel 1 (
  echo [%DATE% %TIME%] sync DOWN - starting
  wscript //nologo "%RUNHIDDEN%" "%DEPLOY%\run-sync.cmd"
) else (
  echo [%DATE% %TIME%] sync OK
)

REM ---- bridge-proxy: port 58889 LISTENING? ----
%PS% "%CHECK%" bridge >nul 2>&1
if errorlevel 1 (
  echo [%DATE% %TIME%] bridge-proxy DOWN - starting
  set "NODE_EXE=C:\Users\54711\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v24.16.0-win-x64\node.exe"
  if not exist "%NODE_EXE%" set "NODE_EXE=node"
  wscript //nologo "%ROOT%\run-hidden-args.vbs" "%NODE_EXE%" "%ROOT%\client\electron\bridge-proxy.cjs"
) else (
  echo [%DATE% %TIME%] bridge-proxy OK
)

endlocal
