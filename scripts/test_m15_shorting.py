import numpy as np
import pandas as pd
import yfinance as yf

def test_m15_shorting():
    tickers = ["BTC-USD", "ETH-USD"]
    print("Testing 15-Minute & 1-Hour Multi-Timeframe Short Strategy...")
    
    for ticker in tickers:
        df = yf.download(ticker, period="60d", interval="15m", progress=False)
        if df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        close = df["Close"].astype(float)
        open_p = df["Open"].astype(float)
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        
        mid = close.rolling(20).mean()
        std = close.rolling(20).std()
        upper = mid + 1.5 * std
        lower = mid - 1.5 * std
        ema50 = close.ewm(span=50, adjust=False).mean()
        
        trades = []
        pos = 0
        entry_p = 0.0
        entry_idx = 0
        sl_pct = 0.0075
        tp_pct = 0.0150 # 1:2 R:R
        
        for i in range(50, len(close)):
            c = close.iloc[i]
            o = open_p.iloc[i]
            h = high.iloc[i]
            l = low.iloc[i]
            u = upper.iloc[i]
            low_b = lower.iloc[i]
            e50 = ema50.iloc[i]
            
            if pos == 1:
                ret = (c - entry_p) / entry_p
                if ret >= tp_pct or ret <= -sl_pct or (i - entry_idx >= 12):
                    trades.append({"type": "LONG", "ret": ret})
                    pos = 0
            elif pos == -1:
                ret = (entry_p - c) / entry_p
                if ret >= tp_pct or ret <= -sl_pct or (i - entry_idx >= 12):
                    trades.append({"type": "SHORT", "ret": ret})
                    pos = 0
            
            if pos == 0:
                candle_rng = h - l
                lower_wick = min(o, c) - l
                upper_wick = h - max(o, c)
                wick_ratio_l = lower_wick / candle_rng if candle_rng > 0 else 0
                wick_ratio_s = upper_wick / candle_rng if candle_rng > 0 else 0
                
                # Long dip
                if c < low_b and wick_ratio_l >= 0.25:
                    pos = 1
                    entry_p = c
                    entry_idx = i
                # Short rally in downtrend
                elif c > u and wick_ratio_s >= 0.25 and c <= e50:
                    pos = -1
                    entry_p = c
                    entry_idx = i
                    
        df_res = pd.DataFrame(trades)
        if df_res.empty:
            continue
        longs = df_res[df_res["type"] == "LONG"]
        shorts = df_res[df_res["type"] == "SHORT"]
        
        print(f"\n=======================================================")
        print(f"ASSET: {ticker} (60 Days 15-Minute Bars)")
        print(f"=======================================================")
        print(f"ALL TRADES:   {len(df_res)} trades | Win Rate: {(df_res['ret']>0).mean()*100:.1f}% | Net Move: {df_res['ret'].sum()*100:+.2f}%")
        print(f"LONG TRADES:  {len(longs)} trades | Win Rate: {(longs['ret']>0).mean()*100:.1f}% | Long Net:  {longs['ret'].sum()*100:+.2f}%")
        print(f"SHORT TRADES: {len(shorts)} trades | Win Rate: {(shorts['ret']>0).mean()*100:.1f}% | Short Net: {shorts['ret'].sum()*100:+.2f}%")

if __name__ == "__main__":
    test_m15_shorting()
