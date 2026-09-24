#!/usr/bin/env python3
"""
scripts/jev_trader_1h_4h_multi_asset_backtest.py
─────────────────────────────────────────────────────────────────────────────
Comprehensive Jev Trader Backtest: 1-Hour vs 4-Hour Timeframes on BTC & ETH
Features:
- Order Book Imbalance (-1.0 to +1.0)
- Cumulative Volume Delta (CVD Flow over 20 periods)
- Basis Points Multi-Horizon Momentum (ret_20_bps)
- Realistic cTrader Broker Commissions ($34/lot BTC, $10.80/lot ETH)
- FundedNext $6,000 Account Safety Verification ($180 daily / $360 max DD)
- Formatted side-by-side comparative ledger
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Jev_1H_4H")

ROOT_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT_DIR / "cache" / "jev_timeframes"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def compute_jev_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute order flow imbalance, CVD flow, and basis point returns."""
    df = df.copy()
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float)

    # Returns in Basis Points (1 bps = 0.01%)
    df["ret_1_bps"] = close.pct_change(1) * 10_000
    df["ret_5_bps"] = close.pct_change(5) * 10_000
    df["ret_20_bps"] = close.pct_change(20) * 10_000

    # Order flow proxy (Range Position: +1.0 at high, -1.0 at low)
    range_span = (high - low).replace(0, 1e-9)
    range_pos = ((close - low) - (high - close)) / range_span
    df["book_imbalance"] = range_pos.clip(-1.0, 1.0)

    # Cumulative Volume Delta (CVD) proxy over 20 periods
    estimated_buy_vol = volume * ((close - low) / range_span)
    estimated_sell_vol = volume * ((high - close) / range_span)
    cvd_raw = (estimated_buy_vol - estimated_sell_vol).rolling(20, min_periods=5).sum()
    total_vol = (estimated_buy_vol + estimated_sell_vol).rolling(20, min_periods=5).sum() + 1e-9
    df["cvd_flow"] = (cvd_raw / total_vol).clip(-1.0, 1.0)

    # Moving average trend filter
    df["sma_50"] = close.rolling(50, min_periods=10).mean()
    df["sma_200"] = close.rolling(200, min_periods=20).mean()

    df.dropna(subset=["ret_20_bps", "book_imbalance", "cvd_flow"], inplace=True)
    return df


def jev_signal(row: pd.Series) -> Tuple[str, float]:
    """
    Jev Decision Formulation:
    signal = (ret_20_bps / 12.0) + (book_imbalance * 1.8) + (cvd_flow * 2.2)
    buy_prob = 1 / (1 + exp(-signal))
    """
    ret20 = float(row["ret_20_bps"])
    imbalance = float(row["book_imbalance"])
    flow = float(row["cvd_flow"])

    raw_signal = (ret20 / 12.0) + (imbalance * 1.8) + (flow * 2.2)
    buy_prob = 1.0 / (1.0 + np.exp(-np.clip(raw_signal, -10, 10)))

    if buy_prob >= 0.58:
        return "BUY", buy_prob
    elif buy_prob <= 0.42:
        return "SELL", 1.0 - buy_prob
    return "HOLD", 0.50


def fetch_historical_data(ticker: str, interval: str, period: str = "730d") -> pd.DataFrame:
    """Fetch OHLCV from cache or yfinance."""
    cache_file = CACHE_DIR / f"{ticker.replace('-', '_')}_{interval}_{period}.parquet"
    if cache_file.exists():
        try:
            df = pd.read_parquet(cache_file)
            if len(df) > 100:
                return df
        except Exception:
            pass

    print(f"[*] Downloading {ticker} ({interval} interval, {period})...", flush=True)
    df_raw = yf.download(ticker, period=period, interval=interval, progress=False)
    if df_raw.empty:
        raise ValueError(f"No data returned for {ticker} ({interval})")
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)

    df_raw.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)
    df_raw.to_parquet(cache_file)
    return df_raw


def run_jev_simulation(
    ticker: str = "BTC-USD",
    interval: str = "1h",
    initial_balance: float = 6000.0,
    lot_size: float = 0.04,
    comm_per_lot: float = 34.0,
    slippage_bps: float = 2.5,
    stop_loss_pct: float = 0.015, # 1.5% structural stop on 1H/4H
    take_profit_pct: float = 0.035, # 3.5% extended runner target (~2.33 R:R)
    trailing_breakeven_pct: float = 0.012 # Move SL to BE at +1.2%
) -> Dict[str, Any]:
    """Runs Jev simulation with institutional cTrader execution friction."""
    # Yfinance supports max 730d for hourly data
    period = "730d" if interval in ("1h", "60m") else "2y"
    df_raw = fetch_historical_data(ticker, interval, period=period)
    df = compute_jev_features(df_raw)

    closes = df["Close"].to_numpy()
    highs = df["High"].to_numpy()
    lows = df["Low"].to_numpy()
    opens = df["Open"].to_numpy()
    timestamps = df.index
    n = len(df)

    capital = initial_balance
    equity_curve = [initial_balance]
    trades = []
    
    position = "FLAT" # 'LONG' or 'SHORT'
    entry_price = 0.0
    entry_idx = 0
    current_sl = 0.0
    current_tp = 0.0
    be_locked = False

    daily_tracker: Dict[str, float] = {}

    for i in range(1, n):
        row = df.iloc[i-1] # Previous closed bar signal
        curr_open = opens[i]
        curr_high = highs[i]
        curr_low = lows[i]
        curr_close = closes[i]
        curr_date_str = str(timestamps[i].date())

        action, prob = jev_signal(row)
        slip = curr_open * (slippage_bps / 10_000.0)

        # 1. Manage Active Position
        if position == "LONG":
            # Check Trailing Breakeven Lock
            if not be_locked and curr_high >= entry_price * (1.0 + trailing_breakeven_pct):
                current_sl = entry_price * 1.0006 # BE + cover comms
                be_locked = True

            # Check Stop Loss
            if curr_low <= current_sl:
                exit_price = current_sl - slip
                gross = (exit_price - entry_price) * lot_size
                comm = comm_per_lot * lot_size * 2.0
                net = gross - comm
                capital += net
                trades.append({
                    "entry_time": str(timestamps[entry_idx]),
                    "exit_time": str(timestamps[i]),
                    "side": "LONG",
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "gross": gross,
                    "comm": comm,
                    "net": net,
                    "reason": "BE_STOP" if be_locked else "SL",
                    "is_win": net > 0
                })
                daily_tracker[curr_date_str] = daily_tracker.get(curr_date_str, 0.0) + net
                position = "FLAT"

            # Check Take Profit
            elif curr_high >= current_tp:
                exit_price = current_tp - slip
                gross = (exit_price - entry_price) * lot_size
                comm = comm_per_lot * lot_size * 2.0
                net = gross - comm
                capital += net
                trades.append({
                    "entry_time": str(timestamps[entry_idx]),
                    "exit_time": str(timestamps[i]),
                    "side": "LONG",
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "gross": gross,
                    "comm": comm,
                    "net": net,
                    "reason": "TP",
                    "is_win": net > 0
                })
                daily_tracker[curr_date_str] = daily_tracker.get(curr_date_str, 0.0) + net
                position = "FLAT"

            # Signal Reversal Exit
            elif action == "SELL":
                exit_price = curr_open - slip
                gross = (exit_price - entry_price) * lot_size
                comm = comm_per_lot * lot_size * 2.0
                net = gross - comm
                capital += net
                trades.append({
                    "entry_time": str(timestamps[entry_idx]),
                    "exit_time": str(timestamps[i]),
                    "side": "LONG",
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "gross": gross,
                    "comm": comm,
                    "net": net,
                    "reason": "REVERSAL",
                    "is_win": net > 0
                })
                daily_tracker[curr_date_str] = daily_tracker.get(curr_date_str, 0.0) + net
                position = "FLAT"

        elif position == "SHORT":
            # Check Trailing Breakeven Lock
            if not be_locked and curr_low <= entry_price * (1.0 - trailing_breakeven_pct):
                current_sl = entry_price * 0.9994
                be_locked = True

            # Check Stop Loss
            if curr_high >= current_sl:
                exit_price = current_sl + slip
                gross = (entry_price - exit_price) * lot_size
                comm = comm_per_lot * lot_size * 2.0
                net = gross - comm
                capital += net
                trades.append({
                    "entry_time": str(timestamps[entry_idx]),
                    "exit_time": str(timestamps[i]),
                    "side": "SHORT",
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "gross": gross,
                    "comm": comm,
                    "net": net,
                    "reason": "BE_STOP" if be_locked else "SL",
                    "is_win": net > 0
                })
                daily_tracker[curr_date_str] = daily_tracker.get(curr_date_str, 0.0) + net
                position = "FLAT"

            # Check Take Profit
            elif curr_low <= current_tp:
                exit_price = current_tp + slip
                gross = (entry_price - exit_price) * lot_size
                comm = comm_per_lot * lot_size * 2.0
                net = gross - comm
                capital += net
                trades.append({
                    "entry_time": str(timestamps[entry_idx]),
                    "exit_time": str(timestamps[i]),
                    "side": "SHORT",
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "gross": gross,
                    "comm": comm,
                    "net": net,
                    "reason": "TP",
                    "is_win": net > 0
                })
                daily_tracker[curr_date_str] = daily_tracker.get(curr_date_str, 0.0) + net
                position = "FLAT"

            # Signal Reversal Exit
            elif action == "BUY":
                exit_price = curr_open + slip
                gross = (entry_price - exit_price) * lot_size
                comm = comm_per_lot * lot_size * 2.0
                net = gross - comm
                capital += net
                trades.append({
                    "entry_time": str(timestamps[entry_idx]),
                    "exit_time": str(timestamps[i]),
                    "side": "SHORT",
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "gross": gross,
                    "comm": comm,
                    "net": net,
                    "reason": "REVERSAL",
                    "is_win": net > 0
                })
                daily_tracker[curr_date_str] = daily_tracker.get(curr_date_str, 0.0) + net
                position = "FLAT"

        # 2. Enter New Position
        if position == "FLAT":
            if action == "BUY":
                position = "LONG"
                entry_price = curr_open + slip
                entry_idx = i
                current_sl = entry_price * (1.0 - stop_loss_pct)
                current_tp = entry_price * (1.0 + take_profit_pct)
                be_locked = False
            elif action == "SELL":
                position = "SHORT"
                entry_price = curr_open - slip
                entry_idx = i
                current_sl = entry_price * (1.0 + stop_loss_pct)
                current_tp = entry_price * (1.0 - take_profit_pct)
                be_locked = False

        equity_curve.append(capital)

    # 3. Compile Master Analytics
    total_trades = len(trades)
    winning_trades = [t for t in trades if t["is_win"]]
    losing_trades = [t for t in trades if not t["is_win"]]
    win_rate = (len(winning_trades) / total_trades * 100.0) if total_trades > 0 else 0.0

    avg_win = float(np.mean([t["net"] for t in winning_trades])) if winning_trades else 0.0
    avg_loss = float(np.mean([t["net"] for t in losing_trades])) if losing_trades else 0.0
    payoff = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

    total_gross = sum(t["gross"] for t in trades)
    total_comm = sum(t["comm"] for t in trades)
    net_pnl = capital - initial_balance
    return_pct = (net_pnl / initial_balance) * 100.0

    gross_gains = sum(t["gross"] for t in winning_trades)
    gross_losses = abs(sum(t["gross"] for t in losing_trades))
    profit_factor = (gross_gains / gross_losses) if gross_losses > 0 else 999.0

    # Drawdown calculations
    eq_arr = np.array(equity_curve)
    peaks = np.maximum.accumulate(eq_arr)
    dds = eq_arr - peaks
    max_dd_usd = float(np.min(dds))
    max_dd_pct = (max_dd_usd / initial_balance) * 100.0

    # Max single-day loss
    daily_pnls = list(daily_tracker.values())
    max_single_day_loss = abs(min(daily_pnls)) if daily_pnls and min(daily_pnls) < 0 else 0.0

    # Cadence
    days_elapsed = (timestamps[-1] - timestamps[0]).total_seconds() / 86400.0
    trades_per_day = total_trades / max(1.0, days_elapsed)
    trades_per_week = trades_per_day * 7.0
    trades_per_month = trades_per_day * 30.4

    # Monthly breakdown
    df_trades = pd.DataFrame(trades)
    monthly_data = []
    if not df_trades.empty:
        df_trades["exit_dt"] = pd.to_datetime(df_trades["exit_time"])
        df_trades["month_year"] = df_trades["exit_dt"].dt.to_period("M")
        for m, group in df_trades.groupby("month_year"):
            m_net = group["net"].sum()
            m_win = (group["is_win"].sum() / len(group)) * 100.0
            monthly_data.append({
                "month": str(m),
                "trades": len(group),
                "win_rate_pct": round(m_win, 1),
                "net_pnl_usd": round(m_net, 2),
                "net_pnl_ngn": round(m_net * 1650.0, 0)
            })

    # Benchmark buy & hold
    bh_ret = ((closes[-1] - closes[0]) / closes[0]) * 100.0

    return {
        "ticker": ticker,
        "interval": interval,
        "period": f"{timestamps[0].strftime('%Y-%m-%d')} to {timestamps[-1].strftime('%Y-%m-%d')} ({days_elapsed:.0f} days)",
        "bars": n,
        "initial_balance": initial_balance,
        "final_balance": round(capital, 2),
        "net_pnl_usd": round(net_pnl, 2),
        "net_pnl_ngn": round(net_pnl * 1650.0, 0),
        "return_pct": round(return_pct, 2),
        "buy_and_hold_pct": round(bh_ret, 2),
        "alpha_pct": round(return_pct - bh_ret, 2),
        "total_trades": total_trades,
        "wins": len(winning_trades),
        "losses": len(losing_trades),
        "win_rate_pct": round(win_rate, 2),
        "avg_win_usd": round(avg_win, 2),
        "avg_loss_usd": round(avg_loss, 2),
        "payoff_ratio": round(payoff, 2),
        "profit_factor": round(profit_factor, 2),
        "total_commission_usd": round(total_comm, 2),
        "max_drawdown_usd": round(max_dd_usd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_single_day_loss": round(max_single_day_loss, 2),
        "fundednext_daily_safe": max_single_day_loss < 180.0,
        "fundednext_max_safe": abs(max_dd_usd) < 360.0,
        "cadence": {
            "trades_per_day": round(trades_per_day, 2),
            "trades_per_week": round(trades_per_week, 2),
            "trades_per_month": round(trades_per_month, 2)
        },
        "monthly_data": monthly_data
    }


def main():
    print("=" * 95)
    print("🚀 JEV TRADER INSTITUTIONAL BACKTEST: 1-HOUR vs 4-HOUR TIMEFRAMES")
    print("   Account: $6,000 FundedNext | Model: CVD Flow + Order Book Imbalance + Asymmetric Runner")
    print("   Target R:R: 1.5% SL / 3.5% TP (2.33 R:R) + 1.2% Trailing Breakeven Lock")
    print("=" * 95)

    configs = [
        {"ticker": "BTC-USD", "interval": "1h", "lot": 0.04, "comm": 34.0, "sl": 0.015, "tp": 0.035, "be": 0.012},
        {"ticker": "BTC-USD", "interval": "4h", "lot": 0.04, "comm": 34.0, "sl": 0.025, "tp": 0.060, "be": 0.020},
        {"ticker": "ETH-USD", "interval": "1h", "lot": 0.50, "comm": 10.80, "sl": 0.018, "tp": 0.040, "be": 0.014},
        {"ticker": "ETH-USD", "interval": "4h", "lot": 0.50, "comm": 10.80, "sl": 0.030, "tp": 0.070, "be": 0.025},
    ]

    all_results = []
    for cfg in configs:
        res = run_jev_simulation(
            ticker=cfg["ticker"],
            interval=cfg["interval"],
            initial_balance=6000.0,
            lot_size=cfg["lot"],
            comm_per_lot=cfg["comm"],
            stop_loss_pct=cfg["sl"],
            take_profit_pct=cfg["tp"],
            trailing_breakeven_pct=cfg["be"]
        )
        all_results.append(res)

    # Master Comparative Scorecard
    print("\n" + "=" * 95)
    print("🏆 MASTER TIMEFRAME COMPARATIVE SCORECARD ($6,000 ACCOUNT)")
    print("=" * 95)
    print(f"{'Asset & Timeframe':<22} {'Trades':<8} {'Win Rate':<10} {'Profit Factor':<14} {'Commission':<12} {'Max DD ($)':<12} {'Net PnL ($)':<14}")
    print("-" * 95)
    for r in all_results:
        tag = f"{r['ticker']} ({r['interval'].upper()})"
        pnl_str = f"+${r['net_pnl_usd']:,.2f}" if r['net_pnl_usd'] >= 0 else f"-${abs(r['net_pnl_usd']):,.2f}"
        dd_str = f"-${abs(r['max_drawdown_usd']):,.2f}"
        print(f"{tag:<22} {r['total_trades']:<8} {r['win_rate_pct']:>6.1f}%     {r['profit_factor']:>6.2f}         -${r['total_commission_usd']:>7.2f}    {dd_str:<12} {pnl_str:<14}")
    print("=" * 95)

    # Save to JSON
    out_file = ROOT_DIR / "cache" / "jev_1h_4h_master_comparison.json"
    with open(out_file, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n💾 Full Audit Report persisted to: {out_file}")


if __name__ == "__main__":
    main()
