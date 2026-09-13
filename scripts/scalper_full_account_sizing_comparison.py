"""
Full Position Sizing Comparison: Single Scalper vs Dual Scalper
===============================================================
Compares position sizing models on $50,000 capital:
Model A: Full Account Sizing ($50k notional / Standard ETF shares / 1 Mini Contract)
Model B: Conservative 1 Micro Contract ($2.5k notional / 1 MES)

Measures 1-Year, 3-Year, and 5-Year:
- Monthly Take-Home ($ and Naira @ ₦1,650/$)
- Max Drawdown vs $2,000 Prop Firm Limit
- Total Take-Home
"""

import sys
import json
from pathlib import Path
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.strategies.scalper import ScalperStrategy
from src.strategies.base import _get_close
from src.backtest.runner import _apply_transaction_costs
from src.backtest.metrics import PerformanceMetrics

cache_dir = Path("cache")
spy_raw = pd.read_csv(cache_dir / "SPY_10y.csv", index_col=0, parse_dates=True)
qqq_raw = pd.read_csv(cache_dir / "QQQ_10y.csv", index_col=0, parse_dates=True)

spy_c = _get_close(spy_raw)
qqq_c = _get_close(qqq_raw)

initial_capital = 50000.0
trader_split = 0.85
naira_rate = 1650.0

scalper = ScalperStrategy()
sig_spy = scalper.generate_signal(
    spy_raw,
    {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}
).reindex(spy_c.index).fillna(0).clip(lower=0)

sig_qqq = scalper.generate_signal(
    qqq_raw,
    {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}
).reindex(qqq_c.index).fillna(0).clip(lower=0)

def run_simulation(start_date, label):
    s_spy = spy_raw.loc[spy_raw.index >= start_date].copy()
    s_qqq = qqq_raw.loc[qqq_raw.index >= start_date].copy()
    c_spy = spy_c.loc[spy_c.index >= start_date]
    c_qqq = qqq_c.loc[qqq_c.index >= start_date]
    
    ret_spy = c_spy.pct_change().fillna(0)
    ret_qqq = c_qqq.pct_change().fillna(0)
    
    sig_s = sig_spy.loc[sig_spy.index >= start_date]
    sig_q = sig_qqq.loc[sig_qqq.index >= start_date]
    
    days = len(c_spy)
    years = days / 252.0
    months = years * 12.0

    # 1. Option 1: SPY Alone (Full Account Sizing - 100% capital allocation on active trades)
    cost_spy = sig_s.diff().abs().fillna(0) * 0.0004
    strat_ret_spy = ret_spy * sig_s.shift(1).fillna(0) - cost_spy
    eq_spy = (1 + strat_ret_spy).cumprod() * initial_capital
    profit_spy_full = eq_spy.iloc[-1] - initial_capital
    m_spy = PerformanceMetrics.from_equity(eq_spy)
    dd_spy_full_pct = float(m_spy.get("max_drawdown", 0.0)) * 100.0
    dd_spy_full_usd = float(m_spy.get("max_drawdown", 0.0)) * initial_capital

    # 2. Option 2: Dual Scalper SPY + QQQ (Balanced 50/50 capital allocation when both active, 100% if single)
    # Combined daily returns:
    active_both = (sig_s > 0) & (sig_q > 0)
    active_spy_only = (sig_s > 0) & (sig_q == 0)
    active_qqq_only = (sig_s == 0) & (sig_q > 0)
    
    cost_qqq = sig_q.diff().abs().fillna(0) * 0.0004
    strat_ret_qqq = ret_qqq * sig_q.shift(1).fillna(0) - cost_qqq
    
    # 50% SPY + 50% QQQ when both active, 100% when one active
    comb_ret = pd.Series(0.0, index=c_spy.index)
    comb_ret[active_both] = 0.5 * strat_ret_spy[active_both] + 0.5 * strat_ret_qqq[active_both]
    comb_ret[active_spy_only] = strat_ret_spy[active_spy_only]
    comb_ret[active_qqq_only] = strat_ret_qqq[active_qqq_only]
    
    eq_dual = (1 + comb_ret).cumprod() * initial_capital
    profit_dual_full = eq_dual.iloc[-1] - initial_capital
    m_dual = PerformanceMetrics.from_equity(eq_dual)
    dd_dual_full_pct = float(m_dual.get("max_drawdown", 0.0)) * 100.0
    dd_dual_full_usd = float(m_dual.get("max_drawdown", 0.0)) * initial_capital

    # Trader take-homes:
    th_spy_usd = profit_spy_full * trader_split
    th_spy_ngn = th_spy_usd * naira_rate
    m_th_spy_usd = th_spy_usd / months
    m_th_spy_ngn = m_th_spy_usd * naira_rate

    th_dual_usd = profit_dual_full * trader_split
    th_dual_ngn = th_dual_usd * naira_rate
    m_th_dual_usd = th_dual_usd / months
    m_th_dual_ngn = m_th_dual_usd * naira_rate

    return {
        "period": label,
        "years": round(years, 1),
        "months": round(months, 1),
        "spy_profit_usd": round(profit_spy_full, 2),
        "spy_th_usd": round(th_spy_usd, 2),
        "spy_th_ngn": round(th_spy_ngn, 0),
        "spy_monthly_usd": round(m_th_spy_usd, 2),
        "spy_monthly_ngn": round(m_th_spy_ngn, 0),
        "spy_max_dd_usd": round(dd_spy_full_usd, 2),
        "spy_max_dd_pct": round(dd_spy_full_pct, 2),
        "dual_profit_usd": round(profit_dual_full, 2),
        "dual_th_usd": round(th_dual_usd, 2),
        "dual_th_ngn": round(th_dual_ngn, 0),
        "dual_monthly_usd": round(m_th_dual_usd, 2),
        "dual_monthly_ngn": round(m_th_dual_ngn, 0),
        "dual_max_dd_usd": round(dd_dual_full_usd, 2),
        "dual_max_dd_pct": round(dd_dual_full_pct, 2),
    }

res_1y = run_simulation("2025-09-13", "1 Year (2025 - 2026)")
res_3y = run_simulation("2023-09-13", "3 Years (2023 - 2026)")
res_5y = run_simulation("2021-09-13", "5 Years (2021 - 2026)")

print("=" * 115)
print("             FULL $50,000 ACCOUNT POSITION SIZING COMPARISON (APPLES-TO-APPLES)")
print("=" * 115)
print(f"{'Timeframe':<24} | {'SPY Alone Monthly ($)':<22} | {'SPY Alone Monthly (₦)':<22} | {'Dual Scalper Monthly ($)':<24} | {'Dual Scalper Monthly (₦)'}")
print("-" * 115)
for r in [res_1y, res_3y, res_5y]:
    print(f"{r['period']:<24} | ${r['spy_monthly_usd']:>18,.2f}/mo | ₦{r['spy_monthly_ngn']:>18,.0f}/mo | ${r['dual_monthly_usd']:>20,.2f}/mo | ₦{r['dual_monthly_ngn']:>20,.0f}/mo")
print("-" * 115)

print("\nDRAWDOWN & TOTAL PROFIT METRICS:")
for r in [res_1y, res_3y, res_5y]:
    print(f"\n--- {r['period']} ---")
    print(f"  SPY Alone Total Profit:     ${r['spy_profit_usd']:>10,.2f} (Your 85%: ${r['spy_th_usd']:>10,.2f} / ₦{r['spy_th_ngn']:>12,.0f} NGN) | Max DD: ${r['spy_max_dd_usd']:>8,.2f} ({r['spy_max_dd_pct']}%)")
    print(f"  Dual Scalper Total Profit:  ${r['dual_profit_usd']:>10,.2f} (Your 85%: ${r['dual_th_usd']:>10,.2f} / ₦{r['dual_th_ngn']:>12,.0f} NGN) | Max DD: ${r['dual_max_dd_usd']:>8,.2f} ({r['dual_max_dd_pct']}%)")
