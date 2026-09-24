"""
Bitcoin 1-Minute Strategy 6-Month Backtest ($20.00 Personal Micro-Account)
==========================================================================
Simulates the exact 1-Minute Microstructure Sniper Strategy across 250,000 real M1 bars
starting from a $20.00 personal account (no prop firm limits).

Evaluates:
- Number of trades per day, per week, per month, and total
- Profit per day, per week, per month (detailed monthly trajectory)
- 3 Realistic Sizing Models:
  1. Fixed Micro-Lot ($20.00 fixed size / 1x margin)
  2. Realistic Micro-Compounding (3x Leverage, Capped at $1,000 Max Notional)
  3. Dynamic Compounding (5x Leverage, Capped at $3,000 Max Notional)
"""

import json
import sys
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CACHE_FILE = Path("cache/crypto_1m/BTCUSDT_1m_250k.parquet")


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_p = df["open"]
    vol = df["volume"]

    # 20-Period Mean & 2.0-Sigma Bands
    df["ma_20"] = close.rolling(20).mean()
    df["std_20"] = close.rolling(20).std()
    df["lower_band"] = df["ma_20"] - (2.0 * df["std_20"])
    df["ema_5"] = close.ewm(span=5, adjust=False).mean()

    # Candlestick Geometry & Wick Absorption
    candle_range = (high - low).replace(0, 1e-9)
    body_size = (close - open_p).abs()
    lower_wick = np.minimum(close, open_p) - low
    df["lower_wick_ratio"] = lower_wick / candle_range

    # Volume Spike Factor
    df["vol_ma"] = vol.rolling(20).mean() + 1e-9
    df["vol_spike"] = vol / df["vol_ma"]

    df.dropna(inplace=True)
    return df


def simulate_btc_account(df: pd.DataFrame, initial_capital: float = 20.0, mode: str = "fixed", max_notional_cap: float = 1000.0):
    capital = initial_capital
    peak_capital = initial_capital
    max_dd_usd = 0.0
    max_dd_pct = 0.0

    position = "FLAT"
    entry_price = 0.0
    position_size = 0.0
    entry_idx = 0
    stop_loss_price = 0.0
    take_profit_price = 0.0

    trades = []
    equity_curve = [initial_capital]

    fee_rate = 0.0003  # 3 bps exchange fee
    slippage = 0.0001  # 1 bps slippage
    sl_pct = 0.0050    # 0.50% hard stop loss
    tp_pct = 0.0060    # 0.60% take profit
    max_hold_minutes = 15

    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    lower_bands = df["lower_band"].values
    ema_5s = df["ema_5"].values
    lower_wicks = df["lower_wick_ratio"].values
    vol_spikes = df["vol_spike"].values
    dates = df.index

    for i in range(len(df)):
        curr_date = dates[i]
        curr_price = float(closes[i])
        curr_high = float(highs[i])
        curr_low = float(lows[i])

        # 1. Manage Open Position
        if position == "LONG":
            bars_held = i - entry_idx

            # Check Stop Loss (Intra-bar low breached stop)
            if curr_low <= stop_loss_price:
                exit_p = stop_loss_price * (1.0 - slippage)
                pnl = position_size * (exit_p - entry_price)
                fee = (position_size * exit_p + position_size * entry_price) * fee_rate
                net_pnl = pnl - fee
                capital += net_pnl
                trades.append({
                    "entry_time": dates[entry_idx],
                    "exit_time": curr_date,
                    "type": "STOP_LOSS",
                    "entry_price": entry_price,
                    "exit_price": exit_p,
                    "pnl": net_pnl,
                    "equity": capital,
                    "duration_mins": bars_held,
                    "win": False
                })
                equity_curve.append(capital)
                position = "FLAT"

            # Check Take Profit (Target hit or EMA-5 reversion reached)
            elif curr_high >= take_profit_price or curr_price >= ema_5s[i]:
                exit_p = max(take_profit_price, curr_price) * (1.0 - slippage)
                pnl = position_size * (exit_p - entry_price)
                fee = (position_size * exit_p + position_size * entry_price) * fee_rate
                net_pnl = pnl - fee
                capital += net_pnl
                trades.append({
                    "entry_time": dates[entry_idx],
                    "exit_time": curr_date,
                    "type": "TAKE_PROFIT",
                    "entry_price": entry_price,
                    "exit_price": exit_p,
                    "pnl": net_pnl,
                    "equity": capital,
                    "duration_mins": bars_held,
                    "win": True
                })
                equity_curve.append(capital)
                position = "FLAT"

            # Check Max Timeout (Time exit after 15 minutes)
            elif bars_held >= max_hold_minutes:
                exit_p = curr_price * (1.0 - slippage)
                pnl = position_size * (exit_p - entry_price)
                fee = (position_size * exit_p + position_size * entry_price) * fee_rate
                net_pnl = pnl - fee
                capital += net_pnl
                trades.append({
                    "entry_time": dates[entry_idx],
                    "exit_time": curr_date,
                    "type": "TIMEOUT",
                    "entry_price": entry_price,
                    "exit_price": exit_p,
                    "pnl": net_pnl,
                    "equity": capital,
                    "duration_mins": bars_held,
                    "win": net_pnl > 0
                })
                equity_curve.append(capital)
                position = "FLAT"

            if capital > peak_capital:
                peak_capital = capital
            dd_usd = peak_capital - capital
            dd_pct = (dd_usd / peak_capital) * 100.0 if peak_capital > 0 else 0.0
            if dd_usd > max_dd_usd:
                max_dd_usd = dd_usd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        # 2. Check New Entry (If FLAT)
        if position == "FLAT":
            if curr_price <= lower_bands[i] and lower_wicks[i] >= 0.25 and vol_spikes[i] >= 1.20:
                if mode == "fixed":
                    notional = 20.0
                elif mode == "compounding_3x":
                    notional = min(max_notional_cap, max(20.0, capital * 3.0))
                elif mode == "compounding_5x":
                    notional = min(max_notional_cap, max(20.0, capital * 5.0))

                position_size = notional / curr_price
                entry_price = curr_price
                entry_idx = i
                stop_loss_price = curr_price * (1.0 - sl_pct)
                take_profit_price = curr_price * (1.0 + tp_pct)
                position = "LONG"

    trades_df = pd.DataFrame(trades)
    return trades_df, capital, max_dd_usd, max_dd_pct


def print_detailed_breakdown(trades_df: pd.DataFrame, initial_capital: float, final_equity: float, max_dd_usd: float, max_dd_pct: float, model_name: str):
    if trades_df.empty:
        print(f"No trades for {model_name}")
        return

    trades_df["exit_dt"] = pd.to_datetime(trades_df["exit_time"])
    trades_df.set_index("exit_dt", inplace=True)

    total_trades = len(trades_df)
    wins = len(trades_df[trades_df["win"]])
    losses = total_trades - wins
    win_rate = (wins / total_trades) * 100.0
    net_profit = final_equity - initial_capital
    return_pct = (net_profit / initial_capital) * 100.0

    gross_win = trades_df[trades_df["pnl"] > 0]["pnl"].sum()
    gross_loss = abs(trades_df[trades_df["pnl"] < 0]["pnl"].sum())
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else 99.9

    total_days = (trades_df.index[-1] - trades_df.index[0]).total_seconds() / 86400.0
    total_weeks = total_days / 7.0
    total_months = total_days / 30.0

    avg_trades_day = total_trades / total_days
    avg_trades_week = total_trades / total_weeks
    avg_trades_month = total_trades / total_months

    avg_profit_day = net_profit / total_days
    avg_profit_week = net_profit / total_weeks
    avg_profit_month = net_profit / total_months

    print("=" * 85)
    print(f"🪙 BITCOIN (BTC) 1-MINUTE SNIPER — {model_name.upper()}")
    print("=" * 85)
    print(f"• Starting Balance:       ${initial_capital:,.2f} USD")
    print(f"• Final Account Balance:  ${final_equity:,.2f} USD")
    print(f"• Total Net Profit:       +${net_profit:,.2f} USD (+{return_pct:,.1f}%)")
    print(f"• Total 1-Min Candles:    250,000 bars (~173.6 Days / 5.8 Months)")
    print(f"• Total Trades Taken:     {total_trades:,} trades")
    print(f"• Win Rate:               {win_rate:.2f}% ({wins:,} Wins / {losses:,} Losses)")
    print(f"• Profit Factor:          {profit_factor:.2f}")
    print(f"• Max Drawdown:           -${max_dd_usd:,.2f} USD ({max_dd_pct:.2f}%)")
    print("-" * 85)
    print("⚡ TRADE ACTIVITY (EXECUTION FREQUENCY):")
    print(f"  • Trades per Day:       {avg_trades_day:.1f} trades / day")
    print(f"  • Trades per Week:      {avg_trades_week:.1f} trades / week")
    print(f"  • Trades per Month:     {avg_trades_month:.1f} trades / month")
    print("-" * 85)
    print("💵 PROFIT RUN-RATE (AVERAGES):")
    print(f"  • Average Profit / Day:   +${avg_profit_day:,.2f} USD / day")
    print(f"  • Average Profit / Week:  +${avg_profit_week:,.2f} USD / week")
    print(f"  • Average Profit / Month: +${avg_profit_month:,.2f} USD / month")
    print("-" * 85)
    print("📅 MONTH-BY-MONTH DETAILED PROGRESSION (Starting from $20.00):")
    print(f"{'Month':<10} | {'Trades':<8} | {'Monthly PnL ($)':<18} | {'Win Rate':<10} | {'Ending Balance ($)':<22}")
    print("-" * 85)

    trades_df["month_str"] = trades_df.index.strftime("%Y-%m")
    for m, group in trades_df.groupby("month_str"):
        m_count = len(group)
        m_wins = len(group[group["win"]])
        m_wr = (m_wins / m_count) * 100.0 if m_count > 0 else 0.0
        m_pnl = group["pnl"].sum()
        ending_bal = group["equity"].iloc[-1]
        print(f"{m:<10} | {m_count:<8} | +${m_pnl:>14,.2f} | {m_wr:>8.1f}% | ${ending_bal:>19,.2f}")

    print("=" * 85)
    print("\n")


def main():
    if not CACHE_FILE.exists():
        print(f"Error: {CACHE_FILE} not found!")
        return

    df = pd.read_parquet(CACHE_FILE)
    df_ind = compute_indicators(df)
    print(f"Loaded {len(df):,} BTC 1-Minute bars from {df.index[0]} to {df.index[-1]}.\n")

    # 1. Fixed Micro-Lot ($20 Flat Size / 1x Margin)
    t_fix, eq_fix, dd_usd_fix, dd_pct_fix = simulate_btc_account(df_ind, initial_capital=20.0, mode="fixed")
    print_detailed_breakdown(t_fix, 20.0, eq_fix, dd_usd_fix, dd_pct_fix, "Fixed Micro-Lot ($20.00 Flat Size - No Compounding)")

    # 2. Realistic Micro-Compounding (3x Leverage, $1,000 Cap)
    t_3x, eq_3x, dd_usd_3x, dd_pct_3x = simulate_btc_account(df_ind, initial_capital=20.0, mode="compounding_3x", max_notional_cap=1000.0)
    print_detailed_breakdown(t_3x, 20.0, eq_3x, dd_usd_3x, dd_pct_3x, "Realistic Micro-Compounding (3x Leverage, $1,000 Cap)")

    # 3. Dynamic Growth Compounding (5x Leverage, $3,000 Cap)
    t_5x, eq_5x, dd_usd_5x, dd_pct_5x = simulate_btc_account(df_ind, initial_capital=20.0, mode="compounding_5x", max_notional_cap=3000.0)
    print_detailed_breakdown(t_5x, 20.0, eq_5x, dd_usd_5x, dd_pct_5x, "Dynamic Compounding (5x Leverage, $3,000 Cap)")


if __name__ == "__main__":
    main()
