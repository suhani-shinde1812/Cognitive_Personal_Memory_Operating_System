@echo off
title CogniSphere Desktop Agent
echo ======================================================
echo    CogniSphere Desktop Agent — File ^& Memory Sync
echo ======================================================
echo.

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe desktop_agent\agent.py %*
) else if exist "backend\.venv\Scripts\python.exe" (
    backend\.venv\Scripts\python.exe desktop_agent\agent.py %*
) else (
    python desktop_agent\agent.py %*
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Desktop Agent stopped or encountered an error.
    pause
)
