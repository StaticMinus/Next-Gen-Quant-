import numpy as np
import pandas as pd
import yfinance as yf

def test_high_precision_shorting():
    tickers = ["BTC-USD", "ETH-USD"]
    print("Testing Precision Price Action Short Strategy...")
    
    for ticker in tickers:
        df = yf.download(ticker, period="7d", interval="1m", progress=False)
        if df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        close = df["Close"].astype(float)
        open_p = df["Open"].astype(float)
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        
        # 1. 20-period Bollinger Bands
        mid = close.rolling(20).mean()
        std = close.rolling(20).std()
        upper = mid + 1.5 * std
        lower = mid - 1.5 * std
        ema50 = close.ewm(span=50, adjust=False).mean()
        
        # 2. Strategy Simulation
        trades = []
        pos = 0 # 1=LONG, -1=SHORT
        entry_p = 0.0
        entry_idx = 0
        sl_pct = 0.0035
        tp_pct = 0.0075
        
        for i in range(50, len(close)):
            c = close.iloc[i]
            o = open_p.iloc[i]
            h = high.iloc[i]
            l = low.iloc[i]
            m = mid.iloc[i]
            u = upper.iloc[i]
            low_b = lower.iloc[i]
            e50 = ema50.iloc[i]
            
            # Position management
            if pos == 1:
                # Long position exit
                ret = (c - entry_p) / entry_p
                if ret >= tp_pct or ret <= -sl_pct or (i - entry_idx >= 15):
                    trades.append({"type": "LONG", "ret": ret})
                    pos = 0
            elif pos == -1:
                # Short position exit
                ret = (entry_p - c) / entry_p
                if ret >= tp_pct or ret <= -sl_pct or (i - entry_idx >= 15):
                    trades.append({"type": "SHORT", "ret": ret})
                    pos = 0
            
            # Entry rules when flat
            if pos == 0:
                # LONG: Price below lower band + buyer wick >= 25% + price not in severe cascade
                lower_wick = min(o, c) - l
                candle_rng = h - l
                wick_ratio_l = lower_wick / candle_rng if candle_rng > 0 else 0
                
                if c < low_b and wick_ratio_l >= 0.25:
                    pos = 1
                    entry_p = c
                    entry_idx = i
                    continue
                
                # SHORT (Precision Price Action Rule):
                # 1. Price is at/above upper band (overbought rally)
                # 2. Trend is bearish/neutral (c <= e50 * 1.002) - shorting relief rallies
                # 3. Upper rejection wick >= 25% (Shooting star / Seller absorption)
                upper_wick = h - max(o, c)
                wick_ratio_s = upper_wick / candle_rng if candle_rng > 0 else 0
                
                if c > u and wick_ratio_s >= 0.25 and c <= e50 * 1.002:
                    pos = -1
                    entry_p = c
                    entry_idx = i
        
        df_res = pd.DataFrame(trades)
        if df_res.empty:
            continue
        
        longs = df_res[df_res["type"] == "LONG"]
        shorts = df_res[df_res["type"] == "SHORT"]
        
        wr_total = (df_res["ret"] > 0).mean() * 100.0
        ret_total = df_res["ret"].sum() * 100.0
        
        wr_long = (longs["ret"] > 0).mean() * 100.0 if len(longs) > 0 else 0
        ret_long = longs["ret"].sum() * 100.0 if len(longs) > 0 else 0
        
        wr_short = (shorts["ret"] > 0).mean() * 100.0 if len(shorts) > 0 else 0
        ret_short = shorts["ret"].sum() * 100.0 if len(shorts) > 0 else 0
        
        print(f"\n=======================================================")
        print(f"ASSET: {ticker} (7 Days M1 Price Action Dual-Mode)")
        print(f"=======================================================")
        print(f"ALL TRADES:   {len(df_res)} trades | Win Rate: {wr_total:.1f}% | Total Net Move: {ret_total:+.2f}%")
        print(f"LONG TRADES:  {len(longs)} trades | Win Rate: {wr_long:.1f}% | Long Net Move:  {ret_long:+.2f}%")
        print(f"SHORT TRADES: {len(shorts)} trades | Win Rate: {wr_short:.1f}% | Short Net Move: {ret_short:+.2f}%")

if __name__ == "__main__":
    test_high_precision_shorting()
