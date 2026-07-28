@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo First run: installing Rift Translate dependencies...
  python -m venv .venv
  if errorlevel 1 goto :error
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  if errorlevel 1 goto :error
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :error
)

start "" ".venv\Scripts\pythonw.exe" main.py
exit /b 0

:error
echo.
echo Installation failed. Please keep this window open and report the error.
pause
exit /b 1
