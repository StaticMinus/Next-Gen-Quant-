@echo off
title AgentQuant Master Launcher - Command Center & Multi Copier
echo ========================================================
echo   AgentQuant Pro: Command Center + Multi-Channel Copier
echo   Account: FundedNext Stellar $6,000 (#5942153)
echo   Assets: Spot Gold (XAUUSD) + Forex (EURUSD, GBPUSD, AUDNZD, EURJPY)
echo   Channels: SureShotFX, ForexGDP, Learn2Trade, AnabelSignals
echo   Strategy: Automated Breakeven + Anti-Chase + Conflict Shield
echo   Target: +$480.00 USD (+8.0%% Challenge Pass)
echo ========================================================
cd /d "C:\Users\David\Music\Trade\AgentQuant-main"

echo [1/3] Starting Telegram Mobile Command Center & WebApp...
start "AgentQuant Telegram Bot" .venv\Scripts\python.exe -m src.integrations.telegram_bot_service

echo [2/3] Starting 0-Latency Multi-Channel Signal Copier...
start "AgentQuant Multi Copier" .venv\Scripts\python.exe src/integrations/telegram_multi_signal_copier.py

echo [3/3] Starting TradingAgents 24/7 Live Engine (#5947478)...
start "TradingAgents 24/7 Engine" cmd /k "scripts\run_247_tradingagents_background.bat"

echo.
echo ========================================================
echo   All 3 services are now running live in background!
echo   - Check Telegram (@YourBot) for the Mobile Command Center.
echo   - Multi-Channel Copier is armed across Gold & Forex groups (#5947479).
echo   - TradingAgents 24/7 Engine is active for BTCUSD & XAUUSD (#5947478).
echo ========================================================
timeout /t 5
