"""
Analysis: 1-Month Challenge Feasibility & Tiered Ultra-Dip Booster Evaluation
=============================================================================
1. Analyzes monthly profit distribution of Dual-Asset Scalper to determine probability of passing in 1 month.
2. Evaluates adding a "Tier-2 Ultra Dip Booster" (1.75σ dip) on top of the base Dual-Asset Scalper (1.25σ dip).
"""

import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.strategies.base import _get_close

def run_analysis():
    with open("results/spy_vs_dual_scalper_10year_monthly.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    monthly = data["monthly_records"]
    df_m = pd.DataFrame(monthly)

    print("=" * 80)
    print("        PART 1: CAN YOU PASS IN 1 MONTH? ($600 TARGET / 10% ON $6,000)")
    print("=" * 80)

    total_months = len(df_m)
    p_600 = df_m[df_m["dual_pnl"] >= 600.0]
    p_400 = df_m[df_m["dual_pnl"] >= 400.0]
    p_300 = df_m[df_m["dual_pnl"] >= 300.0]
    p_200 = df_m[df_m["dual_pnl"] >= 200.0]

    print(f"Total Historical Months Analyzed: {total_months} months (10 Years)")
    print(f"Months making >= $600 in ONE month: {len(p_600)} months ({len(p_600)/total_months*100:.1f}%)")
    print(f"Months making >= $400 in ONE month: {len(p_400)} months ({len(p_400)/total_months*100:.1f}%)")
    print(f"Months making >= $300 in ONE month: {len(p_300)} months ({len(p_300)/total_months*100:.1f}%)")
    print(f"Months making >= $200 in ONE month: {len(p_200)} months ({len(p_200)/total_months*100:.1f}%)")

    # Rolling 2-month and 3-month windows
    rolling_2m = df_m["dual_pnl"].rolling(2).sum().dropna()
    rolling_3m = df_m["dual_pnl"].rolling(3).sum().dropna()

    p_600_2m = (rolling_2m >= 600.0).sum()
    p_600_3m = (rolling_3m >= 600.0).sum()

    print(f"\nRolling 2-Month Windows reaching >= $600: {p_600_2m}/{len(rolling_2m)} ({p_600_2m/len(rolling_2m)*100:.1f}%)")
    print(f"Rolling 3-Month Windows reaching >= $600: {p_600_3m}/{len(rolling_3m)} ({p_600_3m/len(rolling_3m)*100:.1f}%)")

    print("\nTop Months with Massive Returns:")
    for _, r in p_400.iterrows():
        print(f"  {r['month']}: +${r['dual_pnl']:,.2f} ({r['dual_trades']} trades)")

    print("\n" + "=" * 80)
    print("        PART 2: TIERED ULTRA-DIP BOOSTER (1.25σ BASE + 1.75σ BOOSTER)")
    print("=" * 80)

    # Now let's simulate the Tiered Layer:
    # Base Layer: 1.25σ dip (standard 0.10 lot / 10 units)
    # Booster Layer: 1.75σ dip (extra 0.10 lot / 10 units added when market dips extremely)
    cache_dir = Path("cache")
    c_spy = _get_close(pd.read_csv(cache_dir / "SPY_10y.csv", index_col=0, parse_dates=True))
    c_qqq = _get_close(pd.read_csv(cache_dir / "QQQ_10y.csv", index_col=0, parse_dates=True))

    contract_mult = 10.0
    comm = 1.50

    def simulate_tiered(c_series, asset_name):
        m5 = c_series.rolling(5).mean()
        s5 = c_series.rolling(5).std()
        l_base = m5 - 1.25 * s5
        l_boost = m5 - 1.75 * s5

        trades = []
        in_base = False
        in_boost = False
        base_p = 0.0
        boost_p = 0.0
        base_dt = None
        boost_dt = None
        bars_base = 0
        bars_boost = 0

        for dt in c_series.index:
            p = float(c_series.loc[dt])
            mean_val = float(m5.loc[dt])
            base_trigger = (p <= float(l_base.loc[dt]))
            boost_trigger = (p <= float(l_boost.loc[dt]))

            # Base entry
            if not in_base and base_trigger:
                in_base = True
                base_p = p
                base_dt = dt
                bars_base = 0

            # Booster entry
            if not in_boost and boost_trigger:
                in_boost = True
                boost_p = p
                boost_dt = dt
                bars_boost = 0

            # Management
            if in_base:
                bars_base += 1
                if p >= mean_val or p <= (base_p * 0.97) or bars_base >= 5:
                    pnl = (p - base_p) * contract_mult - (comm * 2)
                    trades.append({"type": "BASE", "asset": asset_name, "entry": base_p, "exit": p, "pnl": pnl, "win": pnl > 0})
                    in_base = False

            if in_boost:
                bars_boost += 1
                if p >= mean_val or p <= (boost_p * 0.97) or bars_boost >= 5:
                    pnl = (p - boost_p) * contract_mult - (comm * 2)
                    trades.append({"type": "BOOSTER", "asset": asset_name, "entry": boost_p, "exit": p, "pnl": pnl, "win": pnl > 0})
                    in_boost = False

        return trades

    t_spy = simulate_tiered(c_spy, "SPY")
    t_qqq = simulate_tiered(c_qqq, "QQQ")
    all_t = t_spy + t_qqq

    base_trades = [t for t in all_t if t["type"] == "BASE"]
    boost_trades = [t for t in all_t if t["type"] == "BOOSTER"]

    print(f"Base Layer (1.25σ) Trades:      {len(base_trades)} trades (Win Rate: {sum(1 for t in base_trades if t['win'])/len(base_trades)*100:.1f}%)")
    print(f"Base Layer Total Profit:        ${sum(t['pnl'] for t in base_trades):,.2f}")
    print(f"Booster Layer (1.75σ) Trades:   {len(boost_trades)} trades (Win Rate: {sum(1 for t in boost_trades if t['win'])/len(boost_trades)*100:.1f}%)")
    print(f"Booster Layer Total Profit:     +${sum(t['pnl'] for t in boost_trades):,.2f}")
    print(f"COMBINED Total Profit (10 Yrs): ${sum(t['pnl'] for t in all_t):,.2f}")
    print(f"Total Trades (10 Yrs):          {len(all_t)} ({len(all_t)/120:.2f} trades/month)")
    print(f"Overall Combined Win Rate:      {sum(1 for t in all_t if t['win'])/len(all_t)*100:.1f}%")
    print("=" * 80)

if __name__ == "__main__":
    run_analysis()
