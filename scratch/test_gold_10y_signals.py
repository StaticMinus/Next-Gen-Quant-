import sys
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

# Load GLD from cache
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

# Strategy Signals:
# 1. Sniper Dip
df['Sig_Sniper'] = (
    (df['Close'] > df['SMA200']) &
    ((df['RSI'] < 38) | (df['Low'] <= df['BB_Low'])) &
    (df['Close'] > df['Close'].shift(1)) &
    (df['VIX_Pct'] < 0.85)
)

# 2. Trend Pullback
df['Sig_Trend'] = (
    (df['Close'] > df['SMA50']) &
    (df['SMA50'] > df['SMA200']) &
    (df['Low'] <= df['EMA20'] * 1.008) &
    (df['Close'] >= df['EMA20']) &
    (df['RSI'] >= 42) & (df['RSI'] <= 65) &
    (df['Close'] > df['Close'].shift(1)) &
    (df['VIX_Pct'] < 0.70)
)

# 3. Volatility Squeeze
df['Squeeze_Recent'] = (df['BB_Width'] <= df['BB_Width_Min20'] * 1.08).rolling(3).max() > 0
df['Sig_Squeeze'] = (
    (df['Close'] > df['SMA200']) &
    (df['Squeeze_Recent']) &
    (df['Close'] > df['BB_High']) &
    (df['Close'] > df['Close'].shift(1)) &
    (df['VIX_Pct'] < 0.80) &
    (df['Vol_Ratio'] > 1.02)
)

# Also test Scalper 5d 1.25 std
scalper_mid = df['Close'].rolling(5).mean()
scalper_std = df['Close'].rolling(5).std()
scalper_lower = scalper_mid - 1.25 * scalper_std
scalper_upper = scalper_mid + 1.25 * scalper_std
df['Sig_Scalper'] = (df['Close'] <= scalper_lower) & (df['Close'] > df['Close'].shift(1))

print(f"Total Bars: {len(df)}")
print(f"Sniper Signals: {df['Sig_Sniper'].sum()}")
print(f"Trend Signals:  {df['Sig_Trend'].sum()}")
print(f"Squeeze Signals:{df['Sig_Squeeze'].sum()}")
print(f"Scalper Signals:{df['Sig_Scalper'].sum()}")
