@echo off
title Photo Cleaner Launcher
echo =========================================
echo       Starting Photo Cleaner...
echo =========================================
echo.

:: Switch to the directory where this bat file is located
cd /d "%~dp0"

:: Use the specific python environment that has all dependencies installed
"D:\anaconda3\envs\py312-clean\python.exe" main.py

echo.
echo Process exited.
pause
