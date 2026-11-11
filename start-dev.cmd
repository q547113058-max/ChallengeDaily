@echo off
chcp 65001 >nul 2>&1
setlocal

REM ============================================================
REM  ChallengeDaily 源码调试启动（双击即用）
REM  不使用 npm / .ps1，绕开 PowerShell 执行策略限制
REM  等价于: node scripts/dev-launch.cjs
REM
REM  可选参数:
REM    start-dev.cmd          构建前端 + 启动源码 Electron
REM    start-dev.cmd fast     跳过构建，直接启动（仅改了 .cjs 时用）
REM    start-dev.cmd browser  只构建并打开浏览器外壳
REM ============================================================

set "CLIENT=D:\project\daily\ChallengeDaily\client"
cd /d "%CLIENT%"

if /i "%~1"=="fast"    goto :FAST
if /i "%~1"=="browser" goto :BROWSER

echo [1/1] 构建前端并启动源码 Electron ...
node scripts\dev-launch.cjs
goto :DONE

:FAST
echo [跳过构建] 直接启动源码 Electron ...
node scripts\dev-launch.cjs --no-build
goto :DONE

:BROWSER
echo 构建前端并打开浏览器外壳 ...
node scripts\dev-launch.cjs --no-build 2>nul
start "" "http://127.0.0.1:5173/"
goto :DONE

:DONE
echo.
echo 若窗口未出现或一闪而过，请把日志发我：
echo   %%APPDATA%%\challenge-daily\logs\electron-main.log
timeout /t 3 >nul
endlocal
