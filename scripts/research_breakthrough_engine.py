#!/usr/bin/env python3
"""
scripts/research_breakthrough_engine.py
────────────────────────────────────────────────────────────────────────────
Empirical Breakthrough Research:
Comparing Current ATLAS-Quant vs Upgraded Breakthrough Engine over 10 Years (2016-2026)

Key Variables Tested:
1. Slot Architecture: 2 slots @ $450 vs 3 slots @ $300 ($900 total exposure preserved)
2. Exit Logic: Fixed +3.5% target (8-day max hold) vs Dynamic Mean-Reversion Exit (Close > SMA5 or +2.5% target, max 4-day hold)
3. Entry Precision: Standard Dip vs Connors RSI(2) + 200 SMA Confluence
4. Asset Universe: 5 assets (SPY, QQQ, AAPL, NVDA, GLD) vs 7 assets (+MSFT, +META)
"""

import sys
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

INITIAL_BALANCE = 6000.0
UNIVERSE_7 = ['SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'GLD', 'META']

print("=" * 90)
print("FETCHING & PREPARING 10-YEAR DATA FOR 7 ASSETS + VIX (2016 - 2026)...")
print("=" * 90)

# 1. Fetch VIX
vix_raw = yf.Ticker('^VIX').history(period='10y', interval='1d')
vix_raw.index = vix_raw.index.tz_convert('UTC').normalize()
vix_close = vix_raw['Close']

dfs = {}
for ticker in UNIVERSE_7:
    cache_file = Path(f"cache/{ticker}_10y.csv")
    if cache_file.exists():
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
    else:
        print(f"  Downloading 10y for {ticker}...")
        tk = yf.Ticker(ticker)
        df = tk.history(period='10y', interval='1d')
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache_file)
    
    if len(df) < 1000:
        continue
    df.columns = [c.capitalize() for c in df.columns]
    df.index = pd.to_datetime(df.index, utc=True).normalize()

    # VIX alignment
    df['VIX'] = vix_close.reindex(df.index).ffill()
    df['VIX_Pct'] = df['VIX'].rolling(252, min_periods=50).apply(lambda s: (s < s.iloc[-1]).mean() if len(s)>0 else 0.5, raw=False)

    # Technicals
    df['SMA5'] = df['Close'].rolling(5, min_periods=2).mean()
    df['SMA50'] = df['Close'].rolling(50, min_periods=20).mean()
    df['SMA200'] = df['Close'].rolling(200, min_periods=50).mean()
    df['EMA20'] = df['Close'].ewm(span=20).mean()

    # RSI 14
    delta = df['Close'].diff()
    gain14 = delta.clip(lower=0).rolling(14, min_periods=5).mean()
    loss14 = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
    rs14 = gain14 / (loss14 + 1e-9)
    df['RSI14'] = 100 - (100 / (1 + rs14))

    # Connors RSI 2
    gain2 = delta.clip(lower=0).rolling(2, min_periods=1).mean()
    loss2 = (-delta.clip(upper=0)).rolling(2, min_periods=1).mean()
    rs2 = gain2 / (loss2 + 1e-9)
    df['RSI2'] = 100 - (100 / (1 + rs2))

    # Bollinger Bands (20, 2.0)
    df['BB_Mid'] = df['Close'].rolling(20, min_periods=10).mean()
    df['BB_Std'] = df['Close'].rolling(20, min_periods=10).std()
    df['BB_Low'] = df['BB_Mid'] - 2.0 * df['BB_Std']
    df['BB_High'] = df['BB_Mid'] + 2.0 * df['BB_Std']
    df['BB_Width'] = (df['BB_High'] - df['BB_Low']) / (df['BB_Mid'] + 1e-9)
    df['BB_Width_Min20'] = df['BB_Width'].rolling(20, min_periods=10).min()

    # Short Bollinger Bands (5, 1.25) for high-frequency mean reversion scalping
    df['BB5_Mid'] = df['Close'].rolling(5, min_periods=3).mean()
    df['BB5_Std'] = df['Close'].rolling(5, min_periods=3).std()
    df['BB5_Low'] = df['BB5_Mid'] - 1.25 * df['BB5_Std']

    # Volume
    df['Vol_MA20'] = df['Volume'].rolling(20, min_periods=5).mean()
    df['Vol_Ratio'] = df['Volume'] / (df['Vol_MA20'] + 1e-9)

    # ── Signals ───────────────────────────────────────────────────────────────
    # 1. Baseline ATLAS Sniper Dip
    df['Sig_Sniper_Base'] = (
        (df['Close'] > df['SMA200']) &
        ((df['RSI14'] < 36) | (df['Low'] <= df['BB_Low'])) &
        (df['Close'] > df['Close'].shift(1)) &
        (df['VIX_Pct'] < 0.85)
    )

    # 2. Baseline ATLAS Trend Pullback
    df['Sig_Trend_Base'] = (
        (df['Close'] > df['SMA50']) &
        (df['SMA50'] > df['SMA200']) &
        (df['Low'] <= df['EMA20'] * 1.008) &
        (df['Close'] >= df['EMA20']) &
        (df['RSI14'] >= 42) & (df['RSI14'] <= 60) &
        (df['Close'] > df['Close'].shift(1)) &
        (df['VIX_Pct'] < 0.65)
    )

    # 3. Baseline ATLAS Squeeze
    df['Squeeze_Recent'] = (df['BB_Width'] <= df['BB_Width_Min20'] * 1.05).rolling(3).max() > 0
    df['Sig_Squeeze_Base'] = (
        (df['Close'] > df['SMA200']) &
        (df['Squeeze_Recent']) &
        (df['Close'] > df['BB_High']) &
        (df['Close'] > df['Close'].shift(1)) &
        (df['VIX_Pct'] < 0.75) &
        (df['Vol_Ratio'] > 1.05)
    )

    # 4. BREAKTHROUGH SIGNAL: Dual-Speed Confluence (Connors RSI2 < 10 OR Short BB5 Dip in Bull Trend)
    df['Sig_Breakthrough_Dip'] = (
        (df['Close'] > df['SMA200']) &
        ((df['RSI2'] < 10) | (df['Low'] <= df['BB5_Low'])) &
        (df['VIX_Pct'] < 0.80)
    )

    dfs[ticker] = df

print("Data preparation complete.")

def run_simulation(name, universe, max_positions, position_size, stop_loss_pct, take_profit_pct, 
                   max_hold_days, use_mean_rev_exit=False, use_breakthrough_signal=False):
    common_dates = sorted(list(set.intersection(*[set(dfs[tk].index) for tk in universe])))
    common_dates = [d for d in common_dates if d >= pd.Timestamp('2016-09-16', tz='UTC')]

    balance = INITIAL_BALANCE
    peak_balance = INITIAL_BALANCE
    max_drawdown = 0.0
    open_positions = []
    closed_trades = []
    daily_pnl_tracker = {}

    for date in common_dates:
        daily_pnl = 0.0
        remaining_positions = []

        # 1. Manage open positions
        for pos in open_positions:
            tk = pos['ticker']
            df = dfs[tk]
            if date not in df.index:
                remaining_positions.append(pos)
                continue

            bar = df.loc[date]
            ret = (bar['Close'] - pos['entry_p']) / pos['entry_p']
            days_held = pos['days_held'] + 1
            pos['days_held'] = days_held

            exit_trade = False
            pnl = 0.0
            reason = ''

            # Stop Loss (always hard)
            if ret <= -stop_loss_pct:
                exit_trade = True
                pnl = position_size * (-stop_loss_pct)
                reason = 'Stop_Loss'
            # Take profit
            elif ret >= take_profit_pct:
                exit_trade = True
                pnl = position_size * take_profit_pct
                reason = 'Take_Profit'
            # Dynamic Mean Reversion Exit: Fast exit when closing above SMA5 in profit
            elif use_mean_rev_exit and (bar['Close'] > bar['SMA5']) and (ret > 0.005):
                exit_trade = True
                pnl = position_size * ret
                reason = 'Mean_Rev_SMA5_Exit'
            # Max holding days
            elif days_held >= max_hold_days:
                exit_trade = True
                pnl = position_size * ret
                reason = 'Time_Exit'

            if exit_trade:
                balance += pnl
                daily_pnl += pnl
                closed_trades.append({
                    'ticker': tk,
                    'pnl': pnl,
                    'ret': pnl / position_size,
                    'win': pnl > 0,
                    'reason': reason,
                    'days': days_held,
                    'year_month': date.strftime('%Y-%m'),
                    'date': date
                })
            else:
                remaining_positions.append(pos)

        open_positions = remaining_positions

        # 2. Check entries if slots available
        if len(open_positions) < max_positions:
            candidates = []
            active_tickers = [p['ticker'] for p in open_positions]

            for tk in universe:
                if tk in active_tickers or date not in dfs[tk].index:
                    continue
                bar = dfs[tk].loc[date]

                if use_breakthrough_signal:
                    if bar['Sig_Breakthrough_Dip']:
                        candidates.append({'ticker': tk, 'strat': 'Breakthrough_Dip', 'priority': 1, 'p': bar['Close']})
                    elif bar['Sig_Trend_Base']:
                        candidates.append({'ticker': tk, 'strat': 'Trend_Pullback', 'priority': 2, 'p': bar['Close']})
                    elif bar['Sig_Squeeze_Base']:
                        candidates.append({'ticker': tk, 'strat': 'Squeeze_Breakout', 'priority': 3, 'p': bar['Close']})
                else:
                    if bar['Sig_Sniper_Base']:
                        candidates.append({'ticker': tk, 'strat': 'Sniper_Dip', 'priority': 1, 'p': bar['Close']})
                    elif bar['Sig_Trend_Base']:
                        candidates.append({'ticker': tk, 'strat': 'Trend_Pullback', 'priority': 2, 'p': bar['Close']})
                    elif bar['Sig_Squeeze_Base']:
                        candidates.append({'ticker': tk, 'strat': 'Squeeze_Breakout', 'priority': 3, 'p': bar['Close']})

            candidates.sort(key=lambda x: x['priority'])

            for cand in candidates:
                if len(open_positions) >= max_positions:
                    break
                open_positions.append({
                    'ticker': cand['ticker'],
                    'strat': cand['strat'],
                    'entry_p': cand['p'],
                    'days_held': 0
                })

        # Drawdown tracking
        if balance > peak_balance:
            peak_balance = balance
        dd = peak_balance - balance
        if dd > max_drawdown:
            max_drawdown = dd
        daily_pnl_tracker[date.strftime('%Y-%m-%d')] = daily_pnl

    df_t = pd.DataFrame(closed_trades)
    tot_trades = len(df_t)
    wins = df_t['win'].sum() if tot_trades > 0 else 0
    win_rate = (wins / tot_trades * 100) if tot_trades > 0 else 0
    net_pnl = balance - INITIAL_BALANCE
    avg_hold = df_t['days'].mean() if tot_trades > 0 else 0
    max_day_loss = abs(min(daily_pnl_tracker.values())) if daily_pnl_tracker else 0

    # Monthly frequency
    if tot_trades > 0:
        trades_per_mo = df_t.groupby('year_month').size()
        avg_tr_per_mo = trades_per_mo.mean()
        max_tr_in_mo = trades_per_mo.max()
        active_months = len(trades_per_mo)
    else:
        avg_tr_per_mo = 0
        max_tr_in_mo = 0
        active_months = 0

    return {
        'name': name,
        'trades': tot_trades,
        'win_rate': round(win_rate, 1),
        'net_pnl': round(net_pnl, 2),
        'max_dd': round(max_drawdown, 2),
        'max_day_loss': round(max_day_loss, 2),
        'avg_hold_days': round(avg_hold, 1),
        'avg_trades_per_active_mo': round(avg_tr_per_mo, 2),
        'overall_trades_per_mo': round(tot_trades / 120.0, 2),
        'max_trades_in_a_mo': max_tr_in_mo,
        'active_months': active_months
    }

print("\nRUNNING TOURNAMENT OF ARCHITECTURES...")

configs = [
    {
        'name': '1. Current Baseline (2 slots @ $450, 5 assets, 8d hold, fixed 3.5%)',
        'universe': ['SPY', 'QQQ', 'AAPL', 'NVDA', 'GLD'],
        'max_positions': 2,
        'position_size': 450.0,
        'stop_loss_pct': 0.030,
        'take_profit_pct': 0.035,
        'max_hold_days': 8,
        'use_mean_rev_exit': False,
        'use_breakthrough_signal': False
    },
    {
        'name': '2. Slot Expansion (3 slots @ $300, 5 assets, 8d hold, fixed 3.5%)',
        'universe': ['SPY', 'QQQ', 'AAPL', 'NVDA', 'GLD'],
        'max_positions': 3,
        'position_size': 300.0,
        'stop_loss_pct': 0.030,
        'take_profit_pct': 0.035,
        'max_hold_days': 8,
        'use_mean_rev_exit': False,
        'use_breakthrough_signal': False
    },
    {
        'name': '3. Universe Expansion (3 slots @ $300, 7 assets, 8d hold, fixed 3.5%)',
        'universe': UNIVERSE_7,
        'max_positions': 3,
        'position_size': 300.0,
        'stop_loss_pct': 0.030,
        'take_profit_pct': 0.035,
        'max_hold_days': 8,
        'use_mean_rev_exit': False,
        'use_breakthrough_signal': False
    },
    {
        'name': '4. Fast Turnover Engine (3 slots @ $300, 7 assets, SMA5 Reversion Exit, 4d hold)',
        'universe': UNIVERSE_7,
        'max_positions': 3,
        'position_size': 300.0,
        'stop_loss_pct': 0.030,
        'take_profit_pct': 0.025,
        'max_hold_days': 4,
        'use_mean_rev_exit': True,
        'use_breakthrough_signal': False
    },
    {
        'name': '5. BREAKTHROUGH NEXUS (3 slots @ $300, 7 assets, Connors RSI2 Confluence + Fast Reversion Exit)',
        'universe': UNIVERSE_7,
        'max_positions': 3,
        'position_size': 300.0,
        'stop_loss_pct': 0.030,
        'take_profit_pct': 0.025,
        'max_hold_days': 4,
        'use_mean_rev_exit': True,
        'use_breakthrough_signal': True
    },
    {
        'name': '6. ULTRA-BREAKTHROUGH (4 slots @ $225 = $900 total, 7 assets, Connors Confluence + Fast Exit)',
        'universe': UNIVERSE_7,
        'max_positions': 4,
        'position_size': 225.0,
        'stop_loss_pct': 0.030,
        'take_profit_pct': 0.025,
        'max_hold_days': 4,
        'use_mean_rev_exit': True,
        'use_breakthrough_signal': True
    }
]

res_list = []
for c in configs:
    res = run_simulation(
        name=c['name'],
        universe=c['universe'],
        max_positions=c['max_positions'],
        position_size=c['position_size'],
        stop_loss_pct=c['stop_loss_pct'],
        take_profit_pct=c['take_profit_pct'],
        max_hold_days=c['max_hold_days'],
        use_mean_rev_exit=c['use_mean_rev_exit'],
        use_breakthrough_signal=c['use_breakthrough_signal']
    )
    res_list.append(res)

print("\n" + "=" * 125)
print("             10-YEAR BREAKTHROUGH ARCHITECTURAL AUDIT & COMPARISON (2016 - 2026)")
print("=" * 125)
print(f"{'Config Name':<55} | {'WinRate':<7} | {'Trades':<6} | {'Tr/Mo':<6} | {'AvgHold':<7} | {'MaxDD':<8} | {'MaxDayLoss':<10} | {'Net PnL':<9}")
print("-" * 125)
for r in res_list:
    print(f"{r['name']:<55} | {r['win_rate']:>5.1f}% | {r['trades']:<6} | {r['overall_trades_per_mo']:<6.2f} | {r['avg_hold_days']:<7.1f} | ${r['max_dd']:<7.2f} | ${r['max_day_loss']:<9.2f} | +${r['net_pnl']:<8.2f}")
print("=" * 125)
