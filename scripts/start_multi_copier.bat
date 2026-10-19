@echo off
title Multi-Channel Signal Copier (Gold + Forex - cTrader)
echo ========================================================
echo   Universal Multi-Channel Signal Copier for cTrader
echo   Channels:
echo     - SureShotFX Gold (t.me/ssfgold)
echo     - ForexGDP Free (t.me/forexgdpfree)
echo     - Learn 2 Trade (t.me/learn2tradenews)
echo     - Gold Scalper (t.me/XAUUSD_GOLD_TRADING_FOREX)
echo   Assets: Gold (XAUUSD) + Forex (EURUSD, GBPUSD, AUDNZD, EURJPY)
echo   Protection: Anti-Chase Guard + Auto-Breakeven + Conflict Arbiter
echo ========================================================
cd /d "C:\Users\David\Music\Trade\AgentQuant-main"

if "%1"=="--dry-run" (
    echo Starting in DRY-RUN mode...
    .venv\Scripts\python.exe src\integrations\telegram_multi_signal_copier.py --dry-run
) else (
    echo Starting in LIVE EXECUTION mode...
    .venv\Scripts\python.exe src\integrations\telegram_multi_signal_copier.py
)
pause
