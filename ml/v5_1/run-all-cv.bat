@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0..\..\.venv\Scripts\python.exe"
"%PYTHON%" check_environment.py --require-cuda
if errorlevel 1 exit /b 1
"%PYTHON%" cross_validate.py --require-cuda
if errorlevel 1 exit /b 1
echo v5.1 all 36 cross-validation runs completed.

