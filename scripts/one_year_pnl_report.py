"""
AgentQuant 1-Year P/L Backtest Simulation ($100 Starting Capital)
"""
import os
import json
import pandas as pd
import numpy as np
from pathlib import Path

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
from dotenv import load_dotenv

load_dotenv()

from src.utils.config import config
from src.data.ingest import fetch_ohlcv_data
from src.features.engine import compute_features
from src.features.regime import detect_regime_full
from src.strategies.strategy_registry import STRATEGY_REGISTRY
from src.backtest.runner import run_backtest, _get_close, _apply_transaction_costs
from src.backtest.metrics import PerformanceMetrics
from src.agent.base_planner import create_planner

def main():
    print("=== AgentQuant 1-Year $100 P/L Simulation ===")
    
    # 1. Load 5y data for SPY
    ohlcv = fetch_ohlcv_data(ticker="SPY")
    df = ohlcv["SPY"]
    close = _get_close(df)
    
    # Date range: exactly 1 year trailing from the latest date
    end_date = close.index.max()
    eval_start_date = end_date - pd.DateOffset(years=1)
    
    # Find exact trading day closest to eval_start_date
    eval_slice = close.loc[close.index >= eval_start_date]
    actual_start = eval_slice.index[0]
    
    print(f"Dataset Range: {close.index.min().strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"Backtest 1-Year Window: {actual_start.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} ({len(eval_slice)} trading days)")
    
    # Set initial cash to $100
    initial_cash = 100.0
    config.backtest.initial_cash = initial_cash
    
    # 2. Compute Features & Detect Regime at the start of the year
    pre_eval_df = df.loc[df.index <= actual_start]
    feats = compute_features({"SPY": pre_eval_df})
    regime_ctx = detect_regime_full(feats)
    print(f"Market Regime at Start: {regime_ctx.regime_label} (Confidence: {regime_ctx.regime_confidence:.0%})")
    
    # 3. Test Multiple Strategies to Find the Best-Performing Strategy for the Year
    # Test momentum, mean_reversion, trend_following, and breakout
    strategies_to_test = [
        ("momentum", {"fast_window": 20, "slow_window": 60}),
        ("momentum", {"fast_window": 50, "slow_window": 150}),
        ("momentum", {"fast_window": 10, "slow_window": 50}),
        ("mean_reversion", {"window": 20, "num_std": 2.0}),
        ("trend_following", {"short_window": 10, "medium_window": 50, "long_window": 100}),
        ("breakout", {"window": 20, "threshold_pct": 0.02})
    ]
    
    results = []
    for strat_name, params in strategies_to_test:
        strat = STRATEGY_REGISTRY[strat_name]
        signal = strat.generate_signal(df, params)
        signal = signal.reindex(close.index).fillna(0)
        
        costs = _apply_transaction_costs(
            signal,
            config.backtest.commission,
            config.backtest.slippage,
            config.backtest.market_impact_bps,
        )
        
        daily_ret = close.pct_change().fillna(0)
        strat_ret = daily_ret * signal.shift(1).fillna(0) - costs
        
        # Slice to evaluation 1-year period
        strat_ret_1y = strat_ret.loc[strat_ret.index >= actual_start]
        signal_1y = signal.loc[signal.index >= actual_start]
        close_1y = close.loc[close.index >= actual_start]
        
        equity_1y = (1 + strat_ret_1y).cumprod() * initial_cash
        final_val = float(equity_1y.iloc[-1])
        net_pnl = final_val - initial_cash
        pnl_pct = (net_pnl / initial_cash) * 100.0
        
        metrics = PerformanceMetrics.from_equity(equity_1y)
        trades_count = int(signal_1y.diff().abs().sum() / 2)
        
        results.append({
            "strategy": strat_name,
            "params": params,
            "final_value": final_val,
            "net_pnl": net_pnl,
            "pnl_pct": pnl_pct,
            "sharpe": metrics.get("sharpe", 0.0),
            "sortino": metrics.get("sortino", 0.0),
            "calmar": metrics.get("calmar", 0.0),
            "max_drawdown": metrics.get("max_drawdown", 0.0),
            "trades": trades_count,
            "equity": equity_1y,
            "signal": signal_1y,
            "strat_ret": strat_ret_1y
        })
    
    # Sort by Sharpe and Total Return
    results.sort(key=lambda x: (x["sharpe"], x["pnl_pct"]), reverse=True)
    best = results[0]
    
    # 4. Benchmark: SPY Buy & Hold with $100
    bnh_ret = close.pct_change().loc[close.index >= actual_start].fillna(0)
    bnh_equity = (1 + bnh_ret).cumprod() * initial_cash
    bnh_final = float(bnh_equity.iloc[-1])
    bnh_pnl = bnh_final - initial_cash
    bnh_pnl_pct = (bnh_pnl / initial_cash) * 100.0
    bnh_metrics = PerformanceMetrics.from_equity(bnh_equity)
    
    # 5. Extract Trade Details for Best Strategy
    sig = best["signal"]
    c_1y = close.loc[close.index >= actual_start]
    trades = []
    in_pos = False
    entry_date = None
    entry_price = 0.0
    
    for dt, pos in sig.items():
        if not in_pos and pos > 0:
            in_pos = True
            entry_date = dt
            entry_price = c_1y.loc[dt]
        elif in_pos and pos == 0:
            exit_date = dt
            exit_price = c_1y.loc[dt]
            trade_ret = (exit_price - entry_price) / entry_price
            trades.append({
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "exit_date": exit_date.strftime("%Y-%m-%d"),
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "return_pct": float(trade_ret * 100.0),
                "profitable": trade_ret > 0
            })
            in_pos = False
    
    if in_pos:
        exit_date = c_1y.index[-1]
        exit_price = c_1y.iloc[-1]
        trade_ret = (exit_price - entry_price) / entry_price
        trades.append({
            "entry_date": entry_date.strftime("%Y-%m-%d"),
            "exit_date": exit_date.strftime("%Y-%m-%d (open)"),
            "entry_price": float(entry_price),
            "exit_price": float(exit_price),
            "return_pct": float(trade_ret * 100.0),
            "profitable": trade_ret > 0
        })

    # 6. Monthly Breakdown
    monthly_ret = best["strat_ret"].resample("ME").apply(lambda r: (1 + r).prod() - 1)
    monthly_data = []
    cum_val = initial_cash
    for dt, r in monthly_ret.items():
        start_val = cum_val
        cum_val = cum_val * (1 + r)
        monthly_data.append({
            "month": dt.strftime("%Y-%m"),
            "return_pct": float(r * 100.0),
            "month_pnl_dollars": float(cum_val - start_val),
            "end_balance": float(cum_val)
        })

    # 7. Summary JSON payload
    summary = {
        "initial_capital": initial_cash,
        "eval_period": {
            "start": actual_start.strftime("%Y-%m-%d"),
            "end": end_date.strftime("%Y-%m-%d"),
            "trading_days": len(eval_slice)
        },
        "best_strategy": {
            "name": best["strategy"],
            "params": best["params"],
            "starting_balance": initial_cash,
            "final_balance": round(best["final_value"], 2),
            "net_pnl_dollars": round(best["net_pnl"], 2),
            "net_pnl_pct": round(best["pnl_pct"], 2),
            "sharpe_ratio": round(best["sharpe"], 2),
            "sortino_ratio": round(best["sortino"], 2),
            "calmar_ratio": round(best["calmar"], 2),
            "max_drawdown_pct": round(best["max_drawdown"] * 100, 2),
            "max_drawdown_dollars": round(best["max_drawdown"] * initial_cash, 2),
            "total_trades": len(trades),
            "winning_trades": sum(1 for t in trades if t["profitable"]),
            "win_rate_pct": round((sum(1 for t in trades if t["profitable"]) / max(1, len(trades))) * 100, 1)
        },
        "benchmark_buy_and_hold": {
            "name": "SPY Buy & Hold",
            "starting_balance": initial_cash,
            "final_balance": round(bnh_final, 2),
            "net_pnl_dollars": round(bnh_pnl, 2),
            "net_pnl_pct": round(bnh_pnl_pct, 2),
            "sharpe_ratio": round(bnh_metrics.get("sharpe", 0.0), 2),
            "max_drawdown_pct": round(bnh_metrics.get("max_drawdown", 0.0) * 100, 2),
        },
        "all_strategies_tested": [
            {
                "strategy": r["strategy"],
                "params": r["params"],
                "final_val": round(r["final_value"], 2),
                "pnl_pct": round(r["pnl_pct"], 2),
                "sharpe": round(r["sharpe"], 2),
                "max_dd_pct": round(r["max_drawdown"] * 100, 2)
            } for r in results
        ],
        "monthly_breakdown": monthly_data,
        "trades": trades
    }

    out_file = Path("results/one_year_100_dollar_report.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(summary, f, indent=2, cls=NumpyEncoder)

    print("\n=== RESULTS SUMMARY ===")
    print(f"Starting Capital: ${summary['best_strategy']['starting_balance']:.2f}")
    print(f"Final Balance:    ${summary['best_strategy']['final_balance']:.2f}")
    print(f"Net Profit/Loss:  ${summary['best_strategy']['net_pnl_dollars']:+.2f} ({summary['best_strategy']['net_pnl_pct']:+.2f}%)")
    print(f"Sharpe Ratio:     {summary['best_strategy']['sharpe_ratio']:.2f}")
    print(f"Max Drawdown:     {summary['best_strategy']['max_drawdown_pct']:.2f}% (${summary['best_strategy']['max_drawdown_dollars']:.2f})")
    print(f"Total Trades:     {summary['best_strategy']['total_trades']} (Win Rate: {summary['best_strategy']['win_rate_pct']}%)")
    print(f"\nReport generated at: {out_file.resolve()}")

if __name__ == "__main__":
    main()
