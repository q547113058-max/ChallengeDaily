@echo off
chcp 65001 >nul 2>&1
setlocal

REM ============================================================
REM  ChallengeDaily 源码调试启动（免打包、免安装）
REM  用法：双击本文件；或命令行传 build / electron / browser
REM    debug.bat           = 构建前端 + 启动源码 Electron
REM    debug.bat build     = 只重新构建前端（改前端代码后跑这个，再刷新）
REM    debug.bat electron  = 不构建，直接启动源码 Electron
REM    debug.bat browser   = 只构建 + 打开浏览器外壳(5173)
REM ============================================================

set "ROOT=D:\project\daily\ChallengeDaily"
set "CLIENT=%ROOT%\client"
set "NODE_EXE=node"
set "ELECTRON_EXE=%CLIENT%\node_modules\electron\dist\electron.exe"

REM ---- 清掉会干扰 GUI 启动的环境变量 ----
set "ELECTRON_RUN_AS_NODE="
set "PYTHONHOME="
set "PYTHONPATH="

REM ---- 强制生产模式（加载 dist/index.html，而非 dev server）----
set "ELECTRON_IS_DEV=0"

REM ---- 连云端只读节点（direct 模式，免起本机 Python）----
REM 从 deploy\sync_agent.json 读取 token（不写死在仓库里）
for /f "usebackq tokens=*" %%T in (`node -e "try{console.log(require('D:/project/daily/deploy/sync_agent.json').token||'')}catch(e){}"`) do set "CD_TOKEN=%%T"
set "CHALLENGE_DAILY_BACKEND_MODE=direct"
set "CHALLENGE_DAILY_BACKEND_URL=http://193.112.246.85"
set "CHALLENGE_DAILY_BACKEND_TOKEN=%CD_TOKEN%"
REM 让 vite 构建期把云端 origin 写进 meta CSP
set "CD_BACKEND_ORIGIN=http://193.112.246.85"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=all"

cd /d "%CLIENT%"

if /i "%MODE%"=="browser" goto :BROWSER
if /i "%MODE%"=="electron" goto :ELECTRON

echo.
echo [1/2] 构建前端 dist\ ...
call "%NODE_EXE%" node_modules\vite\bin\vite.js build
if errorlevel 1 (
  echo [ERROR] 构建失败
  pause
  exit /b 1
)
echo [OK] 构建完成

if /i "%MODE%"=="build" (
  echo.
  echo 构建完成。浏览器外壳可直接刷新 http://127.0.0.1:5173/
  echo 源码 Electron 请运行: debug.bat electron
  goto :END
)

:ELECTRON
if not exist "%ELECTRON_EXE%" (
  echo [ERROR] 未找到 electron.exe，请先 npm install
  pause
  exit /b 1
)
if not exist "%CLIENT%\dist\index.html" (
  echo [ERROR] 未找到 dist\index.html，请先运行 debug.bat build
  pause
  exit /b 1
)
echo.
echo [2/2] 启动源码 Electron（direct 模式连云端）...
echo     端口 58889 不监听是正常的（direct 模式无本地代理）
start "" "%ELECTRON_EXE%" .
goto :END

:BROWSER
echo.
echo 构建 + 使用浏览器外壳 http://127.0.0.1:5173/
call "%NODE_EXE%" node_modules\vite\bin\vite.js build
if errorlevel 1 ( echo [ERROR] 构建失败 & pause & exit /b 1 )
echo [OK] 请在浏览器打开 http://127.0.0.1:5173/
start "" "http://127.0.0.1:5173/"

:END
echo.
timeout /t 2 >nul
endlocal
