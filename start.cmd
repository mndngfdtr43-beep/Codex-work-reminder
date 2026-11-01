@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先运行 powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m bridge %*
pause
