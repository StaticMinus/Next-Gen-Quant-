import sys
import pandas as pd
import numpy as np
sys.path.insert(0, "scripts")
import research_breakthrough_engine as rbe
from research_breakthrough_engine import UNIVERSE_7

common_dates = sorted(list(set.intersection(*[set(rbe.dfs[tk].index) for tk in UNIVERSE_7])))
common_dates = [d for d in common_dates if d >= pd.Timestamp('2016-09-16', tz='UTC')]

print("=" * 80)
print("CAN WE PASS THE $600 (10%) EVALUATION IN 1 MONTH WITH 7 TICKERS?")
print("=" * 80)

for slot_size in [300, 500, 750, 1000]:
    trades = []
    open_pos = []
    daily_pnl = {}
    
    for d in common_dates:
        rem = []
        d_pnl = 0.0
        for p in open_pos:
            df = rbe.dfs[p['ticker']]
            if d not in df.index:
                rem.append(p)
                continue
            bar = df.loc[d]
            ret = (bar['Close'] - p['entry_p']) / p['entry_p']
            days = p['days'] + 1
            p['days'] = days
            exit_tr = False
            pnl = 0.0
            if ret <= -0.03:
                exit_tr = True
                pnl = slot_size * -0.03
            elif ret >= 0.025:
                exit_tr = True
                pnl = slot_size * 0.025
            elif bar['Close'] > bar['SMA5'] and ret > 0.005:
                exit_tr = True
                pnl = slot_size * ret
            elif days >= 4:
                exit_tr = True
                pnl = slot_size * ret
            
            if exit_tr:
                trades.append({'month': d.strftime('%Y-%m'), 'pnl': pnl, 'win': pnl > 0})
                d_pnl += pnl
            else:
                rem.append(p)
        open_pos = rem
        
        # Entries
        if len(open_pos) < 3:
            active = [p['ticker'] for p in open_pos]
            for tk in UNIVERSE_7:
                if tk in active or d not in rbe.dfs[tk].index:
                    continue
                bar = rbe.dfs[tk].loc[d]
                if bar['Sig_Breakthrough_Dip'] or bar['Sig_Trend_Base']:
                    if len(open_pos) < 3:
                        open_pos.append({'ticker': tk, 'entry_p': bar['Close'], 'days': 0})
        daily_pnl[d.strftime('%Y-%m-%d')] = d_pnl

    df_t = pd.DataFrame(trades)
    monthly = df_t.groupby('month')['pnl'].sum()
    months_over_600 = (monthly >= 600).sum()
    months_over_400 = (monthly >= 400).sum()
    months_over_300 = (monthly >= 300).sum()
    months_over_200 = (monthly >= 200).sum()
    
    # Check 2-month and 3-month rolling sums
    rolling_2m = monthly.rolling(2).sum()
    rolling_3m = monthly.rolling(3).sum()
    p_600_2m = (rolling_2m >= 600).sum()
    p_600_3m = (rolling_3m >= 600).sum()
    
    max_day_loss = abs(min(daily_pnl.values()))
    
    print(f"\n--- SIZING: ${slot_size} per Slot (Risk: ${slot_size*0.03:.2f}/trade | Max Day Loss: ${max_day_loss:.2f}) ---")
    print(f"  Average Monthly PnL:       +${monthly.mean():.2f}/month")
    print(f"  Top Month (Best Run):      +${monthly.max():.2f}")
    print(f"  Single Months >= $600:     {months_over_600}/{len(monthly)} ({months_over_600/len(monthly)*100:.1f}%)")
    print(f"  Single Months >= $400:     {months_over_400}/{len(monthly)} ({months_over_400/len(monthly)*100:.1f}%)")
    print(f"  Single Months >= $300:     {months_over_300}/{len(monthly)} ({months_over_300/len(monthly)*100:.1f}%)")
    print(f"  2-Month Window Reaching $600: {p_600_2m}/{len(rolling_2m)} ({p_600_2m/len(rolling_2m)*100:.1f}%)")
    print(f"  3-Month Window Reaching $600: {p_600_3m}/{len(rolling_3m)} ({p_600_3m/len(rolling_3m)*100:.1f}%)")
