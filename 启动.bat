@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo Starting MOMO AI Girlfriend...
echo.

REM SERVER_PORT comes only from .env. Use 8001 when .env is absent.
set "SERVER_PORT=8001"
if exist ".env" (
  for /f "tokens=1,* delims==" %%A in ('findstr /R /C:"^SERVER_PORT=" ".env"') do set "SERVER_PORT=%%B"
)

py -3.14 -m pip install -r requirements.txt -q 2>nul

cd frontend
if not exist "node_modules" call npm install --silent 2>nul
cd ..

REM Stop only an old backend listening on the configured port.
for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%SERVER_PORT%.*LISTENING"') do taskkill /F /PID %%A >nul 2>&1

start "Backend" /min py -3.14 -m backend.main

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

start "Frontend" cmd /k "cd frontend && npm run dev"

timeout /t 2 /nobreak >nul
start http://localhost:5173

echo.
echo Started! Backend:%SERVER_PORT% Frontend:5173
echo.
