@echo off
setlocal
cd /d "%~dp0"
set "PROJECT_ROOT=%~dp0..\.."
set "PROJECT_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "TORCH_INDEX=%~1"
if "%TORCH_INDEX%"=="" set "TORCH_INDEX=https://download.pytorch.org/whl/cu126"
if not exist "%PROJECT_PYTHON%" (
  echo [1/4] Creating the shared gateway and ML environment...
  powershell.exe -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\bootstrap.ps1"
  if errorlevel 1 goto :fail
) else (
  echo [1/4] Reusing shared environment %PROJECT_ROOT%\.venv
)
echo [2/4] Updating pip...
"%PROJECT_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto :fail
echo Installing or refreshing the gateway and GUI package...
pushd "%PROJECT_ROOT%"
"%PROJECT_PYTHON%" -m pip install -e ".[gui]"
if errorlevel 1 (popd & goto :fail)
popd
echo [3/4] Installing PyTorch from %TORCH_INDEX% ...
"%PROJECT_PYTHON%" -m pip install torch torchvision --index-url "%TORCH_INDEX%"
if errorlevel 1 goto :fail
echo [4/4] Installing training dependencies...
"%PROJECT_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
"%PROJECT_PYTHON%" check_environment.py --require-cuda
if errorlevel 1 goto :fail
echo Shared gateway and ML setup complete.
exit /b 0
:fail
echo Setup failed. Check the message above.
exit /b 1
