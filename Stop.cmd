@echo off
chcp 65001 >nul
title Yandex Disk - Local Proxy
cd /d "%~dp0"
py -3.12 "%~dp0bootstrap.py" --stop %*
if errorlevel 20 exit /b 0
echo.
pause
