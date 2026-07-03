@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Starting MOMO AI Girlfriend...
echo.

py -3.14 -m pip install -r requirements.txt -q 2>nul

cd frontend
if not exist "node_modules" call npm install --silent 2>nul
cd ..

REM 杀死任何还在占用 8000 的旧 uvicorn，避免新旧端口冲突
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do taskkill /F /PID %%a >nul 2>&1

start "Backend" /min py -3.14 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
timeout /t 2 /nobreak >nul

start "Frontend" cmd /k "cd frontend && npm run dev"

timeout /t 2 /nobreak >nul
start http://localhost:5173

echo.
echo Started! Backend:8000 Frontend:5173
echo.
