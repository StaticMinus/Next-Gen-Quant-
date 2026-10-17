@echo off
title AgentQuant Master Launcher - Gold Command Center & Copier
echo ========================================================
echo   AgentQuant Pro: Gold Command Center + Copier (cTrader)
echo   Account: FundedNext Stellar $6,000 (#5942153)
echo   Asset: Spot Gold (XAUUSD • symbolId 41)
echo   Strategy: Mode A (2 Tickets: TP1 & TP2 • 0.05 lot each)
echo   Target: +$480.00 USD (+8.0%% Challenge Pass)
echo ========================================================
cd /d "C:\Users\David\Music\Trade\AgentQuant-main"

echo [1/2] Starting Telegram Mobile Command Center & WebApp...
start "AgentQuant Telegram Bot" .venv\Scripts\python.exe -m src.integrations.telegram_bot_service

echo [2/2] Starting 0-Latency Telegram Gold Signal Copier...
start "AgentQuant Gold Copier" .venv\Scripts\python.exe -m src.integrations.telegram_gold_copier

echo.
echo ========================================================
echo   Both services are now running live in background!
echo   - Check Telegram (@YourBot) for the Gold Command Center.
echo   - Copier is armed for Monday London Open signals.
echo ========================================================
timeout /t 5
