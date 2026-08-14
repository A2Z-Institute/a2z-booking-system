@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0create-share-package.ps1" %*
set "A2Z_EXIT=%ERRORLEVEL%"
endlocal & exit /b %A2Z_EXIT%
