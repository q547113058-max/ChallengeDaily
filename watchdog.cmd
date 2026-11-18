@echo off
setlocal
REM ============================================================
REM  ChallengeDaily watchdog - runs every minute via Task Scheduler
REM  Ensures collector (port 58888) and sync agent are running.
REM  Pure ASCII. Uses PowerShell for reliable process detection
REM  (wmic is deprecated/unavailable on this host).
REM ============================================================

set "ROOT=D:\project\daily\ChallengeDaily"
set "DEPLOY=D:\project\daily\deploy"
set "PS=powershell -NoProfile -ExecutionPolicy Bypass -Command"

REM ---- collector: any python process with main.py in cmdline? ----
%PS% "if (-not (Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -match 'main.py' })) { exit 1 }" >nul 2>&1
if errorlevel 1 (
  echo [%DATE% %TIME%] collector DOWN - starting
  start "" /min /d "%ROOT%" "%ROOT%\run-collector.cmd"
) else (
  echo [%DATE% %TIME%] collector OK
)

REM ---- sync agent: any python process with sync_agent.py in cmdline? ----
%PS% "if (-not (Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -match 'sync_agent.py' })) { exit 1 }" >nul 2>&1
if errorlevel 1 (
  echo [%DATE% %TIME%] sync DOWN - starting
  start "" /min /d "%DEPLOY%" "%DEPLOY%\run-sync.cmd"
) else (
  echo [%DATE% %TIME%] sync OK
)

endlocal
