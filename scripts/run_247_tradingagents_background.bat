@echo off
title TradingAgents 24/7 Live Engine (Account #5947478)
echo ========================================================
echo   TRADINGAGENTS 24/7 MULTI-AGENT LIVE ENGINE
echo   Target Account: #5947478 (FundedNext $6K)
echo   Target Assets:  BTCUSD (24/7) + XAUUSD (Gold)
echo ========================================================
echo.

cd /d "%~dp0\.."

:loop
echo [%date% %time%] Running TradingAgents fast cycle (Gold, Bitcoin, then Forex Majors)...
call .venv\Scripts\python.exe scripts\run_tradingagents_cycle.py --symbol FAST_MAJORS --live

echo.
echo [%date% %time%] Fast cycle completed. Waiting 15 minutes for next scan...
echo Press Ctrl+C to stop.
timeout /t 900 /nobreak >nul
goto loop
