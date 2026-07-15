@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0frontend"

if not exist "node_modules" (
  echo Installing frontend dependencies...
  call npm install --silent
  if errorlevel 1 exit /b 1
)

call npm run build
