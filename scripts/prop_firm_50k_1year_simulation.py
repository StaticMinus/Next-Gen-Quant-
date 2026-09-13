"""
$50,000 Prop Firm Account 1-Year P/L Simulation — AgentQuant
============================================================
Simulates our winning Scalper strategy on a $50,000 funded account over 1 year (252 trading days).
Calculates exact monthly profits, 85% trader profit split, conversion to Nigerian Naira,
and verifies drawdown compliance against prop firm risk limits.
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


def run_50k_simulation():
    print("=" * 80)
    print("       AGENTQUANT $50,000 FUNDED ACCOUNT 1-YEAR P/L SIMULATION")
    print("=" * 80)

    initial_capital = 50000.0
    config.backtest.initial_cash = initial_capital
    naira_rate = 1650.0  # Approx ₦1,650 per USD
    trader_split = 0.85  # 85% trader profit split

    assets = ["SPY", "QQQ", "IWM"]

    # Scalper variants
    variants = [
        {
            "name": "Balanced Long-Only Scalper (Recommended)",
            "params": {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5},
            "desc": "5-day lookback, 1.25s bands, exit at mean, 3% stop loss (Ultra-low drawdown)",
        },
        {
            "name": "Aggressive Long-Only Scalper",
            "params": {"window": 5, "num_std": 1.0, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5},
            "desc": "5-day lookback, 1.0s bands, exit at mean, 3% stop loss (Higher trade frequency)",
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

    print(f"Starting Capital:       ${initial_capital:,.2f}")
    print(f"Trader Profit Split:    {trader_split * 100:.0f}% to Trader / {(1 - trader_split) * 100:.0f}% to Prop Firm")
    print(f"Exchange Rate Baseline: $1 = ₦{naira_rate:,.0f} NGN")
    print(f"Evaluation Window:      {actual_start.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} ({len(eval_slice)} trading days)")

    results = []

    for asset in assets:
        df = ohlcv_dict[asset]
        c = close_dict[asset]
        c_1y = c.loc[c.index >= actual_start]
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
            strat_ret_1y = strat_ret.loc[strat_ret.index >= actual_start]
            signal_1y = signal.loc[signal.index >= actual_start]

            equity_1y = (1 + strat_ret_1y).cumprod() * initial_capital
            final_val = float(equity_1y.iloc[-1])
            total_net_pnl = final_val - initial_capital
            pnl_pct = (total_net_pnl / initial_capital) * 100.0

            trader_share_usd = total_net_pnl * trader_split
            trader_share_ngn = trader_share_usd * naira_rate

            prop_share_usd = total_net_pnl * (1 - trader_split)

            metrics = PerformanceMetrics.from_equity(equity_1y)
            max_dd_pct = float(metrics.get("max_drawdown", 0.0)) * 100.0
            max_dd_usd = float(metrics.get("max_drawdown", 0.0)) * initial_capital

            # Trades breakdown
            trades = []
            in_pos = 0
            entry_dt = None
            entry_p = 0.0
            bars_held = 0

            for dt in c_1y.index:
                pos = signal_1y.loc[dt]
                price = c_1y.loc[dt]

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
                        trade_pnl_usd = initial_capital * ret
                        trades.append({
                            "type": "LONG",
                            "entry_date": entry_dt.strftime("%Y-%m-%d"),
                            "exit_date": exit_dt.strftime("%Y-%m-%d"),
                            "bars_held": bars_held,
                            "entry_price": round(float(entry_p), 2),
                            "exit_price": round(float(exit_p), 2),
                            "return_pct": round(float(ret * 100.0), 2),
                            "pnl_usd": round(float(trade_pnl_usd), 2),
                            "trader_takehome_usd": round(float(trade_pnl_usd * trader_split), 2),
                            "trader_takehome_ngn": round(float(trade_pnl_usd * trader_split * naira_rate), 0),
                            "profitable": ret > 0,
                        })

                        if pos != 0:
                            in_pos = pos
                            entry_dt = dt
                            entry_p = price
                            bars_held = 0
                        else:
                            in_pos = 0

            # Monthly breakdown
            monthly_ret = strat_ret_1y.resample("ME").apply(lambda r: (1 + r).prod() - 1)
            monthly_breakdown = []
            curr_val = initial_capital

            for dt, r in monthly_ret.items():
                prev_val = curr_val
                curr_val = curr_val * (1 + r)
                month_gain_usd = curr_val - prev_val
                month_trader_usd = month_gain_usd * trader_split if month_gain_usd > 0 else month_gain_usd
                month_trader_ngn = month_trader_usd * naira_rate

                monthly_breakdown.append({
                    "month": dt.strftime("%Y-%m"),
                    "monthly_return_pct": round(float(r * 100.0), 2),
                    "total_month_pnl_usd": round(float(month_gain_usd), 2),
                    "your_takehome_usd": round(float(month_trader_usd), 2),
                    "your_takehome_ngn": round(float(month_trader_ngn), 0),
                    "account_balance": round(float(curr_val), 2),
                })

            wins = [t for t in trades if t["profitable"]]
            win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0

            results.append({
                "asset": asset,
                "variant_name": v_name,
                "initial_capital": initial_capital,
                "final_balance": round(final_val, 2),
                "total_profit_usd": round(total_net_pnl, 2),
                "total_return_pct": round(pnl_pct, 2),
                "trader_share_usd (85%)": round(trader_share_usd, 2),
                "trader_share_ngn (85%)": round(trader_share_ngn, 0),
                "prop_firm_share_usd (15%)": round(prop_share_usd, 2),
                "monthly_average_takehome_usd": round(trader_share_usd / 12.0, 2),
                "monthly_average_takehome_ngn": round(trader_share_ngn / 12.0, 0),
                "sharpe": round(float(metrics.get("sharpe", 0.0)), 2),
                "max_drawdown_pct": round(max_dd_pct, 2),
                "max_drawdown_usd": round(max_dd_usd, 2),
                "prop_firm_safe": max_dd_pct < 4.0,  # Strict prop firm drawdown safety check
                "total_trades": len(trades),
                "win_rate_pct": round(win_rate, 1),
                "monthly_breakdown": monthly_breakdown,
                "trades": trades,
            })

    # Sort results
    results.sort(key=lambda x: (x["sharpe"], x["total_return_pct"]), reverse=True)
    best = results[0]

    # Export to JSON
    out_dir = Path("results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "prop_firm_50k_1year_report.json"

    with open(out_file, "w") as f:
        json.dump({
            "metadata": {
                "initial_capital": initial_capital,
                "trader_split": trader_split,
                "naira_rate": naira_rate,
                "start_date": actual_start.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "trading_days": len(eval_slice),
            },
            "best_run": best,
            "all_runs": results,
        }, f, indent=2, cls=NumpyEncoder)

    print("\n" + "=" * 95)
    print("                    $50,000 ACCOUNT PERFORMANCE SUMMARY (1 YEAR)")
    print("=" * 95)
    header = f"{'Asset':<5} {'Strategy Variant':<28} {'Total Profit':<14} {'YOUR 85% (USD)':<16} {'YOUR 85% (NGN)':<18} {'Sharpe':<7} {'MaxDD %':<8} {'Safe?'}"
    print(header)
    print("-" * 95)
    for r in results:
        safe_str = "PASSED" if r["prop_firm_safe"] else "MONITOR"
        print(f"{r['asset']:<5} {r['variant_name']:<28} ${r['total_profit_usd']:<13,.2f} ${r['trader_share_usd (85%)']:<15,.2f} ₦{r['trader_share_ngn (85%)']:<17,.0f} {r['sharpe']:<7.2f} {r['max_drawdown_pct']:<8.2f} {safe_str}")

    print("\n" + "=" * 95)
    print(f"WINNER: {best['variant_name']} on {best['asset']}")
    print("=" * 95)
    print(f"Total Account Profit (100%):  ${best['total_profit_usd']:,.2f} (+{best['total_return_pct']:.2f}%)")
    print(f"YOUR TAKE-HOME PAYOUT (85%):  ${best['trader_share_usd (85%)']:,.2f}  (₦{best['trader_share_ngn (85%)']:,.0f} Naira)")
    print(f"Prop Firm Share (15%):        ${best['prop_firm_share_usd (15%)']:,.2f}")
    print(f"Average Monthly Take-Home:    ${best['monthly_average_takehome_usd']:,.2f}/month  (₦{best['monthly_average_takehome_ngn']:,.0f} Naira/month)")
    print(f"Sharpe Ratio:                 {best['sharpe']:.2f}")
    print(f"Maximum Account Drawdown:     {best['max_drawdown_pct']:.2f}% (${best['max_drawdown_usd']:,.2f} max dip)")
    print(f"Total Trades:                 {best['total_trades']} trades ({best['win_rate_pct']:.1f}% Win Rate)")
    print(f"\nReport saved to: {out_file.resolve()}")

    return best, results


if __name__ == "__main__":
    run_50k_simulation()
