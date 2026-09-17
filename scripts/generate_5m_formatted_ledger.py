"""
scripts/generate_5m_formatted_ledger.py
======================================
Produces the exact identical format for the 5-Minute Strategy as requested by the user:
- Part 1: Per Day Breakdown (Sample of trading days & averages)
- Part 2: Per Week Breakdown (All weeks in empirical period)
- Part 3: Per Month Breakdown (Monthly empirical & run-rate)
- Part 4: Year-by-Year Breakdown for the Next 5 Years (Year 1 to Year 5 individual tables)
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import numpy as np
import pandas as pd
import yfinance as yf
import json

def generate_5m_ledger():
    initial_balance = 50000.0
    trader_split = 0.85
    naira_rate = 1650.0
    lot_multiplier = 1.0
    
    all_trades = []
    
    for ticker, c_sym in [("SPY", "SPX500"), ("QQQ", "NDX100")]:
        df = yf.download(ticker, period="60d", interval="5m", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0].lower() for col in df.columns]
        else:
            df.columns = [str(c).lower() for c in df.columns]
            
        df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3.0
        df["pv"] = df["typical_price"] * df["volume"]
        
        days = df.groupby(df.index.date)
        std_multiplier = 1.75 if ticker == "SPY" else 1.80
        stop_loss_pct = 0.0035  # 0.35%
        max_bars_hold = 7       # 35 minutes max
        
        for date, day_df in days:
            if len(day_df) < 20:
                continue
                
            cum_vol = day_df["volume"].cumsum()
            cum_pv = day_df["pv"].cumsum()
            vwap = cum_pv / (cum_vol + 1e-9)
            
            sq_diff = (day_df["typical_price"] - vwap) ** 2
            vwap_std = np.sqrt((sq_diff * day_df["volume"]).cumsum() / (cum_vol + 1e-9))
            lower_band = vwap - std_multiplier * vwap_std
            
            in_pos = False
            entry_p = 0.0
            entry_time = None
            bars_held = 0
            
            for j in range(6, len(day_df)):
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
                    sl_hit = l <= entry_p * (1.0 - stop_loss_pct)
                    tp_target = max(v_val, entry_p * 1.0030)
                    tp_hit = h >= tp_target
                    timeout = bars_held >= max_bars_hold or is_eod
                    
                    if sl_hit:
                        exit_p = entry_p * (1.0 - stop_loss_pct)
                        pnl_usd = (exit_p - entry_p) * lot_multiplier * (10 if ticker == "SPY" else 1)
                        all_trades.append({
                            "ticker": ticker, "entry_time": str(entry_time), "exit_time": str(t),
                            "date": str(entry_time.date()),
                            "entry_price": round(entry_p, 2), "exit_price": round(exit_p, 2),
                            "pnl_usd": round(pnl_usd, 2), "ret_pct": round(-stop_loss_pct * 100, 2),
                            "minutes_held": bars_held * 5, "win": False, "reason": "STOP_LOSS"
                        })
                        in_pos = False
                    elif tp_hit:
                        exit_p = tp_target
                        pnl_usd = (exit_p - entry_p) * lot_multiplier * (10 if ticker == "SPY" else 1)
                        all_trades.append({
                            "ticker": ticker, "entry_time": str(entry_time), "exit_time": str(t),
                            "date": str(entry_time.date()),
                            "entry_price": round(entry_p, 2), "exit_price": round(exit_p, 2),
                            "pnl_usd": round(pnl_usd, 2), "ret_pct": round(((exit_p - entry_p)/entry_p) * 100, 2),
                            "minutes_held": bars_held * 5, "win": True, "reason": "TAKE_PROFIT"
                        })
                        in_pos = False
                    elif timeout:
                        exit_p = c
                        pnl_usd = (exit_p - entry_p) * lot_multiplier * (10 if ticker == "SPY" else 1)
                        all_trades.append({
                            "ticker": ticker, "entry_time": str(entry_time), "exit_time": str(t),
                            "date": str(entry_time.date()),
                            "entry_price": round(entry_p, 2), "exit_price": round(exit_p, 2),
                            "pnl_usd": round(pnl_usd, 2), "ret_pct": round(((exit_p - entry_p)/entry_p) * 100, 2),
                            "minutes_held": bars_held * 5, "win": pnl_usd > 0, "reason": "TIMEOUT_FLAT"
                        })
                        in_pos = False
                else:
                    if t.hour < 10 or (t.hour == 15 and t.minute > 15) or is_eod:
                        continue
                    fresh_dip = day_df["low"].iloc[j-1] <= low_b
                    fresh_reversal = (c > o) and (c > day_df["close"].iloc[j-1])
                    if fresh_dip and fresh_reversal:
                        in_pos = True
                        entry_p = c
                        entry_time = t
                        bars_held = 0
                        
    all_trades.sort(key=lambda x: x["entry_time"])
    trades_df = pd.DataFrame(all_trades)
    trades_df["entry_dt"] = pd.to_datetime(trades_df["entry_time"])
    trades_df["date"] = trades_df["entry_dt"].dt.date
    trades_df["week"] = trades_df["entry_dt"].dt.isocalendar().week
    trades_df["month"] = trades_df["entry_dt"].dt.month
    
    # 1. Day Breakdown
    daily_stats = trades_df.groupby("date").agg(
        trades_count=("pnl_usd", "count"),
        net_profit_usd=("pnl_usd", "sum"),
        wins=("win", lambda s: sum(s)),
        losses=("win", lambda s: len(s) - sum(s)),
    ).reset_index()
    daily_stats["win_rate_pct"] = (daily_stats["wins"] / daily_stats["trades_count"] * 100).round(1)
    daily_stats["net_profit_ngn"] = (daily_stats["net_profit_usd"] * naira_rate).round(0)
    
    avg_trades_per_day = daily_stats["trades_count"].mean()
    avg_profit_per_day = daily_stats["net_profit_usd"].mean()
    
    # 2. Week Breakdown
    weekly_stats = trades_df.groupby("week").agg(
        trades_count=("pnl_usd", "count"),
        net_profit_usd=("pnl_usd", "sum"),
        wins=("win", lambda s: sum(s)),
        losses=("win", lambda s: len(s) - sum(s)),
    ).reset_index()
    weekly_stats["win_rate_pct"] = (weekly_stats["wins"] / weekly_stats["trades_count"] * 100).round(1)
    weekly_stats["net_profit_ngn"] = (weekly_stats["net_profit_usd"] * naira_rate).round(0)
    avg_trades_per_week = weekly_stats["trades_count"].mean()
    avg_profit_per_week = weekly_stats["net_profit_usd"].mean()
    
    # 3. Monthly Breakdown (21 trading days/month)
    total_trades_empirical = len(trades_df)
    total_wins_empirical = len(trades_df[trades_df["win"] == True])
    overall_win_rate = (total_wins_empirical / total_trades_empirical * 100) if total_trades_empirical else 0
    total_pnl_empirical = trades_df["pnl_usd"].sum()
    
    trades_per_month = avg_trades_per_day * 21.0
    profit_per_month = avg_profit_per_day * 21.0
    
    # 4. 5-Year Year-by-Year Breakdown (252 trading days per year)
    year_regimes = [
        {"year": "Year 1", "desc": "Current Market Regime (Baseline Mean-Reversion)", "multiplier": 1.00},
        {"year": "Year 2", "desc": "Trending Bull Expansion (Sustained Momentum)", "multiplier": 1.04},
        {"year": "Year 3", "desc": "High Volatility Rate Cycle (Expanded Range)", "multiplier": 1.08},
        {"year": "Year 4", "desc": "Consolidation / Tighter Range", "multiplier": 0.92},
        {"year": "Year 5", "desc": "Macro Bull Acceleration", "multiplier": 1.05}
    ]
    
    yearly_breakdown = []
    cum_payout = 0.0
    for yr in year_regimes:
        yr_days = 252
        yr_trades = int(round(avg_trades_per_day * yr_days * yr["multiplier"]))
        yr_gross_profit = avg_profit_per_day * yr_days * yr["multiplier"]
        trader_85 = yr_gross_profit * trader_split
        cum_payout += trader_85
        yearly_breakdown.append({
            "year": yr["year"],
            "regime": yr["desc"],
            "trades_in_year": yr_trades,
            "avg_trades_per_month": round(yr_trades / 12.0, 1),
            "avg_trades_per_day": round(yr_trades / yr_days, 1),
            "win_rate_pct": round(overall_win_rate, 1),
            "gross_profit_usd": round(yr_gross_profit, 2),
            "trader_85_usd": round(trader_85, 2),
            "trader_85_ngn": round(trader_85 * naira_rate, 0),
            "cumulative_payout_usd": round(cum_payout, 2)
        })
        
    out = {
        "daily_stats": daily_stats.to_dict(orient="records"),
        "weekly_stats": weekly_stats.to_dict(orient="records"),
        "yearly_breakdown": yearly_breakdown,
        "summary": {
            "total_trades": total_trades_empirical,
            "overall_win_rate": round(overall_win_rate, 1),
            "total_pnl_usd": round(total_pnl_empirical, 2),
            "avg_trades_per_day": round(avg_trades_per_day, 1),
            "avg_profit_per_day_usd": round(avg_profit_per_day, 2),
            "avg_trades_per_week": round(avg_trades_per_week, 1),
            "avg_profit_per_week_usd": round(avg_profit_per_week, 2),
            "avg_trades_per_month": round(trades_per_month, 1),
            "avg_profit_per_month_usd": round(profit_per_month, 2),
        }
    }
    
    with open(ROOT_DIR / "results" / "sharp_5min_exact_ledger.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
        
    print("5m Exact Ledger Generated Successfully!")
    print(f"Total Trades: {total_trades_empirical}, Win Rate: {overall_win_rate:.1f}%, Net PnL: ${total_pnl_empirical:.2f}")

if __name__ == "__main__":
    generate_5m_ledger()
