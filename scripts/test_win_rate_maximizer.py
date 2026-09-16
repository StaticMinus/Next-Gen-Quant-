"""
Win Rate Maximizer: Finding 80% to 85%+ Setups on SPY & QQQ
===========================================================
Tests different exit rules (mean reversion, fixed profit targets +0.75%, +1.0%, +1.5%),
filters (RSI, moving averages, Bollinger bands), and stop loss levels across 10 years.
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.strategies.scalper import ScalperStrategy
from src.strategies.base import _get_close

def run_maximizer():
    cache_dir = Path("cache")
    df_spy = pd.read_csv(cache_dir / "SPY_10y.csv", index_col=0, parse_dates=True)
    df_qqq = pd.read_csv(cache_dir / "QQQ_10y.csv", index_col=0, parse_dates=True)

    c_spy = _get_close(df_spy)
    c_qqq = _get_close(df_qqq)

    contract_mult = 10.0
    comm = 1.50

    results = []

    # Grid search across exit and entry variations
    configs = [
        # 1. Faster Profit Taking (Scalp targets: exit at +0.75%, +1.0%, +1.5% or Mean)
        {"name": "Quick-Target Scalper (+0.8% Target, 5d Mean)", "window": 5, "num_std": 1.25, "tp_pct": 0.008, "sl_pct": 0.025, "max_hold": 4},
        {"name": "Quick-Target Scalper (+1.0% Target, 5d Mean)", "window": 5, "num_std": 1.25, "tp_pct": 0.010, "sl_pct": 0.030, "max_hold": 5},
        {"name": "Asymmetric Scalp (+1.2% Target, 5d Mean)", "window": 5, "num_std": 1.25, "tp_pct": 0.012, "sl_pct": 0.030, "max_hold": 5},
        
        # 2. Deeper Dips with Mean Exit (1.35s, 1.40s, 1.50s)
        {"name": "Selective Dip Scalper (1.35σ Dip, Mean Exit)", "window": 5, "num_std": 1.35, "tp_pct": None, "sl_pct": 0.030, "max_hold": 5},
        {"name": "High-Conviction Dip Scalper (1.40σ Dip, Mean Exit)", "window": 5, "num_std": 1.40, "tp_pct": None, "sl_pct": 0.030, "max_hold": 5},
        {"name": "Institutional Deep Dip (1.50σ Dip, Mean Exit)", "window": 5, "num_std": 1.50, "tp_pct": None, "sl_pct": 0.030, "max_hold": 5},

        # 3. Longer Lookback Bands (10-Day, 15-Day, 20-Day Bollinger)
        {"name": "10-Day Mean Reversion (10d, 1.5σ Band)", "window": 10, "num_std": 1.50, "tp_pct": None, "sl_pct": 0.030, "max_hold": 7},
        {"name": "15-Day Mean Reversion (15d, 1.75σ Band)", "window": 15, "num_std": 1.75, "tp_pct": None, "sl_pct": 0.030, "max_hold": 8},
        {"name": "Classic 20-Day Bollinger (20d, 2.0σ Band)", "window": 20, "num_std": 2.00, "tp_pct": None, "sl_pct": 0.030, "max_hold": 10},

        # 4. Trend-Filtered (Above 50 SMA / Above 200 SMA)
        {"name": "Trend-Aligned Dip (5d, 1.25σ + Price > 50 SMA)", "window": 5, "num_std": 1.25, "tp_pct": None, "sl_pct": 0.030, "max_hold": 5, "sma_filter": 50},
        {"name": "Macro Trend Dip (5d, 1.25σ + Price > 200 SMA)", "window": 5, "num_std": 1.25, "tp_pct": None, "sl_pct": 0.030, "max_hold": 5, "sma_filter": 200},
        {"name": "Golden Trend Deep Dip (1.40σ + Price > 200 SMA)", "window": 5, "num_std": 1.40, "tp_pct": None, "sl_pct": 0.030, "max_hold": 5, "sma_filter": 200},
    ]

    for asset_name, df, c in [("SPY", df_spy, c_spy), ("QQQ", df_qqq, c_qqq)]:
        for cfg in configs:
            w = cfg["window"]
            n_std = cfg["num_std"]
            tp = cfg.get("tp_pct")
            sl = cfg.get("sl_pct", 0.03)
            max_h = cfg.get("max_hold", 5)
            sma_f = cfg.get("sma_filter")

            mean = c.rolling(w).mean()
            std = c.rolling(w).std()
            lower = mean - n_std * std

            entry_condition = (c <= lower)
            if sma_f:
                sma_series = c.rolling(sma_f).mean()
                entry_condition = entry_condition & (c > sma_series)

            trades = []
            in_pos = False
            entry_p = 0.0
            entry_dt = None
            bars = 0

            for dt in c.index:
                p = float(c.loc[dt])
                is_entry = bool(entry_condition.loc[dt]) if dt in entry_condition.index else False
                cur_mean = float(mean.loc[dt]) if dt in mean.index else p

                if not in_pos:
                    if is_entry:
                        in_pos = True
                        entry_p = p
                        entry_dt = dt
                        bars = 0
                else:
                    bars += 1
                    target_hit = (p >= (entry_p * (1.0 + tp))) if tp else (p >= cur_mean)
                    stop_hit = p <= (entry_p * (1.0 - sl))
                    time_stop = bars >= max_h

                    if target_hit or stop_hit or time_stop:
                        exit_p = p
                        pnl = (exit_p - entry_p) * contract_mult - (comm * 2)
                        trades.append({
                            "entry_dt": entry_dt,
                            "exit_dt": dt,
                            "pnl": pnl,
                            "bars": bars,
                            "win": pnl > 0
                        })
                        in_pos = False

            if not trades:
                continue

            tot_t = len(trades)
            wins = sum(1 for t in trades if t["win"])
            wr = (wins / tot_t) * 100.0
            tot_pnl = sum(t["pnl"] for t in trades)
            t_per_yr = tot_t / (len(c) / 252.0)

            # Max Drawdown
            cum = np.cumsum([t["pnl"] for t in trades])
            peak = np.maximum.accumulate(cum)
            dd = peak - cum
            max_dd = np.max(dd) if len(dd) > 0 else 0.0

            results.append({
                "name": cfg["name"],
                "asset": asset_name,
                "win_rate": round(wr, 1),
                "trades": tot_t,
                "trades_per_yr": round(t_per_yr, 1),
                "trades_per_mo": round(t_per_yr / 12.0, 2),
                "tot_pnl": round(tot_pnl, 2),
                "max_dd": round(max_dd, 2),
            })

    df_out = pd.DataFrame(results).sort_values(by="win_rate", ascending=False)
    
    print("\n" + "=" * 115)
    print("           WIN RATE MAXIMIZER: TOP HIGH WIN RATE STRATEGIES (10 YEARS: 2016 - 2026)")
    print("=" * 115)
    print(f"{'Strategy Configuration':<48} {'Asset':<6} {'Win Rate':<10} {'Trades':<8} {'Tr/Mo':<8} {'Total PnL':<12} {'Max DD':<10}")
    print("-" * 115)
    for _, r in df_out.iterrows():
        star = "🌟 80%+" if r["win_rate"] >= 80.0 else ("✨ 85%+" if r["win_rate"] >= 85.0 else "")
        print(f"{r['name']:<48} {r['asset']:<6} {r['win_rate']:>5.1f}%     {r['trades']:<8} {r['trades_per_mo']:<8.2f} ${r['tot_pnl']:<11,.2f} ${r['max_dd']:<9,.2f} {star}")
    print("=" * 115)

if __name__ == "__main__":
    run_maximizer()
