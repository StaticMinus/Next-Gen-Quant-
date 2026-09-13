"""
15-Year Historical Stress Test (2011 - 2026) — AgentQuant
==========================================================
Stress-tests the Balanced Long-Only Scalper on SPY across 15 full years (~3,770+ trading days).
Covers:
- 2011 US Debt Downgrade Crash
- 2015-2016 China Slowdown & Oil Crash
- 2018 Trade War & Volmageddon Crash
- 2020 COVID-19 Crash (-35% in 1 month!)
- 2022 Fed Rate Hike Bear Market (-20%)
- 2023-2026 Modern AI & Bull Expansion

Calculates:
- 15-Year Survival Telemetry
- Total Net Profit & 85% Trader Take-Home ($ USD & ₦ Naira @ ₦1,650/$)
- Average Monthly Income
- Maximum Drawdown vs Prop Firm Limits
- Year-by-Year Breakdown across all 15 years
"""

import sys
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.strategies.scalper import ScalperStrategy
from src.strategies.base import _get_close
from src.backtest.metrics import PerformanceMetrics

print("=" * 105)
print("       AGENTQUANT $50,000 FUNDED ACCOUNT 15-YEAR STRESS TEST (2011 - 2026)")
print("=" * 105)

initial_capital = 50000.0
trader_split = 0.85
naira_rate = 1650.0
prop_firm_max_dd_limit = 2000.0  # $2,000 trailing drawdown buffer

cache_dir = Path("cache")
cache_dir.mkdir(exist_ok=True)
cache_file = cache_dir / "SPY_15y.csv"

if cache_file.exists() and cache_file.stat().st_size > 1000:
    print(f"Loading 15-year SPY data from local cache ({cache_file})...")
    raw = pd.read_csv(cache_file, index_col=0, parse_dates=True)
else:
    print("Downloading 15-year SPY dataset via Yahoo Finance...")
    raw = None
    for attempt in range(4):
        try:
            raw = yf.download("SPY", period="15y", progress=False)
            if raw is not None and not raw.empty:
                break
        except Exception as ex:
            print(f"  Attempt {attempt+1} failed: {ex}")
        time.sleep(2)

    if raw is None or raw.empty:
        raise RuntimeError("Could not download 15-year data for SPY")

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [col[0].lower() for col in raw.columns]
    else:
        raw.columns = [str(c).lower() for c in raw.columns]
    raw.to_csv(cache_file)

if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = [col[0].lower() for col in raw.columns]
else:
    raw.columns = [str(c).lower() for c in raw.columns]

close = _get_close(raw)
start_dt = close.index.min()
end_dt = close.index.max()
total_bars = len(close)
years = total_bars / 252.0
total_months = years * 12.0

print(f"Horizon:                {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')} ({total_bars} trading days / ~{years:.1f} years)")
print(f"Starting Capital:       ${initial_capital:,.2f}")
print(f"Trader Profit Share:    {trader_split * 100:.0f}% (USDT to Binance)")

# Run Scalper Strategy (5d window, 1.25s, exit at mean, 3% stop loss, max hold 5 bars, Long-Only)
scalper = ScalperStrategy()
signal = scalper.generate_signal(
    raw,
    {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}
).reindex(close.index).fillna(0).clip(lower=0)

# Simulate 2 sizing models:
# 1. Standard Prop Firm Sizing: Full Account Notional ($50k position size / 1 Mini contract)
# 2. Ultra-Defensive Micro Contract Sizing: 1 Micro Contract ($10/pt)

daily_ret = close.pct_change().fillna(0)
cost_per_trade = 0.0004
trades_flips = signal.diff().abs().fillna(0)
costs = trades_flips * cost_per_trade

strat_ret = daily_ret * signal.shift(1).fillna(0) - costs
equity_standard = (1 + strat_ret).cumprod() * initial_capital

metrics_std = PerformanceMetrics.from_equity(equity_standard)
final_bal_std = float(equity_standard.iloc[-1])
total_profit_std = final_bal_std - initial_capital
trader_takehome_std_usd = total_profit_std * trader_split
trader_takehome_std_ngn = trader_takehome_std_usd * naira_rate
monthly_takehome_std_usd = trader_takehome_std_usd / total_months
monthly_takehome_std_ngn = monthly_takehome_std_usd * naira_rate

# Detailed trade extraction
trades = []
in_pos = 0
entry_dt = None
entry_p = 0.0
bars = 0

for dt in close.index:
    pos = int(signal.loc[dt])
    p = float(close.loc[dt])

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
                "entry_dt": entry_dt.strftime("%Y-%m-%d"),
                "exit_dt": exit_dt.strftime("%Y-%m-%d"),
                "year": dt.year,
                "month": dt.strftime("%Y-%m"),
                "bars": bars,
                "entry_p": entry_p,
                "exit_p": exit_p,
                "ret_pct": ret * 100.0,
                "profitable": ret > 0,
            })
            in_pos = 0

wins = [t for t in trades if t["profitable"]]
win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0

# Year-by-Year breakdown across all 15 years
years_list = sorted(list(set(dt.year for dt in close.index)))
yearly_breakdown = []

for y in years_list:
    sub_c = close.loc[close.index.year == y]
    sub_eq = equity_standard.loc[equity_standard.index.year == y]
    sub_trades = [t for t in trades if t["year"] == y]
    
    spy_market_ret = ((sub_c.iloc[-1] - sub_c.iloc[0]) / sub_c.iloc[0]) * 100.0 if len(sub_c) > 1 else 0.0
    bot_ret = ((sub_eq.iloc[-1] - sub_eq.iloc[0]) / sub_eq.iloc[0]) * 100.0 if len(sub_eq) > 1 else 0.0
    bot_profit = (sub_eq.iloc[-1] - sub_eq.iloc[0]) if len(sub_eq) > 1 else 0.0
    trader_pnl = bot_profit * trader_split
    trader_ngn = trader_pnl * naira_rate
    
    y_wins = [t for t in sub_trades if t["profitable"]]
    y_wr = (len(y_wins) / len(sub_trades) * 100.0) if sub_trades else 0.0
    
    # Calculate year's max drawdown
    y_peak = sub_eq.cummax()
    y_dd = ((y_peak - sub_eq) / y_peak).max() * 100.0 if len(sub_eq) > 0 else 0.0
    y_dd_usd = ((y_peak - sub_eq)).max() if len(sub_eq) > 0 else 0.0

    context = "Normal Bull"
    if y == 2011:
        context = "US Debt Downgrade Crash"
    elif y in [2015, 2016]:
        context = "China Slowdown & Oil Crash"
    elif y == 2018:
        context = "Trade War & Volmageddon Crash (-20%)"
    elif y == 2020:
        context = "COVID-19 Historic Crash (-35%)"
    elif y == 2022:
        context = "Fed Rate Hike Bear Market (-20%)"
    elif y in [2023, 2024, 2025, 2026]:
        context = "Modern Bull Expansion"

    yearly_breakdown.append({
        "year": y,
        "context": context,
        "bot_profit_usd": round(bot_profit, 2),
        "trader_takehome_usd": round(trader_pnl, 2),
        "trader_takehome_ngn": round(trader_ngn, 0),
        "bot_return_pct": round(bot_ret, 2),
        "spy_market_pct": round(spy_market_ret, 2),
        "trades": len(sub_trades),
        "win_rate_pct": round(y_wr, 1),
        "year_max_dd_pct": round(y_dd, 2),
        "year_max_dd_usd": round(y_dd_usd, 2),
        "prop_safe": y_dd_usd < prop_firm_max_dd_limit
    })

print("\n" + "=" * 115)
print("                   15-YEAR HISTORICAL STRESS TEST RESULTS (2011 - 2026)")
print("=" * 115)
print(f"Starting Capital:               ${initial_capital:,.2f}")
print(f"Final Account Balance:          ${final_bal_std:,.2f}")
print(f"Total 15-Year Bot Profit:       +${total_profit_std:,.2f} (+{(total_profit_std/initial_capital)*100:.1f}%)")
print(f"Your 85% Take-Home (USD):       ${trader_takehome_std_usd:,.2f} USD")
print(f"Your 85% Take-Home (Naira):     ₦{trader_takehome_std_ngn:,.0f} Naira (~₦{trader_takehome_std_ngn/1e6:.1f}M NGN)")
print(f"Average Monthly Take-Home:      ${monthly_takehome_std_usd:,.2f} / month (~₦{monthly_takehome_std_ngn:,.0f} Naira / month)")
print(f"Total Trades Closed:            {len(trades)} trades (~{len(trades)/years:.1f} trades/year or ~{len(trades)/total_months:.1f} trades/month)")
print(f"Overall 15-Year Win Rate:       {win_rate:.1f}% ({len(wins)} wins / {len(trades)-len(wins)} losses)")
print(f"Sharpe Ratio:                   {float(metrics_std.get('sharpe', 0.0)):.2f}")
print(f"Sortino Ratio:                  {float(metrics_std.get('sortino', 0.0)):.2f}")

print("\n" + "-" * 115)
print(f"{'Year':<6} | {'Bot Profit ($)':<16} | {'Trader Share ($)':<16} | {'Trader Share (₦)':<20} | {'Trades':<7} | {'Win %':<6} | {'Max DD ($)':<11} | {'Market Context'}")
print("-" * 115)

profitable_years = 0
for y in yearly_breakdown:
    if y['bot_profit_usd'] > 0:
        profitable_years += 1
    safe_mark = "SAFE" if y['prop_safe'] else "WATCH"
    print(f"{y['year']:<6} | ${y['bot_profit_usd']:>14,.2f} | ${y['trader_takehome_usd']:>14,.2f} | ₦{y['trader_takehome_ngn']:>18,.0f} | {y['trades']:<7} | {y['win_rate_pct']:>5.1f}% | ${y['year_max_dd_usd']:>9,.2f} | {y['context']}")

print("-" * 115)
print(f"Profitable Years:               {profitable_years} of {len(yearly_breakdown)} years ({profitable_years/len(yearly_breakdown)*100:.1f}%)")

# Save results
save_res = {
    "summary": {
        "initial_capital": initial_capital,
        "final_balance": round(final_bal_std, 2),
        "total_profit_usd": round(total_profit_std, 2),
        "trader_takehome_usd": round(trader_takehome_std_usd, 2),
        "trader_takehome_ngn": round(trader_takehome_std_ngn, 0),
        "monthly_takehome_usd": round(monthly_takehome_std_usd, 2),
        "monthly_takehome_ngn": round(monthly_takehome_std_ngn, 0),
        "total_trades": len(trades),
        "win_rate_pct": round(win_rate, 1),
        "years": round(years, 1),
    },
    "yearly_breakdown": yearly_breakdown
}

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_, bool)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

out_file = Path("results/prop_firm_50k_15year_report.json")
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(save_res, f, indent=2, cls=NumpyEncoder)

print(f"\nReport saved to: {out_file}")
