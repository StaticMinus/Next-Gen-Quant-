import pandas as pd
import numpy as np

raw = pd.read_csv('cache/SPY_15y.csv', index_col=0, parse_dates=True)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = [col[0].lower() for col in raw.columns]
else:
    raw.columns = [str(c).lower() for c in raw.columns]

from src.strategies.scalper import ScalperStrategy
from src.strategies.base import _get_close

close = _get_close(raw)
scalper = ScalperStrategy()
signal = scalper.generate_signal(
    raw,
    {'window': 5, 'num_std': 1.25, 'exit_at_mean': True, 'allow_short': False, 'stop_loss_pct': 0.03, 'max_hold_bars': 5}
).reindex(close.index).fillna(0).clip(lower=0)

daily_ret = close.pct_change().fillna(0)
cost_per_trade = 0.0004
trades_flips = signal.diff().abs().fillna(0)
costs = trades_flips * cost_per_trade
strat_ret = daily_ret * signal.shift(1).fillna(0) - costs

# Sizing Options:
# Option 1: 100% Notional ($6,000 equity)
dollar_pnl_100 = strat_ret * 6000.0
cum_pnl_100 = dollar_pnl_100.cumsum()
peak_100 = cum_pnl_100.cummax()
dd_100 = peak_100 - cum_pnl_100

# Option 2: Micro / Defensive Risk Sizing (0.38% Risk per Trade = $22.80 risk / ~0.10 lots / 50% notional)
dollar_pnl_micro = strat_ret * 3000.0  # Conservative 0.5x leverage
cum_pnl_micro = dollar_pnl_micro.cumsum()
peak_micro = cum_pnl_micro.cummax()
dd_micro = peak_micro - cum_pnl_micro

# Option 3: Lot sizing (0.15 lots = $15/pt SPY)
# SPY moves ~2-5 pts per trade

print("=== Sizing Analysis on $6k Account across 15 Years ===")
print(f"Option 1 (Full $6k notional):")
print(f"  Total 15-Year Profit: ${cum_pnl_100.iloc[-1]:,.2f}")
print(f"  Max DD (USD): ${dd_100.max():,.2f}")
print(f"  Max DD (%): {(dd_100.max()/6000.0)*100:.2f}%")

print(f"\nOption 2 (Conservative 50% notional / $3,000 sizing):")
print(f"  Total 15-Year Profit: ${cum_pnl_micro.iloc[-1]:,.2f}")
print(f"  Max DD (USD): ${dd_micro.max():,.2f}")
print(f"  Max DD (%): {(dd_micro.max()/6000.0)*100:.2f}%")
print(f"  FundedNext Buffer ($360) Breached? {'YES' if dd_micro.max() > 360 else 'NO (100% PASS)'}")

# Yearly breakdown for Option 1 and Option 2
years = sorted(list(set(close.index.year)))
print("\nYearly Profit Breakdown:")
for y in years:
    p1 = dollar_pnl_100.loc[dollar_pnl_100.index.year == y].sum()
    p2 = dollar_pnl_micro.loc[dollar_pnl_micro.index.year == y].sum()
    print(f"  {y}: Full Sizing=${p1:7.2f} | Conservative=${p2:7.2f}")
