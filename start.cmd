@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
python -m ai_baby %*
if errorlevel 1 pause
