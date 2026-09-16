#!/usr/bin/env python3
"""
scripts/analyze_breakthrough_eval_speed.py
Analyze monthly profit, trade velocity, and speed to reach $600 target
for 3-Slot ($300) + Connors RSI(2) + 5-SMA dynamic exit logic on 7 assets.
"""

import sys
import pandas as pd
import numpy as np
from research_breakthrough_engine import run_simulation, UNIVERSE_7

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Run simulation with detailed output
# Let's inspect the trades
import research_breakthrough_engine as rbe

# Modify rbe's run_simulation or do it directly to get full closed trades df
def run_and_get_trades():
    common_dates = sorted(list(set.intersection(*[set(rbe.dfs[tk].index) for tk in UNIVERSE_7])))
    common_dates = [d for d in common_dates if d >= pd.Timestamp('2016-09-16', tz='UTC')]

    balance = 6000.0
    initial_balance = 6000.0
    open_positions = []
    closed_trades = []
    daily_equity = []

    for date in common_dates:
        # Exit evaluation
        remaining = []
        for pos in open_positions:
            tk = pos['ticker']
            df = rbe.dfs[tk]
            if date not in df.index:
                remaining.append(pos)
                continue

            bar = df.loc[date]
            ret = (bar['Close'] - pos['entry_p']) / pos['entry_p']
            days_held = pos['days_held'] + 1
            pos['days_held'] = days_held

            exit_trade = False
            pnl = 0.0
            reason = ''

            # Hard stop -3%
            if ret <= -0.030:
                exit_trade = True
                pnl = 300.0 * (-0.030)
                reason = 'Stop_Loss'
            elif ret >= 0.025:
                exit_trade = True
                pnl = 300.0 * 0.025
                reason = 'Take_Profit'
            elif (bar['Close'] > bar['SMA5']) and (ret > 0.005):
                exit_trade = True
                pnl = 300.0 * ret
                reason = 'SMA5_MeanRev_Exit'
            elif days_held >= 4:
                exit_trade = True
                pnl = 300.0 * ret
                reason = 'Time_Exit'

            if exit_trade:
                balance += pnl
                closed_trades.append({
                    'ticker': tk,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'year_month': date.strftime('%Y-%m'),
                    'year': date.year,
                    'month': date.month,
                    'pnl': pnl,
                    'ret': ret,
                    'win': pnl > 0,
                    'reason': reason,
                    'days': days_held,
                    'balance': balance
                })
            else:
                remaining.append(pos)
        open_positions = remaining

        # Entries
        if len(open_positions) < 3:
            active_tk = [p['ticker'] for p in open_positions]
            candidates = []
            for tk in UNIVERSE_7:
                if tk in active_tk or date not in rbe.dfs[tk].index:
                    continue
                bar = rbe.dfs[tk].loc[date]
                if bar['Sig_Breakthrough_Dip']:
                    candidates.append({'ticker': tk, 'strat': 'Breakthrough_Dip', 'priority': 1, 'p': bar['Close']})
                elif bar['Sig_Trend_Base']:
                    candidates.append({'ticker': tk, 'strat': 'Trend_Pullback', 'priority': 2, 'p': bar['Close']})
                elif bar['Sig_Squeeze_Base']:
                    candidates.append({'ticker': tk, 'strat': 'Squeeze_Breakout', 'priority': 3, 'p': bar['Close']})

            candidates.sort(key=lambda x: x['priority'])
            for cand in candidates:
                if len(open_positions) >= 3:
                    break
                open_positions.append({
                    'ticker': cand['ticker'],
                    'strat': cand['strat'],
                    'entry_p': cand['p'],
                    'entry_date': date,
                    'days_held': 0
                })

        daily_equity.append({'date': date, 'balance': balance})

    return pd.DataFrame(closed_trades), pd.DataFrame(daily_equity)

df_trades, df_eq = run_and_get_trades()

# Monthly metrics
monthly_pnl = df_trades.groupby('year_month')['pnl'].sum()
monthly_trades = df_trades.groupby('year_month').size()
monthly_wr = df_trades.groupby('year_month')['win'].apply(lambda s: (s.mean()*100))

print("=" * 80)
print("3-SLOT ($300) + CONNORS RSI(2) + 5-SMA DYNAMIC EXIT: MONTHLY METRICS")
print("=" * 80)
print(f"Total Trades:               {len(df_trades)}")
print(f"Overall Win Rate:           {(df_trades['win'].mean()*100):.1f}%")
print(f"Average Wins:               +${df_trades[df_trades['win']]['pnl'].mean():.2f} per winning trade")
print(f"Average Losses:             -${abs(df_trades[~df_trades['win']]['pnl'].mean()):.2f} per losing trade")
print(f"Profit Factor:              {(df_trades[df_trades['win']]['pnl'].sum() / abs(df_trades[~df_trades['win']]['pnl'].sum())):.2f}")
print(f"Average Holding Period:     {df_trades['days'].mean():.1f} days")
print(f"Exit Reasons:               {df_trades['reason'].value_counts().to_dict()}")

print("\n--- MONTHLY PERFORMANCE STATISTICS ---")
print(f"Active Trading Months:      {len(monthly_pnl)} / 120 months")
print(f"Average Trades per Active Mo: {monthly_trades.mean():.1f} trades/mo")
print(f"Average PnL per Active Mo:  +${monthly_pnl.mean():.2f} / month")
print(f"Median PnL per Active Mo:   +${monthly_pnl.median():.2f} / month")
print(f"Top 25% Profitable Month:   +${monthly_pnl.quantile(0.75):.2f} / month")
print(f"Maximum Profit in 1 Month:  +${monthly_pnl.max():.2f}")
print(f"Worst Loss in 1 Month:      -${abs(monthly_pnl.min()):.2f}")
print(f"Profitable Months Ratio:    {(monthly_pnl > 0).mean()*100:.1f}% ({sum(monthly_pnl > 0)} winning months out of {len(monthly_pnl)})")

# Check Eval $600 Speed Analysis
# From any starting month in a bull/normal market, how long to reach +$600?
print("\n--- EVALUATION TARGET ($600 / +10%) SPEED ANALYSIS ---")
# Rolling 3-month, 6-month, 12-month returns
rolling_3m = monthly_pnl.rolling(3).sum()
rolling_6m = monthly_pnl.rolling(6).sum()

print(f"Rolling 3-Month Average PnL: +${rolling_3m.mean():.2f}")
print(f"Rolling 3-Month Max PnL:     +${rolling_3m.max():.2f}")
print(f"Rolling 6-Month Average PnL: +${rolling_6m.mean():.2f}")

# Also check sizing sensitivity: What if position size is scaled to $400 or $500? Or dynamic?
