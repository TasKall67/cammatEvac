@echo off
setlocal
cd /d "%~dp0"

rem If the server is already up (e.g. left running from a previous launch),
rem just open the browser straight away instead of starting a second copy.
curl -s -o nul http://127.0.0.1:8050/
if not errorlevel 1 goto ready

echo Starting cammatEvac server...
start "cammatEvac server (close this window to stop the app)" cmd /k venv\Scripts\python.exe app.py

echo Waiting for the server to come up (first run can take a bit while the PNG exporter warms up)...
set count=0
:waitloop
curl -s -o nul http://127.0.0.1:8050/
if not errorlevel 1 goto ready
set /a count+=1
if %count% GEQ 60 goto ready
timeout /t 1 /nobreak >nul
goto waitloop

:ready
start http://127.0.0.1:8050/
exit
