@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python check_environment.py --require-cuda
if errorlevel 1 exit /b 1
python train.py --model simple_cnn --smoke-test --require-cuda

