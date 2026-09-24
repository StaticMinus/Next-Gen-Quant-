#!/usr/bin/env python3
"""
scripts/jev_pure_1h_vs_4h_backtest.py
─────────────────────────────────────────────────────────────────────────────
Pure Jev Trader Engine: Direct 1-Hour vs 4-Hour Multi-Asset Comparison
(Bitcoin, Ethereum, Solana)

Features:
- Pure Jev Decision Model: Signal = (ret_20_bps / 12) + (book_imbalance * 1.8) + (cvd_flow * 2.2)
- Order Flow Directional Flips (Hysteresis 0.58 / 0.42)
- Compares 1-Hour vs 4-Hour across 1-Year dataset
- Accurately tracks Win Rate, Return %, Alpha vs Buy & Hold, Drawdown, and Weekly/Monthly Cadence
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Jev_Pure_1H_4H")

ROOT_DIR = Path(__file__).resolve().parent.parent


def compute_jev_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute order flow imbalance proxy, CVD, and returns for Jev model."""
    df = df.copy()
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float)

    # Returns in Basis Points (1 bps = 0.01%)
    df["ret_1_bps"] = close.pct_change(1) * 10_000
    df["ret_5_bps"] = close.pct_change(5) * 10_000
    df["ret_20_bps"] = close.pct_change(20) * 10_000

    # Order flow proxy (Range position: -1.0 to +1.0)
    range_span = (high - low).replace(0, 1e-9)
    range_pos = ((close - low) - (high - close)) / range_span
    df["book_imbalance"] = range_pos.clip(-1.0, 1.0)

    # Cumulative Volume Delta (CVD) proxy over 20 periods
    estimated_buy_vol = volume * ((close - low) / range_span)
    estimated_sell_vol = volume * ((high - close) / range_span)
    cvd_raw = (estimated_buy_vol - estimated_sell_vol).rolling(20, min_periods=5).sum()
    total_vol = (estimated_buy_vol + estimated_sell_vol).rolling(20, min_periods=5).sum() + 1e-9
    df["cvd_flow"] = (cvd_raw / total_vol).clip(-1.0, 1.0)

    df.dropna(subset=["ret_20_bps", "book_imbalance", "cvd_flow"], inplace=True)
    return df


def jev_decision_model(row: pd.Series) -> Tuple[str, float]:
    """Exact Jev quantitative scoring function."""
    ret20 = float(row["ret_20_bps"])
    imbalance = float(row["book_imbalance"])
    flow = float(row["cvd_flow"])

    signal = (ret20 / 12.0) + (imbalance * 1.8) + (flow * 2.2)
    buy_prob = 1.0 / (1.0 + np.exp(-np.clip(signal, -10, 10)))

    if buy_prob >= 0.58:
        return "BUY", buy_prob
    elif buy_prob <= 0.42:
        return "SELL", 1.0 - buy_prob
    return "HOLD", 0.50


def run_jev_backtest(
    ticker: str = "BTC-USD",
    interval: str = "1h",
    initial_capital: float = 6000.0,
    allocation_pct: float = 0.50, # 50% capital per trade ($3k notional)
    fee_rate: float = 0.0004,     # 4 bps exchange fee
    slippage: float = 0.0002      # 2 bps slippage
) -> Dict[str, Any]:
    period = "730d" if interval in ("1h", "60m") else "2y"
    df_raw = yf.download(ticker, period=period, interval=interval, progress=False)
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)

    df = compute_jev_features(df_raw)
    num_bars = len(df)
    dates = df.index
    closes = df["Close"].values

    capital = initial_capital
    position = "FLAT"
    entry_price = 0.0
    position_size = 0.0
    trades = []
    equity_curve = [initial_capital]

    for idx in range(num_bars):
        current_date = dates[idx]
        curr_price = float(closes[idx])
        row = df.iloc[idx]

        action, buy_prob = jev_decision_model(row)
        allocated_capital = capital * allocation_pct

        if action == "BUY" and position != "LONG":
            # Close short if open
            if position == "SHORT":
                exit_price = curr_price * (1.0 + slippage)
                trade_pnl = position_size * (entry_price - exit_price)
                fee = (position_size * exit_price) * fee_rate
                net = trade_pnl - fee
                capital += net
                trades.append({
                    "exit_date": str(current_date), "type": "CLOSE_SHORT",
                    "gross_pnl": trade_pnl, "fee": fee, "net_pnl": net, "is_win": net > 0
                })
                position = "FLAT"
                position_size = 0.0

            # Open Long
            fill_price = curr_price * (1.0 + slippage)
            position_size = allocated_capital / fill_price
            entry_price = fill_price
            fee = (position_size * fill_price) * fee_rate
            capital -= fee
            position = "LONG"

        elif action == "SELL" and position != "SHORT":
            # Close long if open
            if position == "LONG":
                exit_price = curr_price * (1.0 - slippage)
                trade_pnl = position_size * (exit_price - entry_price)
                fee = (position_size * exit_price) * fee_rate
                net = trade_pnl - fee
                capital += net
                trades.append({
                    "exit_date": str(current_date), "type": "CLOSE_LONG",
                    "gross_pnl": trade_pnl, "fee": fee, "net_pnl": net, "is_win": net > 0
                })
                position = "FLAT"
                position_size = 0.0

            # Open Short
            fill_price = curr_price * (1.0 - slippage)
            position_size = allocated_capital / fill_price
            entry_price = fill_price
            fee = (position_size * fill_price) * fee_rate
            capital -= fee
            position = "SHORT"

        # Unrealized PnL
        unrealized = 0.0
        if position == "LONG":
            unrealized = position_size * (curr_price - entry_price)
        elif position == "SHORT":
            unrealized = position_size * (entry_price - curr_price)

        equity_curve.append(capital + unrealized)

    # Close open position at end
    if position != "FLAT":
        final_price = float(closes[-1])
        if position == "LONG":
            exit_p = final_price * (1.0 - slippage)
            trade_pnl = position_size * (exit_p - entry_price)
        else:
            exit_p = final_price * (1.0 + slippage)
            trade_pnl = position_size * (entry_price - exit_p)
        fee = (position_size * exit_p) * fee_rate
        net = trade_pnl - fee
        capital += net
        trades.append({
            "exit_date": str(dates[-1]), "type": "CLOSE_FINAL",
            "gross_pnl": trade_pnl, "fee": fee, "net_pnl": net, "is_win": net > 0
        })

    # Metrics
    final_equity = capital
    net_pnl = final_equity - initial_capital
    return_pct = (net_pnl / initial_capital) * 100.0
    bh_ret = ((float(closes[-1]) - float(closes[0])) / float(closes[0])) * 100.0

    total_closed = len(trades)
    winning = [t for t in trades if t["is_win"]]
    losing = [t for t in trades if not t["is_win"]]
    win_rate = (len(winning) / total_closed * 100.0) if total_closed > 0 else 0.0

    gross_wins = sum(t["gross_pnl"] for t in winning)
    gross_losses = abs(sum(t["gross_pnl"] for t in losing))
    pf = (gross_wins / gross_losses) if gross_losses > 0 else 999.0
    total_fees = sum(t["fee"] for t in trades)

    # Drawdowns
    eq_arr = np.array(equity_curve)
    peaks = np.maximum.accumulate(eq_arr)
    dds = (eq_arr - peaks) / peaks * 100.0
    max_dd_pct = float(np.min(dds))
    max_dd_usd = float(np.min(eq_arr - peaks))

    days_elapsed = (dates[-1] - dates[0]).total_seconds() / 86400.0
    trades_per_week = (total_closed / max(1.0, days_elapsed)) * 7.0

    return {
        "ticker": ticker,
        "interval": interval,
        "bars": num_bars,
        "period": f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')} ({days_elapsed:.0f} days)",
        "initial_capital": initial_capital,
        "final_equity": round(final_equity, 2),
        "net_pnl_usd": round(net_pnl, 2),
        "net_pnl_ngn": round(net_pnl * 1650.0, 0),
        "return_pct": round(return_pct, 2),
        "buy_and_hold_pct": round(bh_ret, 2),
        "alpha_pct": round(return_pct - bh_ret, 2),
        "total_trades": total_closed,
        "trades_per_week": round(trades_per_week, 1),
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": round(pf, 2),
        "total_fees_paid": round(total_fees, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_drawdown_usd": round(max_dd_usd, 2)
    }


def main():
    print("=" * 100)
    print("🚀 PURE JEV TRADER MULTI-TIMEFRAME AUDIT: 1-HOUR vs 4-HOUR BARS")
    print("   Strategy: Cumulative Volume Delta (CVD Flow) + Order Book Imbalance Momentum")
    print("   Account Model: $6,000 Capital (50% Allocation per Trade) | Real Fees & Slippage")
    print("=" * 100)

    assets = ["BTC-USD", "ETH-USD", "SOL-USD"]
    timeframes = ["1h", "4h"]

    results = []
    for ticker in assets:
        for tf in timeframes:
            res = run_jev_backtest(ticker=ticker, interval=tf, initial_capital=6000.0)
            results.append(res)

    print("\n" + "=" * 100)
    print("🏆 MASTER JEV TRADER SCORECARD: 1H vs 4H COMPARISON ($6,000 ACCOUNT)")
    print("=" * 100)
    print(f"{'Asset':<10} {'TF':<5} {'Trades':<8} {'Trades/Wk':<11} {'Win Rate':<10} {'PF':<6} {'Total Fees':<12} {'Max DD (%)':<12} {'Net PnL ($)':<14} {'Return (%)'}")
    print("-" * 100)
    for r in results:
        pnl_str = f"+${r['net_pnl_usd']:,.2f}" if r['net_pnl_usd'] >= 0 else f"-${abs(r['net_pnl_usd']):,.2f}"
        ret_str = f"+{r['return_pct']:.1f}%" if r['return_pct'] >= 0 else f"{r['return_pct']:.1f}%"
        print(f"{r['ticker']:<10} {r['interval'].upper():<5} {r['total_trades']:<8} {r['trades_per_week']:<11} {r['win_rate_pct']:>6.1f}%     {r['profit_factor']:<6.2f} -${r['total_fees_paid']:>7.2f}    {r['max_drawdown_pct']:>6.1f}%       {pnl_str:<14} {ret_str}")
    print("=" * 100)

    out_file = ROOT_DIR / "cache" / "jev_pure_1h_vs_4h_results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n💾 Full Audit Persisted to: {out_file}")


if __name__ == "__main__":
    main()
