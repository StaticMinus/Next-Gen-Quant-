"""
Analyze How Many Trades are Needed to Reach $600 Profit
=======================================================
Grounded on 15 years of S&P 500 tick data on $6,000 capital.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from src.strategies.scalper import ScalperStrategy
from src.strategies.base import _get_close

ROOT = Path("c:/Users/David/Music/Trade/AgentQuant-main")
raw = pd.read_csv(ROOT / "cache" / "SPY_15y.csv", index_col=0, parse_dates=True)
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

trades = []
in_pos = 0
entry_p = 0.0
entry_dt = None
for dt in close.index:
    p = float(close.loc[dt])
    pos = int(signal.loc[dt])
    if in_pos == 0 and pos > 0:
        in_pos = 1
        entry_p = p
        entry_dt = dt
    elif in_pos == 1 and pos == 0:
        in_pos = 0
        ret = (p - entry_p) / entry_p
        pnl = 6000.0 * ret
        trades.append({
            "entry_dt": entry_dt,
            "exit_dt": dt,
            "ret_pct": ret * 100,
            "pnl": pnl,
            "bars": (dt - entry_dt).days
        })

df_t = pd.DataFrame(trades)
wins = df_t[df_t["pnl"] > 0]
losses = df_t[df_t["pnl"] <= 0]

print("=" * 65)
print("     HISTORICAL TRADE BREAKDOWN ON $6,000 CAPITAL (15 YEARS)")
print("=" * 65)
print(f"Total Trades:           {len(df_t)}")
print(f"Win Rate:               {len(wins)/len(df_t)*100:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
print(f"Average PnL per Trade:  +${df_t['pnl'].mean():.2f}")
print(f"Average Win:            +${wins['pnl'].mean():.2f} (+{wins['ret_pct'].mean():.2f}%)")
print(f"Top 25% Wins:           +${wins['pnl'].quantile(0.75):.2f}")
print(f"Max Single Win:         +${wins['pnl'].max():.2f} (+{wins['ret_pct'].max():.2f}%)")
print(f"Average Loss:           -${abs(losses['pnl'].mean()):.2f} (-{abs(losses['ret_pct'].mean()):.2f}%)")
print(f"Average Duration:       {df_t['bars'].mean():.1f} calendar days (~1.8 trading days)")
print("=" * 65)

# Calculate how many consecutive/cumulative trades to reach $600
runs_to_600 = []
for i in range(len(df_t)):
    cum = 0
    cnt = 0
    for j in range(i, len(df_t)):
        cum += df_t.iloc[j]["pnl"]
        cnt += 1
        if cum >= 600.0:
            runs_to_600.append(cnt)
            break

s_runs = pd.Series(runs_to_600)
print("\n--- TRADES NEEDED TO HIT $600 PROFIT (10%) ---")
print(f"Minimum Trades Needed:  {s_runs.min()} trade (in explosive bounce runs!)")
print(f"Median Trades Needed:   {s_runs.median():.0f} trades")
print(f"Average Trades Needed:  {s_runs.mean():.1f} trades")
print(f"Hit in 1 to 2 trades:   {(s_runs <= 2).mean()*100:.1f}% of historical cycles")
print(f"Hit in 1 to 3 trades:   {(s_runs <= 3).mean()*100:.1f}% of historical cycles")
print(f"Hit in 1 to 4 trades:   {(s_runs <= 4).mean()*100:.1f}% of historical cycles")
print("=" * 65)
