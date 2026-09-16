@echo off
title AgentQuant - ASUS TUF Laptop Sleep Crash Repair
cd /d "%~dp0"

echo ======================================================================
echo    AGENTQUANT: 1-CLICK ASUS TUF SLEEP & POWER CRASH REPAIR (PATH 1)
echo ======================================================================
echo.
echo Requesting Windows Administrator privileges to execute power fixes...
echo (When the Windows User Account Control prompt appears, click YES)
echo.

powershell -Command "Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass -File \"\"%~dp0scripts\fix_laptop_sleep_power.ps1\"\"'"
