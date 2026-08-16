@echo off
setlocal
cd /d "%~dp0"
set "PROJECT_ROOT=%~dp0..\.."
set "PROJECT_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "TORCH_INDEX=%~1"
if "%TORCH_INDEX%"=="" set "TORCH_INDEX=https://download.pytorch.org/whl/cu126"
if not exist "%PROJECT_PYTHON%" (
  powershell.exe -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\bootstrap.ps1"
  if errorlevel 1 goto :fail
)
pushd "%PROJECT_ROOT%"
"%PROJECT_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 (popd & goto :fail)
"%PROJECT_PYTHON%" -m pip install -e ".[gui]"
if errorlevel 1 (popd & goto :fail)
popd
"%PROJECT_PYTHON%" -m pip install torch torchvision --index-url "%TORCH_INDEX%"
if errorlevel 1 goto :fail
"%PROJECT_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
"%PROJECT_PYTHON%" check_environment.py --require-cuda
if errorlevel 1 goto :fail
echo v5.1 setup complete.
exit /b 0
:fail
echo Setup failed. Read LAB_TRAINING.md troubleshooting.
exit /b 1

