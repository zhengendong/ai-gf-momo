@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Starting MOMO AI Girlfriend...
echo.

py -3.14 -m pip install -r requirements.txt -q 2>nul

cd frontend
if not exist "node_modules" call npm install --silent 2>nul
cd ..

REM SERVER_PORT 是唯一端口配置来源；.env 缺失时使用默认 8001。
set "SERVER_PORT=8001"
for /f "tokens=1,* delims==" %%a in ('findstr /R /C:"^SERVER_PORT=" ".env"') do set "SERVER_PORT=%%b"

REM 杀死当前配置端口上的旧后端，避免重启时端口冲突。
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%SERVER_PORT%.*LISTENING"') do taskkill /F /PID %%a >nul 2>&1

start "Backend" /min py -3.14 -m backend.main
timeout /t 2 /nobreak >nul

start "Frontend" cmd /k "cd frontend && npm run dev"

timeout /t 2 /nobreak >nul
start http://localhost:5173

echo.
echo Started! Backend:%SERVER_PORT% Frontend:5173
echo.
