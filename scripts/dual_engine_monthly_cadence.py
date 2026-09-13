"""
Dual Engine Monthly Cadence & Payout Frequency Analysis (2016 - 2026)
=====================================================================
Analyzes the exact trade counts per month, payout frequency, and consistency
for:
1. Engine 1: Balanced Scalper on SPY
2. Engine 1b: Balanced Scalper on SPY + QQQ (Two-Asset Scalper)
3. Engine 2: Volatility Filter on QQQ
4. Combined Dual Engine: Scalper (SPY) + Volatility Filter (QQQ)
"""

import sys
import json
from pathlib import Path
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.strategies.scalper import ScalperStrategy
from src.strategies.base import VolatilityStrategy, _get_close

cache_dir = Path("cache")
spy_raw = pd.read_csv(cache_dir / "SPY_10y.csv", index_col=0, parse_dates=True)
qqq_raw = pd.read_csv(cache_dir / "QQQ_10y.csv", index_col=0, parse_dates=True)

spy_c = _get_close(spy_raw)
qqq_c = _get_close(qqq_raw)

# 1. Engine 1: Balanced Scalper SPY
scalper = ScalperStrategy()
sig_scalper_spy = scalper.generate_signal(
    spy_raw,
    {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}
).reindex(spy_c.index).fillna(0).clip(lower=0)

# 2. Engine 1b: Balanced Scalper QQQ
sig_scalper_qqq = scalper.generate_signal(
    qqq_raw,
    {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}
).reindex(qqq_c.index).fillna(0).clip(lower=0)

# 3. Engine 2: Volatility Filter QQQ
vol_strat = VolatilityStrategy()
sig_vol_qqq = vol_strat.generate_signal(
    qqq_raw,
    {"window": 21, "vol_threshold": 0.20}
).reindex(qqq_c.index).fillna(0).clip(lower=0)

def extract_trades(close_series, sig_series, label):
    trades = []
    in_pos = 0
    entry_dt = None
    entry_p = 0.0
    bars = 0
    
    for dt in close_series.index:
        pos = int(sig_series.loc[dt])
        p = float(close_series.loc[dt])
        
        if in_pos == 0 and pos > 0:
            in_pos = 1
            entry_dt = dt
            entry_p = p
            bars = 0
        elif in_pos == 1:
            bars += 1
            if pos == 0:
                exit_dt = dt
                exit_p = p
                ret = (exit_p - entry_p) / entry_p
                trades.append({
                    "strategy": label,
                    "entry_date": entry_dt,
                    "exit_date": exit_dt,
                    "month": exit_dt.strftime("%Y-%m"),
                    "bars_held": bars,
                    "return_pct": ret * 100.0,
                    "profitable": ret > 0
                })
                in_pos = 0
    return pd.DataFrame(trades)

df_sc_spy = extract_trades(spy_c, sig_scalper_spy, "Scalper_SPY")
df_sc_qqq = extract_trades(qqq_c, sig_scalper_qqq, "Scalper_QQQ")
df_vol_qqq = extract_trades(qqq_c, sig_vol_qqq, "VolFilter_QQQ")

# Combine for Dual Engine (Scalper SPY + VolFilter QQQ)
df_dual_1 = pd.concat([df_sc_spy, df_vol_qqq], ignore_index=True)
# Combine for Dual Scalper + VolFilter (Scalper SPY + Scalper QQQ + VolFilter QQQ)
df_dual_all = pd.concat([df_sc_spy, df_sc_qqq, df_vol_qqq], ignore_index=True)

# Generate all 120 calendar months
all_months = pd.date_range(start=spy_c.index.min(), end=spy_c.index.max(), freq="MS").strftime("%Y-%m")
total_months = len(all_months)

def analyze_cadence(df_trades, name):
    monthly_counts = df_trades.groupby("month").size().reindex(all_months, fill_value=0)
    avg_trades = monthly_counts.mean()
    median_trades = monthly_counts.median()
    max_trades = monthly_counts.max()
    min_trades = monthly_counts.min()
    active_months = (monthly_counts > 0).sum()
    pct_active = (active_months / total_months) * 100.0
    
    total_trades = len(df_trades)
    win_rate = (df_trades["profitable"].sum() / total_trades * 100.0) if total_trades else 0.0
    avg_hold = df_trades["bars_held"].mean() if total_trades else 0.0
    
    # Distribution of trades per month: 0, 1, 2, 3, 4+
    c_0 = (monthly_counts == 0).sum()
    c_1 = (monthly_counts == 1).sum()
    c_2 = (monthly_counts == 2).sum()
    c_3 = (monthly_counts == 3).sum()
    c_4plus = (monthly_counts >= 4).sum()
    
    return {
        "name": name,
        "total_trades_10y": total_trades,
        "avg_trades_per_month": round(avg_trades, 2),
        "median_trades": int(median_trades),
        "max_trades_in_a_month": int(max_trades),
        "active_months_pct": round(pct_active, 1),
        "zero_trade_months": int(c_0),
        "months_with_1_trade": int(c_1),
        "months_with_2_trades": int(c_2),
        "months_with_3_trades": int(c_3),
        "months_with_4plus_trades": int(c_4plus),
        "win_rate_pct": round(win_rate, 1),
        "avg_holding_days": round(avg_hold, 1),
    }

res_sc_spy = analyze_cadence(df_sc_spy, "1. Scalper Alone (SPY)")
res_sc_both = analyze_cadence(pd.concat([df_sc_spy, df_sc_qqq]), "2. Scalper on Both (SPY + QQQ)")
res_vol = analyze_cadence(df_vol_qqq, "3. Volatility Filter Alone (QQQ)")
res_dual = analyze_cadence(df_dual_1, "4. Dual Engine (Scalper SPY + VolFilter QQQ)")
res_dual_super = analyze_cadence(df_dual_all, "5. Super Dual Engine (Scalper SPY & QQQ + VolFilter QQQ)")

summary = [res_sc_spy, res_sc_both, res_vol, res_dual, res_dual_super]

print("=" * 90)
print(f"DUAL ENGINE MONTHLY TRADE FREQUENCY ANALYSIS (10 YEARS: {total_months} CALENDAR MONTHS)")
print("=" * 90)
for s in summary:
    print(f"\nConfiguration: {s['name']}")
    print(f"  Total Trades (10 Years):     {s['total_trades_10y']} trades")
    print(f"  Average Trades / Month:      {s['avg_trades_per_month']} trades/month")
    print(f"  Active Months With Trades:   {s['active_months_pct']}% of months")
    print(f"  Overall Win Rate:            {s['win_rate_pct']}%")
    print(f"  Average Trade Duration:      {s['avg_holding_days']} trading days")
    print(f"  Monthly Breakdown:")
    print(f"    - Months with 0 trades:    {s['zero_trade_months']} months ({s['zero_trade_months']/total_months*100:.1f}%)")
    print(f"    - Months with 1-2 trades:  {s['months_with_1_trade'] + s['months_with_2_trades']} months")
    print(f"    - Months with 3+ trades:   {s['months_with_3_trades'] + s['months_with_4plus_trades']} months (up to {s['max_trades_in_a_month']} in busy months)")

with open("results/dual_engine_monthly_cadence.json", "w") as f:
    json.dump(summary, f, indent=2)
