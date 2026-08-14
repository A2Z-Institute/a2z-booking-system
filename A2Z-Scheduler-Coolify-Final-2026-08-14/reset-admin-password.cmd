@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo The local Python environment is missing.
  echo Run start-local.cmd once, stop it with Ctrl+C, then run this reset again.
  exit /b 1
)
".venv\Scripts\python.exe" "reset-admin-password.py"
set "A2Z_EXIT=%ERRORLEVEL%"
endlocal & exit /b %A2Z_EXIT%
