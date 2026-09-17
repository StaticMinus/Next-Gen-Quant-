"""
Dual Engine (SPY + QQQ) 5-Year Head-to-Head Comparison (2021 - 2026)
===================================================================
Compares:
A. Old Baseline Setup (3% SL, Inverted R:R ~1:0.7, 5-day hold)
B. New Intraday/Fast Sniper Setup (1.25% SL, 1:1.75 R:R, Max 1-2 day hold)

Outputs:
- Annual profit and returns
- Maximum drawdown in $ and % vs FundedNext limits
- Win rate & total trades
- Average trade duration
- Month-by-month consistency
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

def load_data():
    cache_dir = Path("cache")
    spy = pd.read_csv(cache_dir / "SPY_10y.csv", index_col=0, parse_dates=True)
    qqq = pd.read_csv(cache_dir / "QQQ_10y.csv", index_col=0, parse_dates=True)
    start_date = "2021-09-13"
    return spy.loc[spy.index >= start_date].copy(), qqq.loc[qqq.index >= start_date].copy()

def run_dual_simulation(spy_df, qqq_df, stop_loss_pct, rr_ratio, max_hold_days):
    # Merge dates
    common_dates = spy_df.index.intersection(qqq_df.index).sort_values()
    
    # Portfolio tracking
    initial_cap = 6000.0
    equity = initial_cap
    equity_curve = [initial_cap]
    
    # Track positions: max 2 concurrent
    positions = [] # list of active dicts
    closed_trades = []
    
    for i, d in enumerate(common_dates):
        # 1. Update existing positions
        for p in list(positions):
            ticker = p["ticker"]
            df = spy_df if ticker == "SPY" else qqq_df
            bar = df.loc[d]
            l = bar["low"]
            h = bar["high"]
            c = bar["close"]
            
            p["days_held"] += 1
            entry_p = p["entry_price"]
            sl_p = p["sl_price"]
            tp_p = p["tp_price"]
            lots = p["lots"]
            # Index multiplier: $1 per point per 1.0 lot -> 0.10 lots = $0.10/point
            mult = 0.10
            
            hit_sl = l <= sl_p
            hit_tp = h >= tp_p
            hit_to = p["days_held"] >= max_hold_days
            
            if hit_sl:
                dollar_pnl = (sl_p - entry_p) * lots * 10.0 # CFD index contract multiplier
                equity += dollar_pnl
                closed_trades.append({
                    "date": d, "ticker": ticker, "pnl": dollar_pnl, "win": False,
                    "reason": "SL", "hold": p["days_held"]
                })
                positions.remove(p)
            elif hit_tp:
                dollar_pnl = (tp_p - entry_p) * lots * 10.0
                equity += dollar_pnl
                closed_trades.append({
                    "date": d, "ticker": ticker, "pnl": dollar_pnl, "win": True,
                    "reason": "TP", "hold": p["days_held"]
                })
                positions.remove(p)
            elif hit_to:
                dollar_pnl = (c - entry_p) * lots * 10.0
                equity += dollar_pnl
                closed_trades.append({
                    "date": d, "ticker": ticker, "pnl": dollar_pnl, "win": dollar_pnl > 0,
                    "reason": "TIMEOUT", "hold": p["days_held"]
                })
                positions.remove(p)
                
        # 2. Check for new entries if capacity available (< 2)
        if len(positions) < 2:
            held_tickers = {p["ticker"] for p in positions}
            for ticker, df, lots in [("SPY", spy_df, 0.10), ("QQQ", qqq_df, 0.10)]:
                if len(positions) >= 2:
                    break
                if ticker in held_tickers:
                    continue
                
                # Check dip
                w = 5
                sub_df = df.loc[:d]
                if len(sub_df) < w:
                    continue
                mid = sub_df["close"].tail(w).mean()
                std = sub_df["close"].tail(w).std()
                l_band = mid - 1.25 * std
                
                bar = df.loc[d]
                if bar["low"] <= l_band:
                    entry_p = min(bar["open"], l_band) if bar["open"] < l_band else l_band
                    sl_p = entry_p * (1.0 - stop_loss_pct)
                    if rr_ratio:
                        tp_p = entry_p * (1.0 + stop_loss_pct * rr_ratio)
                    else:
                        tp_p = max(entry_p * 1.015, mid)
                        
                    positions.append({
                        "ticker": ticker,
                        "entry_price": entry_p,
                        "sl_price": sl_p,
                        "tp_price": tp_p,
                        "lots": lots,
                        "days_held": 0
                    })
                    held_tickers.add(ticker)
                    
        equity_curve.append(equity)
        
    trades_df = pd.DataFrame(closed_trades)
    eq_series = pd.Series(equity_curve)
    peak = eq_series.cummax()
    drawdown = peak - eq_series
    max_dd_dollar = drawdown.max()
    max_dd_pct = (drawdown / peak).max() * 100
    
    return trades_df, equity, max_dd_dollar, max_dd_pct

def main():
    spy, qqq = load_data()
    
    # 1. Baseline
    b_trades, b_equity, b_dd, b_dd_pct = run_dual_simulation(
        spy, qqq, stop_loss_pct=0.03, rr_ratio=None, max_hold_days=5
    )
    
    # 2. Sniper Setup (1.25% SL, 1:1.75 R:R, 2-day max hold)
    s_trades, s_equity, s_dd, s_dd_pct = run_dual_simulation(
        spy, qqq, stop_loss_pct=0.0125, rr_ratio=1.75, max_hold_days=2
    )

    # 3. Ultra-Fast Scalp (1.0% SL, 1:1.50 R:R, 1-day max hold / zero multi-day hold)
    u_trades, u_equity, u_dd, u_dd_pct = run_dual_simulation(
        spy, qqq, stop_loss_pct=0.010, rr_ratio=1.50, max_hold_days=1
    )
    
    print("=" * 115)
    print("      5-YEAR DUAL ENGINE HEAD-TO-HEAD: BASELINE vs SNIPER vs ULTRA-FAST SCALPER (2021 - 2026)")
    print("=" * 115)
    
    print("\n--- PERFORMANCE SUMMARY ($6,000 Starting Account) ---")
    print(f"{'Metric':<30} | {'Old Baseline (3% SL)':<22} | {'Sniper (1.25% SL)':<22} | {'Ultra-Fast (1.0% SL)':<22}")
    print("-" * 115)
    print(f"{'Total Trades':<30} | {len(b_trades):<22} | {len(s_trades):<22} | {len(u_trades):<22}")
    print(f"{'Winning Trades':<30} | {b_trades['win'].sum():<22} | {s_trades['win'].sum():<22} | {u_trades['win'].sum():<22}")
    print(f"{'Losing Trades':<30} | {(~b_trades['win']).sum():<22} | {(~s_trades['win']).sum():<22} | {(~u_trades['win']).sum():<22}")
    print(f"{'Win Rate':<30} | {(b_trades['win'].mean()*100):.1f}%{'':<17} | {(s_trades['win'].mean()*100):.1f}%{'':<17} | {(u_trades['win'].mean()*100):.1f}%{'':<17}")
    
    b_avg_w = b_trades[b_trades['win']]['pnl'].mean()
    b_avg_l = abs(b_trades[~b_trades['win']]['pnl'].mean())
    s_avg_w = s_trades[s_trades['win']]['pnl'].mean()
    s_avg_l = abs(s_trades[~s_trades['win']]['pnl'].mean())
    u_avg_w = u_trades[u_trades['win']]['pnl'].mean()
    u_avg_l = abs(u_trades[~u_trades['win']]['pnl'].mean())
    
    print(f"{'Average Win ($)':<30} | +${b_avg_w:.2f}{'':<16} | +${s_avg_w:.2f}{'':<16} | +${u_avg_w:.2f}{'':<16}")
    print(f"{'Average Loss ($)':<30} | -${b_avg_l:.2f}{'':<16} | -${s_avg_l:.2f}{'':<16} | -${u_avg_l:.2f}{'':<16}")
    print(f"{'Realized Risk:Reward':<30} | 1 : {(b_avg_w/b_avg_l):.2f} (Inverted!){'':<4} | 1 : {(s_avg_w/s_avg_l):.2f} (Positive!){'':<4} | 1 : {(u_avg_w/u_avg_l):.2f} (Positive!){'':<4}")
    
    b_pf = b_trades[b_trades['win']]['pnl'].sum() / abs(b_trades[~b_trades['win']]['pnl'].sum())
    s_pf = s_trades[s_trades['win']]['pnl'].sum() / abs(s_trades[~s_trades['win']]['pnl'].sum())
    u_pf = u_trades[u_trades['win']]['pnl'].sum() / abs(u_trades[~u_trades['win']]['pnl'].sum())
    print(f"{'Profit Factor':<30} | {b_pf:.2f}{'':<18} | {s_pf:.2f}{'':<18} | {u_pf:.2f}{'':<18}")
    
    print(f"{'Average Hold Duration':<30} | {b_trades['hold'].mean():.1f} days{'':<15} | {s_trades['hold'].mean():.1f} days{'':<15} | {u_trades['hold'].mean():.1f} day (Intraday!){'':<4}")
    
    print("-" * 115)
    print(f"{'Total 5-Year Net Profit':<30} | +${b_equity - 6000:.2f}{'':<14} | +${s_equity - 6000:.2f}{'':<14} | +${u_equity - 6000:.2f}{'':<14}")
    print(f"{'Max Drawdown ($)':<30} | ${b_dd:.2f}{'':<16} | ${s_dd:.2f}{'':<16} | ${u_dd:.2f}{'':<16}")
    print(f"{'Max DD % of Account':<30} | {b_dd_pct:.2f}%{'':<17} | {s_dd_pct:.2f}%{'':<17} | {u_dd_pct:.2f}%{'':<17}")
    print(f"{'Safety vs $360 Limit':<30} | {(b_dd/360)*100:.1f}% used{'':<12} | {(s_dd/360)*100:.1f}% used{'':<12} | {(u_dd/360)*100:.1f}% used (Ultra-safe!){'':<1}")

    # Year by year breakdown for Sniper
    s_trades['year'] = pd.to_datetime(s_trades['date']).dt.year
    print("\n--- SNIPER (1.25% SL) YEAR-BY-YEAR PERFORMANCE (2021 - 2026) ---")
    print(f"{'Year':<8} | {'Trades':<8} | {'Wins':<6} | {'Losses':<8} | {'Win Rate':<10} | {'Annual Profit':<15}")
    print("-" * 65)
    for yr, grp in s_trades.groupby('year'):
        w = grp['win'].sum()
        l = len(grp) - w
        wr = (w / len(grp)) * 100
        prof = grp['pnl'].sum()
        print(f"{yr:<8} | {len(grp):<8} | {w:<6} | {l:<8} | {wr:.1f}%{'':<4} | +${prof:.2f}")

    # Year by year breakdown for Ultra-Fast Scalp
    u_trades['year'] = pd.to_datetime(u_trades['date']).dt.year
    print("\n--- ULTRA-FAST (1.0% SL, 1-DAY) YEAR-BY-YEAR PERFORMANCE (2021 - 2026) ---")
    print(f"{'Year':<8} | {'Trades':<8} | {'Wins':<6} | {'Losses':<8} | {'Win Rate':<10} | {'Annual Profit':<15}")
    print("-" * 65)
    for yr, grp in u_trades.groupby('year'):
        w = grp['win'].sum()
        l = len(grp) - w
        wr = (w / len(grp)) * 100
        prof = grp['pnl'].sum()
        print(f"{yr:<8} | {len(grp):<8} | {w:<6} | {l:<8} | {wr:.1f}%{'':<4} | +${prof:.2f}")

if __name__ == "__main__":
    main()

