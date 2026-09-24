import numpy as np
import pandas as pd
import yfinance as yf
from src.strategies.scalper import ScalperStrategy

def run_regime_short_test():
    tickers = ["BTC-USD", "ETH-USD"]
    print("Fetching intraday data for Trend-Filtered Shorting backtest...")
    
    for ticker in tickers:
        df = yf.download(ticker, period="7d", interval="1m", progress=False)
        if df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        close = df["Close"].astype(float)
        
        # 1. Benchmark: Long Only
        strat = ScalperStrategy()
        params_long = {
            "window": 20, "num_std": 1.5, "exit_at_mean": True,
            "allow_short": False, "stop_loss_pct": 0.0050, "max_hold_bars": 12
        }
        sig_long = strat.generate_signal(df, params_long)
        
        # 2. Trend-Filtered Bi-Directional (Trend-Aligned Regime Scalp):
        # - When Price > EMA50 -> Long Dips Only
        # - When Price < EMA50 -> Short Rallies Only
        params_trend_bi = {
            "window": 20, "num_std": 1.5, "exit_at_mean": True,
            "allow_short": True, "stop_loss_pct": 0.0050, "max_hold_bars": 12,
            "trend_filter": True, "trend_window": 50
        }
        sig_trend_bi = strat.generate_signal(df, params_trend_bi)
        
        def evaluate_trades(sig, close_series):
            trades = []
            pos = 0
            entry_p = 0.0
            entry_idx = 0
            
            for i in range(1, len(sig)):
                curr_sig = sig.iloc[i]
                prev_sig = sig.iloc[i-1]
                p = close_series.iloc[i]
                
                if prev_sig == 0 and curr_sig != 0:
                    pos = curr_sig
                    entry_p = p
                    entry_idx = i
                elif prev_sig != 0 and curr_sig == 0:
                    if pos == 1:
                        ret = (p - entry_p) / entry_p
                    else:
                        ret = (entry_p - p) / entry_p
                    trades.append({"type": "LONG" if pos == 1 else "SHORT", "ret": ret, "bars": i - entry_idx})
                    pos = 0
            
            if not trades:
                return 0, 0.0, 0.0, 0.0, 0.0
            df_t = pd.DataFrame(trades)
            win_rate = (df_t["ret"] > 0).mean() * 100.0
            total_ret = df_t["ret"].sum() * 100.0
            long_wins = (df_t[df_t["type"]=="LONG"]["ret"] > 0).mean() * 100.0 if len(df_t[df_t["type"]=="LONG"]) > 0 else 0
            short_wins = (df_t[df_t["type"]=="SHORT"]["ret"] > 0).mean() * 100.0 if len(df_t[df_t["type"]=="SHORT"]) > 0 else 0
            return len(trades), win_rate, total_ret, long_wins, short_wins
            
        n_l, wr_l, ret_l, l_wins_l, _ = evaluate_trades(sig_long, close)
        n_t, wr_t, ret_t, l_wins_t, s_wins_t = evaluate_trades(sig_trend_bi, close)
        
        print(f"\n==========================================")
        print(f"ASSET: {ticker} (7 Days M1 Real Bars)")
        print(f"==========================================")
        print(f"1. Long-Only:            {n_l} trades | Win Rate: {wr_l:.1f}% | Net Move: {ret_l:+.2f}%")
        print(f"2. Trend-Aligned (L & S): {n_t} trades | Win Rate: {wr_t:.1f}% | Net Move: {ret_t:+.2f}% (Longs: {l_wins_t:.1f}%, Shorts: {s_wins_t:.1f}%)")

if __name__ == "__main__":
    run_regime_short_test()
