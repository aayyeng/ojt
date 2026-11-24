@echo off
title OJT Journal
cd /d "%~dp0"

set "REBUILD_VENV=0"
if not exist ".venv\Scripts\python.exe" (
    set "REBUILD_VENV=1"
) else (
    ".venv\Scripts\python.exe" --version >nul 2>&1
    if errorlevel 1 set "REBUILD_VENV=1"
)

if "%REBUILD_VENV%"=="1" (
    echo Setting up OJT Journal virtual environment. Please wait...
    if exist ".venv" rmdir /s /q ".venv"
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Python was not found. Install Python from python.org and tick "Add Python to PATH".
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
python -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo.
    echo Could not install the requirements. Check your internet connection and try again.
    pause
    exit /b 1
)

python -m pip install --disable-pip-version-check -q pillow-heif >nul 2>&1

python app.py
pause
