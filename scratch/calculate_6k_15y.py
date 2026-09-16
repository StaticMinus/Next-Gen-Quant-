import sys
import pandas as pd
import numpy as np
from pathlib import Path

from src.strategies.scalper import ScalperStrategy
from src.strategies.base import _get_close
from src.backtest.metrics import PerformanceMetrics

raw = pd.read_csv("cache/SPY_15y.csv", index_col=0, parse_dates=True)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = [col[0].lower() for col in raw.columns]
else:
    raw.columns = [str(c).lower() for c in raw.columns]

close = _get_close(raw)
scalper = ScalperStrategy()
signal = scalper.generate_signal(
    raw,
    {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}
).reindex(close.index).fillna(0).clip(lower=0)

daily_ret = close.pct_change().fillna(0)
cost_per_trade = 0.0004
trades_flips = signal.diff().abs().fillna(0)
costs = trades_flips * cost_per_trade
strat_ret = daily_ret * signal.shift(1).fillna(0) - costs

# Capital = $6,000
initial_capital = 6000.0
trader_split = 0.85
naira_rate = 1665.0

# 1. Compounding Equity Curve
equity_curve = (1 + strat_ret).cumprod() * initial_capital
total_profit = float(equity_curve.iloc[-1] - initial_capital)
metrics = PerformanceMetrics.from_equity(equity_curve)

# Extract Trades
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
            ret = (p - entry_p) / entry_p
            trades.append({
                "entry_dt": entry_dt.strftime("%Y-%m-%d"),
                "exit_dt": dt.strftime("%Y-%m-%d"),
                "year": dt.year,
                "bars": bars,
                "ret_pct": ret * 100.0,
                "profit_usd": initial_capital * ret,
                "profitable": ret > 0,
            })
            in_pos = 0

wins = [t for t in trades if t["profitable"]]
losses = [t for t in trades if not t["profitable"]]
win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0

# Max Drawdown
peak = equity_curve.cummax()
dd = (peak - equity_curve) / peak
max_dd_pct = float(dd.max() * 100.0)
max_dd_usd = float((peak - equity_curve).max())

years_list = sorted(list(set(dt.year for dt in close.index)))
print(f"Total Trading Days: {len(close)}")
print(f"Total Trades: {len(trades)} | Wins: {len(wins)} | Losses: {len(losses)} | Win Rate: {win_rate:.1f}%")
print(f"Initial Capital: ${initial_capital:,.2f}")
print(f"Final Balance: ${float(equity_curve.iloc[-1]):,.2f}")
print(f"Total Net Profit: ${total_profit:,.2f} (+{(total_profit/initial_capital)*100:.1f}%)")
print(f"Max Drawdown: {max_dd_pct:.2f}% (${max_dd_usd:,.2f}) [Prop Limit is $360.00 / 6.0%]")
print(f"Sharpe Ratio: {float(metrics.get('sharpe', 0.0)):.2f}")
print(f"Profit Factor: {float(metrics.get('profit_factor', 0.0)):.2f}")

# Yearly Breakdown
print("\nYearly Breakdown:")
for y in years_list:
    y_trades = [t for t in trades if t["year"] == y]
    y_sub = equity_curve.loc[equity_curve.index.year == y]
    if len(y_sub) > 1:
        y_pnl = float(y_sub.iloc[-1] - y_sub.iloc[0])
        y_ret = (y_pnl / y_sub.iloc[0]) * 100.0
    else:
        y_pnl = 0.0
        y_ret = 0.0
    y_wins = [t for t in y_trades if t["profitable"]]
    y_wr = (len(y_wins) / len(y_trades) * 100.0) if y_trades else 0.0
    print(f"  {y}: Profit=${y_pnl:8.2f} ({y_ret:5.1f}%) | Trades={len(y_trades):2d} | Win Rate={y_wr:4.1f}%")
