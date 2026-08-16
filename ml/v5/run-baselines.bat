@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0..\..\.venv\Scripts\python.exe"
"%PYTHON%" check_environment.py --require-cuda
if errorlevel 1 exit /b 1
"%PYTHON%" train.py --model simple_cnn --protocol participant --require-cuda
if errorlevel 1 exit /b 1
"%PYTHON%" train.py --model resnet18 --protocol participant --require-cuda
if errorlevel 1 exit /b 1
"%PYTHON%" train.py --model efficientnet_b0 --protocol participant --require-cuda
if errorlevel 1 exit /b 1
"%PYTHON%" compare_results.py

