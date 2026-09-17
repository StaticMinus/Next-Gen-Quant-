"""
scripts/compare_1h_intraday_vs_multiday.py
==========================================
Compares 1-Hour Intraday Flat Exit (force closed same-day)
VS.
1-Hour Multi-Day Sniper (held until target or max 2-3 days).
"""

import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import numpy as np
import pandas as pd
import yfinance as yf

def test_comparison():
    df_spy = yf.download("SPY", period="730d", interval="1h", progress=False)
    if isinstance(df_spy.columns, pd.MultiIndex):
        df_spy.columns = [col[0].lower() for col in df_spy.columns]
    else:
        df_spy.columns = [str(c).lower() for c in df_spy.columns]
        
    df_qqq = yf.download("QQQ", period="730d", interval="1h", progress=False)
    if isinstance(df_qqq.columns, pd.MultiIndex):
        df_qqq.columns = [col[0].lower() for col in df_qqq.columns]
    else:
        df_qqq.columns = [str(c).lower() for c in df_qqq.columns]
        
    for mode in ["SAME_DAY_FLAT (Max 6 hours)", "MULTI_DAY_SNIPER (Max 3 days / 21 hours)"]:
        all_trades = []
        max_bars = 6 if "SAME_DAY" in mode else 21
        force_eod = "SAME_DAY" in mode
        
        for ticker, df in [("SPY", df_spy), ("QQQ", df_qqq)]:
            df = df.copy()
            df["mean20"] = df["close"].rolling(20).mean()
            df["std20"] = df["close"].rolling(20).std()
            df["lower_band"] = df["mean20"] - 1.50 * df["std20"]
            df["sma200"] = df["close"].rolling(200).mean()
            
            in_pos = False
            entry_p = 0.0
            entry_time = None
            bars_held = 0
            sl_pct = 0.0150
            contract_mult = 10.0
            spread = 4.0 if ticker == "SPY" else 5.0
            
            for j in range(200, len(df)):
                t = df.index[j]
                c = df["close"].iloc[j]
                h = df["high"].iloc[j]
                l = df["low"].iloc[j]
                o = df["open"].iloc[j]
                m_val = df["mean20"].iloc[j]
                low_b = df["lower_band"].iloc[j]
                trend_val = df["sma200"].iloc[j]
                
                is_eod = (t.hour == 15 and t.minute >= 30)
                
                if in_pos:
                    bars_held += 1
                    sl_price = entry_p * (1.0 - sl_pct)
                    tp_price = max(entry_p * 1.0125, m_val)
                    
                    sl_hit = l <= sl_price
                    tp_hit = h >= tp_price
                    timeout = (bars_held >= max_bars) or (force_eod and is_eod)
                    
                    if sl_hit:
                        exit_p = sl_price
                        pnl = ((exit_p - entry_p) * contract_mult) - spread
                        all_trades.append({"win": False, "pnl": pnl, "hours": bars_held, "reason": "SL"})
                        in_pos = False
                    elif tp_hit:
                        exit_p = tp_price
                        pnl = ((exit_p - entry_p) * contract_mult) - spread
                        all_trades.append({"win": pnl > 0, "pnl": pnl, "hours": bars_held, "reason": "TP"})
                        in_pos = False
                    elif timeout:
                        exit_p = c
                        pnl = ((exit_p - entry_p) * contract_mult) - spread
                        all_trades.append({"win": pnl > 0, "pnl": pnl, "hours": bars_held, "reason": "TIMEOUT"})
                        in_pos = False
                else:
                    if t.hour < 10 or t.hour >= 15:
                        continue
                    if c > trend_val and l <= low_b:
                        in_pos = True
                        entry_p = min(o, low_b) if o < low_b else low_b
                        entry_time = t
                        bars_held = 0
                        
            n = len(all_trades)
            w = sum(1 for t in all_trades if t["win"])
            wr = (w / n * 100) if n else 0
            tot_pnl = sum(t["pnl"] for t in all_trades)
            avg_hold = np.mean([t["hours"] for t in all_trades]) if n else 0
            
        print("\n" + "=" * 75)
        print(f"MODE: {mode}")
        print(f"Total Trades: {n} | Win Rate: {wr:.1f}% | Net PnL: ${tot_pnl:,.2f} | Avg Hold: {avg_hold:.1f} hours")
        print("=" * 75)

if __name__ == "__main__":
    test_comparison()
