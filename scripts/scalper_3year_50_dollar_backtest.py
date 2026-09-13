"""
3-Year $50 Scalper & Shorting Backtest Simulation — AgentQuant
=============================================================
Evaluates $50 starting capital over a 3-Year period (756 trading days)
comparing Long-Only, Naive Long+Short, and Smart Trend-Filtered Long+Short.
Also includes a 5-Minute Intraday Scalper section to evaluate multiple trades per day.
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


def run_3year_simulation():
    print("=" * 80)
    print("      AGENTQUANT 3-YEAR $50 SCALPING & SHORTING SIMULATION (2023 - 2026)")
    print("=" * 80)

    initial_capital = 50.0
    config.backtest.initial_cash = initial_capital
    assets = ["SPY", "QQQ", "IWM"]

    # Load 5-year cached data
    ohlcv_dict = {}
    close_dict = {}
    for a in assets:
        data = fetch_ohlcv_data(ticker=a)
        df = data[a]
        ohlcv_dict[a] = df
        close_dict[a] = _get_close(df)

    ref_close = close_dict["SPY"]
    end_date = ref_close.index.max()
    eval_start_date = end_date - pd.DateOffset(years=3)
    actual_start = ref_close.loc[ref_close.index >= eval_start_date].index[0]
    eval_slice = ref_close.loc[ref_close.index >= actual_start]

    print(f"Initial Starting Capital: ${initial_capital:.2f}")
    print(f"Backtest 3-Year Window:   {actual_start.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} ({len(eval_slice)} trading days)")
    print(f"Assets Evaluated:         {', '.join(assets)}")

    # Define Configurations to Test (Long-Only vs Naive Short vs Smart Short)
    variants = [
        {
            "name": "Balanced Long-Only",
            "params": {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5},
            "desc": "Long-only on 1.25s dips, exit at 5d MA",
        },
        {
            "name": "Aggressive Long-Only",
            "params": {"window": 5, "num_std": 1.0, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5},
            "desc": "Long-only on 1.0s dips, exit at 5d MA",
        },
        {
            "name": "Naive Long+Short",
            "params": {"window": 5, "num_std": 1.0, "exit_at_mean": True, "allow_short": True, "stop_loss_pct": 0.03, "max_hold_bars": 5},
            "desc": "Long on 1.0s dips + Short on 1.0s spikes (no filter)",
        },
        {
            "name": "Smart Long+Short (Trend Filtered)",
            "params": {
                "window": 5,
                "num_std": 1.0,
                "exit_at_mean": True,
                "allow_short": True,
                "stop_loss_pct": 0.03,
                "short_stop_loss_pct": 0.02,
                "trend_filter": True,
                "trend_window": 50,
                "max_hold_bars": 5,
            },
            "desc": "Long above 50d MA, Short below 50d MA, tight 2% short stop",
        },
        {
            "name": "Fast Smart Long+Short (3-Day)",
            "params": {
                "window": 3,
                "num_std": 1.0,
                "exit_at_mean": True,
                "allow_short": True,
                "stop_loss_pct": 0.02,
                "short_stop_loss_pct": 0.015,
                "trend_filter": True,
                "trend_window": 30,
                "max_hold_bars": 3,
            },
            "desc": "3d lookback, fast turnover, tight 1.5% short stop, trend-filtered",
        },
    ]

    scalper = ScalperStrategy()
    results = []

    # Benchmark Buy & Hold across 3 years
    benchmarks = {}
    for asset in assets:
        c = close_dict[asset]
        daily_ret = c.pct_change().fillna(0)
        bnh_ret = daily_ret.loc[c.index >= actual_start].copy()
        bnh_cost = config.backtest.commission + config.backtest.slippage
        bnh_ret.iloc[0] -= bnh_cost
        bnh_equity = (1 + bnh_ret).cumprod() * initial_capital
        bnh_final = float(bnh_equity.iloc[-1])
        bnh_metrics = PerformanceMetrics.from_equity(bnh_equity)
        benchmarks[asset] = {
            "final_balance": round(bnh_final, 2),
            "net_pnl_dollars": round(bnh_final - initial_capital, 2),
            "pnl_pct": round((bnh_final - initial_capital) / initial_capital * 100.0, 2),
            "sharpe": round(float(bnh_metrics.get("sharpe", 0.0)), 2),
            "max_drawdown_pct": round(float(bnh_metrics.get("max_drawdown", 0.0)) * 100.0, 2),
        }

    print("\n3-Year Benchmark Buy & Hold ($50 Starting Capital):")
    for asset, b in benchmarks.items():
        print(f"  {asset:<5} -> ${b['final_balance']:.2f} ({b['pnl_pct']:+6.2f}%) | Sharpe: {b['sharpe']:4.2f} | MaxDD: {b['max_drawdown_pct']:5.2f}%")

    print("\nSimulating 3-Year Scalper Configurations...")
    for asset in assets:
        df = ohlcv_dict[asset]
        c = close_dict[asset]
        c_3y = c.loc[c.index >= actual_start]
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
            strat_ret_3y = strat_ret.loc[strat_ret.index >= actual_start]
            signal_3y = signal.loc[signal.index >= actual_start]

            equity_3y = (1 + strat_ret_3y).cumprod() * initial_capital
            final_val = float(equity_3y.iloc[-1])
            net_pnl = final_val - initial_capital
            pnl_pct = (net_pnl / initial_capital) * 100.0

            metrics = PerformanceMetrics.from_equity(equity_3y)

            # Reconstruct Trade-by-trade details
            trades = []
            long_trades = []
            short_trades = []
            in_pos = 0
            entry_dt = None
            entry_p = 0.0
            bars_held = 0

            for dt in c_3y.index:
                pos = signal_3y.loc[dt]
                price = c_3y.loc[dt]

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
                        trade_obj = {
                            "type": "LONG" if in_pos == 1 else "SHORT",
                            "entry_date": entry_dt.strftime("%Y-%m-%d"),
                            "exit_date": exit_dt.strftime("%Y-%m-%d"),
                            "bars_held": bars_held,
                            "entry_price": round(float(entry_p), 2),
                            "exit_price": round(float(exit_p), 2),
                            "return_pct": round(float(ret * 100.0), 2),
                            "profitable": ret > 0,
                        }
                        trades.append(trade_obj)
                        if in_pos == 1:
                            long_trades.append(trade_obj)
                        else:
                            short_trades.append(trade_obj)

                        if pos != 0:
                            in_pos = pos
                            entry_dt = dt
                            entry_p = price
                            bars_held = 0
                        else:
                            in_pos = 0

            # Last open trade
            if in_pos != 0:
                exit_dt = c_3y.index[-1]
                exit_p = c_3y.iloc[-1]
                ret = ((exit_p - entry_p) / entry_p) * in_pos
                trade_obj = {
                    "type": "LONG" if in_pos == 1 else "SHORT",
                    "entry_date": entry_dt.strftime("%Y-%m-%d"),
                    "exit_date": exit_dt.strftime("%Y-%m-%d (open)"),
                    "bars_held": bars_held,
                    "entry_price": round(float(entry_p), 2),
                    "exit_price": round(float(exit_p), 2),
                    "return_pct": round(float(ret * 100.0), 2),
                    "profitable": ret > 0,
                }
                trades.append(trade_obj)
                if in_pos == 1:
                    long_trades.append(trade_obj)
                else:
                    short_trades.append(trade_obj)

            long_wins = [t for t in long_trades if t["profitable"]]
            short_wins = [t for t in short_trades if t["profitable"]]
            all_wins = [t for t in trades if t["profitable"]]

            total_win_rate = (len(all_wins) / len(trades) * 100.0) if trades else 0.0
            long_win_rate = (len(long_wins) / len(long_trades) * 100.0) if long_trades else 0.0
            short_win_rate = (len(short_wins) / len(short_trades) * 100.0) if short_trades else 0.0

            # Annualized Return (CAGR)
            years = len(eval_slice) / 252.0
            cagr = ((final_val / initial_capital) ** (1.0 / years) - 1.0) * 100.0

            # Monthly breakdown
            monthly_ret = strat_ret_3y.resample("ME").apply(lambda r: (1 + r).prod() - 1)
            monthly_data = []
            curr_b = initial_capital
            for dt, r in monthly_ret.items():
                prev_b = curr_b
                curr_b = curr_b * (1 + r)
                monthly_data.append({
                    "month": dt.strftime("%Y-%m"),
                    "return_pct": round(float(r * 100.0), 2),
                    "pnl_dollars": round(float(curr_b - prev_b), 2),
                    "balance": round(float(curr_b), 2),
                })

            results.append({
                "asset": asset,
                "variant_name": v_name,
                "description": v["desc"],
                "params": params,
                "initial_capital": initial_capital,
                "final_balance": round(final_val, 2),
                "net_pnl_dollars": round(net_pnl, 2),
                "net_pnl_pct": round(pnl_pct, 2),
                "cagr_pct": round(cagr, 2),
                "sharpe": round(float(metrics.get("sharpe", 0.0)), 2),
                "sortino": round(float(metrics.get("sortino", 0.0)), 2),
                "max_drawdown_pct": round(float(metrics.get("max_drawdown", 0.0)) * 100.0, 2),
                "max_drawdown_dollars": round(float(metrics.get("max_drawdown", 0.0)) * initial_capital, 2),
                "total_trades": len(trades),
                "win_rate_total_pct": round(total_win_rate, 1),
                "long_trades": len(long_trades),
                "long_win_rate_pct": round(long_win_rate, 1),
                "short_trades": len(short_trades),
                "short_win_rate_pct": round(short_win_rate, 1),
                "benchmark": benchmarks[asset],
                "monthly_breakdown": monthly_data,
                "trades": trades,
            })

    # Sort results by Sharpe
    results.sort(key=lambda x: (x["sharpe"], x["net_pnl_pct"]), reverse=True)

    # Print 3-Year Table
    print("\n" + "=" * 90)
    print("                    3-YEAR $50 SCALPING RESULTS TABLE")
    print("=" * 90)
    header = f"{'Asset':<5} {'Scalper Variant':<28} {'Final $':<8} {'Total %':<9} {'CAGR %':<8} {'Sharpe':<7} {'MaxDD %':<8} {'Trades':<7} {'Win %':<6} {'L/S Trades'}"
    print(header)
    print("-" * 90)
    for r in results:
        ls_str = f"{r['long_trades']}L ({r['long_win_rate_pct']}%) / {r['short_trades']}S ({r['short_win_rate_pct']}%)"
        print(f"{r['asset']:<5} {r['variant_name']:<28} ${r['final_balance']:<7.2f} {r['net_pnl_pct']:+7.2f}% {r['cagr_pct']:+6.2f}% {r['sharpe']:<7.2f} {r['max_drawdown_pct']:<8.2f} {r['total_trades']:<7} {r['win_rate_total_pct']:<6.1f}% {ls_str}")

    return results, benchmarks, actual_start, end_date, len(eval_slice)


def run_intraday_5m_simulation():
    print("\n" + "=" * 80)
    print("       INTRADAY 5-MINUTE SCALPER SIMULATION (MULTIPLE TRADES PER DAY)")
    print("=" * 80)

    import yfinance as yf

    initial_capital = 50.0
    ticker = "SPY"
    print(f"Fetching live 5-minute bars for {ticker} (last 5 trading days)...")
    raw_df = yf.download(ticker, period="5d", interval="5m", progress=False)

    if raw_df.empty:
        print("Could not fetch 5m data from yfinance.")
        return None

    # Clean columns
    if isinstance(raw_df.columns, pd.MultiIndex):
        raw_df.columns = [col[0].lower() for col in raw_df.columns]
    else:
        raw_df.columns = [str(c).lower() for c in raw_df.columns]

    close = raw_df["close"]
    n_bars = len(close)
    print(f"Fetched {n_bars} 5-minute intraday bars across {len(np.unique(raw_df.index.date))} trading days.")

    # 5-minute scalper parameters
    # Fast 5-period window (25 minutes)
    # Band: 1.0 sigma
    scalper = ScalperStrategy()
    params = {
        "window": 6,          # 30 minutes lookback
        "num_std": 1.0,       # 1.0 sigma band
        "exit_at_mean": True, # exit when returning to 30m moving average
        "allow_short": True,  # trade BOTH long and short
        "stop_loss_pct": 0.005, # 0.5% stop loss for intraday
        "short_stop_loss_pct": 0.004, # 0.4% stop loss for short
        "max_hold_bars": 6,   # max hold 30 minutes
    }

    signal = scalper.generate_signal(raw_df, params)
    signal = signal.reindex(close.index).fillna(0)

    # Intraday transaction costs: commission + tight slippage
    costs = _apply_transaction_costs(
        signal,
        config.backtest.commission,
        0.0002, # 2 bps slippage on liquid SPY
        2.0,    # 2 bps market impact
    )

    daily_ret = close.pct_change().fillna(0)
    strat_ret = daily_ret * signal.shift(1).fillna(0) - costs
    equity = (1 + strat_ret).cumprod() * initial_capital

    final_val = float(equity.iloc[-1])
    net_pnl = final_val - initial_capital
    pnl_pct = (net_pnl / initial_capital) * 100.0

    # Extract all intraday trades
    trades = []
    in_pos = 0
    entry_dt = None
    entry_p = 0.0
    bars_held = 0

    for dt in close.index:
        pos = signal.loc[dt]
        price = close.loc[dt]

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
                trades.append({
                    "type": "LONG" if in_pos == 1 else "SHORT",
                    "entry_time": entry_dt.strftime("%Y-%m-%d %H:%M"),
                    "exit_time": exit_dt.strftime("%Y-%m-%d %H:%M"),
                    "minutes_held": bars_held * 5,
                    "entry_price": round(float(entry_p), 2),
                    "exit_price": round(float(exit_p), 2),
                    "return_pct": round(float(ret * 100.0), 3),
                    "profit_dollars": round(float(initial_capital * ret), 3),
                    "profitable": ret > 0,
                })

                if pos != 0:
                    in_pos = pos
                    entry_dt = dt
                    entry_p = price
                    bars_held = 0
                else:
                    in_pos = 0

    # Days count
    unique_days = len(np.unique(raw_df.index.date))
    trades_per_day = len(trades) / max(1, unique_days)
    wins = [t for t in trades if t["profitable"]]
    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0

    long_trades = [t for t in trades if t["type"] == "LONG"]
    short_trades = [t for t in trades if t["type"] == "SHORT"]

    print(f"Total Intraday Trades:  {len(trades)} across {unique_days} days ({trades_per_day:.1f} trades/day)")
    print(f"Long Trades:            {len(long_trades)} (Win Rate: {len([t for t in long_trades if t['profitable']]) / max(1, len(long_trades)) * 100:.1f}%)")
    print(f"Short Trades:           {len(short_trades)} (Win Rate: {len([t for t in short_trades if t['profitable']]) / max(1, len(short_trades)) * 100:.1f}%)")
    print(f"Total Win Rate:         {win_rate:.1f}%")
    print(f"Starting Capital:       ${initial_capital:.2f}")
    print(f"Final Capital:          ${final_val:.2f} ({net_pnl:+.2f} / {pnl_pct:+.2f}%)")
    print(f"Average Trade Duration: {np.mean([t['minutes_held'] for t in trades]):.1f} minutes")

    return {
        "ticker": ticker,
        "days": unique_days,
        "total_bars": n_bars,
        "trades": trades,
        "trades_per_day": round(trades_per_day, 1),
        "win_rate_pct": round(win_rate, 1),
        "starting_capital": initial_capital,
        "final_capital": round(final_val, 2),
        "net_pnl_pct": round(pnl_pct, 2),
        "net_pnl_dollars": round(net_pnl, 2),
        "long_count": len(long_trades),
        "short_count": len(short_trades),
    }


def main():
    results, benchmarks, start_dt, end_dt, days = run_3year_simulation()
    intraday_res = run_intraday_5m_simulation()

    out_file = Path("results/scalper_3year_and_intraday_report.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "metadata_3year": {
            "initial_capital": 50.0,
            "start_date": start_dt.strftime("%Y-%m-%d"),
            "end_date": end_dt.strftime("%Y-%m-%d"),
            "trading_days": days,
        },
        "results_3year": results,
        "benchmarks_3year": benchmarks,
        "intraday_5m": intraday_res,
    }

    with open(out_file, "w") as f:
        json.dump(payload, f, indent=2, cls=NumpyEncoder)

    print(f"\nFull 3-Year + Intraday Report exported to: {out_file.resolve()}")


if __name__ == "__main__":
    main()
