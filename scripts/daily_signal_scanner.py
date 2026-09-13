"""
Daily Signal Scanner — AgentQuant Prop Firm & Personal Account Assistant
========================================================================
Runs a live check across SPY, QQQ, IWM, and TQQQ to generate actionable
daily trade signals for prop firm (MES, MNQ) or personal accounts.
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.data.ingest import fetch_ohlcv_data
from src.strategies.scalper import ScalperStrategy
from src.backtest.runner import _get_close


def scan_live_signals():
    print("=" * 80)
    print(f"       AGENTQUANT DAILY SIGNAL SCANNER — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)

    assets = [
        {"ticker": "SPY", "prop_symbol": "MES (Micro S&P 500)", "name": "S&P 500 ETF"},
        {"ticker": "QQQ", "prop_symbol": "MNQ (Micro Nasdaq 100)", "name": "Nasdaq 100 ETF"},
        {"ticker": "IWM", "prop_symbol": "M2K (Micro Russell 2000)", "name": "Russell 2000 ETF"},
    ]

    scalper = ScalperStrategy()
    params = {
        "window": 5,
        "num_std": 1.25,
        "exit_at_mean": True,
        "allow_short": False,
        "stop_loss_pct": 0.03,
        "max_hold_bars": 5,
    }

    signals_found = []

    print("\nScanning active asset universes...")
    for item in assets:
        ticker = item["ticker"]
        prop_sym = item["prop_symbol"]
        try:
            ohlcv = fetch_ohlcv_data(ticker=ticker)
            df = ohlcv[ticker]
            close = _get_close(df)
        except Exception as e:
            print(f"  [!] Could not load data for {ticker}: {e}")
            continue

        # Compute bands
        w = params["window"]
        num_std = params["num_std"]
        mid = close.rolling(w).mean()
        std = close.rolling(w).std()
        lower = mid - num_std * std
        upper = mid + num_std * std

        latest_dt = close.index[-1]
        c = float(close.iloc[-1])
        m = float(mid.iloc[-1])
        l = float(lower.iloc[-1])
        u = float(upper.iloc[-1])

        # Run strategy signal series
        sig = scalper.generate_signal(df, params)
        latest_sig = int(sig.iloc[-1])
        prev_sig = int(sig.iloc[-2]) if len(sig) > 1 else 0

        # Check conditions
        is_oversold_dip = c < l
        is_returning_to_mean = (prev_sig == 1 and c >= m)

        status = "FLAT (CASH)"
        action = "None — Wait for a dip setup."

        if latest_sig == 1:
            if prev_sig == 0:
                status = "🚨 NEW BUY SIGNAL TODAY"
                action = f"BUY 1 {prop_sym} at Market. Target: ${m:.2f} | Stop Loss: ${c * 0.97:.2f} (-3%)"
                signals_found.append((ticker, prop_sym, "NEW BUY", c, m, c * 0.97))
            else:
                status = "HOLDING LONG POSITION"
                action = f"Hold position. Waiting for take-profit target at Mean (${m:.2f})."
                signals_found.append((ticker, prop_sym, "HOLD LONG", c, m, c * 0.97))
        elif prev_sig == 1 and latest_sig == 0:
            status = "✅ TAKE PROFIT REACHED"
            action = f"EXIT LONG. Reached mean target (${m:.2f}). Lock in profits!"

        print(f"\n--- {ticker} ({item['name']}) | Prop Contract: {prop_sym} ---")
        print(f"  Latest Price:     ${c:.2f} (Date: {latest_dt.strftime('%Y-%m-%d')})")
        print(f"  5-Day Mean (Mid): ${m:.2f}")
        print(f"  Lower Band (Buy): ${l:.2f}")
        print(f"  Upper Band:       ${u:.2f}")
        print(f"  Strategy Status:  {status}")
        print(f"  Action Plan:      {action}")

    print("\n" + "=" * 80)
    print("                           SCANNER SUMMARY")
    print("=" * 80)
    summary_lines = []
    if signals_found:
        print(f"Active Signals Detected: {len(signals_found)}")
        summary_lines.append(f"🤖 *AgentQuant Daily Signal Alert* ({datetime.now().strftime('%Y-%m-%d')})\n")
        for ticker, prop_sym, act, price, target, stop in signals_found:
            line = f"• *[{ticker}] {act}* on `{prop_sym}`\n  Price: `${price:.2f}` | Target: `${target:.2f}` | Stop: `${stop:.2f}`"
            print(f"  • [{ticker}] {act} on {prop_sym}: Entry ~${price:.2f} | Target: ${target:.2f} | Stop: ${stop:.2f}")
            summary_lines.append(line)
    else:
        print("  No new entries triggered today. The market is currently between bands.")
        print("  Golden Rule: 90% of winning traders' time is spent waiting in cash.")
        print("  Do not force trades. Let the algorithm tell you when the odds are 80%+ in your favor.")
        summary_lines.append(f"🤖 *AgentQuant Daily Status* ({datetime.now().strftime('%Y-%m-%d')})\n• All markets between bands. 100% Cash / Waiting for dip.")
    print("=" * 80 + "\n")

    # Send Telegram Notification if requested or in CI
    if "--notify" in sys.argv:
        try:
            from src.utils.telegram_notifier import send_telegram_alert
            alert_text = "\n".join(summary_lines)
            sent = send_telegram_alert(alert_text)
            if sent:
                print("✅ Telegram notification delivered to your phone!")
        except Exception as e:
            print(f"Could not send Telegram notification: {e}")


if __name__ == "__main__":
    scan_live_signals()
