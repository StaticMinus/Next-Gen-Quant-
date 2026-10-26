@echo off
echo ===================================================
echo Disabling Windows Hibernation to free 31.64 GB...
echo ===================================================
powercfg -h off
if %errorlevel% equ 0 (
    echo.
    echo [SUCCESS] Windows Hibernation has been disabled!
    echo hiberfil.sys (31.64 GB) has been removed from Drive C:.
) else (
    echo.
    echo [ERROR] Administrator privileges are required!
    echo Please right-click this script and choose "Run as administrator".
)
echo.
pause
