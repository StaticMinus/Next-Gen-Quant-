@echo off
title Invo Master-Trader Copier (cTrader)
echo ========================================================
echo   Invo Social Feed -> cTrader Execution
echo   Source : verified master-trader trade posts you follow
echo   Target : FundedNext cTrader account (same as Telegram copier)
echo   Symbols: BTCUSD, ETHUSD (broker lists no SOL/XRP/DOGE)
echo   Risk   : 0.5%% of equity per copy, ATR synthetic stop
echo ========================================================
cd /d "C:\Users\David\Music\Trade\AgentQuant-main"

if "%1"=="--self-test" (
    .venv\Scripts\python.exe src\integrations\invo_ctrader_copier.py --self-test
    pause
    exit /b
)

if "%1"=="--live" (
    echo Starting in LIVE EXECUTION mode - real orders on the cTrader account...
    .venv\Scripts\python.exe src\integrations\invo_ctrader_copier.py --live
) else (
    echo Starting in DRY-RUN mode - signals logged, no orders sent...
    .venv\Scripts\python.exe src\integrations\invo_ctrader_copier.py --dry-run
)
pause
