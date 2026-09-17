"""
scripts/sniper_exact_daily_breakdown.py
=======================================
Granular Day / Week / Month / Year Ledger for the 75% Win Rate Quantitative Sniper (SPY & QQQ).
Using the exact format requested:
- Part A: Per Day Breakdown (Sample of trading days & averages)
- Part B: Per Week Breakdown (Empirical weeks log & averages)
- Part C: Per Month Breakdown (Monthly empirical & run-rate)
- Part D: Year-by-Year Breakdown for 5 Years (Year 1 to Year 5 individual tables)
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
import json

def run_quant_sniper_ledger():
    trader_split = 0.85
    naira_rate = 1650.0
    
    cache_dir = Path("cache")
    spy_df = pd.read_csv(cache_dir / "SPY_10y.csv", index_col=0, parse_dates=True)
    qqq_df = pd.read_csv(cache_dir / "QQQ_10y.csv", index_col=0, parse_dates=True)
    
    start_date = "2021-09-13"
    spy_5y = spy_df.loc[spy_df.index >= start_date].copy()
    qqq_5y = qqq_df.loc[qqq_df.index >= start_date].copy()
    
    # 0.10 lots CFD = 1 contract equivalent ($10.00 per point move)
    contract_mult = 10.0
    comm = 1.50  # Commission + spread
    
    all_trades = []
    
    for ticker, df in [("SPY", spy_5y), ("QQQ", qqq_5y)]:
        c = df["close"]
        h = df["high"]
        l = df["low"]
        o = df["open"]
        
        m5 = c.rolling(5).mean()
        s5 = c.rolling(5).std()
        lower_band = m5 - 1.25 * s5
        sma200 = c.rolling(200).mean()
        
        in_pos = False
        entry_p = 0.0
        entry_d = None
        bars = 0
        sl_pct = 0.025  # 2.5% hard stop
        max_hold = 5    # 5 days max
        
        for i in range(200, len(df)):
            dt = df.index[i]
            cur_c = c.iloc[i]
            cur_h = h.iloc[i]
            cur_l = l.iloc[i]
            cur_o = o.iloc[i]
            cur_m = m5.iloc[i]
            cur_b = lower_band.iloc[i]
            cur_trend = sma200.iloc[i]
            
            if in_pos:
                bars += 1
                sl_price = entry_p * (1.0 - sl_pct)
                tp_price = cur_m
                
                hit_sl = cur_l <= sl_price
                hit_tp = cur_h >= tp_price
                timeout = bars >= max_hold
                
                if hit_sl:
                    exit_p = sl_price
                    pnl = (exit_p - entry_p) * contract_mult - (comm * 2)
                    all_trades.append({
                        "ticker": ticker, "entry_date": str(entry_d.date()), "exit_date": str(dt.date()),
                        "date": str(entry_d.date()),
                        "entry_price": round(entry_p, 2), "exit_price": round(exit_p, 2),
                        "pnl_usd": round(pnl, 2), "win": False, "days_held": bars, "reason": "STOP_LOSS"
                    })
                    in_pos = False
                elif hit_tp:
                    exit_p = tp_price
                    pnl = (exit_p - entry_p) * contract_mult - (comm * 2)
                    all_trades.append({
                        "ticker": ticker, "entry_date": str(entry_d.date()), "exit_date": str(dt.date()),
                        "date": str(entry_d.date()),
                        "entry_price": round(entry_p, 2), "exit_price": round(exit_p, 2),
                        "pnl_usd": round(pnl, 2), "win": True, "days_held": bars, "reason": "TAKE_PROFIT"
                    })
                    in_pos = False
                elif timeout:
                    exit_p = cur_c
                    pnl = (exit_p - entry_p) * contract_mult - (comm * 2)
                    all_trades.append({
                        "ticker": ticker, "entry_date": str(entry_d.date()), "exit_date": str(dt.date()),
                        "date": str(entry_d.date()),
                        "entry_price": round(entry_p, 2), "exit_price": round(exit_p, 2),
                        "pnl_usd": round(pnl, 2), "win": pnl > 0, "days_held": bars, "reason": "TIMEOUT"
                    })
                    in_pos = False
            else:
                # Bull-filter condition: price > 200 SMA and low <= lower band
                if cur_c > cur_trend and cur_l <= cur_b:
                    in_pos = True
                    entry_p = min(cur_o, cur_b) if cur_o < cur_b else cur_b
                    entry_d = dt
                    bars = 0
                    
    all_trades.sort(key=lambda x: x["entry_date"])
    trades_df = pd.DataFrame(all_trades)
    trades_df["entry_dt"] = pd.to_datetime(trades_df["entry_date"])
    trades_df["year"] = trades_df["entry_dt"].dt.year
    trades_df["week"] = trades_df["entry_dt"].dt.isocalendar().week
    trades_df["month"] = trades_df["entry_dt"].dt.to_period("M").astype(str)
    
    # 1. Day Breakdown
    daily_stats = trades_df.groupby("date").agg(
        trades_count=("pnl_usd", "count"),
        net_profit_usd=("pnl_usd", "sum"),
        wins=("win", lambda s: sum(s)),
        losses=("win", lambda s: len(s) - sum(s)),
    ).reset_index()
    daily_stats["win_rate_pct"] = (daily_stats["wins"] / daily_stats["trades_count"] * 100).round(1)
    daily_stats["net_profit_ngn"] = (daily_stats["net_profit_usd"] * naira_rate).round(0)
    
    total_trading_days = 1255  # 5 years
    avg_trades_per_day = len(trades_df) / total_trading_days
    avg_profit_per_day = trades_df["pnl_usd"].sum() / total_trading_days
    
    # 2. Week Breakdown
    weekly_stats = trades_df.groupby(["year", "week"]).agg(
        trades_count=("pnl_usd", "count"),
        net_profit_usd=("pnl_usd", "sum"),
        wins=("win", lambda s: sum(s)),
        losses=("win", lambda s: len(s) - sum(s)),
    ).reset_index()
    weekly_stats["win_rate_pct"] = (weekly_stats["wins"] / weekly_stats["trades_count"] * 100).round(1)
    weekly_stats["net_profit_ngn"] = (weekly_stats["net_profit_usd"] * naira_rate).round(0)
    avg_trades_per_week = len(trades_df) / (total_trading_days / 5.0)
    avg_profit_per_week = trades_df["pnl_usd"].sum() / (total_trading_days / 5.0)
    
    # 3. Monthly Breakdown
    monthly_stats = trades_df.groupby("month").agg(
        trades_count=("pnl_usd", "count"),
        net_profit_usd=("pnl_usd", "sum"),
        wins=("win", lambda s: sum(s)),
        losses=("win", lambda s: len(s) - sum(s)),
    ).reset_index()
    monthly_stats["win_rate_pct"] = (monthly_stats["wins"] / monthly_stats["trades_count"] * 100).round(1)
    monthly_stats["net_profit_ngn"] = (monthly_stats["net_profit_usd"] * naira_rate).round(0)
    avg_trades_per_month = len(trades_df) / 60.0
    avg_profit_per_month = trades_df["pnl_usd"].sum() / 60.0
    
    # 4. Year-by-Year Breakdown for 5 Years
    yearly_breakdown = []
    cum = 0.0
    for yr, y_df in trades_df.groupby("year"):
        n_y = len(y_df)
        w_y = y_df["win"].sum()
        wr_y = (w_y / n_y) * 100
        pnl_y = y_df["pnl_usd"].sum()
        trader_y = pnl_y * trader_split
        cum += trader_y
        yearly_breakdown.append({
            "year": f"{yr}",
            "trades_in_year": n_y,
            "avg_trades_per_month": round(n_y / 12.0, 1),
            "avg_trades_per_day": round(n_y / 252.0, 2),
            "win_rate_pct": round(wr_y, 1),
            "gross_profit_usd": round(pnl_y, 2),
            "trader_85_usd": round(trader_y, 2),
            "trader_85_ngn": round(trader_y * naira_rate, 0),
            "cumulative_payout_usd": round(cum, 2)
        })
        
    total_trades = len(trades_df)
    total_wins = trades_df["win"].sum()
    overall_win_rate = (total_wins / total_trades) * 100
    total_pnl = trades_df["pnl_usd"].sum()
    avg_hold = trades_df["days_held"].mean()
    
    report = {
        "strategy": "Option A: Quantitative Sniper Scalper (SPY & QQQ)",
        "total_trades": total_trades,
        "overall_win_rate": round(overall_win_rate, 1),
        "total_pnl_usd": round(total_pnl, 2),
        "avg_hold_days": round(avg_hold, 1),
        "daily_stats": daily_stats.tail(20).to_dict(orient="records"),
        "weekly_stats": weekly_stats.tail(15).to_dict(orient="records"),
        "monthly_stats": monthly_stats.tail(12).to_dict(orient="records"),
        "yearly_breakdown": yearly_breakdown,
        "averages": {
            "trades_per_day": round(avg_trades_per_day, 2),
            "trades_per_week": round(avg_trades_per_week, 1),
            "trades_per_month": round(avg_trades_per_month, 1),
            "profit_per_day_usd": round(avg_profit_per_day, 2),
            "profit_per_week_usd": round(avg_profit_per_week, 2),
            "profit_per_month_usd": round(avg_profit_per_month, 2),
            "trader_monthly_takehome_usd": round(avg_profit_per_month * trader_split, 2),
            "trader_monthly_takehome_ngn": round(avg_profit_per_month * trader_split * naira_rate, 0)
        }
    }
    
    with open(ROOT_DIR / "results" / "sniper_option_a_exact_ledger.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
        
    print("\n" + "=" * 80)
    print("OPTION A QUANT SNIPER 5-YEAR EXACT LEDGER:")
    print("=" * 80)
    print(f"Total Trades: {total_trades} | Win Rate: {overall_win_rate:.1f}% | 5Y Net PnL: ${total_pnl:,.2f}")
    print(f"Daily: {avg_trades_per_day:.2f} trades/day, ${avg_profit_per_day:.2f}/day")
    print(f"Weekly: {avg_trades_per_week:.1f} trades/wk, ${avg_profit_per_week:.2f}/wk")
    print(f"Monthly: {avg_trades_per_month:.1f} trades/mo, ${avg_profit_per_month:.2f}/mo")

if __name__ == "__main__":
    run_quant_sniper_ledger()
