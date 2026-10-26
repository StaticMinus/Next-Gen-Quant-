#!/usr/bin/env python3
"""
TradingAgents Cycle CLI Runner
==============================
Command line runner for TradingAgents multi-agent financial analysis
and cTrader dry-run or live order execution.

Usage:
    # Run a dry-run analysis and paper trade for Gold:
    python scripts/run_tradingagents_cycle.py --symbol XAUUSD --dry-run

    # Run a dry-run analysis and paper trade for Bitcoin:
    python scripts/run_tradingagents_cycle.py --symbol BTCUSD --dry-run

    # Run both Gold and Bitcoin sequentially:
    python scripts/run_tradingagents_cycle.py --symbol ALL --dry-run
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure root directory is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.integrations.tradingagents_dry_runner import TradingAgentsRunner


def main():
    parser = argparse.ArgumentParser(description="TradingAgents cTrader Cycle Runner")
    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSD",
        choices=["BTCUSD", "XAUUSD", "ALL"],
        help="Target symbol to analyze and trade (BTCUSD, XAUUSD, or ALL)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute live market orders on cTrader (default is dry-run / paper mode)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run in paper/simulation mode without risking real capital (default)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously in a loop at a specified interval",
    )
    parser.add_argument(
        "--interval-minutes",
        type=int,
        default=60,
        help="Interval in minutes between cycles when running with --loop (default: 60)",
    )

    args = parser.parse_args()
    is_dry_run = not args.live

    print("\n" + "=" * 65)
    print("🚀 TRADINGAGENTS + CTRADER PROP-FIRM RUNNER")
    print("=" * 65)
    print(f"Target:       {args.symbol}")
    print(f"Mode:         {'🧪 DRY-RUN (PAPER SIMULATION)' if is_dry_run else '⚡ LIVE EXECUTION'}")
    print(f"Loop:         {args.loop} (Interval: {args.interval_minutes}m)")
    print("=" * 65 + "\n")

    runner = TradingAgentsRunner(dry_run=is_dry_run)

    symbols = ["BTCUSD", "XAUUSD"] if args.symbol == "ALL" else [args.symbol]

    while True:
        for sym in symbols:
            print(f"\n▶ Analyzing {sym}...")
            result = runner.run_cycle_for_symbol(sym)
            if result.get("success"):
                ticket = result["ticket"]
                print(f"✅ Finished {sym}:")
                print(f"   Rating:    {ticket.get('rating')}")
                print(f"   Action:    {ticket.get('action')}")
                print(f"   Spot:      ${ticket.get('entry_price'):,.2f}")
                print(f"   Stop Loss: ${ticket.get('stop_loss'):,.2f}")
                print(f"   Take Prof: ${ticket.get('take_profit'):,.2f}")
                print(f"   Est Risk:  ${ticket.get('est_risk_usd'):,.2f}")
                print(f"   Status:    {ticket.get('status')}")
            else:
                print(f"❌ Cycle aborted for {sym}: {result.get('reason')}")

        if not args.loop:
            break

        print(f"\n⏳ Sleeping for {args.interval_minutes} minutes before next cycle...")
        time.sleep(args.interval_minutes * 60)


if __name__ == "__main__":
    main()
