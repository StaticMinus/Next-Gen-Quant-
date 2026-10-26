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
echo [%date% %time%] Running TradingAgents cycle...
call .venv\Scripts\python.exe scripts\run_tradingagents_cycle.py --symbol ALL --live

echo.
echo [%date% %time%] Cycle completed. Waiting 60 minutes for next market scan...
echo Press Ctrl+C to stop.
timeout /t 3600 /nobreak >nul
goto loop
