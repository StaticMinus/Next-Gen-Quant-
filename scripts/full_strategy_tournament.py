"""
Full Strategy Tournament — AgentQuant Multi-Asset, Multi-Strategy Evaluation
==========================================================================
Evaluates 32 strategy/parameter configurations across 5 assets (SPY, QQQ, IWM, TLT, GLD)
over the trailing 1-year period (160 backtest combinations total).
"""

import os
import sys
import json
import logging
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
from src.strategies.strategy_registry import STRATEGY_REGISTRY
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


def get_tournament_strategies() -> List[Dict[str, Any]]:
    return [
        # Momentum (10 grids)
        {"strategy": "momentum", "params": {"fast_window": 5, "slow_window": 20}, "label": "Mom(5,20)"},
        {"strategy": "momentum", "params": {"fast_window": 10, "slow_window": 30}, "label": "Mom(10,30)"},
        {"strategy": "momentum", "params": {"fast_window": 10, "slow_window": 50}, "label": "Mom(10,50)"},
        {"strategy": "momentum", "params": {"fast_window": 15, "slow_window": 80}, "label": "Mom(15,80)"},
        {"strategy": "momentum", "params": {"fast_window": 17, "slow_window": 91}, "label": "Mom(17,91)"},
        {"strategy": "momentum", "params": {"fast_window": 20, "slow_window": 60}, "label": "Mom(20,60)"},
        {"strategy": "momentum", "params": {"fast_window": 20, "slow_window": 100}, "label": "Mom(20,100)"},
        {"strategy": "momentum", "params": {"fast_window": 50, "slow_window": 150}, "label": "Mom(50,150)"},
        {"strategy": "momentum", "params": {"fast_window": 50, "slow_window": 200}, "label": "Mom(50,200)"},
        {"strategy": "momentum", "params": {"fast_window": 63, "slow_window": 252}, "label": "Mom(63,252)"},
        # Mean Reversion (5 grids)
        {"strategy": "mean_reversion", "params": {"window": 10, "num_std": 1.5}, "label": "MR(10,1.5s)"},
        {"strategy": "mean_reversion", "params": {"window": 15, "num_std": 2.0}, "label": "MR(15,2.0s)"},
        {"strategy": "mean_reversion", "params": {"window": 20, "num_std": 2.0}, "label": "MR(20,2.0s)"},
        {"strategy": "mean_reversion", "params": {"window": 20, "num_std": 2.5}, "label": "MR(20,2.5s)"},
        {"strategy": "mean_reversion", "params": {"window": 30, "num_std": 3.0}, "label": "MR(30,3.0s)"},
        # Volatility (3 grids)
        {"strategy": "volatility", "params": {"window": 10, "vol_threshold": 0.15}, "label": "Vol(10,0.15)"},
        {"strategy": "volatility", "params": {"window": 21, "vol_threshold": 0.20}, "label": "Vol(21,0.20)"},
        {"strategy": "volatility", "params": {"window": 42, "vol_threshold": 0.25}, "label": "Vol(42,0.25)"},
        # Trend Following (3 grids)
        {"strategy": "trend_following", "params": {"short_window": 5, "medium_window": 20, "long_window": 50}, "label": "Trend(5,20,50)"},
        {"strategy": "trend_following", "params": {"short_window": 10, "medium_window": 50, "long_window": 100}, "label": "Trend(10,50,100)"},
        {"strategy": "trend_following", "params": {"short_window": 15, "medium_window": 60, "long_window": 150}, "label": "Trend(15,60,150)"},
        # Breakout (3 grids)
        {"strategy": "breakout", "params": {"window": 10, "threshold_pct": 0.01}, "label": "Break(10,1%)"},
        {"strategy": "breakout", "params": {"window": 20, "threshold_pct": 0.02}, "label": "Break(20,2%)"},
        {"strategy": "breakout", "params": {"window": 40, "threshold_pct": 0.03}, "label": "Break(40,3%)"},
        # Regime Based (3 grids)
        {"strategy": "regime_based", "params": {"regime_data": "bull_uptrend"}, "label": "Regime(Bull)"},
        {"strategy": "regime_based", "params": {"regime_data": "bear_downtrend"}, "label": "Regime(Bear)"},
        {"strategy": "regime_based", "params": {"regime_data": "crisis_highvol"}, "label": "Regime(Crisis)"},
        # Scalper (5 grids)
        {"strategy": "scalper", "params": {"window": 3, "num_std": 1.0, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.02, "max_hold_bars": 3}, "label": "Scalp(3d,1.0s,L)"},
        {"strategy": "scalper", "params": {"window": 5, "num_std": 1.0, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}, "label": "Scalp(5d,1.0s,L)"},
        {"strategy": "scalper", "params": {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}, "label": "Scalp(5d,1.25s,L)"},
        {"strategy": "scalper", "params": {"window": 10, "num_std": 1.5, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.04, "max_hold_bars": 8}, "label": "Scalp(10d,1.5s,L)"},
        {"strategy": "scalper", "params": {"window": 5, "num_std": 1.0, "exit_at_mean": True, "allow_short": True, "stop_loss_pct": 0.03, "max_hold_bars": 5}, "label": "Scalp(5d,1.0s,LS)"},
    ]


def run_tournament():
    print("=" * 75)
    print("       AGENTQUANT EXHAUSTIVE STRATEGY TOURNAMENT (1-YEAR)")
    print("=" * 75)

    assets = ["SPY", "QQQ", "IWM", "TLT", "GLD"]
    initial_cash = 100.0
    configs = get_tournament_strategies()

    print(f"Universe: {', '.join(assets)}")
    print(f"Strategy configs: {len(configs)}")
    print(f"Total backtests: {len(assets) * len(configs)}")
    print(f"Starting capital per run: ${initial_cash:.2f}")

    # Load data for all assets
    ohlcv_dict = {}
    close_dict = {}
    for asset in assets:
        data = fetch_ohlcv_data(ticker=asset)
        df = data[asset]
        ohlcv_dict[asset] = df
        close_dict[asset] = _get_close(df)

    # Standardized 1-year evaluation period (use SPY as reference)
    ref_close = close_dict["SPY"]
    end_date = ref_close.index.max()
    eval_start_date = end_date - pd.DateOffset(years=1)
    eval_slice = ref_close.loc[ref_close.index >= eval_start_date]
    actual_start = eval_slice.index[0]

    print(f"Evaluation Period: {actual_start.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} ({len(eval_slice)} trading days)")

    # Run benchmarks (Buy & Hold for each asset)
    benchmarks = {}
    for asset in assets:
        c = close_dict[asset]
        c_1y = c.loc[c.index >= actual_start]
        bnh_ret = c.pct_change().loc[c.index >= actual_start].fillna(0)
        # Apply entry transaction cost
        bnh_cost = config.backtest.commission + config.backtest.slippage
        bnh_ret.iloc[0] -= bnh_cost
        bnh_equity = (1 + bnh_ret).cumprod() * initial_cash
        bnh_metrics = PerformanceMetrics.from_equity(bnh_equity)
        final_val = float(bnh_equity.iloc[-1])
        benchmarks[asset] = {
            "asset": asset,
            "final_value": round(final_val, 2),
            "net_pnl": round(final_val - initial_cash, 2),
            "pnl_pct": round((final_val - initial_cash) / initial_cash * 100.0, 2),
            "sharpe": round(float(bnh_metrics.get("sharpe", 0.0)), 2),
            "sortino": round(float(bnh_metrics.get("sortino", 0.0)), 2),
            "calmar": round(float(bnh_metrics.get("calmar", 0.0)), 2),
            "max_drawdown_pct": round(float(bnh_metrics.get("max_drawdown", 0.0)) * 100.0, 2),
        }

    print("\nBenchmark Buy & Hold Performance (1 Year, $100):")
    for asset, b in benchmarks.items():
        print(f"  {asset:<5} -> ${b['final_value']:.2f} ({b['pnl_pct']:+6.2f}%) | Sharpe: {b['sharpe']:4.2f} | MaxDD: {b['max_drawdown_pct']:5.2f}%")

    # Run tournament
    all_results = []
    print("\nRunning tournament evaluations...")

    for asset in assets:
        df = ohlcv_dict[asset]
        c = close_dict[asset]
        daily_ret = c.pct_change().fillna(0)

        for cfg in configs:
            strat_name = cfg["strategy"]
            params = cfg["params"]
            label = cfg["label"]

            strat = STRATEGY_REGISTRY[strat_name]
            try:
                signal = strat.generate_signal(df, params)
                signal = signal.reindex(c.index).fillna(0)
            except Exception as e:
                print(f"Error generating signal for {strat_name} on {asset}: {e}")
                continue

            costs = _apply_transaction_costs(
                signal,
                config.backtest.commission,
                config.backtest.slippage,
                config.backtest.market_impact_bps,
            )

            strat_ret = daily_ret * signal.shift(1).fillna(0) - costs
            strat_ret_1y = strat_ret.loc[strat_ret.index >= actual_start]
            signal_1y = signal.loc[signal.index >= actual_start]
            c_1y = c.loc[c.index >= actual_start]

            equity_1y = (1 + strat_ret_1y).cumprod() * initial_cash
            final_val = float(equity_1y.iloc[-1])
            net_pnl = final_val - initial_cash
            pnl_pct = (net_pnl / initial_cash) * 100.0

            metrics = PerformanceMetrics.from_equity(equity_1y)
            trades_count = int(signal_1y.diff().abs().sum() / 2)

            # Trade return distribution
            # Calculate win rate and trade returns
            in_pos = 0
            entry_p = 0.0
            trade_returns = []
            for dt, pos in signal_1y.items():
                if in_pos == 0 and pos != 0:
                    in_pos = pos
                    entry_p = c_1y.loc[dt]
                elif in_pos != 0 and pos != in_pos:
                    exit_p = c_1y.loc[dt]
                    ret = ((exit_p - entry_p) / entry_p) * in_pos
                    trade_returns.append(ret)
                    in_pos = pos
                    entry_p = exit_p

            win_count = sum(1 for r in trade_returns if r > 0)
            win_rate = (win_count / len(trade_returns) * 100.0) if trade_returns else 0.0

            all_results.append({
                "asset": asset,
                "strategy": strat_name,
                "label": label,
                "params": params,
                "final_value": round(final_val, 2),
                "net_pnl": round(net_pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "sharpe": round(float(metrics.get("sharpe", 0.0)), 2),
                "sortino": round(float(metrics.get("sortino", 0.0)), 2),
                "calmar": round(float(metrics.get("calmar", 0.0)), 2),
                "max_drawdown_pct": round(float(metrics.get("max_drawdown", 0.0)) * 100.0, 2),
                "trades": trades_count,
                "completed_trades": len(trade_returns),
                "win_rate_pct": round(win_rate, 1),
                "excess_vs_bnh_pct": round(pnl_pct - benchmarks[asset]["pnl_pct"], 2),
            })

    print(f"Successfully evaluated {len(all_results)} backtest simulations!")

    # Sort leaderboard by Sharpe, then Sortino, then P/L
    leaderboard_sharpe = sorted(all_results, key=lambda x: (x["sharpe"], x["sortino"], x["pnl_pct"]), reverse=True)
    leaderboard_return = sorted(all_results, key=lambda x: (x["pnl_pct"], x["sharpe"]), reverse=True)

    # Best per asset
    best_per_asset = {}
    for asset in assets:
        asset_res = [r for r in all_results if r["asset"] == asset]
        asset_res.sort(key=lambda x: (x["sharpe"], x["pnl_pct"]), reverse=True)
        best_per_asset[asset] = asset_res[0]

    # Best per strategy family across all assets
    best_per_family = {}
    strat_families = ["momentum", "mean_reversion", "volatility", "trend_following", "breakout", "regime_based", "scalper"]
    for fam in strat_families:
        fam_res = [r for r in all_results if r["strategy"] == fam]
        fam_res.sort(key=lambda x: (x["sharpe"], x["pnl_pct"]), reverse=True)
        if fam_res:
            best_per_family[fam] = fam_res[0]

    # Save to results JSON
    out_dir = Path("results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "full_strategy_tournament.json"

    payload = {
        "tournament_metadata": {
            "evaluation_start": actual_start.strftime("%Y-%m-%d"),
            "evaluation_end": end_date.strftime("%Y-%m-%d"),
            "trading_days": len(eval_slice),
            "initial_cash": initial_cash,
            "total_simulations": len(all_results),
            "assets_tested": assets,
            "strategies_tested": strat_families,
        },
        "benchmarks": benchmarks,
        "best_per_asset": best_per_asset,
        "best_per_strategy_family": best_per_family,
        "top_25_by_sharpe": leaderboard_sharpe[:25],
        "top_25_by_return": leaderboard_return[:25],
        "all_results": all_results,
    }

    with open(out_file, "w") as f:
        json.dump(payload, f, indent=2, cls=NumpyEncoder)

    print("\n" + "=" * 80)
    print("                    TOP 15 OVERALL (BY SHARPE RATIO)")
    print("=" * 80)
    header = f"{'Rank':<4} {'Asset':<5} {'Strategy Label':<20} {'Return %':<10} {'Final $':<9} {'Sharpe':<7} {'Sortino':<8} {'MaxDD %':<8} {'Trades':<6} {'Win %':<6}"
    print(header)
    print("-" * 80)
    for idx, r in enumerate(leaderboard_sharpe[:15], 1):
        print(f"{idx:<4} {r['asset']:<5} {r['label']:<20} {r['pnl_pct']:+8.2f}% ${r['final_value']:<8.2f} {r['sharpe']:<7.2f} {r['sortino']:<8.2f} {r['max_drawdown_pct']:<8.2f} {r['trades']:<6} {r['win_rate_pct']:<6.1f}%")

    print("\n" + "=" * 80)
    print("                    TOP 15 OVERALL (BY TOTAL RETURN %)")
    print("=" * 80)
    print(header)
    print("-" * 80)
    for idx, r in enumerate(leaderboard_return[:15], 1):
        print(f"{idx:<4} {r['asset']:<5} {r['label']:<20} {r['pnl_pct']:+8.2f}% ${r['final_value']:<8.2f} {r['sharpe']:<7.2f} {r['sortino']:<8.2f} {r['max_drawdown_pct']:<8.2f} {r['trades']:<6} {r['win_rate_pct']:<6.1f}%")

    print("\n" + "=" * 80)
    print("                     BEST STRATEGY PER ASSET")
    print("=" * 80)
    for asset, b in best_per_asset.items():
        bnh = benchmarks[asset]
        print(f"Asset: {asset:<5} | Winner: {b['label']:<18} | Ret: {b['pnl_pct']:+6.2f}% (B&H: {bnh['pnl_pct']:+6.2f}%) | Sharpe: {b['sharpe']:.2f} (B&H: {bnh['sharpe']:.2f}) | DD: {b['max_drawdown_pct']:.2f}% | Trades: {b['trades']}")

    print(f"\nTournament results successfully exported to: {out_file.resolve()}")
    return payload


if __name__ == "__main__":
    run_tournament()
