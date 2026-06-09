@echo off
title AOL Crop Vigor Analyzer
cd /d "%~dp0"
echo [AOL Crop Vigor Analyzer]
echo Starting application...
echo.
python main.py
if errorlevel 1 (
    echo.
    echo An error occurred. Check the log for details.
    pause
    exit /b %errorlevel%
)
pause
