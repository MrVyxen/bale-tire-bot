@echo off
chcp 65001 > nul
title مرکز کنترل یکپارچه ربات تایر بله (@tairbot)
cd /d "%~dp0"
if "%~1"=="" (
    python -u bot_ctl.py
) else (
    python -u bot_ctl.py %*
)
if errorlevel 1 pause
