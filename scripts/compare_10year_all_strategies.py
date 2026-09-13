"""
10-Year Comprehensive Strategy Comparison (2016 - 2026) — AgentQuant
====================================================================
Backtests all strategy types in our arsenal across 10 full years (2,514 trading days)
on SPY and QQQ with $50,000 capital.
Ranks by Total Profit, Prop Firm Drawdown Safety, Win Rate, and Sharpe Ratio.
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
from src.strategies.strategy_registry import STRATEGY_REGISTRY
from src.strategies.base import _get_close
from src.backtest.runner import _apply_transaction_costs
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


def run_10year_strategy_search():
    print("=" * 95)
    print("      AGENTQUANT 10-YEAR ARSENAL STRATEGY TOURNAMENT (2016 - 2026)")
    print("=" * 95)

    initial_capital = 50000.0
    config.backtest.initial_cash = initial_capital
    naira_rate = 1650.0
    trader_split = 0.85
    assets = ["SPY", "QQQ"]

    # Load 10-year data
    print("Loading 10-year datasets for SPY and QQQ...")
    ohlcv_dict = {}
    close_dict = {}
    for ticker in assets:
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

    print(f"Horizon: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} ({total_bars} trading days)")

    # Define all strategy configurations in our arsenal to test
    configs_to_test = [
        # 1. Current Scalper
        {"strategy": "scalper", "params": {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}, "label": "Scalper(5d,1.25s,L)"},
        {"strategy": "scalper", "params": {"window": 5, "num_std": 1.0, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}, "label": "Scalper(5d,1.0s,L)"},
        {"strategy": "scalper", "params": {"window": 10, "num_std": 1.5, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.04, "max_hold_bars": 8}, "label": "Scalper(10d,1.5s,L)"},
        # 2. Mean Reversion
        {"strategy": "mean_reversion", "params": {"window": 10, "num_std": 1.5}, "label": "MeanRev(10,1.5s)"},
        {"strategy": "mean_reversion", "params": {"window": 15, "num_std": 2.0}, "label": "MeanRev(15,2.0s)"},
        {"strategy": "mean_reversion", "params": {"window": 20, "num_std": 2.0}, "label": "MeanRev(20,2.0s)"},
        # 3. Momentum
        {"strategy": "momentum", "params": {"fast_window": 10, "slow_window": 30}, "label": "Mom(10,30)"},
        {"strategy": "momentum", "params": {"fast_window": 20, "slow_window": 60}, "label": "Mom(20,60)"},
        {"strategy": "momentum", "params": {"fast_window": 50, "slow_window": 150}, "label": "Mom(50,150)"},
        {"strategy": "momentum", "params": {"fast_window": 50, "slow_window": 200}, "label": "Mom(50,200)"},
        # 4. Trend Following
        {"strategy": "trend_following", "params": {"short_window": 10, "medium_window": 50, "long_window": 100}, "label": "Trend(10,50,100)"},
        {"strategy": "trend_following", "params": {"short_window": 5, "medium_window": 20, "long_window": 50}, "label": "Trend(5,20,50)"},
        # 5. Breakout
        {"strategy": "breakout", "params": {"window": 10, "threshold_pct": 0.01}, "label": "Breakout(10,1%)"},
        {"strategy": "breakout", "params": {"window": 20, "threshold_pct": 0.02}, "label": "Breakout(20,2%)"},
        # 6. Volatility Filter
        {"strategy": "volatility", "params": {"window": 21, "vol_threshold": 0.20}, "label": "VolFilter(21,0.20)"},
        # 7. Regime Based
        {"strategy": "regime_based", "params": {"regime_data": "bull_momentum"}, "label": "Regime(BullMom)"},
        {"strategy": "regime_based", "params": {"regime_data": "bear_mean_reversion"}, "label": "Regime(BearMR)"},
    ]

    results = []

    for ticker in assets:
        df = ohlcv_dict[ticker]
        c = close_dict[ticker]
        daily_ret = c.pct_change().fillna(0)

        # Benchmark
        bnh_eq = (1 + daily_ret).cumprod() * initial_capital
        bnh_final = float(bnh_eq.iloc[-1])
        bnh_metrics = PerformanceMetrics.from_equity(bnh_eq)

        for cfg in configs_to_test:
            strat_name = cfg["strategy"]
            params = cfg["params"]
            label = cfg["label"]

            strat = STRATEGY_REGISTRY[strat_name]
            try:
                signal = strat.generate_signal(df, params)
                signal = signal.reindex(c.index).fillna(0)
            except Exception as e:
                print(f"Error on {strat_name} on {ticker}: {e}")
                continue

            # Ensure long-only for fair prop-firm comparison (shorting was already proven negative on indexes)
            # Clip negative signals to 0 so we test pure long exposures
            signal_long = signal.clip(lower=0)

            costs = _apply_transaction_costs(
                signal_long,
                config.backtest.commission,
                config.backtest.slippage,
                config.backtest.market_impact_bps,
            )

            strat_ret = daily_ret * signal_long.shift(1).fillna(0) - costs
            equity = (1 + strat_ret).cumprod() * initial_capital
            final_val = float(equity.iloc[-1])
            total_profit_usd = final_val - initial_capital
            total_return_pct = (total_profit_usd / initial_capital) * 100.0

            trader_share_usd = total_profit_usd * trader_split
            trader_share_ngn = trader_share_usd * naira_rate

            metrics = PerformanceMetrics.from_equity(equity)
            max_dd_pct = float(metrics.get("max_drawdown", 0.0)) * 100.0
            max_dd_usd = float(metrics.get("max_drawdown", 0.0)) * initial_capital

            trades_count = int(signal_long.diff().abs().sum() / 2)

            # Trades breakdown
            trades = []
            in_pos = 0
            entry_dt = None
            entry_p = 0.0
            bars_held = 0

            for dt in c.index:
                pos = signal_long.loc[dt]
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
                        ret = (exit_p - entry_p) / entry_p
                        trades.append({
                            "entry_date": entry_dt.strftime("%Y-%m-%d"),
                            "exit_date": exit_dt.strftime("%Y-%m-%d"),
                            "bars_held": bars_held,
                            "entry_price": float(entry_p),
                            "exit_price": float(exit_p),
                            "return_pct": float(ret * 100.0),
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

            # Calmar ratio: annual return / max drawdown
            annual_ret = ((final_val / initial_capital) ** (1.0 / 10.0) - 1.0) * 100.0
            calmar_prop = (annual_ret / max_dd_pct) if max_dd_pct > 0 else 0.0

            results.append({
                "asset": ticker,
                "strategy": strat_name,
                "label": label,
                "params": params,
                "final_balance": round(final_val, 2),
                "total_profit_usd": round(total_profit_usd, 2),
                "total_return_pct": round(total_return_pct, 2),
                "annual_cagr_pct": round(annual_ret, 2),
                "trader_takehome_10y_usd": round(trader_share_usd, 2),
                "trader_takehome_10y_ngn": round(trader_share_ngn, 0),
                "monthly_takehome_usd": round(trader_share_usd / 120.0, 2),
                "monthly_takehome_ngn": round(trader_share_ngn / 120.0, 0),
                "sharpe": round(float(metrics.get("sharpe", 0.0)), 2),
                "sortino": round(float(metrics.get("sortino", 0.0)), 2),
                "calmar": round(calmar_prop, 2),
                "max_drawdown_pct": round(max_dd_pct, 2),
                "max_drawdown_usd": round(max_dd_usd, 2),
                "total_trades": len(trades),
                "win_rate_pct": round(win_rate, 1),
            })

    # Sort by Sharpe and Calmar (Risk-adjusted return)
    by_sharpe = sorted(results, key=lambda x: (x["sharpe"], x["total_profit_usd"]), reverse=True)
    # Sort by total profit
    by_profit = sorted(results, key=lambda x: (x["total_profit_usd"]), reverse=True)

    print("\n" + "=" * 110)
    print("            TOP 12 STRATEGIES ACROSS 10 YEARS (BY SHARPE & RISK-ADJUSTED RETURN)")
    print("=" * 110)
    header = f"{'Rank':<4} {'Asset':<5} {'Strategy Label':<22} {'10-Yr Profit':<14} {'Monthly (USD)':<14} {'Monthly (NGN)':<16} {'Sharpe':<7} {'MaxDD %':<8} {'Trades':<7} {'Win %'}"
    print(header)
    print("-" * 110)
    for idx, r in enumerate(by_sharpe[:12], 1):
        print(f"{idx:<4} {r['asset']:<5} {r['label']:<22} ${r['total_profit_usd']:<13,.2f} ${r['monthly_takehome_usd']:<13,.2f} ₦{r['monthly_takehome_ngn']:<15,.0f} {r['sharpe']:<7.2f} {r['max_drawdown_pct']:<8.2f} {r['total_trades']:<7} {r['win_rate_pct']:<5.1f}%")

    print("\n" + "=" * 110)
    print("                 TOP 12 STRATEGIES ACROSS 10 YEARS (BY TOTAL ABSOLUTE PROFIT)")
    print("=" * 110)
    print(header)
    print("-" * 110)
    for idx, r in enumerate(by_profit[:12], 1):
        print(f"{idx:<4} {r['asset']:<5} {r['label']:<22} ${r['total_profit_usd']:<13,.2f} ${r['monthly_takehome_usd']:<13,.2f} ₦{r['monthly_takehome_ngn']:<15,.0f} {r['sharpe']:<7.2f} {r['max_drawdown_pct']:<8.2f} {r['total_trades']:<7} {r['win_rate_pct']:<5.1f}%")

    out_file = Path("results/compare_10year_all_strategies.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        json.dump({
            "metadata": {
                "initial_capital": initial_capital,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "trading_days": total_bars,
            },
            "by_sharpe": by_sharpe,
            "by_profit": by_profit,
        }, f, indent=2, cls=NumpyEncoder)

    print(f"\nReport saved to: {out_file.resolve()}")
    return by_sharpe, by_profit


if __name__ == "__main__":
    run_10year_strategy_search()
