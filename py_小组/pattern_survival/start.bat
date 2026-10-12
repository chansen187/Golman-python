@echo off
rem ============================================================
rem  Pattern Survival launcher (double-click to start the game)
rem  Requires: Python 3.8+ on PATH, pygame/pygame-ce installed.
rem ============================================================
title Pattern Survival
cd /d "%~dp0"
python main.py
if errorlevel 1 (
    echo.
    echo [ERROR] The game failed to start.
    echo Please check that Python 3.8+ is on PATH ^(run: python --version^)
    echo and install dependencies with:  pip install -r requirements.txt
    echo.
    pause
)
