import yfinance as yf
import pandas as pd
from pathlib import Path

spy = yf.Ticker('SPY')
spy_p = float(spy.fast_info.last_price or 0)
qqq = yf.Ticker('QQQ')
qqq_p = float(qqq.fast_info.last_price or 0)

cache_file = Path('cache/SPY_10y.csv')
if cache_file.exists():
    df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
    close = df['close'].tail(20).copy()
    close.iloc[-1] = spy_p
    m5 = float(close.rolling(5).mean().iloc[-1])
    s5 = float(close.rolling(5).std().iloc[-1])
    l_band = m5 - 1.25 * s5
    u_band = m5 + 1.25 * s5
    dist = spy_p - l_band
    dist_pct = (dist / spy_p) * 100

    print(f"SPY Price:         ${spy_p:,.2f}")
    print(f"5d Mean Target:    ${m5:,.2f}")
    print(f"Dip Entry (1.25s): ${l_band:,.2f}")
    print(f"Distance to Dip:   ${dist:,.2f} (+{dist_pct:.2f}%)")
    print(f"Dip Triggered?     {spy_p <= l_band}")
print(f"QQQ Price:         ${qqq_p:,.2f}")
