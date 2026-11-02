@echo off
title Photo Cleaner Launcher
echo =========================================
echo       Starting Photo Cleaner...
echo =========================================
echo.

:: Switch to the directory where this bat file is located
cd /d "%~dp0"

:: Use the specific python environment that has all dependencies installed
set "PYTHON_EXE=D:\anaconda3\envs\py312-clean\python.exe"
if not exist "%PYTHON_EXE%" (
    echo Python not found: "%PYTHON_EXE%"
    echo Edit PYTHON_EXE in this file to point at a Python with requirements.txt installed.
    echo.
    pause
    exit /b 1
)
"%PYTHON_EXE%" main.py

echo.
echo Process exited.
pause
