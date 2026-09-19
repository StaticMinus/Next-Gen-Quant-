import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yfinance as yf
import pandas as pd
import numpy as np
from src.integrations.ctrader_mcp_client import ctrader_client

def check_market():
    ctrader_client.initialize()
    
    # 1. cTrader Live Spot Prices
    spx_spot = ctrader_client.get_spot_price("SPX500")
    ndx_spot = ctrader_client.get_spot_price("NDX100")
    gold_spot = ctrader_client.get_spot_price("XAUUSD")
    
    print("=== LIVE CTRADER QUOTES ===")
    print(f"SPX500: {spx_spot}")
    print(f"NDX100: {ndx_spot}")
    print(f"XAUUSD: {gold_spot}")

    # 2. Historical Daily Bars for SPY and QQQ
    print("\n=== YFINANCE DAILY INDICATORS ===")
    tickers = ["SPY", "QQQ"]
    for t in tickers:
        df = yf.download(t, period="3mo", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"]
        
        # 5-day Bollinger Bands / Dip levels
        w = 5
        num_std = 1.25
        mid = close.rolling(w).mean()
        std = close.rolling(w).std()
        lower_band = mid - num_std * std
        upper_band = mid + num_std * std
        
        # 20 EMA, 50 SMA, RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain / (loss + 1e-9)))
        ema20 = close.ewm(span=20).mean()
        sma50 = close.rolling(50).mean()
        
        c = float(close.iloc[-1])
        c_prev = float(close.iloc[-2])
        m = float(mid.iloc[-1])
        l = float(lower_band.iloc[-1])
        u = float(upper_band.iloc[-1])
        r = float(rsi.iloc[-1])
        e20 = float(ema20.iloc[-1])
        s50 = float(sma50.iloc[-1])
        
        dist_to_dip = c - l
        dist_pct = (dist_to_dip / c) * 100
        
        is_sniper_dip = c <= l
        is_trend_pullback = (c > s50) and (c <= e20 * 1.015) and (c >= e20 * 0.985) and (40.0 <= r <= 65.0)
        
        print(f"\n--- {t} ---")
        print(f"Latest Close: ${c:.2f} (Previous: ${c_prev:.2f})")
        print(f"5-Day Mean:   ${m:.2f}")
        print(f"Lower Dip (1.25σ): ${l:.2f}")
        print(f"Upper Band:   ${u:.2f}")
        print(f"Distance to Dip: ${dist_to_dip:.2f} ({dist_pct:+.2f}%)")
        print(f"20 EMA:       ${e20:.2f} | 50 SMA: ${s50:.2f}")
        print(f"RSI (14):     {r:.1f}")
        print(f"Is Sniper Dip (Close <= Dip): {is_sniper_dip}")
        print(f"Is Trend Pullback (20 EMA sweet spot): {is_trend_pullback}")

if __name__ == '__main__':
    check_market()
