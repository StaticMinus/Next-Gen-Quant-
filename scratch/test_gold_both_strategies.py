import sys
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

# Load GLD
df_gld = pd.read_csv('cache/GLD_10y.csv')
df_gld['Date'] = pd.to_datetime(df_gld['Date'], utc=True).dt.tz_convert('UTC').dt.normalize()
df_gld.set_index('Date', inplace=True)
df_gld.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)

# Fetch VIX & SPY
vix_raw = yf.Ticker('^VIX').history(period='10y', interval='1d')
vix_raw.index = vix_raw.index.tz_convert('UTC').normalize()
vix_close = vix_raw['Close']

spy_raw = yf.Ticker('SPY').history(period='10y', interval='1d')
spy_raw.index = spy_raw.index.tz_convert('UTC').normalize()
spy_ret20 = spy_raw['Close'].pct_change(20)

df = df_gld.copy()
df['VIX'] = vix_close.reindex(df.index).ffill()
df['VIX_Pct'] = df['VIX'].rolling(252, min_periods=50).apply(lambda s: (s < s.iloc[-1]).mean(), raw=False)
df['Ret20'] = df['Close'].pct_change(20)
df['RS_SPY'] = df['Ret20'] - spy_ret20.reindex(df.index).ffill()

# Indicators
df['SMA50'] = df['Close'].rolling(50, min_periods=20).mean()
df['SMA200'] = df['Close'].rolling(200, min_periods=50).mean()
df['EMA20'] = df['Close'].ewm(span=20).mean()

delta = df['Close'].diff()
gain = delta.clip(lower=0).rolling(14, min_periods=5).mean()
loss = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
rs = gain / (loss + 1e-9)
df['RSI'] = 100 - (100 / (1 + rs))

df['BB_Mid'] = df['Close'].rolling(20, min_periods=10).mean()
df['BB_Std'] = df['Close'].rolling(20, min_periods=10).std()
df['BB_Low'] = df['BB_Mid'] - 2.0 * df['BB_Std']
df['BB_High'] = df['BB_Mid'] + 2.0 * df['BB_Std']
df['BB_Width'] = (df['BB_High'] - df['BB_Low']) / (df['BB_Mid'] + 1e-9)
df['BB_Width_Min20'] = df['BB_Width'].rolling(20, min_periods=10).min()

df['Vol_MA20'] = df['Volume'].rolling(20, min_periods=5).mean()
df['Vol_Ratio'] = df['Volume'] / (df['Vol_MA20'] + 1e-9)

# 1. Triad Signals
df['Sig_Sniper'] = (
    (df['Close'] > df['SMA200']) &
    ((df['RSI'] < 38) | (df['Low'] <= df['BB_Low'])) &
    (df['Close'] > df['Close'].shift(1)) &
    (df['VIX_Pct'] < 0.85)
)

df['Sig_Trend'] = (
    (df['Close'] > df['SMA50']) &
    (df['SMA50'] > df['SMA200']) &
    (df['Low'] <= df['EMA20'] * 1.008) &
    (df['Close'] >= df['EMA20']) &
    (df['RSI'] >= 42) & (df['RSI'] <= 65) &
    (df['Close'] > df['Close'].shift(1)) &
    (df['VIX_Pct'] < 0.70)
)

df['Squeeze_Recent'] = (df['BB_Width'] <= df['BB_Width_Min20'] * 1.08).rolling(3).max() > 0
df['Sig_Squeeze'] = (
    (df['Close'] > df['SMA200']) &
    (df['Squeeze_Recent']) &
    (df['Close'] > df['BB_High']) &
    (df['Close'] > df['Close'].shift(1)) &
    (df['VIX_Pct'] < 0.80) &
    (df['Vol_Ratio'] > 1.02)
)

# Backtest Function
def backtest_strategy(name, signals_col_or_fn, position_size=450.0, stop_loss_pct=0.03, take_profit_pct=0.035, max_holding_days=8):
    balance = 6000.0
    peak_balance = 6000.0
    max_dd = 0.0
    pos = None
    trades = []
    daily_pnl = {}
    
    dates = [d for d in df.index if d >= pd.Timestamp('2016-09-16', tz='UTC')]
    
    for date in dates:
        pnl_today = 0.0
        bar = df.loc[date]
        c = bar['Close']
        
        # Check open position
        if pos is not None:
            pos['days_held'] += 1
            ret = (c - pos['entry_p']) / pos['entry_p']
            exit_trade = False
            pnl = 0.0
            reason = ''
            
            if ret <= -stop_loss_pct:
                exit_trade = True
                pnl = position_size * (-stop_loss_pct)
                reason = 'Stop_Loss'
            elif ret >= take_profit_pct:
                exit_trade = True
                pnl = position_size * take_profit_pct
                reason = 'Take_Profit'
            elif pos['days_held'] >= max_holding_days:
                exit_trade = True
                pnl = position_size * ret
                reason = 'Time_Exit'
                
            if exit_trade:
                balance += pnl
                pnl_today += pnl
                trades.append({
                    'ticker': 'GLD',
                    'strat': pos['strat'],
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'year_month': date.strftime('%Y-%m'),
                    'year': date.year,
                    'month': date.month,
                    'pnl': pnl,
                    'ret': pnl / position_size,
                    'win': pnl > 0,
                    'reason': reason,
                    'days': pos['days_held'],
                    'balance': balance
                })
                pos = None

        # Check new entry if flat
        if pos is None:
            has_sig, strat_type = signals_col_or_fn(bar)
            if has_sig:
                pos = {
                    'entry_p': c,
                    'entry_date': date,
                    'strat': strat_type,
                    'days_held': 0
                }
                
        if balance > peak_balance:
            peak_balance = balance
        dd = peak_balance - balance
        if dd > max_dd:
            max_dd = dd
            
        daily_pnl[date.strftime('%Y-%m-%d')] = pnl_today
        
    df_tr = pd.DataFrame(trades)
    wins = df_tr['win'].sum() if len(df_tr) > 0 else 0
    losses = len(df_tr) - wins
    wr = (wins / len(df_tr) * 100) if len(df_tr) > 0 else 0
    gp = df_tr[df_tr['pnl'] > 0]['pnl'].sum() if len(df_tr) > 0 else 0
    gl = abs(df_tr[df_tr['pnl'] < 0]['pnl'].sum()) if len(df_tr) > 0 else 0
    pf = (gp / gl) if gl > 0 else 999.0
    worst_day = abs(min(daily_pnl.values())) if daily_pnl else 0
    
    print(f"\n==================== {name} ====================")
    print(f"Total Trades: {len(df_tr)} | Wins: {wins} | Losses: {losses} | Win Rate: {wr:.1f}%")
    print(f"Net PnL: +${balance - 6000:.2f} ({(balance - 6000)/6000*100:.1f}%) | Profit Factor: {pf:.2f}")
    print(f"Max Drawdown: ${max_dd:.2f} (Limit -$360) | Worst Day Loss: ${worst_day:.2f} (Limit -$180)")
    print(f"Average Profit per Trade: +${df_tr['pnl'].mean():.2f}")
    return df_tr, balance, max_dd, worst_day

# Test Triad on GLD
def triad_signals(bar):
    if bar['Sig_Sniper']:
        return True, 'Sniper_Dip'
    elif bar['Sig_Trend']:
        return True, 'Trend_Pullback'
    elif bar['Sig_Squeeze']:
        return True, 'Squeeze_Breakout'
    return False, ''

df_triad_tr, bal_triad, dd_triad, wd_triad = backtest_strategy(
    "ATLAS-Quant Strategy Triad on Gold (GLD)", triad_signals
)

# Test Scalper Mean Reversion on GLD (5-day window, 1.25 std)
# Using Scalper exit at 5-day mean or 3.5% TP / 3% SL
from src.strategies.scalper import ScalperStrategy
strat_sc = ScalperStrategy()
sig_sc = strat_sc.generate_signal(df, {'window': 5, 'num_std': 1.25, 'exit_at_mean': True, 'allow_short': False, 'stop_loss_pct': 0.03, 'max_hold_bars': 5})
df['Sig_Scalper_Entry'] = (sig_sc == 1) & (sig_sc.shift(1) == 0)

def scalper_signals(bar):
    if bar['Sig_Scalper_Entry']:
        return True, 'Scalper_Dip'
    return False, ''

df_sc_tr, bal_sc, dd_sc, wd_sc = backtest_strategy(
    "AgentQuant Scalper (5d, 1.25s) on Gold (GLD)", scalper_signals, max_holding_days=5
)
