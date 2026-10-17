@echo off
title Telegram Gold Signal Copier (cTrader)
echo ========================================================
echo   Telegram Gold (XAUUSD) Copier for cTrader
echo   Channel: t.me/XAUUSD_GOLD_TRADING_FOREX
echo   Strategy: 2 Split Tickets (0.05 lot each = 0.10 lot total)
echo   Targets: TP1 (Bank Profit) + TP2 (Auto-Breakeven on TP1)
echo   Protection: 10-Point Safe SL Clamp + Anti-Chase Guard
echo ========================================================
cd /d "C:\Users\David\Music\Trade\AgentQuant-main"

if "%1"=="--dry-run" (
    echo Starting in DRY-RUN mode...
    .venv\Scripts\python.exe -m src.integrations.telegram_gold_copier --dry-run
) else (
    echo Starting in LIVE EXECUTION mode...
    .venv\Scripts\python.exe -m src.integrations.telegram_gold_copier
)
pause
