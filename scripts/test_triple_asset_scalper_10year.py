"""
Triple-Asset Scalper Test: SPY (S&P 500) + QQQ (Nasdaq 100) + IWM (Russell 2000)
================================================================================
Compares Single-Asset (SPY), Dual-Asset (SPY+QQQ), and Triple-Asset (SPY+QQQ+IWM)
across 10 years (2016 - 2026) under realistic Prop Firm sizing.
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.strategies.scalper import ScalperStrategy
from src.strategies.base import _get_close

def run_triple_test():
    cache_dir = Path("cache")
    df_spy = pd.read_csv(cache_dir / "SPY_10y.csv", index_col=0, parse_dates=True)
    df_qqq = pd.read_csv(cache_dir / "QQQ_10y.csv", index_col=0, parse_dates=True)
    df_iwm = pd.read_csv(cache_dir / "IWM_10y.csv", index_col=0, parse_dates=True)

    c_spy = _get_close(df_spy)
    c_qqq = _get_close(df_qqq)
    c_iwm = _get_close(df_iwm)

    strat = ScalperStrategy()
    params = {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}

    sig_spy = strat.generate_signal(df_spy, params).reindex(c_spy.index).fillna(0).clip(lower=0)
    sig_qqq = strat.generate_signal(df_qqq, params).reindex(c_qqq.index).fillna(0).clip(lower=0)
    sig_iwm = strat.generate_signal(df_iwm, params).reindex(c_iwm.index).fillna(0).clip(lower=0)

    contract_mult = 10.0  # $10/pt move
    comm = 1.50

    def simulate_trades(c_series, sig_series, asset_name):
        trades = []
        in_pos = 0
        entry_p = 0.0
        entry_dt = None
        bars = 0

        for dt in c_series.index:
            pos = int(sig_series.loc[dt])
            p = float(c_series.loc[dt])

            if in_pos == 0 and pos > 0:
                in_pos = 1
                entry_p = p
                entry_dt = dt
                bars = 0
            elif in_pos == 1:
                bars += 1
                if pos == 0:
                    exit_p = p
                    pnl = (exit_p - entry_p) * contract_mult - (comm * 2)
                    trades.append({
                        "asset": asset_name,
                        "entry_dt": entry_dt,
                        "exit_dt": dt,
                        "month": dt.strftime("%Y-%m"),
                        "year": dt.year,
                        "pnl": pnl,
                        "win": pnl > 0,
                        "bars": bars
                    })
                    in_pos = 0
        return trades

    t_spy = simulate_trades(c_spy, sig_spy, "SPY")
    t_qqq = simulate_trades(c_qqq, sig_qqq, "QQQ")
    t_iwm = simulate_trades(c_iwm, sig_iwm, "IWM")

    print("=" * 105)
    print("      AGENTQUANT 10-YEAR PORTFOLIO EXPANSION: SINGLE vs DUAL vs TRIPLE ASSET SCALPER")
    print("=" * 105)

    def summarize(trades_list, label):
        tot_t = len(trades_list)
        wins = sum(1 for t in trades_list if t["win"])
        wr = (wins / tot_t * 100.0) if tot_t > 0 else 0.0
        tot_pnl = sum(t["pnl"] for t in trades_list)
        tr_per_yr = tot_t / 10.0
        tr_per_mo = tot_t / 120.0

        # Drawdown
        cum = np.cumsum([t["pnl"] for t in trades_list])
        peak = np.maximum.accumulate(cum)
        dd = peak - cum
        max_dd = np.max(dd) if len(dd) > 0 else 0.0

        # Monthly aggregation
        by_m = {}
        for t in trades_list:
            by_m[t["month"]] = by_m.get(t["month"], 0.0) + t["pnl"]

        months_over_300 = sum(1 for p in by_m.values() if p >= 300.0)
        months_over_400 = sum(1 for p in by_m.values() if p >= 400.0)
        months_over_600 = sum(1 for p in by_m.values() if p >= 600.0)
        best_m = max(by_m.values()) if by_m else 0.0

        return {
            "label": label,
            "trades": tot_t,
            "tr_yr": round(tr_per_yr, 1),
            "tr_mo": round(tr_per_mo, 2),
            "win_rate": round(wr, 1),
            "tot_pnl": round(tot_pnl, 2),
            "max_dd": round(max_dd, 2),
            "m_over_300": months_over_300,
            "m_over_400": months_over_400,
            "m_over_600": months_over_600,
            "best_month": round(best_m, 2)
        }

    s_spy = summarize(t_spy, "1. Single-Asset (SPY Only)")
    s_qqq = summarize(t_qqq, "• IWM Alone (Russell 2000)")
    s_dual = summarize(t_spy + t_qqq, "2. Dual-Asset (SPY + QQQ)")
    s_triple = summarize(t_spy + t_qqq + t_iwm, "3. Triple-Asset (SPY + QQQ + IWM)")

    all_summaries = [s_spy, s_dual, s_triple]
    df_s = pd.DataFrame(all_summaries)

    print(f"{'Portfolio Setup':<32} {'Trades':<8} {'Tr/Mo':<8} {'Win Rate':<10} {'10-Yr Profit':<14} {'Max DD':<10} {'Months >=$400':<14} {'Best Month':<12}")
    print("-" * 115)
    for _, r in df_s.iterrows():
        print(f"{r['label']:<32} {r['trades']:<8} {r['tr_mo']:<8.2f} {r['win_rate']:>5.1f}%     ${r['tot_pnl']:<13,.2f} ${r['max_dd']:<9,.2f} {r['m_over_400']:<14} +${r['best_month']:<11,.2f}")
    print("=" * 115)

    # IWM isolated performance
    s_iwm = summarize(t_iwm, "IWM Alone")
    print(f"\n[IWM Solo Telemetry]: {s_iwm['trades']} trades ({s_iwm['tr_mo']} tr/mo) | Win Rate: {s_iwm['win_rate']}% | Total Profit: ${s_iwm['tot_pnl']:,.2f} | Max DD: ${s_iwm['max_dd']:,.2f}")

    # Correlation Matrix between SPY, QQQ, and IWM daily returns
    df_returns = pd.DataFrame({
        "SPY": c_spy.pct_change(),
        "QQQ": c_qqq.pct_change(),
        "IWM": c_iwm.pct_change()
    }).dropna()

    corr = df_returns.corr()
    print("\n[Asset Return Correlation Matrix (10 Years)]:")
    print(corr.round(3))

if __name__ == "__main__":
    run_triple_test()
