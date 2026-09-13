"""
$50 Scalper Strategy Backtest Simulation — AgentQuant
=====================================================
Simulates an aggressive, fast-turnaround daily scalper with $50 starting capital.
Evaluates across liquid ETFs (SPY, QQQ, IWM), generates detailed monthly P/L,
trade-by-trade execution log, win rate, profit factor, and comparison with Buy & Hold.
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


def run_scalper_50_simulation():
    print("=" * 75)
    print("         AGENTQUANT $50 ACCOUNT SCALPER SIMULATION (1-YEAR)")
    print("=" * 75)

    initial_capital = 50.0
    config.backtest.initial_cash = initial_capital
    assets = ["SPY", "QQQ", "IWM"]

    scalper_variants = [
        {
            "name": "Ultra-Aggressive Scalper",
            "params": {"window": 3, "num_std": 1.0, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.02, "max_hold_bars": 3},
            "desc": "3-day lookback, 1.0s bands, 2% stop loss, 3-day max hold",
        },
        {
            "name": "Aggressive Scalper",
            "params": {"window": 5, "num_std": 1.0, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5},
            "desc": "5-day lookback, 1.0s bands, 3% stop loss, 5-day max hold",
        },
        {
            "name": "Balanced Scalper",
            "params": {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5},
            "desc": "5-day lookback, 1.25s bands, 3% stop loss, 5-day max hold",
        },
        {
            "name": "Conservative Scalper",
            "params": {"window": 10, "num_std": 1.5, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.04, "max_hold_bars": 8},
            "desc": "10-day lookback, 1.5s bands, 4% stop loss, 8-day max hold",
        },
        {
            "name": "Long+Short Scalper",
            "params": {"window": 5, "num_std": 1.0, "exit_at_mean": True, "allow_short": True, "stop_loss_pct": 0.03, "max_hold_bars": 5},
            "desc": "5-day lookback, 1.0s bands, long on dips + short on spikes",
        },
    ]

    scalper = ScalperStrategy()

    # Load data
    ohlcv_dict = {}
    close_dict = {}
    for a in assets:
        data = fetch_ohlcv_data(ticker=a)
        df = data[a]
        ohlcv_dict[a] = df
        close_dict[a] = _get_close(df)

    ref_close = close_dict["SPY"]
    end_date = ref_close.index.max()
    eval_start_date = end_date - pd.DateOffset(years=1)
    actual_start = ref_close.loc[ref_close.index >= eval_start_date].index[0]
    eval_slice = ref_close.loc[ref_close.index >= actual_start]

    print(f"Initial Starting Capital: ${initial_capital:.2f}")
    print(f"Backtest Period:          {actual_start.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} ({len(eval_slice)} trading days)")
    print(f"Assets Evaluated:         {', '.join(assets)}")

    results = []

    for asset in assets:
        df = ohlcv_dict[asset]
        c = close_dict[asset]
        c_1y = c.loc[c.index >= actual_start]
        daily_ret = c.pct_change().fillna(0)

        # Benchmark Buy & Hold
        bnh_ret = daily_ret.loc[c.index >= actual_start].copy()
        bnh_cost = config.backtest.commission + config.backtest.slippage
        bnh_ret.iloc[0] -= bnh_cost
        bnh_equity = (1 + bnh_ret).cumprod() * initial_capital
        bnh_final = float(bnh_equity.iloc[-1])
        bnh_metrics = PerformanceMetrics.from_equity(bnh_equity)

        for v in scalper_variants:
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
            strat_ret_1y = strat_ret.loc[strat_ret.index >= actual_start]
            signal_1y = signal.loc[signal.index >= actual_start]

            equity_1y = (1 + strat_ret_1y).cumprod() * initial_capital
            final_val = float(equity_1y.iloc[-1])
            net_pnl = final_val - initial_capital
            pnl_pct = (net_pnl / initial_capital) * 100.0

            metrics = PerformanceMetrics.from_equity(equity_1y)
            trades_count = int(signal_1y.diff().abs().sum() / 2)

            # Reconstruct Trade-by-trade history with entry, exit, duration, reason
            # Compute mid, upper, lower for the asset
            window = params.get("window", 5)
            num_std = params.get("num_std", 1.0)
            mid = c.rolling(window).mean()
            std = c.rolling(window).std()
            upper = mid + num_std * std
            lower = mid - num_std * std

            trades = []
            in_pos = 0
            entry_dt = None
            entry_p = 0.0
            bars_in_trade = 0

            for dt in c_1y.index:
                pos = signal_1y.loc[dt]
                price = c_1y.loc[dt]

                if in_pos == 0 and pos != 0:
                    in_pos = pos
                    entry_dt = dt
                    entry_p = price
                    bars_in_trade = 0
                elif in_pos != 0:
                    bars_in_trade += 1
                    if pos != in_pos:
                        # Exit occurred
                        exit_dt = dt
                        exit_p = price
                        ret = ((exit_p - entry_p) / entry_p) * in_pos
                        # Infer exit reason
                        m = mid.loc[dt]
                        u = upper.loc[dt]
                        l = lower.loc[dt]
                        sl_thresh = entry_p * (1.0 - params.get("stop_loss_pct", 0.03)) if in_pos == 1 else entry_p * (1.0 + params.get("stop_loss_pct", 0.03))
                        
                        if in_pos == 1:
                            if exit_p >= m:
                                reason = "Mean Reversion Take-Profit"
                            elif exit_p <= sl_thresh:
                                reason = "Stop Loss Hit"
                            else:
                                reason = "Time Timeout Exit"
                        else:
                            if exit_p <= m:
                                reason = "Mean Reversion Take-Profit"
                            elif exit_p >= sl_thresh:
                                reason = "Stop Loss Hit"
                            else:
                                reason = "Time Timeout Exit"

                        trades.append({
                            "type": "LONG" if in_pos == 1 else "SHORT",
                            "entry_date": entry_dt.strftime("%Y-%m-%d"),
                            "exit_date": exit_dt.strftime("%Y-%m-%d"),
                            "bars_held": bars_in_trade,
                            "entry_price": round(float(entry_p), 2),
                            "exit_price": round(float(exit_p), 2),
                            "return_pct": round(float(ret * 100.0), 2),
                            "profit_dollars": round(float(initial_capital * ret), 3),
                            "profitable": ret > 0,
                            "reason": reason,
                        })

                        if pos != 0:
                            in_pos = pos
                            entry_dt = dt
                            entry_p = price
                            bars_in_trade = 0
                        else:
                            in_pos = 0

            # If still in trade at end
            if in_pos != 0:
                exit_dt = c_1y.index[-1]
                exit_p = c_1y.iloc[-1]
                ret = ((exit_p - entry_p) / entry_p) * in_pos
                trades.append({
                    "type": "LONG" if in_pos == 1 else "SHORT",
                    "entry_date": entry_dt.strftime("%Y-%m-%d"),
                    "exit_date": exit_dt.strftime("%Y-%m-%d (open)"),
                    "bars_held": bars_in_trade,
                    "entry_price": round(float(entry_p), 2),
                    "exit_price": round(float(exit_p), 2),
                    "return_pct": round(float(ret * 100.0), 2),
                    "profit_dollars": round(float(initial_capital * ret), 3),
                    "profitable": ret > 0,
                    "reason": "Still Open",
                })

            wins = [t for t in trades if t["profitable"]]
            losses = [t for t in trades if not t["profitable"]]
            win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
            sum_win = sum(t["return_pct"] for t in wins)
            sum_loss = abs(sum(t["return_pct"] for t in losses))
            profit_factor = (sum_win / sum_loss) if sum_loss > 0 else (999.0 if sum_win > 0 else 0.0)

            # Monthly breakdown
            monthly_ret = strat_ret_1y.resample("ME").apply(lambda r: (1 + r).prod() - 1)
            monthly_breakdown = []
            curr_val = initial_capital
            for dt, r in monthly_ret.items():
                prev_val = curr_val
                curr_val = curr_val * (1 + r)
                monthly_breakdown.append({
                    "month": dt.strftime("%Y-%m"),
                    "monthly_return_pct": round(float(r * 100.0), 2),
                    "monthly_pnl_dollars": round(float(curr_val - prev_val), 2),
                    "balance": round(float(curr_val), 2),
                })

            results.append({
                "asset": asset,
                "variant_name": v_name,
                "description": v["desc"],
                "params": params,
                "starting_balance": initial_capital,
                "final_balance": round(final_val, 2),
                "net_pnl_dollars": round(net_pnl, 2),
                "net_pnl_pct": round(pnl_pct, 2),
                "sharpe": round(float(metrics.get("sharpe", 0.0)), 2),
                "sortino": round(float(metrics.get("sortino", 0.0)), 2),
                "calmar": round(float(metrics.get("calmar", 0.0)), 2),
                "max_drawdown_pct": round(float(metrics.get("max_drawdown", 0.0)) * 100.0, 2),
                "max_drawdown_dollars": round(float(metrics.get("max_drawdown", 0.0)) * initial_capital, 2),
                "total_trades": len(trades),
                "win_rate_pct": round(win_rate, 1),
                "profit_factor": round(profit_factor, 2),
                "avg_bars_held": round(float(np.mean([t["bars_held"] for t in trades])), 1) if trades else 0.0,
                "benchmark": {
                    "final_balance": round(bnh_final, 2),
                    "net_pnl_dollars": round(bnh_final - initial_capital, 2),
                    "pnl_pct": round((bnh_final - initial_capital) / initial_capital * 100.0, 2),
                    "sharpe": round(float(bnh_metrics.get("sharpe", 0.0)), 2),
                    "max_drawdown_pct": round(float(bnh_metrics.get("max_drawdown", 0.0)) * 100.0, 2),
                },
                "monthly_breakdown": monthly_breakdown,
                "trades": trades,
            })

    # Sort results by Sharpe ratio
    results.sort(key=lambda x: (x["sharpe"], x["net_pnl_pct"]), reverse=True)
    best = results[0]

    # Export to JSON
    out_dir = Path("results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "scalper_50_dollar_report.json"

    payload = {
        "metadata": {
            "initial_capital": initial_capital,
            "period_start": actual_start.strftime("%Y-%m-%d"),
            "period_end": end_date.strftime("%Y-%m-%d"),
            "trading_days": len(eval_slice),
        },
        "best_scalper": best,
        "all_scalper_runs": results,
    }

    with open(out_file, "w") as f:
        json.dump(payload, f, indent=2, cls=NumpyEncoder)

    print("\n" + "=" * 85)
    print("                    $50 SCALPER LEADERBOARD (ALL VARIANTS & ASSETS)")
    print("=" * 85)
    header = f"{'Rank':<4} {'Asset':<5} {'Scalper Variant':<24} {'Final $':<8} {'P/L %':<9} {'Sharpe':<7} {'MaxDD %':<8} {'Trades':<7} {'Win %':<6} {'PF':<5}"
    print(header)
    print("-" * 85)
    for idx, r in enumerate(results, 1):
        print(f"{idx:<4} {r['asset']:<5} {r['variant_name']:<24} ${r['final_balance']:<7.2f} {r['net_pnl_pct']:+7.2f}% {r['sharpe']:<7.2f} {r['max_drawdown_pct']:<8.2f} {r['total_trades']:<7} {r['win_rate_pct']:<6.1f}% {r['profit_factor']:<5.2f}")

    print("\n" + "=" * 85)
    print(f"BEST SCALPER WINNER: {best['variant_name']} on {best['asset']}")
    print("=" * 85)
    print(f"Starting Capital:   ${best['starting_balance']:.2f}")
    print(f"Ending Balance:     ${best['final_balance']:.2f}")
    print(f"Net Profit / Loss:  ${best['net_pnl_dollars']:+.2f} ({best['net_pnl_pct']:+.2f}%)")
    print(f"Sharpe Ratio:       {best['sharpe']:.2f} (vs Benchmark: {best['benchmark']['sharpe']:.2f})")
    print(f"Max Drawdown:       {best['max_drawdown_pct']:.2f}% (${best['max_drawdown_dollars']:.2f})")
    print(f"Total Trades:       {best['total_trades']} (Win Rate: {best['win_rate_pct']}%, Profit Factor: {best['profit_factor']})")
    print(f"Avg Holding Period: {best['avg_bars_held']} trading days")
    print(f"\nReport exported to: {out_file.resolve()}")

    return payload


if __name__ == "__main__":
    run_scalper_50_simulation()
