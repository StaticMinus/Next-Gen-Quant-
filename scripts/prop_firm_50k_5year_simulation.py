"""
$50,000 Prop Firm Account 5-Year P/L Simulation (2021 - 2026) — AgentQuant
========================================================================
Stress-tests our winning Scalper strategy across 5 full years (1,255 trading days),
including the 2022 Bear Market crash, 2023 banking crisis, and 2024-2026 bull cycle.
Evaluates year-by-year P/L, drawdown survival, 85% trader payouts, and Naira conversions.
"""

import os
import sys
import json
from pathlib import Path
from typing import Any, Dict, List
import numpy as np
import pandas as pd
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from src.utils.config import config
from src.data.ingest import fetch_ohlcv_data
from src.strategies.scalper import ScalperStrategy
from src.backtest.runner import _get_close, _apply_transaction_costs
from src.backtest.metrics import PerformanceMetrics


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def run_5year_simulation():
    print("=" * 85)
    print("      AGENTQUANT $50,000 FUNDED ACCOUNT 5-YEAR STRESS TEST (2021 - 2026)")
    print("=" * 85)

    initial_capital = 50000.0
    config.backtest.initial_cash = initial_capital
    naira_rate = 1650.0
    trader_split = 0.85
    assets = ["SPY", "QQQ", "IWM"]

    # Load 5-year data
    ohlcv_dict = {}
    close_dict = {}
    for a in assets:
        data = fetch_ohlcv_data(ticker=a)
        df = data[a]
        ohlcv_dict[a] = df
        close_dict[a] = _get_close(df)

    ref_close = close_dict["SPY"]
    start_date = ref_close.index.min()
    end_date = ref_close.index.max()
    total_bars = len(ref_close)

    print(f"Starting Capital:       ${initial_capital:,.2f}")
    print(f"Full 5-Year Horizon:    {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} ({total_bars} trading days)")
    print(f"Assets Evaluated:       {', '.join(assets)}")

    scalper = ScalperStrategy()

    variants = [
        {
            "name": "Balanced Long-Only Scalper",
            "params": {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5},
            "desc": "5-day lookback, 1.25s bands, 3% stop loss, exit at mean",
        },
        {
            "name": "Aggressive Long-Only Scalper",
            "params": {"window": 5, "num_std": 1.0, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5},
            "desc": "5-day lookback, 1.0s bands, 3% stop loss, exit at mean",
        },
        {
            "name": "Conservative Long-Only Scalper",
            "params": {"window": 10, "num_std": 1.5, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.04, "max_hold_bars": 8},
            "desc": "10-day lookback, 1.5s bands, 4% stop loss, exit at mean",
        },
    ]

    all_results = []

    # Benchmarks (Buy & Hold over 5 years)
    benchmarks = {}
    for asset in assets:
        c = close_dict[asset]
        daily_ret = c.pct_change().fillna(0)
        bnh_ret = daily_ret.copy()
        bnh_cost = config.backtest.commission + config.backtest.slippage
        bnh_ret.iloc[0] -= bnh_cost
        bnh_equity = (1 + bnh_ret).cumprod() * initial_capital
        bnh_final = float(bnh_equity.iloc[-1])
        bnh_metrics = PerformanceMetrics.from_equity(bnh_equity)
        benchmarks[asset] = {
            "final_balance": round(bnh_final, 2),
            "net_profit_usd": round(bnh_final - initial_capital, 2),
            "total_return_pct": round((bnh_final - initial_capital) / initial_capital * 100.0, 2),
            "sharpe": round(float(bnh_metrics.get("sharpe", 0.0)), 2),
            "max_drawdown_pct": round(float(bnh_metrics.get("max_drawdown", 0.0)) * 100.0, 2),
        }

    print("\n5-Year Benchmark Buy & Hold Performance ($50,000 Initial):")
    for a, b in benchmarks.items():
        print(f"  {a:<5} -> Final: ${b['final_balance']:<10,.2f} ({b['total_return_pct']:+6.2f}%) | Sharpe: {b['sharpe']:4.2f} | MaxDD: {b['max_drawdown_pct']:5.2f}%")

    print("\nRunning 5-Year Simulations...")
    for asset in assets:
        df = ohlcv_dict[asset]
        c = close_dict[asset]
        daily_ret = c.pct_change().fillna(0)

        for v in variants:
            v_name = v["name"]
            params = v["params"]

            signal = scalper.generate_signal(df, params)
            signal = signal.reindex(c.index).fillna(0)

            costs = _apply_transaction_costs(
                signal,
                config.backtest.commission,
                config.backtest.slippage,
                config.backtest.market_impact_bps,
            )

            strat_ret = daily_ret * signal.shift(1).fillna(0) - costs
            equity = (1 + strat_ret).cumprod() * initial_capital
            final_val = float(equity.iloc[-1])
            total_profit_usd = final_val - initial_capital
            total_return_pct = (total_profit_usd / initial_capital) * 100.0

            trader_usd = total_profit_usd * trader_split
            trader_ngn = trader_usd * naira_rate

            metrics = PerformanceMetrics.from_equity(equity)
            max_dd_pct = float(metrics.get("max_drawdown", 0.0)) * 100.0
            max_dd_usd = float(metrics.get("max_drawdown", 0.0)) * initial_capital

            # Trades extraction
            trades = []
            in_pos = 0
            entry_dt = None
            entry_p = 0.0
            bars_held = 0

            for dt in c.index:
                pos = signal.loc[dt]
                price = c.loc[dt]

                if in_pos == 0 and pos != 0:
                    in_pos = pos
                    entry_dt = dt
                    entry_p = price
                    bars_held = 0
                elif in_pos != 0:
                    bars_held += 1
                    if pos != in_pos:
                        exit_dt = dt
                        exit_p = price
                        ret = ((exit_p - entry_p) / entry_p) * in_pos
                        trade_pnl = initial_capital * ret
                        trades.append({
                            "type": "LONG",
                            "entry_date": entry_dt.strftime("%Y-%m-%d"),
                            "exit_date": exit_dt.strftime("%Y-%m-%d"),
                            "year": entry_dt.year,
                            "bars_held": bars_held,
                            "entry_price": round(float(entry_p), 2),
                            "exit_price": round(float(exit_p), 2),
                            "return_pct": round(float(ret * 100.0), 2),
                            "pnl_usd": round(float(trade_pnl), 2),
                            "profitable": ret > 0,
                        })

                        if pos != 0:
                            in_pos = pos
                            entry_dt = dt
                            entry_p = price
                            bars_held = 0
                        else:
                            in_pos = 0

            wins = [t for t in trades if t["profitable"]]
            win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0

            # Year-by-Year Breakdown
            yearly_data = []
            # Cut into 5 distinct 1-year periods
            # Year 1: Sep 2021 - Sep 2022 (The 2022 Bear Crash)
            # Year 2: Sep 2022 - Sep 2023 (The Recovery)
            # Year 3: Sep 2023 - Sep 2024 (AI Expansion)
            # Year 4: Sep 2024 - Sep 2025 (Bull Continuation)
            # Year 5: Sep 2025 - Sep 2026 (Recent Year)
            cutoffs = [
                ("Year 1 (2021-2022 Bear Market)", start_date, start_date + pd.DateOffset(years=1)),
                ("Year 2 (2022-2023 Recovery)", start_date + pd.DateOffset(years=1), start_date + pd.DateOffset(years=2)),
                ("Year 3 (2023-2024 AI Expansion)", start_date + pd.DateOffset(years=2), start_date + pd.DateOffset(years=3)),
                ("Year 4 (2024-2025 Bull Run)", start_date + pd.DateOffset(years=3), start_date + pd.DateOffset(years=4)),
                ("Year 5 (2025-2026 Recent Cycle)", start_date + pd.DateOffset(years=4), end_date),
            ]

            for label, y_start, y_end in cutoffs:
                y_ret = strat_ret.loc[(strat_ret.index >= y_start) & (strat_ret.index < y_end)]
                bnh_y_ret = daily_ret.loc[(daily_ret.index >= y_start) & (daily_ret.index < y_end)]
                
                y_cum_ret = float((1 + y_ret).prod() - 1.0)
                bnh_y_cum = float((1 + bnh_y_ret).prod() - 1.0)

                y_pnl_usd = initial_capital * y_cum_ret
                y_trader_usd = y_pnl_usd * trader_split if y_pnl_usd > 0 else y_pnl_usd
                y_trader_ngn = y_trader_usd * naira_rate

                y_eq = (1 + y_ret).cumprod() * initial_capital
                y_dd = float(PerformanceMetrics.from_equity(y_eq).get("max_drawdown", 0.0)) * 100.0

                yearly_data.append({
                    "period_label": label,
                    "strategy_return_pct": round(y_cum_ret * 100.0, 2),
                    "benchmark_return_pct": round(bnh_y_cum * 100.0, 2),
                    "year_profit_usd": round(y_pnl_usd, 2),
                    "your_takehome_usd (85%)": round(y_trader_usd, 2),
                    "your_takehome_ngn (85%)": round(y_trader_ngn, 0),
                    "year_max_drawdown_pct": round(y_dd, 2),
                    "prop_firm_safe": y_dd < 4.5,
                })

            all_results.append({
                "asset": asset,
                "variant_name": v_name,
                "initial_capital": initial_capital,
                "final_balance": round(final_val, 2),
                "total_profit_usd": round(total_profit_usd, 2),
                "total_return_pct": round(total_return_pct, 2),
                "annualized_cagr_pct": round(((final_val / initial_capital) ** (1.0 / 5.0) - 1.0) * 100.0, 2),
                "trader_takehome_5year_usd": round(trader_usd, 2),
                "trader_takehome_5year_ngn": round(trader_ngn, 0),
                "average_yearly_takehome_usd": round(trader_usd / 5.0, 2),
                "average_yearly_takehome_ngn": round(trader_ngn / 5.0, 0),
                "average_monthly_takehome_usd": round(trader_usd / 60.0, 2),
                "average_monthly_takehome_ngn": round(trader_ngn / 60.0, 0),
                "sharpe": round(float(metrics.get("sharpe", 0.0)), 2),
                "max_drawdown_pct": round(max_dd_pct, 2),
                "max_drawdown_usd": round(max_dd_usd, 2),
                "total_trades": len(trades),
                "win_rate_pct": round(win_rate, 1),
                "yearly_breakdown": yearly_data,
                "benchmark": benchmarks[asset],
            })

    # Sort results
    all_results.sort(key=lambda x: (x["sharpe"], x["total_profit_usd"]), reverse=True)
    best = all_results[0]

    # Save to JSON
    out_dir = Path("results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "prop_firm_50k_5year_report.json"

    with open(out_file, "w") as f:
        json.dump({
            "metadata": {
                "initial_capital": initial_capital,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "total_trading_days": total_bars,
                "trader_split": trader_split,
                "naira_rate": naira_rate,
            },
            "best_run": best,
            "all_runs": all_results,
            "benchmarks": benchmarks,
        }, f, indent=2, cls=NumpyEncoder)

    print("\n" + "=" * 100)
    print("                   $50,000 ACCOUNT 5-YEAR STRESS TEST LEADERBOARD")
    print("=" * 100)
    header = f"{'Asset':<5} {'Strategy Variant':<28} {'5-Yr Profit':<13} {'YOUR 85% (USD)':<16} {'Monthly (USD)':<14} {'Monthly (NGN)':<16} {'Sharpe':<7} {'MaxDD %'}"
    print(header)
    print("-" * 100)
    for r in all_results:
        print(f"{r['asset']:<5} {r['variant_name']:<28} ${r['total_profit_usd']:<12,.2f} ${r['trader_takehome_5year_usd']:<15,.2f} ${r['average_monthly_takehome_usd']:<13,.2f} ₦{r['average_monthly_takehome_ngn']:<15,.0f} {r['sharpe']:<7.2f} {r['max_drawdown_pct']:<8.2f}")

    print("\n" + "=" * 100)
    print(f"5-YEAR CHAMPION: {best['variant_name']} on {best['asset']}")
    print("=" * 100)
    print(f"Starting Capital:                 ${best['initial_capital']:,.2f}")
    print(f"Final Balance:                    ${best['final_balance']:,.2f}")
    print(f"5-Year Total Profit:              ${best['total_profit_usd']:,.2f} (+{best['total_return_pct']:.2f}%)")
    print(f"YOUR 85% TAKE-HOME CASH:          ${best['trader_takehome_5year_usd']:,.2f} (₦{best['trader_takehome_5year_ngn']:,.0f} Naira)")
    print(f"Average Monthly Payout (5 Years): ${best['average_monthly_takehome_usd']:,.2f}/month (₦{best['average_monthly_takehome_ngn']:,.0f} Naira/month)")
    print(f"Overall Sharpe Ratio:             {best['sharpe']:.2f}")
    print(f"5-Year Max Drawdown:              {best['max_drawdown_pct']:.2f}% (${best['max_drawdown_usd']:,.2f})")
    print(f"Total Trades:                     {best['total_trades']} (Win Rate: {best['win_rate_pct']:.1f}%)")

    print("\n--- Year-by-Year Stress Test Breakdown ---")
    for y in best["yearly_breakdown"]:
        print(f"  • {y['period_label']:<34} -> Return: {y['strategy_return_pct']:+6.2f}% (B&H: {y['benchmark_return_pct']:+6.2f}%) | Payout: ${y['your_takehome_usd (85%)']:<9,.2f} (₦{y['your_takehome_ngn (85%)']:<12,.0f}) | MaxDD: {y['year_max_drawdown_pct']:5.2f}%")

    print(f"\nReport exported to: {out_file.resolve()}")
    return best, all_results


if __name__ == "__main__":
    run_5year_simulation()
