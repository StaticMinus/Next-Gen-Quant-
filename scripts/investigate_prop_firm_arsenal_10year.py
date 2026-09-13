"""
Deep Arsenal Investigation: 10-Year Prop Firm Tournament (2016 - 2026)
=====================================================================
Investigates all strategies in AgentQuant's arsenal across 10 years (2,514 days)
under realistic Prop Firm rules ($50,000 account, $2,000 max drawdown limit, 
Micro Futures contract sizing: 1 MES for SPY, 1 MNQ for QQQ).

Compares:
1. Current Chosen Strategy: Balanced Long-Only Scalper
2. Volatility Filter Strategy: VolFilter(21, 0.20)
3. Momentum Strategy: Mom(10, 30) & Mom(50, 200)
4. Trend Following Strategy: Trend(5, 20, 50)
5. Mean Reversion Bollinger: MeanRev(15, 2.0s)
6. Hybrid Ensemble: Volatility-Filtered Scalper (Scalper + Vol Filter)
7. Dual-Engine Ensemble: 50% Volatility Trend + 50% Scalper
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
from src.strategies.scalper import ScalperStrategy
from src.strategies.base import (
    VolatilityStrategy,
    MomentumStrategy,
    TrendFollowingStrategy,
    MeanReversionStrategy,
    _get_close,
)
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


def run_investigation():
    print("=" * 105)
    print("      AGENTQUANT DEEP ARSENAL INVESTIGATION & 10-YEAR PROP FIRM TOURNAMENT (2016 - 2026)")
    print("=" * 105)

    initial_capital = 50000.0
    prop_firm_max_dd_limit = 2000.0  # $2,000 max drawdown limit on $50k account
    naira_rate = 1650.0
    trader_split = 0.85

    # Download 10 years of data
    assets = ["SPY", "QQQ"]
    ohlcv = {}
    close_series = {}

    print("\n[1/4] Fetching 10 years of clean market data (2016 - 2026)...")
    cache_dir = Path("cache")
    cache_dir.mkdir(exist_ok=True)
    import time

    for ticker in assets:
        cache_file = cache_dir / f"{ticker}_10y.csv"
        if cache_file.exists() and cache_file.stat().st_size > 1000:
            print(f"  Loading {ticker} from local cache ({cache_file})...")
            raw = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        else:
            print(f"  Downloading {ticker} via yfinance...")
            raw = None
            for attempt in range(4):
                try:
                    raw = yf.download(ticker, period="10y", progress=False)
                    if raw is not None and not raw.empty:
                        break
                except Exception as ex:
                    print(f"  Attempt {attempt+1} failed for {ticker}: {ex}")
                time.sleep(2)

            if raw is None or raw.empty:
                raise RuntimeError(f"Could not load 10-year data for {ticker}")

            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = [col[0].lower() for col in raw.columns]
            else:
                raw.columns = [str(c).lower() for c in raw.columns]
            raw.to_csv(cache_file)

        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [col[0].lower() for col in raw.columns]
        else:
            raw.columns = [str(c).lower() for c in raw.columns]
        ohlcv[ticker] = raw
        close_series[ticker] = _get_close(raw)
        print(f"  Loaded {ticker}: {len(close_series[ticker])} trading days.")

    ref = close_series["SPY"]
    start_dt = ref.index.min()
    end_dt = ref.index.max()
    total_days = len(ref)
    years = total_days / 252.0

    print(f"Data period: {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')} ({total_days} days / ~{years:.1f} years)")

    # Define all candidate strategies to test
    # Each contract has a point multiplier: MES = $5/pt (or 10 shares equivalent of SPY = $10/pt).
    # Specifically for CME Micro Futures:
    # 1 MES contract: 1 index point = $5. (SPY price ~= 1/10 of S&P index, so $1 move in SPY ~= $50 on MES, or 1 share of SPY is $1/pt).
    # To be conservative and standard across CFD/Prop firm brokers:
    # 1 Micro contract = 10 units of the underlying ETF index ($10 per $1 ETF price move).
    contract_multiplier = 10.0  # $10 per 1.00 move in ETF price (1 micro lot)

    candidates = [
        # 1. Our Current Baseline
        {
            "id": "scalper_balanced",
            "name": "Balanced Scalper (Current Strategy)",
            "type": "scalper",
            "asset": "SPY",
            "params": {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5},
            "desc": "Mean reversion dip buyer on SPY (5d, 1.25s, 3% stop)",
        },
        {
            "id": "scalper_qqq",
            "name": "Balanced Scalper (QQQ Tech)",
            "type": "scalper",
            "asset": "QQQ",
            "params": {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5},
            "desc": "Mean reversion dip buyer on QQQ (5d, 1.25s, 3% stop)",
        },
        # 2. Volatility Filter
        {
            "id": "vol_filter_spy",
            "name": "Volatility Filter (SPY)",
            "type": "volatility",
            "asset": "SPY",
            "params": {"window": 21, "vol_threshold": 0.20},
            "desc": "Long SPY when 21d vol < 20%; 100% Cash in panic crashes",
        },
        {
            "id": "vol_filter_qqq",
            "name": "Volatility Filter (QQQ)",
            "type": "volatility",
            "asset": "QQQ",
            "params": {"window": 21, "vol_threshold": 0.20},
            "desc": "Long QQQ when 21d vol < 20%; 100% Cash in panic crashes",
        },
        # 3. Momentum
        {
            "id": "mom_10_30_qqq",
            "name": "Fast Momentum (QQQ 10/30)",
            "type": "momentum",
            "asset": "QQQ",
            "params": {"fast_window": 10, "slow_window": 30},
            "desc": "Fast moving-average crossover trend rider on QQQ",
        },
        {
            "id": "mom_50_200_qqq",
            "name": "Golden Cross Momentum (QQQ 50/200)",
            "type": "momentum",
            "asset": "QQQ",
            "params": {"fast_window": 50, "slow_window": 200},
            "desc": "Macro institutional 50/200 MA crossover on QQQ",
        },
        # 4. Trend Following
        {
            "id": "trend_5_20_50_spy",
            "name": "Triple Trend Following (SPY 5/20/50)",
            "type": "trend_following",
            "asset": "SPY",
            "params": {"short_window": 5, "medium_window": 20, "long_window": 50},
            "desc": "Triple moving average trend alignment on SPY",
        },
        # 5. Mean Reversion
        {
            "id": "mean_rev_15_2_spy",
            "name": "Classic Bollinger Mean Reversion (SPY)",
            "type": "mean_reversion",
            "asset": "SPY",
            "params": {"window": 15, "num_std": 2.0},
            "desc": "Classic 15-day 2.0 standard deviation band reversion",
        },
        # 6. Novel Hybrid: Volatility-Filtered Scalper (The Best of Both Worlds)
        {
            "id": "hybrid_vol_scalper_spy",
            "name": "Hybrid Vol-Filtered Scalper (SPY)",
            "type": "hybrid_vol_scalper",
            "asset": "SPY",
            "params": {"window": 5, "num_std": 1.25, "exit_at_mean": True, "stop_loss_pct": 0.03, "max_hold_bars": 5, "max_vol": 0.25},
            "desc": "Scalper buy dips ONLY when market vol < 25% (avoids falling knives)",
        },
    ]

    print("\n[2/4] Generating Signals for All Candidates across 2,514 days...")
    results = []

    for item in candidates:
        ticker = item["asset"]
        df = ohlcv[ticker]
        c = close_series[ticker]
        daily_ret = c.pct_change().fillna(0)

        # Generate signal series
        if item["type"] == "scalper":
            strat = ScalperStrategy()
            sig = strat.generate_signal(df, item["params"])
        elif item["type"] == "volatility":
            strat = VolatilityStrategy()
            sig = strat.generate_signal(df, item["params"])
        elif item["type"] == "momentum":
            strat = MomentumStrategy()
            sig = strat.generate_signal(df, item["params"])
        elif item["type"] == "trend_following":
            strat = TrendFollowingStrategy()
            sig = strat.generate_signal(df, item["params"])
        elif item["type"] == "mean_reversion":
            strat = MeanReversionStrategy()
            sig = strat.generate_signal(df, item["params"])
        elif item["type"] == "hybrid_vol_scalper":
            # Compute scalper signal AND vol filter
            scalper_strat = ScalperStrategy()
            sig_raw = scalper_strat.generate_signal(df, {
                "window": item["params"]["window"],
                "num_std": item["params"]["num_std"],
                "exit_at_mean": item["params"]["exit_at_mean"],
                "allow_short": False,
                "stop_loss_pct": item["params"]["stop_loss_pct"],
                "max_hold_bars": item["params"]["max_hold_bars"]
            })
            # 21-day annualized volatility
            daily_vol = c.pct_change().rolling(21).std() * (252 ** 0.5)
            # Filter out entries if vol > max_vol
            sig = sig_raw.copy()
            sig[(daily_vol > item["params"]["max_vol"])] = 0
        else:
            continue

        sig = sig.reindex(c.index).fillna(0).clip(lower=0)  # Strictly Long-Only

        # --- A. Percentage-of-Equity Compounded Test ---
        # Comm + slippage
        cost_per_trade = 0.0004
        trades_flips = sig.diff().abs().fillna(0)
        costs = trades_flips * cost_per_trade
        compounded_ret = daily_ret * sig.shift(1).fillna(0) - costs
        compounded_eq = (1 + compounded_ret).cumprod() * initial_capital
        final_compounded_val = float(compounded_eq.iloc[-1])
        compounded_profit = final_compounded_val - initial_capital
        compounded_metrics = PerformanceMetrics.from_equity(compounded_eq)
        compounded_sharpe = float(compounded_metrics.get("sharpe", 0.0))
        compounded_max_dd_pct = float(compounded_metrics.get("max_drawdown", 0.0)) * 100.0

        # --- B. Prop Firm Dollar Simulation (1 Micro Contract MES / MNQ) ---
        # With 1 Micro contract, cash PnL = (price_change) * contract_multiplier ($10/point) - commission ($1.50/trade)
        commission_per_order = 1.50
        contract_balance = initial_capital
        contract_peak = initial_capital
        contract_equity_curve = [initial_capital]
        contract_max_dd_usd = 0.0
        contract_max_dd_pct = 0.0
        contract_trades = []

        in_pos = 0
        entry_price = 0.0
        entry_idx = None
        bars_held = 0

        for dt in c.index:
            pos = int(sig.loc[dt])
            p = float(c.loc[dt])
            current_eq = contract_balance

            if in_pos == 0 and pos > 0:
                # Enter Long 1 micro contract
                in_pos = 1
                entry_price = p
                entry_idx = dt
                bars_held = 0
                contract_balance -= commission_per_order
                current_eq = contract_balance
            elif in_pos == 1:
                bars_held += 1
                # Mark to market for daily equity
                unrealized_pnl = (p - entry_price) * contract_multiplier
                current_eq = contract_balance + unrealized_pnl
                
                # Check exit
                if pos == 0:
                    exit_price = p
                    realized_pnl = (exit_price - entry_price) * contract_multiplier - commission_per_order
                    contract_balance += realized_pnl
                    current_eq = contract_balance
                    in_pos = 0
                    contract_trades.append({
                        "entry_dt": entry_idx.strftime("%Y-%m-%d"),
                        "exit_dt": dt.strftime("%Y-%m-%d"),
                        "bars_held": bars_held,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "pnl_usd": round(realized_pnl, 2),
                        "profitable": realized_pnl > 0,
                    })

            # Track peak and drawdown
            if current_eq > contract_peak:
                contract_peak = current_eq
            dd_usd = contract_peak - current_eq
            dd_pct = (dd_usd / contract_peak) * 100.0 if contract_peak > 0 else 0.0
            if dd_usd > contract_max_dd_usd:
                contract_max_dd_usd = dd_usd
            if dd_pct > contract_max_dd_pct:
                contract_max_dd_pct = dd_pct
            contract_equity_curve.append(current_eq)

        contract_final_bal = contract_balance
        contract_total_profit = contract_final_bal - initial_capital
        contract_takehome_usd = contract_total_profit * trader_split
        contract_takehome_ngn = contract_takehome_usd * naira_rate
        contract_monthly_usd = contract_takehome_usd / (years * 12.0)
        contract_monthly_ngn = contract_monthly_usd * naira_rate

        wins = [t for t in contract_trades if t["profitable"]]
        win_rate = (len(wins) / len(contract_trades) * 100.0) if contract_trades else 0.0
        avg_bars = np.mean([t["bars_held"] for t in contract_trades]) if contract_trades else 0.0
        trades_per_year = len(contract_trades) / years

        # Did it survive the prop firm $2,000 max drawdown?
        prop_firm_passed = contract_max_dd_usd < prop_firm_max_dd_limit

        record = {
            "id": item["id"],
            "name": item["name"],
            "asset": ticker,
            "desc": item["desc"],
            # Compounding stats
            "compounded_profit_usd": round(compounded_profit, 2),
            "compounded_return_pct": round((compounded_profit / initial_capital) * 100.0, 2),
            "compounded_sharpe": round(compounded_sharpe, 2),
            "compounded_max_dd_pct": round(compounded_max_dd_pct, 2),
            # Prop Firm 1 Micro contract stats
            "contract_final_bal": round(contract_final_bal, 2),
            "contract_profit_usd": round(contract_total_profit, 2),
            "contract_takehome_usd": round(contract_takehome_usd, 2),
            "contract_takehome_ngn": round(contract_takehome_ngn, 0),
            "contract_monthly_usd": round(contract_monthly_usd, 2),
            "contract_monthly_ngn": round(contract_monthly_ngn, 0),
            "contract_max_dd_usd": round(contract_max_dd_usd, 2),
            "contract_max_dd_pct": round(contract_max_dd_pct, 2),
            "total_trades": len(contract_trades),
            "trades_per_year": round(trades_per_year, 1),
            "win_rate_pct": round(win_rate, 1),
            "avg_holding_days": round(avg_bars, 1),
            "prop_firm_survived": prop_firm_passed,
        }
        results.append(record)

    # Sort results
    by_compounded_sharpe = sorted(results, key=lambda x: x["compounded_sharpe"], reverse=True)
    by_contract_profit = sorted(results, key=lambda x: x["contract_profit_usd"], reverse=True)
    by_win_rate = sorted(results, key=lambda x: x["win_rate_pct"], reverse=True)

    # Save to JSON
    output_path = Path("results/deep_arsenal_investigation_10year.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "horizon_years": round(years, 1),
                "trading_days": total_days,
                "initial_capital": initial_capital,
                "prop_firm_dd_limit": prop_firm_max_dd_limit,
                "results": results,
                "by_sharpe": by_compounded_sharpe,
                "by_contract_profit": by_contract_profit,
                "by_win_rate": by_win_rate,
            },
            f,
            indent=2,
            cls=NumpyEncoder,
        )

    print("\n[3/4] Investigation Completed! Displaying Tournament Leaderboards:")
    print("-" * 105)
    print(f"{'Strategy Name':<34} | {'Asset':<5} | {'10y Profit ($)':<14} | {'Monthly (₦)':<12} | {'Max DD ($)':<11} | {'Win %':<6} | {'Trades/Yr':<9} | {'Pass Prop?'}")
    print("-" * 105)

    for r in by_contract_profit:
        pass_str = "YES (SAFE)" if r["prop_firm_survived"] else "FAILED (BREACH)"
        print(f"{r['name']:<34} | {r['asset']:<5} | ${r['contract_profit_usd']:>12,.2f} | ₦{r['contract_monthly_ngn']:>10,.0f} | ${r['contract_max_dd_usd']:>9,.2f} | {r['win_rate_pct']:>5.1f}% | {r['trades_per_year']:>7.1f}/yr | {pass_str}")

    print("-" * 105)
    print("\nCompounded Raw Return Rankings (Mathematical Edge & Sharpe):")
    for r in by_compounded_sharpe:
        print(f"  {r['name']:<34} -> Sharpe: {r['compounded_sharpe']:4.2f} | 10y Raw Profit: ${r['compounded_profit_usd']:>10,.2f} ({r['compounded_return_pct']:>6.1f}%) | Max DD: {r['compounded_max_dd_pct']:5.2f}%")

    print("\n[4/4] Report saved to:", output_path)


if __name__ == "__main__":
    run_investigation()
