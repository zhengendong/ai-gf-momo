@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Starting MOMO AI Girlfriend...
echo.

pip install -r requirements.txt -q 2>nul

cd frontend
if not exist "node_modules" call npm install --silent 2>nul
cd ..

start "Backend" /min python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
timeout /t 2 /nobreak >nul

start "Frontend" cmd /k "cd frontend && npm run dev"

timeout /t 2 /nobreak >nul
start http://localhost:5173

echo.
echo Started! Backend:8000 Frontend:5173
echo.
