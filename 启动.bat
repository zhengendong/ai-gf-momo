@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo Starting MOMO AI Girlfriend (single-service mode)...
echo.

REM SERVER_PORT comes only from .env. Use 8001 when .env is absent.
set "SERVER_PORT=8001"
if exist ".env" (
  for /f "tokens=1,* delims==" %%A in ('findstr /R /C:"^SERVER_PORT=" ".env"') do set "SERVER_PORT=%%B"
)

REM Only install Python dependencies when this machine does not have them yet.
py -3.14 -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
  echo Installing Python dependencies...
  py -3.14 -m pip install -r requirements.txt -q
  if errorlevel 1 (
    echo Failed to install Python dependencies.
    pause
    exit /b 1
  )
)

cd frontend
if not exist "node_modules" (
  echo Installing frontend dependencies...
  call npm install --silent
  if errorlevel 1 (
    echo Failed to install frontend dependencies.
    pause
    exit /b 1
  )
)
if not exist "dist\index.html" (
  echo Building frontend for first use...
  call npm run build
  if errorlevel 1 (
    echo Frontend build failed.
    pause
    exit /b 1
  )
)
cd ..

REM Stop an old backend and any orphan reload worker that inherited its socket.
REM A dead reload parent can still appear as the listener owner while spawn_main
REM keeps serving old code, so killing only the PID reported by netstat is unsafe.
for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%SERVER_PORT%.*LISTENING"') do (
  powershell -NoProfile -Command "$listenerId = [int]%%A; $processes = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -eq $listenerId -or $_.ParentProcessId -eq $listenerId -or ($_.CommandLine -and $_.CommandLine.Contains(('parent_pid=' + $listenerId + ','))) }); $processes | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
)

REM Never start a second backend while any previous listener still owns the port.
for /L %%I in (1,1,5) do (
  set "OLD_BACKEND_LISTENER="
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%SERVER_PORT%.*LISTENING"') do set "OLD_BACKEND_LISTENER=%%A"
  if defined OLD_BACKEND_LISTENER timeout /t 1 /nobreak >nul
)
if defined OLD_BACKEND_LISTENER (
  echo Failed to stop the previous backend on port %SERVER_PORT% ^(PID %OLD_BACKEND_LISTENER%^).
  echo Refusing to start another backend because the browser could reach stale code.
  pause
  exit /b 1
)

REM SERVER_RELOAD is deliberately off in the normal single-service launcher.
set "SERVER_RELOAD=false"
start "MOMO Backend" /min py -3.14 -m backend.main

REM Wait for the backend and keep this window open when startup fails.
set "BACKEND_READY="
for /L %%I in (1,1,5) do (
  powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 http://127.0.0.1:%SERVER_PORT%/api/health | Out-Null; exit 0 } catch { exit 1 }"
  if not errorlevel 1 set "BACKEND_READY=1"
  if not defined BACKEND_READY timeout /t 1 /nobreak >nul
)

if not defined BACKEND_READY (
  echo Backend failed to start at http://127.0.0.1:%SERVER_PORT%
  echo Check .env SERVER_PORT and the backend process output.
  pause
  exit /b 1
)

REM The normal launcher must expose exactly one listener for the configured port.
set "BACKEND_LISTENER_COUNT=0"
for /f %%A in ('netstat -ano ^| findstr ":%SERVER_PORT%.*LISTENING" ^| find /C "LISTENING"') do set "BACKEND_LISTENER_COUNT=%%A"
if not "%BACKEND_LISTENER_COUNT%"=="1" (
  echo Expected one backend listener on port %SERVER_PORT%, found %BACKEND_LISTENER_COUNT%.
  echo Close the backend windows and run this launcher again.
  pause
  exit /b 1
)

start http://127.0.0.1:%SERVER_PORT%

echo.
echo Started! http://127.0.0.1:%SERVER_PORT%
echo.
