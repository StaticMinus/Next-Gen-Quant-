#!/usr/bin/env python3
"""
scripts/test_eval_acceleration.py
Test sizing tiers for 3-Slot Connors RSI(2) + 5-SMA strategy:
Evaluating:
  - Time to reach $600 (+10% eval target)
  - Monthly profit
  - Max Drawdown vs -$360 limit
  - Max Daily Loss vs -$180 limit
"""

import sys
import pandas as pd
import numpy as np
import research_breakthrough_engine as rbe
from research_breakthrough_engine import UNIVERSE_7

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

common_dates = sorted(list(set.intersection(*[set(rbe.dfs[tk].index) for tk in UNIVERSE_7])))
common_dates = [d for d in common_dates if d >= pd.Timestamp('2016-09-16', tz='UTC')]

def test_sizing(pos_size):
    balance = 6000.0
    initial_balance = 6000.0
    peak_balance = 6000.0
    max_dd = 0.0
    open_positions = []
    closed_trades = []
    daily_pnl_tracker = {}
    time_to_600 = [] # list of days to gain +$600 from start or reset

    current_cycle_start = common_dates[0]
    cycle_start_bal = 6000.0

    for date in common_dates:
        daily_pnl = 0.0
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
                pnl = pos_size * (-0.030)
                reason = 'Stop_Loss'
            elif ret >= 0.025:
                exit_trade = True
                pnl = pos_size * 0.025
                reason = 'Take_Profit'
            elif (bar['Close'] > bar['SMA5']) and (ret > 0.005):
                exit_trade = True
                pnl = pos_size * ret
                reason = 'SMA5_MeanRev_Exit'
            elif days_held >= 4:
                exit_trade = True
                pnl = pos_size * ret
                reason = 'Time_Exit'

            if exit_trade:
                balance += pnl
                daily_pnl += pnl
                closed_trades.append({
                    'ticker': tk,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'year_month': date.strftime('%Y-%m'),
                    'pnl': pnl,
                    'win': pnl > 0,
                    'reason': reason
                })
            else:
                remaining.append(pos)
        open_positions = remaining

        # Check entries if slots available
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

        # Track Drawdown
        if balance > peak_balance:
            peak_balance = balance
        dd = peak_balance - balance
        if dd > max_dd:
            max_dd = dd
        daily_pnl_tracker[date.strftime('%Y-%m-%d')] = daily_pnl

        # Track speed to +$600 profit
        if (balance - cycle_start_bal) >= 600.0:
            days_taken = (date - current_cycle_start).days
            time_to_600.append(days_taken)
            cycle_start_bal = balance
            current_cycle_start = date

    df_t = pd.DataFrame(closed_trades)
    monthly = df_t.groupby('year_month')['pnl'].sum()
    max_day_loss = abs(min(daily_pnl_tracker.values()))

    return {
        'pos_size': pos_size,
        'risk_per_trade_usd': pos_size * 0.03,
        'max_3_slot_loss_usd': pos_size * 0.03 * 3,
        'avg_monthly_pnl': monthly.mean(),
        'top_month_pnl': monthly.max(),
        'median_month_pnl': monthly.median(),
        'worst_month_loss': abs(monthly.min()),
        'max_10y_drawdown': max_dd,
        'max_single_day_loss': max_day_loss,
        'completed_600_cycles': len(time_to_600),
        'avg_days_to_600': np.mean(time_to_600) if time_to_600 else 0,
        'win_rate': (df_t['win'].mean() * 100) if len(df_t) > 0 else 0
    }

print("=" * 115)
print("ACCELERATION TOURNAMENT: SIZING TIERS FOR $600 EVAL TARGET")
print("=" * 115)
print(f"{'Slot Size':<11} | {'Risk/Tr':<8} | {'Max3Stop':<9} | {'Avg Mo PnL':<11} | {'Top Month':<10} | {'Max 10y DD':<11} | {'Max Day Loss':<13} | {'Avg Days to $600':<16}")
print("-" * 115)

for size in [300.0, 450.0, 600.0, 800.0, 1000.0]:
    r = test_sizing(size)
    print(f"${r['pos_size']:<10.0f} | ${r['risk_per_trade_usd']:<7.2f} | ${r['max_3_slot_loss_usd']:<8.2f} | +${r['avg_monthly_pnl']:<9.2f} | +${r['top_month_pnl']:<8.2f} | ${r['max_10y_drawdown']:<10.2f} | ${r['max_single_day_loss']:<12.2f} | {r['avg_days_to_600']:<5.0f} days ({r['avg_days_to_600']/30.4:.1f} mo)")
print("=" * 115)
