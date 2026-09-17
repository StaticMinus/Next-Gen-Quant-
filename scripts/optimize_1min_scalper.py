"""
scripts/optimize_1min_scalper.py
================================
Tests different filters on 1-minute data to see if 1m can be salvaged:
1. Pure VWAP 2.0 std dev
2. VWAP 2.0 std dev + EMA 20 trend filter
3. VWAP 2.5 std dev (Extreme oversold only)
4. VWAP 2.0 std dev + RSI < 30
5. Comparing 1m vs 5m on the same exact 30-day date window
"""

import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

def fetch_data(ticker, interval):
    now = datetime.now()
    chunks = []
    days_per_chunk = 7 if interval == "1m" else 30
    num_chunks = 4 if interval == "1m" else 2
    for i in range(num_chunks):
        end_date = now - timedelta(days=i*days_per_chunk)
        start_date = end_date - timedelta(days=days_per_chunk)
        try:
            df = yf.download(ticker, start=start_date.strftime('%Y-%m-%d'), end=end_date.strftime('%Y-%m-%d'), interval=interval, progress=False)
            if not df.empty:
                chunks.append(df)
        except Exception as e:
            pass
    if not chunks:
        return pd.DataFrame()
    full_df = pd.concat(chunks).sort_index()
    full_df = full_df[~full_df.index.duplicated(keep='first')]
    if isinstance(full_df.columns, pd.MultiIndex):
        full_df.columns = [col[0].lower() for col in full_df.columns]
    else:
        full_df.columns = [str(c).lower() for c in full_df.columns]
    return full_df

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def test_configurations():
    print("Fetching SPY & QQQ data...")
    spy_1m = fetch_data("SPY", "1m")
    qqq_1m = fetch_data("QQQ", "1m")
    
    spy_5m = fetch_data("SPY", "5m")
    qqq_5m = fetch_data("QQQ", "5m")
    
    print(f"SPY 1m: {len(spy_1m)} bars | SPY 5m: {len(spy_5m)} bars")
    
    configs = [
        {"name": "1m: Standard VWAP 2.0 std", "interval": "1m", "std": 2.0, "sl": 0.0020, "tp_mult": 1.0025, "rsi_filter": False, "ema_filter": False},
        {"name": "1m: Extreme VWAP 2.5 std", "interval": "1m", "std": 2.5, "sl": 0.0025, "tp_mult": 1.0035, "rsi_filter": False, "ema_filter": False},
        {"name": "1m: VWAP 2.0 + RSI < 30", "interval": "1m", "std": 2.0, "sl": 0.0020, "tp_mult": 1.0025, "rsi_filter": True, "ema_filter": False},
        {"name": "1m: VWAP 2.0 + EMA20 Filter", "interval": "1m", "std": 2.0, "sl": 0.0025, "tp_mult": 1.0030, "rsi_filter": False, "ema_filter": True},
        {"name": "5m: Standard VWAP 1.75 std", "interval": "5m", "std": 1.75, "sl": 0.0035, "tp_mult": 1.0035, "rsi_filter": False, "ema_filter": False},
    ]
    
    print("\n" + "=" * 95)
    print(f"{'Configuration':<32} | {'Trades':<7} | {'Win Rate':<9} | {'Net PnL ($)':<12} | {'Trades/Day':<11} | {'Avg Hold':<10}")
    print("=" * 95)
    
    for cfg in configs:
        all_trades = []
        data_dict = {"SPY": spy_1m if cfg["interval"] == "1m" else spy_5m,
                     "QQQ": qqq_1m if cfg["interval"] == "1m" else qqq_5m}
        
        spread_costs = {"SPY": 0.40, "QQQ": 1.00}
        
        for ticker, df in data_dict.items():
            if df.empty:
                continue
            df = df.copy()
            df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3.0
            df["pv"] = df["typical_price"] * df["volume"]
            df["rsi"] = compute_rsi(df["close"], 14)
            df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
            
            days = df.groupby(df.index.date)
            for date, day_df in days:
                if len(day_df) < 20:
                    continue
                cum_vol = day_df["volume"].cumsum()
                cum_pv = day_df["pv"].cumsum()
                vwap = cum_pv / (cum_vol + 1e-9)
                sq_diff = (day_df["typical_price"] - vwap) ** 2
                vwap_std = np.sqrt((sq_diff * day_df["volume"]).cumsum() / (cum_vol + 1e-9))
                lower_band = vwap - cfg["std"] * vwap_std
                
                in_pos = False
                entry_p = 0.0
                bars_held = 0
                max_bars = 15 if cfg["interval"] == "1m" else 7
                
                for j in range(15, len(day_df)):
                    t = day_df.index[j]
                    c = day_df["close"].iloc[j]
                    h = day_df["high"].iloc[j]
                    l = day_df["low"].iloc[j]
                    o = day_df["open"].iloc[j]
                    v_val = vwap.iloc[j]
                    low_b = lower_band.iloc[j]
                    is_eod = (t.hour == 15 and t.minute >= 50)
                    
                    if in_pos:
                        bars_held += 1
                        sl_hit = l <= entry_p * (1.0 - cfg["sl"])
                        tp_hit = h >= max(v_val, entry_p * cfg["tp_mult"])
                        timeout = bars_held >= max_bars or is_eod
                        
                        if sl_hit:
                            exit_p = entry_p * (1.0 - cfg["sl"])
                            pnl = ((exit_p - entry_p) * (10 if ticker == "SPY" else 1)) - spread_costs[ticker]
                            all_trades.append({"win": False, "pnl": pnl, "bars": bars_held, "date": date})
                            in_pos = False
                        elif tp_hit:
                            exit_p = max(v_val, entry_p * cfg["tp_mult"])
                            pnl = ((exit_p - entry_p) * (10 if ticker == "SPY" else 1)) - spread_costs[ticker]
                            all_trades.append({"win": pnl > 0, "pnl": pnl, "bars": bars_held, "date": date})
                            in_pos = False
                        elif timeout:
                            exit_p = c
                            pnl = ((exit_p - entry_p) * (10 if ticker == "SPY" else 1)) - spread_costs[ticker]
                            all_trades.append({"win": pnl > 0, "pnl": pnl, "bars": bars_held, "date": date})
                            in_pos = False
                    else:
                        if t.hour < 10 or (t.hour == 15 and t.minute > 30) or is_eod:
                            continue
                        fresh_dip = day_df["low"].iloc[j-1] <= low_b
                        fresh_reversal = (c > o) and (c > day_df["close"].iloc[j-1])
                        
                        if cfg["rsi_filter"]:
                            if day_df["rsi"].iloc[j-1] > 32:
                                continue
                        if cfg["ema_filter"]:
                            if c < day_df["ema20"].iloc[j]:
                                continue
                                
                        if fresh_dip and fresh_reversal:
                            in_pos = True
                            entry_p = c
                            bars_held = 0
                            
        n_t = len(all_trades)
        wins = sum(1 for t in all_trades if t["win"])
        wr = (wins / n_t * 100) if n_t else 0.0
        tot_pnl = sum(t["pnl"] for t in all_trades)
        unique_days = len(set(t["date"] for t in all_trades)) if n_t else 1
        trades_day = n_t / unique_days if unique_days else 0
        hold_time_unit = "m" if cfg["interval"] == "1m" else " (5m bars)"
        avg_bars = np.mean([t["bars"] for t in all_trades]) if n_t else 0
        avg_mins = avg_bars if cfg["interval"] == "1m" else avg_bars * 5
        
        print(f"{cfg['name']:<32} | {n_t:<7} | {wr:<8.1f}% | ${tot_pnl:<11.2f} | {trades_day:<11.1f} | {avg_mins:<8.1f} min")
    print("=" * 95)

if __name__ == "__main__":
    test_configurations()
