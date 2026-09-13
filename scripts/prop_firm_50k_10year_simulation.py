"""
$50,000 Prop Firm Account 10-Year Stress Test (2016 - 2026) — AgentQuant
========================================================================
Stress-tests our winning Balanced Scalper across 10 full years (2,514 trading days),
including the 2018 Crash, the 2020 COVID-19 Crash (-35%), the 2022 Bear Market,
and the modern 2023-2026 bull expansion.
Calculates year-by-year survival, maximum drawdown, payouts in USD and Naira.
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

import yfinance as yf
from src.utils.config import config
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


def run_10year_simulation():
    print("=" * 90)
    print("       AGENTQUANT $50,000 FUNDED ACCOUNT 10-YEAR STRESS TEST (2016 - 2026)")
    print("=" * 90)

    initial_capital = 50000.0
    config.backtest.initial_cash = initial_capital
    naira_rate = 1650.0
    trader_split = 0.85
    assets = ["SPY", "QQQ"]

    scalper = ScalperStrategy()
    variants = [
        {
            "name": "Balanced Long-Only Scalper (Our Chosen Strategy)",
            "params": {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5},
            "desc": "5d MA, 1.25s lower band, exit at mean, 3% stop loss (Ultra-low drawdown)",
        },
        {
            "name": "Aggressive Long-Only Scalper",
            "params": {"window": 5, "num_std": 1.0, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5},
            "desc": "5d MA, 1.0s lower band, exit at mean, 3% stop loss (Higher frequency)",
        },
    ]

    all_results = []

    print("\nFetching 10 years of historical OHLCV data from Yahoo Finance...")
    ohlcv_dict = {}
    close_dict = {}

    for ticker in assets:
        print(f"  Downloading 10-year dataset for {ticker}...")
        raw = yf.download(ticker, period="10y", progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [col[0].lower() for col in raw.columns]
        else:
            raw.columns = [str(c).lower() for c in raw.columns]
        ohlcv_dict[ticker] = raw
        close_dict[ticker] = _get_close(raw)

    ref_close = close_dict["SPY"]
    start_date = ref_close.index.min()
    end_date = ref_close.index.max()
    total_bars = len(ref_close)

    print(f"\n10-Year Horizon:        {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} ({total_bars} trading days)")
    print(f"Starting Capital:       ${initial_capital:,.2f}")
    print(f"Trader Profit Share:    {trader_split * 100:.0f}% (Prop Firm keeps 15%)")

    # Benchmarks (10-year buy and hold)
    benchmarks = {}
    for ticker in assets:
        c = close_dict[ticker]
        ret = c.pct_change().fillna(0)
        ret.iloc[0] -= 0.0006  # entry cost
        bnh_eq = (1 + ret).cumprod() * initial_capital
        bnh_final = float(bnh_eq.iloc[-1])
        bnh_metrics = PerformanceMetrics.from_equity(bnh_eq)
        benchmarks[ticker] = {
            "final_balance": round(bnh_final, 2),
            "net_profit_usd": round(bnh_final - initial_capital, 2),
            "total_return_pct": round((bnh_final - initial_capital) / initial_capital * 100.0, 2),
            "sharpe": round(float(bnh_metrics.get("sharpe", 0.0)), 2),
            "max_drawdown_pct": round(float(bnh_metrics.get("max_drawdown", 0.0)) * 100.0, 2),
        }

    print("\n10-Year Benchmark Buy & Hold:")
    for a, b in benchmarks.items():
        print(f"  {a:<5} -> Final: ${b['final_balance']:<10,.2f} ({b['total_return_pct']:+7.2f}%) | Sharpe: {b['sharpe']:4.2f} | MaxDD: {b['max_drawdown_pct']:5.2f}%")

    print("\nRunning 10-Year Strategy Simulations...")
    for ticker in assets:
        df = ohlcv_dict[ticker]
        c = close_dict[ticker]
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

            # Trades breakdown
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

            # Year-by-Year Breakdown (10 separate calendar years: 2016-2026)
            years_list = sorted(list(set(c.index.year)))
            yearly_breakdown = []

            for yr in years_list:
                yr_slice_ret = strat_ret.loc[strat_ret.index.year == yr]
                yr_bnh_ret = daily_ret.loc[daily_ret.index.year == yr]
                if yr_slice_ret.empty:
                    continue

                yr_strat_cum = float((1 + yr_slice_ret).prod() - 1.0) * 100.0
                yr_bnh_cum = float((1 + yr_bnh_ret).prod() - 1.0) * 100.0

                yr_profit_usd = initial_capital * (yr_strat_cum / 100.0)
                yr_trader_usd = yr_profit_usd * trader_split if yr_profit_usd > 0 else yr_profit_usd
                yr_trader_ngn = yr_trader_usd * naira_rate

                yr_eq = (1 + yr_slice_ret).cumprod() * initial_capital
                yr_dd = float(PerformanceMetrics.from_equity(yr_eq).get("max_drawdown", 0.0)) * 100.0

                # Note major historical context
                note = "Normal market"
                if yr == 2016:
                    note = "Late 2016 Election cycle"
                elif yr == 2018:
                    note = "2018 Trade War & Q4 Crash (-20%)"
                elif yr == 2020:
                    note = "COVID-19 Crash (-35% collapse!)"
                elif yr == 2022:
                    note = "2022 Fed Rate Hike Bear Market"
                elif yr == 2023:
                    note = "2023 Recovery & Bank Crisis"
                elif yr == 2024:
                    note = "2024 AI Bull Expansion"

                yearly_breakdown.append({
                    "year": yr,
                    "market_context": note,
                    "strategy_return_pct": round(yr_strat_cum, 2),
                    "benchmark_return_pct": round(yr_bnh_cum, 2),
                    "year_profit_usd": round(yr_profit_usd, 2),
                    "your_takehome_usd": round(yr_trader_usd, 2),
                    "your_takehome_ngn": round(yr_trader_ngn, 0),
                    "year_max_drawdown_pct": round(yr_dd, 2),
                    "prop_firm_safe": yr_dd < 4.5,
                })

            all_results.append({
                "asset": ticker,
                "variant_name": v_name,
                "initial_capital": initial_capital,
                "final_balance": round(final_val, 2),
                "total_profit_usd": round(total_profit_usd, 2),
                "total_return_pct": round(total_return_pct, 2),
                "annualized_cagr_pct": round(((final_val / initial_capital) ** (1.0 / 10.0) - 1.0) * 100.0, 2),
                "trader_takehome_10year_usd": round(trader_usd, 2),
                "trader_takehome_10year_ngn": round(trader_ngn, 0),
                "average_yearly_takehome_usd": round(trader_usd / 10.0, 2),
                "average_yearly_takehome_ngn": round(trader_ngn / 10.0, 0),
                "average_monthly_takehome_usd": round(trader_usd / 120.0, 2),
                "average_monthly_takehome_ngn": round(trader_ngn / 120.0, 0),
                "sharpe": round(float(metrics.get("sharpe", 0.0)), 2),
                "max_drawdown_pct": round(max_dd_pct, 2),
                "max_drawdown_usd": round(max_dd_usd, 2),
                "total_trades": len(trades),
                "win_rate_pct": round(win_rate, 1),
                "yearly_breakdown": yearly_breakdown,
                "benchmark": benchmarks[ticker],
            })

    # Sort results by Sharpe
    all_results.sort(key=lambda x: (x["sharpe"], x["total_profit_usd"]), reverse=True)
    best = all_results[0]

    # Save to JSON
    out_dir = Path("results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "prop_firm_50k_10year_report.json"

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

    print("\n" + "=" * 105)
    print("                  $50,000 ACCOUNT 10-YEAR HISTORICAL SURVIVAL TABLE")
    print("=" * 105)
    header = f"{'Asset':<5} {'Strategy Variant':<28} {'10-Yr Profit':<14} {'YOUR 85% (USD)':<16} {'Monthly (USD)':<14} {'Monthly (NGN)':<16} {'Sharpe':<7} {'MaxDD %'}"
    print(header)
    print("-" * 105)
    for r in all_results:
        print(f"{r['asset']:<5} {r['variant_name']:<28} ${r['total_profit_usd']:<13,.2f} ${r['trader_takehome_10year_usd']:<15,.2f} ${r['average_monthly_takehome_usd']:<13,.2f} ₦{r['average_monthly_takehome_ngn']:<15,.0f} {r['sharpe']:<7.2f} {r['max_drawdown_pct']:<8.2f}")

    print("\n" + "=" * 105)
    print(f"10-YEAR CHAMPION: {best['variant_name']} on {best['asset']}")
    print("=" * 105)
    print(f"Starting Capital:                  ${best['initial_capital']:,.2f}")
    print(f"Final Balance:                     ${best['final_balance']:,.2f}")
    print(f"10-Year Total Profit:              ${best['total_profit_usd']:,.2f} (+{best['total_return_pct']:.2f}%)")
    print(f"YOUR 85% TAKE-HOME CASH:           ${best['trader_takehome_10year_usd']:,.2f} (₦{best['trader_takehome_10year_ngn']:,.0f} Naira)")
    print(f"Average Monthly Payout (10 Years): ${best['average_monthly_takehome_usd']:,.2f}/month (₦{best['average_monthly_takehome_ngn']:,.0f} Naira/month)")
    print(f"Overall Sharpe Ratio:              {best['sharpe']:.2f}")
    print(f"10-Year Max Drawdown:              {best['max_drawdown_pct']:.2f}% (${best['max_drawdown_usd']:,.2f})")
    print(f"Total Trades Over 10 Years:        {best['total_trades']} (Win Rate: {best['win_rate_pct']:.1f}%)")

    print("\n--- Year-by-Year Historical Breakdown ---")
    for y in best["yearly_breakdown"]:
        safe_str = "SAFE" if y["prop_firm_safe"] else "WARNING"
        print(f"  {y['year']} | {y['market_context']:<35} | Ret: {y['strategy_return_pct']:+6.2f}% (B&H: {y['benchmark_return_pct']:+6.2f}%) | Payout: ${y['your_takehome_usd']:<8,.2f} (₦{y['your_takehome_ngn']:<11,.0f}) | MaxDD: {y['year_max_drawdown_pct']:5.2f}% [{safe_str}]")

    print(f"\nReport exported to: {out_file.resolve()}")
    return best, all_results


if __name__ == "__main__":
    run_10year_simulation()
