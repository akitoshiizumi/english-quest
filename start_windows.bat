@echo off
setlocal
cd /d "%~dp0"
title English Quest

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher was not found.
    echo Install Python 3 from https://www.python.org/downloads/ and try again.
    echo Make sure to enable the Python Launcher during installation.
    pause
    exit /b 1
)

py -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo Python 3.10 or newer is required.
    py --version
    pause
    exit /b 1
)

if not exist "english_overlap\static\app\index.html" (
    where npm >nul 2>nul
    if errorlevel 1 (
        echo Node.js and npm are required to build the React interface.
        echo Install Node.js 20.19 or newer, then run this file again.
        pause
        exit /b 1
    )
    echo Building the React and TypeScript interface...
    call npm.cmd ci
    if errorlevel 1 (
        echo Could not install the frontend dependencies.
        pause
        exit /b 1
    )
    call npm.cmd run build
    if errorlevel 1 (
        echo Could not build the frontend interface.
        pause
        exit /b 1
    )
)

py server.py --open-browser

if errorlevel 1 (
    echo.
    echo The server stopped because of an error. See the message above.
    pause
)
