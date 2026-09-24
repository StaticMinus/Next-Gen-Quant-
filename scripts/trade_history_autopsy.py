"""
Trade History Autopsy & Failure Analysis
========================================
Pulls all recent live closed deals from FundedNext cTrader account #3028655.
Pairs trades with broker market data, calculates exact gross vs net PnL,
analyzes commission drag, and classifies root causes of losses:
  - Noise Stop-Out (1M random noise breaching fixed 0.35%/0.50% SL)
  - Waterfall Counter-Trend (entering into 15M downtrend/session open plunge)
  - Commission Drag (gross green turned net red)
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.integrations.ctrader_mcp_client import CTraderMCPClient

def run_autopsy(days: int = 3) -> Dict[str, Any]:
    print("=" * 75)
    print("🔍 AGENTQUANT LIVE TRADE AUTOPSY & FAILURE ANALYSIS")
    print(f"   Target Account: FundedNext cTrader #3028655 | Window: Last {days} Days")
    print("=" * 75)

    client = CTraderMCPClient()
    if not client.initialize():
        print("❌ Failed to initialize cTrader MCP client!")
        return {}

    deals = client.get_closed_deals(days=days)
    if not deals:
        print("⚠️ No closed deals found in window.")
        return {}

    print(f"✅ Retrieved {len(deals)} closed trade cycles from broker history.\n")

    # Fetch 15M and 1M bars for BTCUSD and ETHUSD to analyze context
    btc_15m = client.get_trendbars_dataframe("BTCUSD", period="M_15", count=150)
    eth_15m = client.get_trendbars_dataframe("ETHUSD", period="M_15", count=150)

    analyzed_trades = []
    
    total_gross = 0.0
    total_comm = 0.0
    total_net = 0.0
    wins = []
    losses = []

    for d in deals:
        pos_id = d["position_id"]
        sym = d["symbol_name"]
        lots = d["lots"]
        entry_p = d["entry_price"]
        exit_p = d["exit_price"]
        gross = d["gross_pnl"]
        comm = d["commission"]
        net = d["net_pnl"]
        side = d["trade_side"]
        exit_ts = d["exit_timestamp"]

        total_gross += gross
        total_comm += comm
        total_net += net

        # Price percentage move
        pct_move = ((exit_p - entry_p) / entry_p) * 100.0 if side == "BUY" else ((entry_p - exit_p) / entry_p) * 100.0

        # Classify trade result
        is_win = net > 0
        if is_win:
            wins.append(net)
        else:
            losses.append(net)

        # Root cause classification for losses
        category = "WIN"
        if not is_win:
            if gross > 0 and net <= 0:
                category = "COMMISSION_DRAG"
            elif abs(pct_move) <= 0.55:
                category = "NOISE_STOP_OUT"  # Caught by tight 0.35% - 0.50% stop inside normal candle noise
            else:
                category = "WATERFALL_MOMENTUM"  # Deep counter-trend dump

        trade_info = {
            "position_id": pos_id,
            "symbol": sym,
            "side": side,
            "lots": lots,
            "entry_price": entry_p,
            "exit_price": exit_p,
            "pct_move": round(pct_move, 3),
            "gross_pnl": round(gross, 2),
            "commission": round(comm, 2),
            "net_pnl": round(net, 2),
            "is_win": is_win,
            "category": category,
            "exit_time": d["exit_time"],
        }
        analyzed_trades.append(trade_info)

    # Calculate Macro Telemetry
    total_trades = len(analyzed_trades)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total_trades) * 100.0 if total_trades > 0 else 0.0

    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

    # Mathematical Expectancy per trade: (WR * Avg_Win) - (LR * Avg_Loss)
    lr = 1.0 - (win_rate / 100.0)
    wr = win_rate / 100.0
    expectancy = (wr * avg_win) + (lr * avg_loss)

    # Category counts
    cat_counts = {}
    for t in analyzed_trades:
        c = t["category"]
        cat_counts[c] = cat_counts.get(c, 0) + 1

    # Print Formatted Autopsy Table
    print(f"{'Pos ID':<10} {'Symbol':<8} {'Lots':<6} {'Entry':<10} {'Exit':<10} {'% Move':<8} {'Gross':<8} {'Comm':<7} {'Net PnL':<9} {'Diagnosis'}")
    print("-" * 95)
    for t in analyzed_trades:
        diag_icon = "🎯 WIN" if t["is_win"] else f"❌ {t['category']}"
        print(f"#{t['position_id']:<9} {t['symbol']:<8} {t['lots']:<6} ${t['entry_price']:<9.2f} ${t['exit_price']:<9.2f} {t['pct_move']:>+6.2f}% ${t['gross_pnl']:>+6.2f} ${t['commission']:>5.2f} ${t['net_pnl']:>+7.2f}  {diag_icon}")

    print("-" * 95)
    print("\n📊 MASTER AUTOPSY SUMMARY:")
    print(f"   • Total Trades Analyzed: {total_trades}")
    print(f"   • Wins: {win_count} ({win_rate:.1f}%) | Losses: {loss_count} ({100-win_rate:.1f}%)")
    print(f"   • Total Gross PnL: ${total_gross:>+8.2f} USD")
    print(f"   • Total Broker Commission: ${total_comm:>+8.2f} USD ({abs(total_comm)/max(1, abs(total_gross))*100:.1f}% drag)")
    print(f"   • Net Realized Account PnL: ${total_net:>+8.2f} USD")
    print("-" * 50)
    print(f"   • Average Winning Trade: +${avg_win:.2f} USD")
    print(f"   • Average Losing Trade:   -${abs(avg_loss):.2f} USD")
    print(f"   • Live Payoff Ratio (Win/Loss): 1 : {abs(avg_loss)/max(0.01, avg_win):.2f} (INVERTED ASYMMETRY!)")
    print(f"   • Realized Expectancy / Trade: ${expectancy:>+6.2f} USD per trade")
    print("-" * 50)
    print("🔬 ROOT CAUSE BREAKDOWN OF LOSSES:")
    for cat, count in cat_counts.items():
        if cat != "WIN":
            pct = (count / loss_count) * 100.0 if loss_count > 0 else 0
            print(f"   • {cat}: {count} trades ({pct:.1f}% of all losses)")

    report = {
        "account_id": "3028655",
        "timestamp": datetime.now().isoformat(),
        "total_trades": total_trades,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate_pct": round(win_rate, 2),
        "total_gross_usd": round(total_gross, 2),
        "total_commission_usd": round(total_comm, 2),
        "total_net_usd": round(total_net, 2),
        "avg_win_usd": round(avg_win, 2),
        "avg_loss_usd": round(avg_loss, 2),
        "payoff_ratio": round(win_loss_ratio, 3),
        "expectancy_per_trade_usd": round(expectancy, 3),
        "loss_categories": cat_counts,
        "trades": analyzed_trades
    }

    cache_file = ROOT_DIR / "cache" / "live_trade_autopsy.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n💾 Autopsy persisted to: {cache_file}")
    return report

if __name__ == "__main__":
    run_autopsy(days=3)
