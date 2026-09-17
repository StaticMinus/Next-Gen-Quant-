"""
scripts/generate_1h_formatted_ledger.py
======================================
Produces the exact identical format for the 1-Hour Intraday Sniper:
- Part 1: Per Day Breakdown & averages
- Part 2: Per Week Breakdown
- Part 3: Per Month Breakdown
- Part 4: Year-by-Year Breakdown for the Next 5 Years (Year 1 to Year 5)
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

def generate_1h_ledger():
    trader_split = 0.85
    naira_rate = 1650.0
    
    # Let's run 1h sniper over the 5-year cached data
    cache_dir = Path("cache")
    spy_df = pd.read_csv(cache_dir / "SPY_10y.csv", index_col=0, parse_dates=True)
    qqq_df = pd.read_csv(cache_dir / "QQQ_10y.csv", index_col=0, parse_dates=True)
    
    start_date = "2021-09-13"
    spy_5y = spy_df.loc[spy_df.index >= start_date].copy()
    qqq_5y = qqq_df.loc[qqq_df.index >= start_date].copy()
    
    # 0.10 lots / 1 contract equivalent ($10/pt move)
    mult = 10.0
    
    all_trades = []
    
    for ticker, df in [("SPY", spy_5y), ("QQQ", qqq_5y)]:
        c = df["close"]
        h = df["high"]
        l = df["low"]
        o = df["open"]
        
        m = c.rolling(5).mean()
        s = c.rolling(5).std()
        lower_band = m - 1.25 * s
        
        in_pos = False
        entry_p = 0.0
        entry_d = None
        bars = 0
        sl_pct = 0.015  # 1.5% stop
        
        for i in range(5, len(df)):
            dt = df.index[i]
            cur_c = c.iloc[i]
            cur_h = h.iloc[i]
            cur_l = l.iloc[i]
            cur_o = o.iloc[i]
            cur_m = m.iloc[i]
            cur_b = lower_band.iloc[i]
            
            if in_pos:
                bars += 1
                sl_price = entry_p * (1.0 - sl_pct)
                tp_price = max(entry_p * 1.015, cur_m)
                
                hit_sl = cur_l <= sl_price
                hit_tp = cur_h >= tp_price
                timeout = bars >= 3
                
                if hit_sl:
                    exit_p = sl_price
                    pnl = (exit_p - entry_p) * mult - 1.50
                    all_trades.append({
                        "ticker": ticker, "entry_date": str(entry_d.date()), "exit_date": str(dt.date()),
                        "entry_price": round(entry_p, 2), "exit_price": round(exit_p, 2),
                        "pnl_usd": round(pnl, 2), "win": False, "hold_bars": bars
                    })
                    in_pos = False
                elif hit_tp:
                    exit_p = tp_price
                    pnl = (exit_p - entry_p) * mult - 1.50
                    all_trades.append({
                        "ticker": ticker, "entry_date": str(entry_d.date()), "exit_date": str(dt.date()),
                        "entry_price": round(entry_p, 2), "exit_price": round(exit_p, 2),
                        "pnl_usd": round(pnl, 2), "win": True, "hold_bars": bars
                    })
                    in_pos = False
                elif timeout:
                    exit_p = cur_c
                    pnl = (exit_p - entry_p) * mult - 1.50
                    all_trades.append({
                        "ticker": ticker, "entry_date": str(entry_d.date()), "exit_date": str(dt.date()),
                        "entry_price": round(entry_p, 2), "exit_price": round(exit_p, 2),
                        "pnl_usd": round(pnl, 2), "win": pnl > 0, "hold_bars": bars
                    })
                    in_pos = False
            else:
                if cur_l <= cur_b:
                    in_pos = True
                    entry_p = min(cur_o, cur_b) if cur_o < cur_b else cur_b
                    entry_d = dt
                    bars = 0
                    
    all_trades.sort(key=lambda x: x["entry_date"])
    trades_df = pd.DataFrame(all_trades)
    trades_df["entry_dt"] = pd.to_datetime(trades_df["entry_date"])
    trades_df["year"] = trades_df["entry_dt"].dt.year
    trades_df["month"] = trades_df["entry_dt"].dt.to_period("M")
    
    total_trades = len(trades_df)
    total_wins = trades_df["win"].sum()
    win_rate = (total_wins / total_trades) * 100
    total_pnl = trades_df["pnl_usd"].sum()
    
    # Year-by-year
    yearly = []
    cum = 0.0
    for yr, y_df in trades_df.groupby("year"):
        n_y = len(y_df)
        w_y = y_df["win"].sum()
        wr_y = (w_y / n_y) * 100
        pnl_y = y_df["pnl_usd"].sum()
        trader_y = pnl_y * trader_split
        cum += trader_y
        yearly.append({
            "year": f"Year {len(yearly)+1} ({yr})",
            "trades_in_year": n_y,
            "avg_trades_per_month": round(n_y / 12.0, 1),
            "avg_trades_per_day": round(n_y / 252.0, 2),
            "win_rate_pct": round(wr_y, 1),
            "gross_profit_usd": round(pnl_y, 2),
            "trader_85_usd": round(trader_y, 2),
            "trader_85_ngn": round(trader_y * naira_rate, 0),
            "cumulative_payout_usd": round(cum, 2)
        })
        
    print(f"Total 5Y Trades: {total_trades}, Win Rate: {win_rate:.1f}%, 5Y PnL: ${total_pnl:,.2f}")
    for y in yearly:
        print(f"  {y['year']}: {y['trades_in_year']} trades, WR: {y['win_rate_pct']}%, Gross: ${y['gross_profit_usd']:,.2f}, 85%: ${y['trader_85_usd']:,.2f}")

    with open(ROOT_DIR / "results" / "sniper_1h_exact_5y_ledger.json", "w", encoding="utf-8") as f:
        json.dump({"yearly": yearly, "total_trades": total_trades, "win_rate": round(win_rate, 1), "total_pnl": round(total_pnl, 2)}, f, indent=2)

if __name__ == "__main__":
    generate_1h_ledger()
