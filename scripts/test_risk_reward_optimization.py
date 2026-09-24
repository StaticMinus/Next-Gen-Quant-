import numpy as np
import pandas as pd
import yfinance as yf
from src.strategies.scalper import ScalperStrategy

def run_rr_test():
    tickers = ["BTC-USD", "ETH-USD"]
    print("Fetching intraday data for Risk-to-Reward Ratio optimization...")
    
    configs = [
        {"name": "1. Current (SL 0.50%, TP 0.60%, Exit@Mean)", "sl": 0.0050, "tp": 0.0060, "exit_mean": True},
        {"name": "2. Tight SL / Target Exit (SL 0.30%, TP 0.60%, No Mean Exit)", "sl": 0.0030, "tp": 0.0060, "exit_mean": False},
        {"name": "3. Asymmetric R:R 1:2 (SL 0.35%, TP 0.70%, Exit@Mean)", "sl": 0.0035, "tp": 0.0070, "exit_mean": True},
        {"name": "4. Asymmetric R:R 1:2.5 (SL 0.30%, TP 0.75%, No Mean Exit)", "sl": 0.0030, "tp": 0.0075, "exit_mean": False},
        {"name": "5. Runner R:R 1:3 (SL 0.30%, TP 0.90%, No Mean Exit)", "sl": 0.0030, "tp": 0.0090, "exit_mean": False},
    ]
    
    for ticker in tickers:
        df = yf.download(ticker, period="7d", interval="1m", progress=False)
        if df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        close = df["Close"].astype(float)
        
        print(f"\n=========================================================================")
        print(f"ASSET: {ticker} (7-Day 1-Minute Real Tick Data)")
        print(f"=========================================================================")
        print(f"{'Config Name':<50} | {'Trades':<6} | {'Win Rate':<8} | {'Avg Win':<8} | {'Avg Loss':<8} | {'Net Return'}")
        print("-" * 105)
        
        for cfg in configs:
            strat = ScalperStrategy()
            params = {
                "window": 20,
                "num_std": 1.5,
                "exit_at_mean": cfg["exit_mean"],
                "allow_short": False,
                "stop_loss_pct": cfg["sl"],
                "max_hold_bars": 15
            }
            sig = strat.generate_signal(df, params)
            
            trades = []
            pos = 0
            entry_p = 0.0
            
            for i in range(1, len(sig)):
                curr_sig = sig.iloc[i]
                prev_sig = sig.iloc[i-1]
                p = close.iloc[i]
                
                if prev_sig == 0 and curr_sig == 1:
                    pos = 1
                    entry_p = p
                elif prev_sig == 1 and curr_sig == 0:
                    ret = (p - entry_p) / entry_p
                    trades.append(ret)
                    pos = 0
            
            if not trades:
                continue
            arr = np.array(trades)
            wins = arr[arr > 0]
            losses = arr[arr <= 0]
            wr = len(wins) / len(arr) * 100.0
            avg_w = wins.mean() * 100.0 if len(wins) > 0 else 0.0
            avg_l = losses.mean() * 100.0 if len(losses) > 0 else 0.0
            net_ret = arr.sum() * 100.0
            
            print(f"{cfg['name']:<50} | {len(arr):<6} | {wr:<7.1f}% | +{avg_w:<6.2f}% | {avg_l:<6.2f}% | {net_ret:+.2f}%")

if __name__ == "__main__":
    run_rr_test()
