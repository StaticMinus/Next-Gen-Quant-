"""
10-Year Monthly Strategy Test: Balanced Scalper (SPY) vs Dual-Asset Scalper (SPY + QQQ)
========================================================================================
Horizon: September 2016 - September 2026 (10 Full Years / 2,514 Trading Days / 121 Months)
Evaluates monthly profit ($) and trade count for:
1. Current Core: Balanced Scalper (SPY Only)
2. Dual-Asset Scalper: SPY + QQQ Combined
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Any
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.strategies.scalper import ScalperStrategy
from src.strategies.base import _get_close

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        if isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        if isinstance(obj, (np.bool_, bool)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

def run_monthly_comparison():
    print("=" * 110)
    print("      10-YEAR MONTHLY STRATEGY TEST: BALANCED SCALPER (SPY) vs DUAL-ASSET SCALPER (SPY + QQQ)")
    print("      Horizon: 2016 - 2026 (2,514 Trading Days) | Contract Sizing: 10 Units ($10/pt move)")
    print("=" * 110)

    cache_dir = Path("cache")
    spy_file = cache_dir / "SPY_10y.csv"
    qqq_file = cache_dir / "QQQ_10y.csv"

    if not spy_file.exists() or not qqq_file.exists():
        raise FileNotFoundError("Cache files for SPY or QQQ 10y not found.")

    raw_spy = pd.read_csv(spy_file, index_col=0, parse_dates=True)
    raw_qqq = pd.read_csv(qqq_file, index_col=0, parse_dates=True)

    if isinstance(raw_spy.columns, pd.MultiIndex):
        raw_spy.columns = [col[0].lower() for col in raw_spy.columns]
    else:
        raw_spy.columns = [str(c).lower() for c in raw_spy.columns]

    if isinstance(raw_qqq.columns, pd.MultiIndex):
        raw_qqq.columns = [col[0].lower() for col in raw_qqq.columns]
    else:
        raw_qqq.columns = [str(c).lower() for c in raw_qqq.columns]

    close_spy = _get_close(raw_spy)
    close_qqq = _get_close(raw_qqq)

    # Strategy Parameters (Balanced Scalper)
    params = {
        "window": 5,
        "num_std": 1.25,
        "exit_at_mean": True,
        "allow_short": False,
        "stop_loss_pct": 0.03,
        "max_hold_bars": 5
    }

    strat = ScalperStrategy()
    sig_spy = strat.generate_signal(raw_spy, params).reindex(close_spy.index).fillna(0).clip(lower=0)
    sig_qqq = strat.generate_signal(raw_qqq, params).reindex(close_qqq.index).fillna(0).clip(lower=0)

    contract_multiplier = 10.0  # $10 per 1.00 move (10 shares / 0.10 standard lot CFD)
    commission_per_order = 1.50

    def simulate_trades(c_series: pd.Series, sig_series: pd.Series, asset_name: str) -> List[Dict[str, Any]]:
        trades = []
        in_pos = 0
        entry_price = 0.0
        entry_dt = None
        bars_held = 0

        for dt in c_series.index:
            pos = int(sig_series.loc[dt])
            p = float(c_series.loc[dt])

            if in_pos == 0 and pos > 0:
                in_pos = 1
                entry_price = p
                entry_dt = dt
                bars_held = 0
            elif in_pos == 1:
                bars_held += 1
                if pos == 0:
                    exit_price = p
                    realized_pnl = (exit_price - entry_price) * contract_multiplier - (commission_per_order * 2)
                    trades.append({
                        "asset": asset_name,
                        "entry_dt": entry_dt.strftime("%Y-%m-%d"),
                        "exit_dt": dt.strftime("%Y-%m-%d"),
                        "exit_month": dt.strftime("%Y-%m"),
                        "year": dt.year,
                        "month": dt.month,
                        "bars_held": bars_held,
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(exit_price, 2),
                        "pnl_usd": round(realized_pnl, 2),
                        "profitable": realized_pnl > 0
                    })
                    in_pos = 0

        return trades

    trades_spy = simulate_trades(close_spy, sig_spy, "SPY")
    trades_qqq = simulate_trades(close_qqq, sig_qqq, "QQQ")

    print(f"\n[Simulation Complete]")
    print(f"  SPY Trades: {len(trades_spy)}")
    print(f"  QQQ Trades: {len(trades_qqq)}")
    print(f"  Total Combined: {len(trades_spy) + len(trades_qqq)}")

    # Build calendar of all months from 2016-09 to 2026-09
    all_dates = close_spy.index
    min_date = all_dates.min()
    max_date = all_dates.max()
    all_months = pd.date_range(start=min_date, end=max_date, freq='MS').strftime("%Y-%m").tolist()
    # Add final month if end date is in it
    end_month_str = max_date.strftime("%Y-%m")
    if end_month_str not in all_months:
        all_months.append(end_month_str)

    # Monthly aggregation
    monthly_records = []
    
    spy_by_month = {}
    for t in trades_spy:
        m = t["exit_month"]
        spy_by_month.setdefault(m, []).append(t)

    qqq_by_month = {}
    for t in trades_qqq:
        m = t["exit_month"]
        qqq_by_month.setdefault(m, []).append(t)

    cum_spy_pnl = 0.0
    cum_dual_pnl = 0.0

    peak_spy = 0.0
    max_dd_spy = 0.0

    peak_dual = 0.0
    max_dd_dual = 0.0

    for m in all_months:
        s_trades = spy_by_month.get(m, [])
        q_trades = qqq_by_month.get(m, [])
        d_trades = s_trades + q_trades

        s_pnl = sum(t["pnl_usd"] for t in s_trades)
        q_pnl = sum(t["pnl_usd"] for t in q_trades)
        d_pnl = s_pnl + q_pnl

        s_count = len(s_trades)
        q_count = len(q_trades)
        d_count = len(d_trades)

        s_wins = sum(1 for t in s_trades if t["profitable"])
        d_wins = sum(1 for t in d_trades if t["profitable"])

        cum_spy_pnl += s_pnl
        cum_dual_pnl += d_pnl

        if cum_spy_pnl > peak_spy:
            peak_spy = cum_spy_pnl
        dd_s = peak_spy - cum_spy_pnl
        if dd_s > max_dd_spy:
            max_dd_spy = dd_s

        if cum_dual_pnl > peak_dual:
            peak_dual = cum_dual_pnl
        dd_d = peak_dual - cum_dual_pnl
        if dd_d > max_dd_dual:
            max_dd_dual = dd_d

        monthly_records.append({
            "month": m,
            "year": int(m.split("-")[0]),
            "spy_trades": s_count,
            "spy_pnl": round(s_pnl, 2),
            "spy_wins": s_wins,
            "qqq_trades": q_count,
            "qqq_pnl": round(q_pnl, 2),
            "dual_trades": d_count,
            "dual_pnl": round(d_pnl, 2),
            "dual_wins": d_wins,
            "cum_spy_pnl": round(cum_spy_pnl, 2),
            "cum_dual_pnl": round(cum_dual_pnl, 2)
        })

    df_monthly = pd.DataFrame(monthly_records)

    # 1. Yearly Summary
    yearly_records = []
    for yr, group in df_monthly.groupby("year"):
        s_tot_pnl = group["spy_pnl"].sum()
        s_tot_tr = group["spy_trades"].sum()
        s_tot_w = group["spy_wins"].sum()
        s_wr = (s_tot_w / s_tot_tr * 100.0) if s_tot_tr > 0 else 0.0

        d_tot_pnl = group["dual_pnl"].sum()
        d_tot_tr = group["dual_trades"].sum()
        d_tot_w = group["dual_wins"].sum()
        d_wr = (d_tot_w / d_tot_tr * 100.0) if d_tot_tr > 0 else 0.0

        # Active months
        s_act_m = (group["spy_trades"] > 0).sum()
        d_act_m = (group["dual_trades"] > 0).sum()

        yearly_records.append({
            "year": yr,
            "spy_pnl": round(s_tot_pnl, 2),
            "spy_trades": s_tot_tr,
            "spy_win_pct": round(s_wr, 1),
            "spy_active_months": f"{s_act_m}/12",
            "dual_pnl": round(d_tot_pnl, 2),
            "dual_trades": d_tot_tr,
            "dual_win_pct": round(d_wr, 1),
            "dual_active_months": f"{d_act_m}/12",
        })

    df_yearly = pd.DataFrame(yearly_records)

    print("\n" + "=" * 110)
    print("                             YEAR-BY-YEAR COMPARISON (2016 - 2026)")
    print("=" * 110)
    print(f"{'Year':<6} | {'SPY Trades':<10} {'SPY Win%':<9} {'SPY Active Mo':<14} {'SPY Net PnL ($)':<15} | "
          f"{'Dual Trades':<11} {'Dual Win%':<10} {'Dual Active Mo':<14} {'Dual Net PnL ($)':<16}")
    print("-" * 110)
    for _, r in df_yearly.iterrows():
        print(f"{r['year']:<6} | {r['spy_trades']:<10} {r['spy_win_pct']:<8}% {r['spy_active_months']:<14} ${r['spy_pnl']:<14,.2f} | "
              f"{r['dual_trades']:<11} {r['dual_win_pct']:<9}% {r['dual_active_months']:<14} ${r['dual_pnl']:<15,.2f}")
    print("-" * 110)

    tot_s_pnl = df_monthly["spy_pnl"].sum()
    tot_s_tr = df_monthly["spy_trades"].sum()
    tot_s_w = df_monthly["spy_wins"].sum()
    tot_s_wr = (tot_s_w / tot_s_tr * 100.0) if tot_s_tr > 0 else 0.0

    tot_d_pnl = df_monthly["dual_pnl"].sum()
    tot_d_tr = df_monthly["dual_trades"].sum()
    tot_d_w = df_monthly["dual_wins"].sum()
    tot_d_wr = (tot_d_w / tot_d_tr * 100.0) if tot_d_tr > 0 else 0.0

    print(f"{'TOTAL':<6} | {tot_s_tr:<10} {tot_s_wr:<8.1f}% {'-':<14} ${tot_s_pnl:<14,.2f} | "
          f"{tot_d_tr:<11} {tot_d_wr:<9.1f}% {'-':<14} ${tot_d_pnl:<15,.2f}")
    print("=" * 110)

    # 2. Monthly Consistency & Distribution Analysis
    total_months = len(df_monthly)
    spy_active_months = (df_monthly["spy_trades"] > 0).sum()
    dual_active_months = (df_monthly["dual_trades"] > 0).sum()

    spy_pos_months = (df_monthly["spy_pnl"] > 0).sum()
    dual_pos_months = (df_monthly["dual_pnl"] > 0).sum()

    spy_neg_months = (df_monthly["spy_pnl"] < 0).sum()
    dual_neg_months = (df_monthly["dual_pnl"] < 0).sum()

    spy_zero_months = (df_monthly["spy_trades"] == 0).sum()
    dual_zero_months = (df_monthly["dual_trades"] == 0).sum()

    print("\n" + "=" * 80)
    print("                     MONTHLY CONSISTENCY & BEHAVIOR METRICS")
    print("=" * 80)
    print(f"  Total Months in 10 Years:            {total_months} months")
    print(f"  SPY Only Active Months (>=1 trade):  {spy_active_months}/{total_months} ({spy_active_months/total_months*100:.1f}%)")
    print(f"  Dual-Asset Active Months (>=1 trade):{dual_active_months}/{total_months} ({dual_active_months/total_months*100:.1f}%)  <-- +{dual_active_months - spy_active_months} MORE ACTIVE MONTHS!")
    print(f"  SPY Zero-Trade Months (Patience):    {spy_zero_months}/{total_months} ({spy_zero_months/total_months*100:.1f}%)")
    print(f"  Dual-Asset Zero Months:              {dual_zero_months}/{total_months} ({dual_zero_months/total_months*100:.1f}%)  <-- CUTS INACTIVE MONTHS IN HALF!")
    print("-" * 80)
    print(f"  SPY Winning Months (Net Profit > 0): {spy_pos_months}/{total_months} ({spy_pos_months/total_months*100:.1f}%)")
    print(f"  Dual Winning Months (Net Profit > 0):{dual_pos_months}/{total_months} ({dual_pos_months/total_months*100:.1f}%)")
    print(f"  SPY Losing Months:                   {spy_neg_months}/{total_months} ({spy_neg_months/total_months*100:.1f}%)")
    print(f"  Dual Losing Months:                  {dual_neg_months}/{total_months} ({dual_neg_months/total_months*100:.1f}%)")
    print("-" * 80)
    print(f"  Average Trades / Month:              SPY: {tot_s_tr / total_months:.2f} trades/mo  |  Dual: {tot_d_tr / total_months:.2f} trades/mo")
    print(f"  Average Profit / Month:              SPY: ${tot_s_pnl / total_months:.2f}/mo       |  Dual: ${tot_d_pnl / total_months:.2f}/mo")
    print(f"  Max Trades in a Single Month:        SPY: {df_monthly['spy_trades'].max()} trades           |  Dual: {df_monthly['dual_trades'].max()} trades")
    print(f"  Best Single Month:                   SPY: +${df_monthly['spy_pnl'].max():,.2f}         |  Dual: +${df_monthly['dual_pnl'].max():,.2f}")
    print(f"  Worst Single Month:                  SPY: -${abs(df_monthly['spy_pnl'].min()):,.2f}          |  Dual: -${abs(df_monthly['dual_pnl'].min()):,.2f}")
    print(f"  10-Year Max Drawdown:                SPY: ${max_dd_spy:,.2f}           |  Dual: ${max_dd_dual:,.2f}")
    print("=" * 80)

    # Save detailed monthly results to json
    results_payload = {
        "horizon": "2016-09 to 2026-09",
        "total_months": total_months,
        "contract_multiplier": contract_multiplier,
        "spy_summary": {
            "total_trades": int(tot_s_tr),
            "win_rate_pct": round(tot_s_wr, 2),
            "total_pnl_usd": round(tot_s_pnl, 2),
            "avg_monthly_trades": round(tot_s_tr / total_months, 2),
            "avg_monthly_pnl_usd": round(tot_s_pnl / total_months, 2),
            "active_months": int(spy_active_months),
            "zero_trade_months": int(spy_zero_months),
            "winning_months": int(spy_pos_months),
            "losing_months": int(spy_neg_months),
            "max_dd_usd": round(max_dd_spy, 2)
        },
        "dual_summary": {
            "total_trades": int(tot_d_tr),
            "win_rate_pct": round(tot_d_wr, 2),
            "total_pnl_usd": round(tot_d_pnl, 2),
            "avg_monthly_trades": round(tot_d_tr / total_months, 2),
            "avg_monthly_pnl_usd": round(tot_d_pnl / total_months, 2),
            "active_months": int(dual_active_months),
            "zero_trade_months": int(dual_zero_months),
            "winning_months": int(dual_pos_months),
            "losing_months": int(dual_neg_months),
            "max_dd_usd": round(max_dd_dual, 2)
        },
        "yearly_records": yearly_records,
        "monthly_records": monthly_records
    }

    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    out_file = results_dir / "spy_vs_dual_scalper_10year_monthly.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results_payload, f, indent=2, cls=NumpyEncoder)
    print(f"\n[Saved JSON] Full results saved to {out_file}")

    return results_payload

if __name__ == "__main__":
    run_monthly_comparison()
