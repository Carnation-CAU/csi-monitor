@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python check_environment.py --require-cuda
if errorlevel 1 exit /b 1
python train.py --model simple_cnn --protocol participant --require-cuda
if errorlevel 1 exit /b 1
python train.py --model resnet18 --protocol participant --require-cuda
if errorlevel 1 exit /b 1
python compare_results.py
if errorlevel 1 exit /b 1
echo Both baseline runs completed. Results are under output\

