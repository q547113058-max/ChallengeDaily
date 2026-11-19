@echo off
REM Diagnostic launcher. Pure ASCII. Double-click this to test startup.
REM It runs electron in the FOREGROUND and logs the exit code + all output.
setlocal
set "ROOT=%~dp0"
set "CLIENT=%ROOT%client"
set "EXE=%CLIENT%\node_modules\electron\dist\electron.exe"
set "LOG=%ROOT%data\start-debug.log"

echo ==== START %DATE% %TIME% ==== > "%LOG%"
echo ROOT=%ROOT% >> "%LOG%"
echo CLIENT=%CLIENT% >> "%LOG%"
echo EXE=%EXE% >> "%LOG%"
echo ELECTRON_RUN_AS_NODE_BEFORE=[%ELECTRON_RUN_AS_NODE%] >> "%LOG%"
echo ELECTRON_IS_DEV_BEFORE=[%ELECTRON_IS_DEV%] >> "%LOG%"
echo APPDATA=%APPDATA% >> "%LOG%"

set ELECTRON_RUN_AS_NODE=
set ELECTRON_IS_DEV=0
set PYTHONHOME=
set PYTHONPATH=
set PYTHONIOENCODING=utf-8
set "CHALLENGE_DAILY_USER_DATA_DIR=%ROOT%data\electron-profile"
if not exist "%CHALLENGE_DAILY_USER_DATA_DIR%" mkdir "%CHALLENGE_DAILY_USER_DATA_DIR%" 2>nul
set "CD_CHROME_USER_DATA=%ROOT%data\chrome-profile"
if not exist "%CD_CHROME_USER_DATA%" mkdir "%CD_CHROME_USER_DATA%" 2>nul
set "CD_NO_SINGLETON=1"

if exist "%EXE%" (echo EXE=YES >> "%LOG%") else (echo EXE=NO >> "%LOG%")
if exist "%CLIENT%\dist\index.html" (echo DIST=YES >> "%LOG%") else (echo DIST=NO >> "%LOG%")
if exist "%CLIENT%\package.json" (echo PKG=YES >> "%LOG%") else (echo PKG=NO >> "%LOG%")

echo ---- launching (foreground) ---- >> "%LOG%"
cd /d "%CLIENT%"
"%EXE%" "%CLIENT%" --no-sandbox --disable-gpu --user-data-dir="%CD_CHROME_USER_DATA%" >> "%LOG%" 2>&1
echo ---- EXIT code=%ERRORLEVEL% %TIME% ---- >> "%LOG%"
echo ==== END ==== >> "%LOG%"

echo.
echo Done. Opening log...
notepad "%LOG%"
