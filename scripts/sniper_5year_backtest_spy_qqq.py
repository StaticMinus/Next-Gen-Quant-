"""
Comprehensive 5-Year Backtest: SPY & QQQ Sniper Scalper (2021 - 2026)
=====================================================================
Analyzes:
1. Baseline (Wide 3.0% SL, 5-day hold, exit at mean)
2. Sniper Variant A (Tight 1.25% SL, 1:1.5 Risk-to-Reward, fast exit)
3. Sniper Variant B (Tight 1.50% SL, 1:2.0 Risk-to-Reward)
4. Intraday / Fast-Exit (Max 1-2 day hold vs 5-day hold)
5. Prop Firm Safety ($6,000 FundedNext account with $180 daily / $360 max limit)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from datetime import datetime

# Sizing on cTrader FundedNext:
# SPX500: 0.10 lots = 0.10 contract = $0.10 per index point
# NDX100: 0.10 lots = 0.10 contract = $0.10 per index point

def load_5y_data():
    cache_dir = Path("cache")
    spy = pd.read_csv(cache_dir / "SPY_10y.csv", index_col=0, parse_dates=True)
    qqq = pd.read_csv(cache_dir / "QQQ_10y.csv", index_col=0, parse_dates=True)
    
    start_date = "2021-09-13"
    spy_5y = spy.loc[spy.index >= start_date].copy()
    qqq_5y = qqq.loc[qqq.index >= start_date].copy()
    return spy_5y, qqq_5y


def simulate_sniper(df, ticker, stop_loss_pct, target_rr_ratio=None, max_hold_days=5, dip_std=1.25, exit_at_mean=True):
    """
    Simulates a high-precision dip entry strategy using bar-level high/low execution.
    - stop_loss_pct: e.g. 0.0125 (1.25%) or 0.03 (3.0%)
    - target_rr_ratio: if set, TP is set to entry * (1 + stop_loss_pct * target_rr_ratio)
    - max_hold_days: max holding days before timeout exit
    - dip_std: standard deviation multiplier for lower band
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_p = df["open"]
    
    # 5-day mean and volatility bands
    w = 5
    mid = close.rolling(w).mean()
    std = close.rolling(w).std()
    lower_band = mid - dip_std * std
    
    trades = []
    in_pos = False
    entry_price = 0.0
    entry_date = None
    entry_idx = 0
    tp_price = 0.0
    sl_price = 0.0
    
    dates = df.index
    n = len(df)
    
    for i in range(w, n):
        d = dates[i]
        c = close.iloc[i]
        h = high.iloc[i]
        l = low.iloc[i]
        o = open_p.iloc[i]
        m = mid.iloc[i]
        band = lower_band.iloc[i]
        
        if in_pos:
            hold_days = i - entry_idx
            
            # Check Stop Loss hit today?
            hit_sl = l <= sl_price
            
            # Check Take Profit hit today?
            hit_tp = h >= tp_price
            
            # Timeout hit?
            hit_timeout = hold_days >= max_hold_days
            
            # If both hit in same bar, assume worst case (SL first) for conservative realism
            if hit_sl:
                exit_price = sl_price
                exit_reason = "STOP_LOSS"
                pnl_pct = (exit_price - entry_price) / entry_price
                trades.append({
                    "ticker": ticker,
                    "entry_date": entry_date,
                    "exit_date": d,
                    "hold_days": hold_days,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "exit_reason": exit_reason,
                    "win": False
                })
                in_pos = False
            elif hit_tp:
                exit_price = tp_price
                exit_reason = "TAKE_PROFIT"
                pnl_pct = (exit_price - entry_price) / entry_price
                trades.append({
                    "ticker": ticker,
                    "entry_date": entry_date,
                    "exit_date": d,
                    "hold_days": hold_days,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "exit_reason": exit_reason,
                    "win": True
                })
                in_pos = False
            elif hit_timeout:
                exit_price = c
                exit_reason = "TIMEOUT"
                pnl_pct = (exit_price - entry_price) / entry_price
                trades.append({
                    "ticker": ticker,
                    "entry_date": entry_date,
                    "exit_date": d,
                    "hold_days": hold_days,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "exit_reason": exit_reason,
                    "win": pnl_pct > 0
                })
                in_pos = False
                
        else:
            # Entry Signal: Low dips below lower band
            # We enter at lower band if Low <= lower band, or at Open/Close
            if l <= band:
                # Execution price: touch of lower band (Sniper dip buy)
                # If Open was already below lower band, enter at Open
                entry_price = min(o, band) if o < band else band
                entry_date = d
                entry_idx = i
                in_pos = True
                
                # Set Stop Loss
                sl_price = entry_price * (1.0 - stop_loss_pct)
                
                # Set Take Profit
                if target_rr_ratio is not None:
                    # Asymmetric R:R (e.g. 1.5x or 2.0x the SL)
                    tp_price = entry_price * (1.0 + stop_loss_pct * target_rr_ratio)
                else:
                    # Exit at 5-day mean
                    tp_price = max(entry_price * 1.015, m)
                    
    return pd.DataFrame(trades)


def evaluate_results(trades_df, name=""):
    if len(trades_df) == 0:
        return {"name": name, "trades": 0, "win_rate": 0, "net_return": 0}
        
    n_trades = len(trades_df)
    wins = trades_df["win"].sum()
    win_rate = (wins / n_trades) * 100
    
    avg_win = trades_df[trades_df["win"]]["pnl_pct"].mean() * 100 if wins > 0 else 0.0
    losses = trades_df[~trades_df["win"]]
    avg_loss = abs(losses["pnl_pct"].mean() * 100) if len(losses) > 0 else 0.0
    
    # Realized R:R
    realized_rr = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    
    # Cumulative return compounding
    cum_ret = (1.0 + trades_df["pnl_pct"]).prod() - 1.0
    
    # Holding duration
    avg_hold = trades_df["hold_days"].mean()
    day1_exits = (trades_df["hold_days"] <= 1).sum()
    day1_pct = (day1_exits / n_trades) * 100
    
    # Max Consecutive Losses
    is_loss = (~trades_df["win"]).astype(int)
    max_streak = 0
    current_streak = 0
    for l in is_loss:
        if l == 1:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0
            
    # Exit reasons
    tp_exits = (trades_df["exit_reason"] == "TAKE_PROFIT").sum()
    sl_exits = (trades_df["exit_reason"] == "STOP_LOSS").sum()
    to_exits = (trades_df["exit_reason"] == "TIMEOUT").sum()
    
    # Profit Factor
    total_gain = trades_df[trades_df["win"]]["pnl_pct"].sum()
    total_loss = abs(trades_df[~trades_df["win"]]["pnl_pct"].sum())
    profit_factor = (total_gain / total_loss) if total_loss > 0 else 99.0
    
    return {
        "name": name,
        "total_trades": n_trades,
        "wins": wins,
        "losses": n_trades - wins,
        "win_rate": win_rate,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "realized_rr": realized_rr,
        "profit_factor": profit_factor,
        "total_return_pct": cum_ret * 100,
        "avg_hold_days": avg_hold,
        "fast_exits_pct": day1_pct,
        "max_loss_streak": max_streak,
        "tp_exits": tp_exits,
        "sl_exits": sl_exits,
        "timeout_exits": to_exits
    }


def run_full_5year_experiment():
    spy_5y, qqq_5y = load_5y_data()
    print("=" * 110)
    print("      AGENTQUANT 5-YEAR RIGOROUS BACKTEST & ARCHITECTURAL COMPARISON (2021 - 2026)")
    print("      Testing: Stop Loss Sensitivity, R:R Asymmetry, Holding Duration, and Prop Firm Limits")
    print("=" * 110)
    
    configs = [
        {"desc": "Old Baseline (Wide 3.0% SL, Exit at Mean, 5d Hold)", "sl": 0.030, "rr": None, "hold": 5},
        {"desc": "Sniper Mod 1 (Tight 1.5% SL, 1:1.5 R:R, 3d Hold)", "sl": 0.015, "rr": 1.5, "hold": 3},
        {"desc": "Sniper Mod 2 (Tight 1.25% SL, 1:2.0 R:R, 2d Hold)", "sl": 0.0125, "rr": 2.0, "hold": 2},
        {"desc": "Ultra-Fast Scalp (1.0% SL, 1:1.5 R:R, 1d Hold)", "sl": 0.010, "rr": 1.5, "hold": 1},
        {"desc": "Hybrid Sniper (1.5% SL, Exit at Mean, 3d Hold)", "sl": 0.015, "rr": None, "hold": 3},
    ]
    
    print("\n--- PART 1: SPY (S&P 500) 5-YEAR TOURNAMENT ---")
    results_spy = []
    for cfg in configs:
        res_df = simulate_sniper(spy_5y, "SPY", stop_loss_pct=cfg["sl"], target_rr_ratio=cfg["rr"], max_hold_days=cfg["hold"])
        metrics = evaluate_results(res_df, cfg["desc"])
        results_spy.append(metrics)
        print(f"\nModel: {cfg['desc']}")
        print(f"  • Trades: {metrics['total_trades']} | Wins: {metrics['wins']} | Losses: {metrics['losses']} | Win Rate: {metrics['win_rate']:.1f}%")
        print(f"  • Avg Win: +{metrics['avg_win_pct']:.2f}% | Avg Loss: -{metrics['avg_loss_pct']:.2f}% | Realized R:R: 1:{metrics['realized_rr']:.2f}")
        print(f"  • Profit Factor: {metrics['profit_factor']:.2f} | 5-Year Return: {metrics['total_return_pct']:+.1f}% | Worst Streak: {metrics['max_loss_streak']} losses")
        print(f"  • Avg Hold: {metrics['avg_hold_days']:.1f} days | <=1 Day Exits: {metrics['fast_exits_pct']:.1f}% | TP/SL/Timeout: {metrics['tp_exits']}/{metrics['sl_exits']}/{metrics['timeout_exits']}")
        
    print("\n" + "=" * 110)
    print("--- PART 2: QQQ (NASDAQ 100) 5-YEAR TOURNAMENT ---")
    results_qqq = []
    for cfg in configs:
        res_df = simulate_sniper(qqq_5y, "QQQ", stop_loss_pct=cfg["sl"], target_rr_ratio=cfg["rr"], max_hold_days=cfg["hold"])
        metrics = evaluate_results(res_df, cfg["desc"])
        results_qqq.append(metrics)
        print(f"\nModel: {cfg['desc']}")
        print(f"  • Trades: {metrics['total_trades']} | Wins: {metrics['wins']} | Losses: {metrics['losses']} | Win Rate: {metrics['win_rate']:.1f}%")
        print(f"  • Avg Win: +{metrics['avg_win_pct']:.2f}% | Avg Loss: -{metrics['avg_loss_pct']:.2f}% | Realized R:R: 1:{metrics['realized_rr']:.2f}")
        print(f"  • Profit Factor: {metrics['profit_factor']:.2f} | 5-Year Return: {metrics['total_return_pct']:+.1f}% | Worst Streak: {metrics['max_loss_streak']} losses")
        print(f"  • Avg Hold: {metrics['avg_hold_days']:.1f} days | <=1 Day Exits: {metrics['fast_exits_pct']:.1f}% | TP/SL/Timeout: {metrics['tp_exits']}/{metrics['sl_exits']}/{metrics['timeout_exits']}")

    # Dollarized Simulation on $6,000 FundedNext Account
    print("\n" + "=" * 110)
    print("--- PART 3: REALISTIC FUNDEDNEXT $6,000 PROP FIRM DOLLARIZED IMPACT ---")
    print("Account Parameters: Capital $6,000 | Daily Loss Limit: $180 | Max Trailing Limit: $360")
    print("Trade Sizing: 0.10 Lots (~$10/pt on SPX / ~$10/pt on NDX)")
    print("-" * 110)
    
    for asset, df_data, ticker in [("SPY", spy_5y, "SPX500"), ("QQQ", qqq_5y, "NDX100")]:
        old_trades = simulate_sniper(df_data, asset, stop_loss_pct=0.03, target_rr_ratio=None, max_hold_days=5)
        sniper_trades = simulate_sniper(df_data, asset, stop_loss_pct=0.015, target_rr_ratio=1.5, max_hold_days=3)
        
        # Calculate dollar risk and return per trade on $6k account
        # Average risk on old: 3% of entry * lots
        # Average risk on sniper: 1.5% of entry * lots
        avg_price = df_data["close"].mean()
        
        old_dollar_risk = avg_price * 0.03 * 0.10
        old_dollar_gain = avg_price * 0.02 * 0.10
        sniper_dollar_risk = avg_price * 0.015 * 0.10
        sniper_dollar_gain = avg_price * 0.0225 * 0.10
        
        print(f"\n>>> {asset} ({ticker}) Dollarized Profile:")
        print(f"  • Old Setup (3% SL):   Risk per trade = ${old_dollar_risk:.2f}  | Reward = ${old_dollar_gain:.2f} | Max DD Buffer Used: {(old_dollar_risk/180)*100:.1f}% of Daily Limit")
        print(f"  • Sniper (1.5% SL):  Risk per trade = ${sniper_dollar_risk:.2f}  | Reward = ${sniper_dollar_gain:.2f} | Max DD Buffer Used: {(sniper_dollar_risk/180)*100:.1f}% of Daily Limit")


if __name__ == "__main__":
    run_full_5year_experiment()
