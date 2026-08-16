@echo off
setlocal
cd /d "%~dp0"
set "TORCH_INDEX=%~1"
if "%TORCH_INDEX%"=="" set "TORCH_INDEX=https://download.pytorch.org/whl/cu126"
echo [1/4] Creating Python 3.11 environment...
py -3.11 -m venv .venv
if errorlevel 1 goto :fail
call .venv\Scripts\activate.bat
echo [2/4] Updating pip...
python -m pip install --upgrade pip
if errorlevel 1 goto :fail
echo [3/4] Installing PyTorch from %TORCH_INDEX% ...
python -m pip install torch torchvision --index-url "%TORCH_INDEX%"
if errorlevel 1 goto :fail
echo [4/4] Installing training dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail
python check_environment.py --require-cuda
if errorlevel 1 goto :fail
echo Setup complete.
exit /b 0
:fail
echo Setup failed. Check the message above.
exit /b 1

