import sys
import pandas as pd
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

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

# Compounding Model ($6k base, reinvesting profits)
equity_comp = (1 + strat_ret).cumprod() * 6000.0

# Fixed Model ($6k notional position size per trade)
dollar_ret_fixed = strat_ret * 6000.0
equity_fixed = 6000.0 + dollar_ret_fixed.cumsum()

# Micro Model ($3k conservative notional per trade = 50% margin)
dollar_ret_micro = strat_ret * 3000.0
equity_micro = 6000.0 + dollar_ret_micro.cumsum()

print("==========================================================================")
print(" SIZING COMPARISON ACROSS 15 YEARS (2011 - 2026) ON $6,000 BASE")
print("==========================================================================")
print(f"Compounding Model: Total Profit=+${equity_comp.iloc[-1]-6000:,.2f} (+{((equity_comp.iloc[-1]-6000)/6000)*100:.1f}%)")
print(f"Fixed $6k Sizing:  Total Profit=+${equity_fixed.iloc[-1]-6000:,.2f} (+{((equity_fixed.iloc[-1]-6000)/6000)*100:.1f}%)")
print(f"Micro $3k Sizing:  Total Profit=+${equity_micro.iloc[-1]-6000:,.2f} (+{((equity_micro.iloc[-1]-6000)/6000)*100:.1f}%)")
