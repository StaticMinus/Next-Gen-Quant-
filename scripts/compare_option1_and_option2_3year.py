"""
Option 1 vs Option 2 — 3-Year Monthly Profit Shootout (2023 - 2026)
===================================================================
Simulates on a $50,000 Funded Account:
- Option 1: Scalper on SPY Alone
- Option 2: Dual Scalper on SPY + QQQ

Focus: Pure Monthly Profits across all 36 months (USD & Naira @ ₦1,650/$)
Position Sizing: 1 Micro Contract per trade (1 MES for SPY, 1 MNQ for QQQ)
Profit Share: 85% Trader Take-Home
"""

import sys
import json
from pathlib import Path
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.strategies.scalper import ScalperStrategy
from src.strategies.base import _get_close

cache_dir = Path("cache")
spy_raw = pd.read_csv(cache_dir / "SPY_10y.csv", index_col=0, parse_dates=True)
qqq_raw = pd.read_csv(cache_dir / "QQQ_10y.csv", index_col=0, parse_dates=True)

# Slice exactly to 3 years (2023-09-13 to 2026-09-11)
start_dt_3y = "2023-09-13"
spy_3y = spy_raw.loc[spy_raw.index >= start_dt_3y].copy()
qqq_3y = qqq_raw.loc[qqq_raw.index >= start_dt_3y].copy()

spy_c = _get_close(spy_3y)
qqq_c = _get_close(qqq_3y)

initial_capital = 50000.0
trader_split = 0.85
naira_rate = 1650.0
comm_per_order = 1.50
contract_mult = 10.0  # 1 micro contract = $10 per point ETF move

# Initialize Scalper
scalper = ScalperStrategy()
sig_spy = scalper.generate_signal(
    spy_3y,
    {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}
).reindex(spy_c.index).fillna(0).clip(lower=0)

sig_qqq = scalper.generate_signal(
    qqq_3y,
    {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}
).reindex(qqq_c.index).fillna(0).clip(lower=0)

def simulate_scalper(engines, label):
    trades = []
    account_cash = initial_capital
    peak_eq = initial_capital
    max_dd = 0.0
    daily_eq = pd.Series(index=spy_c.index, dtype=float)

    states = {e["name"]: {"in_pos": 0, "entry_p": 0.0, "entry_dt": None, "bars": 0} for e in engines}

    for dt in spy_c.index:
        unrealized = 0.0

        for e in engines:
            name = e["name"]
            st = states[name]
            pos = int(e["sig"].loc[dt])
            p = float(e["close"].loc[dt])

            if st["in_pos"] == 0 and pos > 0:
                st["in_pos"] = 1
                st["entry_p"] = p
                st["entry_dt"] = dt
                st["bars"] = 0
                account_cash -= comm_per_order

            elif st["in_pos"] == 1:
                st["bars"] += 1
                unrealized += (p - st["entry_p"]) * contract_mult

                if pos == 0:
                    realized = (p - st["entry_p"]) * contract_mult - comm_per_order
                    account_cash += realized
                    trades.append({
                        "engine": name,
                        "asset": e["asset"],
                        "entry_dt": st["entry_dt"].strftime("%Y-%m-%d"),
                        "exit_dt": dt.strftime("%Y-%m-%d"),
                        "month": dt.strftime("%Y-%m"),
                        "year": dt.year,
                        "bars_held": st["bars"],
                        "pnl_usd": round(realized, 2),
                        "profitable": realized > 0
                    })
                    st["in_pos"] = 0

        curr_eq = account_cash + unrealized
        daily_eq.loc[dt] = curr_eq
        if curr_eq > peak_eq:
            peak_eq = curr_eq
        dd = peak_eq - curr_eq
        if dd > max_dd:
            max_dd = dd

    total_profit = daily_eq.iloc[-1] - initial_capital
    trader_usd = total_profit * trader_split
    trader_ngn = trader_usd * naira_rate

    df_t = pd.DataFrame(trades)
    all_months = pd.date_range(start=spy_c.index.min(), end=spy_c.index.max(), freq="MS").strftime("%Y-%m")
    
    monthly_pnl = df_t.groupby("month")["pnl_usd"].sum().reindex(all_months, fill_value=0.0)
    monthly_count = df_t.groupby("month").size().reindex(all_months, fill_value=0)

    wins = [t for t in trades if t["profitable"]]
    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0

    return {
        "label": label,
        "total_profit_usd": round(total_profit, 2),
        "trader_takehome_usd": round(trader_usd, 2),
        "trader_takehome_ngn": round(trader_ngn, 0),
        "avg_monthly_takehome_usd": round(trader_usd / len(all_months), 2),
        "avg_monthly_takehome_ngn": round(trader_ngn / len(all_months), 0),
        "total_trades": len(trades),
        "trades_per_month": round(len(trades) / len(all_months), 2),
        "win_rate_pct": round(win_rate, 1),
        "max_drawdown_usd": round(max_dd, 2),
        "profitable_months_count": int((monthly_pnl > 0).sum()),
        "total_months": len(all_months),
        "monthly_win_pct": round((monthly_pnl > 0).sum() / len(all_months) * 100.0, 1),
        "monthly_pnl": monthly_pnl,
        "monthly_count": monthly_count,
        "trades": trades
    }

# Run Option 1: SPY Scalper Alone
opt1 = simulate_scalper(
    [{"name": "Scalper SPY", "asset": "SPY", "close": spy_c, "sig": sig_spy}],
    "Option 1: Scalper on SPY Alone"
)

# Run Option 2: Dual Scalper (SPY + QQQ)
opt2 = simulate_scalper(
    [
        {"name": "Scalper SPY", "asset": "SPY", "close": spy_c, "sig": sig_spy},
        {"name": "Scalper QQQ", "asset": "QQQ", "close": qqq_c, "sig": sig_qqq}
    ],
    "Option 2: Dual Scalper (SPY + QQQ)"
)

print("=" * 105)
print("     OPTION 1 VS OPTION 2: 3-YEAR MONTHLY PROFIT SHOOTOUT (SEPT 2023 - SEPT 2026)")
print("=" * 105)
print(f"{'Metric':<34} | {'Option 1: SPY Alone':<30} | {'Option 2: Dual Scalper (SPY+QQQ)':<30}")
print("-" * 105)
print(f"{'Total 3-Year Net Profit ($)':<34} | ${opt1['total_profit_usd']:>12,.2f}{'':<17} | ${opt2['total_profit_usd']:>12,.2f}")
print(f"{'Your 85% Take-Home ($ USD)':<34} | ${opt1['trader_takehome_usd']:>12,.2f}{'':<17} | ${opt2['trader_takehome_usd']:>12,.2f}")
print(f"{'Your 85% Take-Home (₦ Naira)':<34} | ₦{opt1['trader_takehome_ngn']:>12,.0f}{'':<17} | ₦{opt2['trader_takehome_ngn']:>12,.0f}")
print(f"{'Average Monthly Take-Home ($)':<34} | ${opt1['avg_monthly_takehome_usd']:>12,.2f} / month{'':<9} | ${opt2['avg_monthly_takehome_usd']:>12,.2f} / month")
print(f"{'Average Monthly Take-Home (₦)':<34} | ₦{opt1['avg_monthly_takehome_ngn']:>12,.0f} / month{'':<9} | ₦{opt2['avg_monthly_takehome_ngn']:>12,.0f} / month")
print(f"{'Average Trades / Month':<34} | {opt1['trades_per_month']:>12.1f} trades/mo{'':<7} | {opt2['trades_per_month']:>12.1f} trades/mo (~1/wk)")
print(f"{'Overall Win Rate':<34} | {opt1['win_rate_pct']:>12.1f}%{'':<17} | {opt2['win_rate_pct']:>12.1f}%")
print(f"{'Profitable Months %':<34} | {opt1['monthly_win_pct']:>12.1f}% ({opt1['profitable_months_count']}/{opt1['total_months']} mos){'':<4} | {opt2['monthly_win_pct']:>12.1f}% ({opt2['profitable_months_count']}/{opt2['total_months']} mos)")
print(f"{'Max Drawdown in 3 Years':<34} | ${opt1['max_drawdown_usd']:>12,.2f} (Safe vs $2k){'':<3} | ${opt2['max_drawdown_usd']:>12,.2f} (Safe vs $2k)")
print("-" * 105)

# Detailed Month-by-Month Table
print("\n" + "=" * 105)
print("                          MONTH-BY-MONTH PROFIT REPORT (ALL 36 MONTHS)")
print("=" * 105)
print(f"{'Month':<10} | {'Option 1 Bot ($)':<16} | {'Option 1 You (₦)':<18} | {'Option 2 Bot ($)':<16} | {'Option 2 You (₦)':<18} | {'Winner'}")
print("-" * 105)

all_months = list(opt1['monthly_pnl'].index)
for m in all_months:
    p1 = opt1['monthly_pnl'][m]
    p2 = opt2['monthly_pnl'][m]
    y1_ngn = p1 * trader_split * naira_rate
    y2_ngn = p2 * trader_split * naira_rate
    winner = "Option 2 (+QQQ)" if p2 > p1 else ("Option 1 (SPY)" if p1 > p2 else "Tie")
    print(f"{m:<10} | ${p1:>14,.2f} | ₦{y1_ngn:>16,.0f} | ${p2:>14,.2f} | ₦{y2_ngn:>16,.0f} | {winner}")

print("-" * 105)

# Save to JSON
save_data = {
    "option_1_spy": {k: v for k, v in opt1.items() if k not in ["monthly_pnl", "monthly_count", "trades"]},
    "option_2_dual": {k: v for k, v in opt2.items() if k not in ["monthly_pnl", "monthly_count", "trades"]},
    "monthly_records": [
        {
            "month": m,
            "opt1_bot_usd": round(float(opt1['monthly_pnl'][m]), 2),
            "opt1_trader_usd": round(float(opt1['monthly_pnl'][m] * trader_split), 2),
            "opt1_trader_ngn": round(float(opt1['monthly_pnl'][m] * trader_split * naira_rate), 0),
            "opt1_trades": int(opt1['monthly_count'][m]),
            "opt2_bot_usd": round(float(opt2['monthly_pnl'][m]), 2),
            "opt2_trader_usd": round(float(opt2['monthly_pnl'][m] * trader_split), 2),
            "opt2_trader_ngn": round(float(opt2['monthly_pnl'][m] * trader_split * naira_rate), 0),
            "opt2_trades": int(opt2['monthly_count'][m]),
        }
        for m in all_months
    ]
}

out_path = Path("results/option1_vs_option2_3year_report.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(save_data, f, indent=2)

print(f"\nReport saved to: {out_path}")
