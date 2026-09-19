#!/usr/bin/env python3
"""
scripts/backtest_m15_m30_deep_dive.py
────────────────────────────────────────────────────────────────────────────
Comprehensive Intraday Backtesting Sweep for David:
Comparing 15-Minute (M15) vs 30-Minute (M30) Mean-Reversion Scalpers
Across Fab-4 US Indices (SPY, QQQ, DIA, IWM) with Exact cTrader Contract Multipliers

Focus:
- "Get In and Get Out" (Fast turnover: 30m - 3h)
- 0% Overnight Risk (Strict EOD Flatten at 15:45 EST)
- Time-Decay Profit Banking (Take money off table when in profit)
- Prop Firm Safety (-$180 daily / -$360 max trailing cushion)
"""

import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import json
import numpy as np
import pandas as pd
import yfinance as yf

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ASSETS = [
    # symbol, cTrader index price proxy, 0.1 lot contract value factor
    {"ticker": "SPY", "csym": "SPX500", "notional_usd": 765.0,  "spread_usd": 0.08},
    {"ticker": "QQQ", "csym": "NDX100", "notional_usd": 2966.0, "spread_usd": 0.22},
    {"ticker": "DIA", "csym": "US30",   "notional_usd": 5173.0, "spread_usd": 0.28},
    {"ticker": "IWM", "csym": "US2000", "notional_usd": 288.0,  "spread_usd": 0.08},
]

def load_data(interval: str):
    data = {}
    for a in ASSETS:
        tk = a["ticker"]
        cache_p = Path(f"cache/{tk}_{interval}_30d.parquet")
        if cache_p.exists():
            df = pd.read_parquet(cache_p)
        else:
            df = yf.download(tk, period="1mo", interval=interval, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0].lower() for col in df.columns]
            else:
                df.columns = [str(c).lower() for c in df.columns]
            cache_p.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(cache_p)
        data[tk] = df
    return data

def run_simulation(data, interval_name, bar_mins, window, num_std, max_hold_bars, 
                   sl_pct, tp_pct, exit_at_mean, time_decay_bars=0, time_decay_min_profit=0.0010):
    trades = []
    
    for a in ASSETS:
        tk = a["ticker"]
        df_raw = data.get(tk)
        if df_raw is None or len(df_raw) < 30:
            continue
            
        df = df_raw.copy()
        df["mean"] = df["close"].rolling(window).mean()
        df["std"] = df["close"].rolling(window).std()
        df["lower"] = df["mean"] - num_std * df["std"]
        df["sma50"] = df["close"].rolling(min(50, len(df)//2)).mean()
        
        in_pos = False
        entry_p = 0.0
        entry_time = None
        bars_held = 0
        notional = a["notional_usd"]
        spread = a["spread_usd"]
        
        for j in range(max(window, 50), len(df)):
            t = df.index[j]
            c = float(df["close"].iloc[j])
            h = float(df["high"].iloc[j])
            l = float(df["low"].iloc[j])
            o = float(df["open"].iloc[j])
            m_val = float(df["mean"].iloc[j])
            low_b = float(df["lower"].iloc[j])
            trend = float(df["sma50"].iloc[j])
            
            # Session constraints (US Market Hours): 10:00 EST to 15:45 EST
            is_entry_window = (t.hour >= 10 and (t.hour < 14 or (t.hour == 14 and t.minute <= 30)))
            is_eod_flatten = (t.hour == 15 and t.minute >= 45)
            
            if in_pos:
                bars_held += 1
                curr_ret = (c - entry_p) / entry_p
                sl_p = entry_p * (1.0 - sl_pct)
                tp_p = entry_p * (1.0 + tp_pct)
                
                # Check Exits
                sl_hit = l <= sl_p
                tp_hit = (h >= tp_p) or (exit_at_mean and h >= m_val and (m_val > entry_p))
                time_decay_hit = (time_decay_bars > 0 and bars_held >= time_decay_bars and curr_ret >= time_decay_min_profit)
                timeout = (bars_held >= max_hold_bars) or is_eod_flatten
                
                if sl_hit:
                    ret = -sl_pct
                    pnl = (ret * notional) - spread
                    trades.append({
                        "ticker": tk, "symbol": a["csym"], "in": entry_time, "out": t,
                        "mins": bars_held * bar_mins, "pnl": pnl, "win": False, "reason": "SL",
                        "ret_pct": ret * 100
                    })
                    in_pos = False
                elif tp_hit:
                    eff_target = (m_val - entry_p) / entry_p if (exit_at_mean and m_val > entry_p) else tp_pct
                    ret = max(0.0015, min(tp_pct, eff_target))
                    pnl = (ret * notional) - spread
                    trades.append({
                        "ticker": tk, "symbol": a["csym"], "in": entry_time, "out": t,
                        "mins": bars_held * bar_mins, "pnl": pnl, "win": pnl > 0, "reason": "TP",
                        "ret_pct": ret * 100
                    })
                    in_pos = False
                elif time_decay_hit:
                    ret = curr_ret
                    pnl = (ret * notional) - spread
                    trades.append({
                        "ticker": tk, "symbol": a["csym"], "in": entry_time, "out": t,
                        "mins": bars_held * bar_mins, "pnl": pnl, "win": pnl > 0, "reason": "TIME_DECAY_PROFIT",
                        "ret_pct": ret * 100
                    })
                    in_pos = False
                elif timeout:
                    ret = curr_ret
                    pnl = (ret * notional) - spread
                    trades.append({
                        "ticker": tk, "symbol": a["csym"], "in": entry_time, "out": t,
                        "mins": bars_held * bar_mins, "pnl": pnl, "win": pnl > 0, "reason": "EOD_OR_MAX_HOLD",
                        "ret_pct": ret * 100
                    })
                    in_pos = False
            else:
                if not is_entry_window:
                    continue
                # Long-only dip: Trend filter (c > trend) and dip below lower band
                if c > trend and l <= low_b:
                    in_pos = True
                    entry_p = min(o, low_b) if o < low_b else low_b
                    entry_time = t
                    bars_held = 0
                    
    # Compute aggregate statistics
    df_res = pd.DataFrame(trades)
    n = len(df_res)
    if n == 0:
        return {"trades": 0, "win_rate": 0.0, "net_pnl": 0.0, "pf": 0.0, "avg_hold_mins": 0.0, 
                "avg_hold_hrs": 0.0, "max_hold_hrs": 0.0, "max_dd": 0.0, "trades_per_week": 0.0}
        
    wins = df_res[df_res["win"]]
    losses = df_res[~df_res["win"]]
    win_rate = (len(wins) / n) * 100.0
    net_pnl = df_res["pnl"].sum()
    gross_win = wins["pnl"].sum()
    gross_loss = abs(losses["pnl"].sum())
    pf = (gross_win / gross_loss) if gross_loss > 0 else 999.0
    avg_mins = df_res["mins"].mean()
    max_mins = df_res["mins"].max()
    
    # Drawdown tracking
    df_res["cum_pnl"] = df_res["pnl"].cumsum()
    peak = df_res["cum_pnl"].cummax()
    dd = peak - df_res["cum_pnl"]
    max_dd = dd.max()
    
    trades_per_day = n / 22.0 # ~22 trading days in 1 month
    trades_per_week = trades_per_day * 5.0
    
    return {
        "trades": n,
        "trades_per_week": round(trades_per_week, 1),
        "win_rate": round(win_rate, 1),
        "net_pnl": round(net_pnl, 2),
        "pf": round(pf, 2),
        "avg_hold_mins": round(avg_mins, 1),
        "avg_hold_hrs": round(avg_mins / 60.0, 1),
        "max_hold_hrs": round(max_mins / 60.0, 1),
        "max_dd": round(max_dd, 2),
        "win_count": len(wins),
        "loss_count": len(losses)
    }

def main():
    print("=" * 125)
    print("DOWNLOADING / LOADING 30-DAY INTRADAY DATA FOR FAB-4 (SPY, QQQ, DIA, IWM)...")
    print("=" * 125)
    data_15m = load_data("15m")
    data_30m = load_data("30m")
    print("Data loaded successfully.")
    
    scenarios = [
        # ── 15-Minute (M15) Scenarios ──
        {
            "name": "M15 Scalper A: Rapid Turnover (+0.25% TP, 0.40% SL, max 1.5h, Time-Decay at 45m)",
            "interval_data": data_15m, "name_tag": "M15", "bar_mins": 15,
            "window": 8, "num_std": 1.50, "max_hold_bars": 6, "sl_pct": 0.0040, "tp_pct": 0.0025,
            "exit_at_mean": True, "time_decay_bars": 3, "time_decay_min_profit": 0.0010
        },
        {
            "name": "M15 Scalper B: Balanced Mean-Reversion (+0.35% TP, 0.50% SL, max 2.0h, Time-Decay at 1h)",
            "interval_data": data_15m, "name_tag": "M15", "bar_mins": 15,
            "window": 10, "num_std": 1.75, "max_hold_bars": 8, "sl_pct": 0.0050, "tp_pct": 0.0035,
            "exit_at_mean": True, "time_decay_bars": 4, "time_decay_min_profit": 0.0012
        },
        {
            "name": "M15 Scalper C: High-Conviction Dip (+0.45% TP, 0.55% SL, max 2.5h, 2.0σ Dip)",
            "interval_data": data_15m, "name_tag": "M15", "bar_mins": 15,
            "window": 12, "num_std": 2.00, "max_hold_bars": 10, "sl_pct": 0.0055, "tp_pct": 0.0045,
            "exit_at_mean": True, "time_decay_bars": 5, "time_decay_min_profit": 0.0015
        },
        
        # ── 30-Minute (M30) Scenarios ──
        {
            "name": "M30 Sniper A: Fast Intraday (+0.35% TP, 0.50% SL, max 2.5h, Time-Decay at 1.5h)",
            "interval_data": data_30m, "name_tag": "M30", "bar_mins": 30,
            "window": 8, "num_std": 1.50, "max_hold_bars": 5, "sl_pct": 0.0050, "tp_pct": 0.0035,
            "exit_at_mean": True, "time_decay_bars": 3, "time_decay_min_profit": 0.0012
        },
        {
            "name": "M30 Sniper B: Balanced Sniper (+0.50% TP, 0.70% SL, max 3.5h, Time-Decay at 2h)",
            "interval_data": data_30m, "name_tag": "M30", "bar_mins": 30,
            "window": 10, "num_std": 1.75, "max_hold_bars": 7, "sl_pct": 0.0070, "tp_pct": 0.0050,
            "exit_at_mean": True, "time_decay_bars": 4, "time_decay_min_profit": 0.0015
        },
        {
            "name": "M30 Sniper C: Institutional 2.0σ (+0.60% TP, 0.80% SL, max 4.0h, Time-Decay at 2.5h)",
            "interval_data": data_30m, "name_tag": "M30", "bar_mins": 30,
            "window": 12, "num_std": 2.00, "max_hold_bars": 8, "sl_pct": 0.0080, "tp_pct": 0.0060,
            "exit_at_mean": True, "time_decay_bars": 5, "time_decay_min_profit": 0.0020
        },
    ]
    
    results = []
    print("\n" + "=" * 135)
    print(f"{'Configuration / Strategy Scenario':<55} | {'WinRate':<7} | {'Trades':<6} | {'Tr/Wk':<5} | {'AvgHold':<7} | {'MaxHold':<7} | {'MaxDD':<7} | {'Net PnL':<9} | {'PF':<5}")
    print("=" * 135)
    
    for sc in scenarios:
        res = run_simulation(
            data=sc["interval_data"],
            interval_name=sc["name_tag"],
            bar_mins=sc["bar_mins"],
            window=sc["window"],
            num_std=sc["num_std"],
            max_hold_bars=sc["max_hold_bars"],
            sl_pct=sc["sl_pct"],
            tp_pct=sc["tp_pct"],
            exit_at_mean=sc["exit_at_mean"],
            time_decay_bars=sc["time_decay_bars"],
            time_decay_min_profit=sc["time_decay_min_profit"]
        )
        res["scenario"] = sc["name"]
        results.append(res)
        pnl_str = f"+${res['net_pnl']:<8.2f}" if res['net_pnl'] >= 0 else f"-${abs(res['net_pnl']):<8.2f}"
        print(
            f"{sc['name'][:55]:<55} | {res['win_rate']:>5.1f}% | {res['trades']:<6} | {res['trades_per_week']:<5} | "
            f"{res['avg_hold_hrs']:>4.1f}h  | {res['max_hold_hrs']:>4.1f}h  | ${res['max_dd']:<6.2f} | {pnl_str} | {res['pf']:>4.2f}"
        )
        
    print("=" * 135)
    
    out_file = Path("results/m15_m30_deep_dive_report.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n[+] Detailed report exported to: {out_file}")

if __name__ == "__main__":
    main()
