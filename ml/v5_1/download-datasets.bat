@echo off
setlocal
cd /d "%~dp0"
set "PROJECT_PYTHON=%~dp0..\..\.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" (
  echo Python environment not found. Run setup-lab.bat first.
  exit /b 1
)
"%PROJECT_PYTHON%" download_datasets.py
if errorlevel 1 goto :fail
"%PROJECT_PYTHON%" check_environment.py --require-cuda
if errorlevel 1 goto :fail
echo Public datasets downloaded and validated.
exit /b 0
:fail
echo Dataset setup failed. Read LAB_TRAINING.md troubleshooting.
exit /b 1
