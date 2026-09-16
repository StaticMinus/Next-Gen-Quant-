import yfinance as yf
import pandas as pd
import numpy as np

tk = yf.Ticker('QQQ')
fi = tk.fast_info
last_p = getattr(fi, 'last_price', None)
print(f"QQQ Fast Info Last Price: {last_p:.2f}")

hist = tk.history(period='3mo', interval='1d')
c = hist['Close']
p_curr = float(c.iloc[-1])
m5 = float(c.rolling(5).mean().iloc[-1])
s5 = float(c.rolling(5).std().iloc[-1])
l_band = m5 - 1.25 * s5
u_band = m5 + 1.25 * s5

delta = c.diff()
gain = delta.clip(lower=0).rolling(14).mean()
loss = (-delta.clip(upper=0)).rolling(14).mean()
rs = gain / (loss + 1e-9)
rsi = float((100 - (100 / (1 + rs))).iloc[-1])

ema20 = float(c.ewm(span=20).mean().iloc[-1])
sma50 = float(c.rolling(50).mean().iloc[-1])

dt_str = str(hist.index[-1])[:10]
print(f"Latest Bar Date: {dt_str}")
print(f"Close Price: ${p_curr:.2f}")
print(f"5-day Mean: ${m5:.2f}")
print(f"Lower Band (Dip Level): ${l_band:.2f}")
print(f"Upper Band: ${u_band:.2f}")
print(f"Distance to Dip Lower Band: ${p_curr - l_band:+.2f}")
print(f"RSI(14): {rsi:.1f}")
print(f"20 EMA: ${ema20:.2f} (Distance to EMA: ${p_curr - ema20:+.2f})")
print(f"50 SMA: ${sma50:.2f}")

# Check strategy criteria
is_scalper_dip = p_curr <= l_band
is_trend_pullback = (p_curr >= ema20 * 0.995) and (p_curr <= ema20 * 1.015) and (40 <= rsi <= 65)
print(f"Scalper Dip Triggered (<= Lower Band): {is_scalper_dip}")
print(f"Trend Pullback Sweet Spot (Near 20 EMA & RSI 40-65): {is_trend_pullback}")
