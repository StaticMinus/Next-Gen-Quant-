"""
Super Dual Engine (Option 4) — 5-Year Prop Firm Simulation (2021 - 2026)
========================================================================
Simulates the Option 4 "Super Dual Engine" on a $50,000 Funded Account:
1. Scalper on SPY (5d, 1.25s, exit at mean, 3% stop loss)
2. Scalper on QQQ (5d, 1.25s, exit at mean, 3% stop loss)
3. Volatility Filter on QQQ (21d, 0.20 vol threshold, exit to cash on panic)

Analyzes:
- 5-Year Total Net Profit & 85% Trader Take-Home ($ & ₦)
- Month-by-Month Cash Payouts across all 60 months
- Year-by-Year Breakdown (including the brutal 2022 Bear Crash!)
- Maximum Drawdown vs Prop Firm's $2,000 Drawdown Limit
- Win Rate, Trade Count, and Consistency
- Multi-Account Scaling (1, 5, and 20 accounts)
"""

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

from src.strategies.scalper import ScalperStrategy
from src.strategies.base import VolatilityStrategy, _get_close
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


def run_super_dual_engine_5year():
    print("=" * 105)
    print("      AGENTQUANT OPTION 4: SUPER DUAL ENGINE 5-YEAR PROP FIRM TEST (2021 - 2026)")
    print("=" * 105)

    initial_capital = 50000.0
    prop_firm_max_dd_limit = 2000.0  # $2,000 max drawdown on $50k account
    trader_split = 0.85
    naira_rate = 1650.0

    # Load 10y cache and slice to 5 years (2021-09-13 to 2026-09-11)
    cache_dir = Path("cache")
    spy_raw = pd.read_csv(cache_dir / "SPY_10y.csv", index_col=0, parse_dates=True)
    qqq_raw = pd.read_csv(cache_dir / "QQQ_10y.csv", index_col=0, parse_dates=True)

    start_date_5y = "2021-09-13"
    spy_5y = spy_raw.loc[spy_raw.index >= start_date_5y].copy()
    qqq_5y = qqq_raw.loc[qqq_raw.index >= start_date_5y].copy()

    spy_c = _get_close(spy_5y)
    qqq_c = _get_close(qqq_5y)

    total_days = len(spy_c)
    years = total_days / 252.0
    total_months = int(np.round(years * 12.0))

    print(f"\nSimulation Horizon:     {spy_c.index.min().strftime('%Y-%m-%d')} to {spy_c.index.max().strftime('%Y-%m-%d')}")
    print(f"Total Trading Days:     {total_days} days (~{years:.1f} years / {total_months} months)")
    print(f"Starting Capital:       ${initial_capital:,.2f}")
    print(f"Prop Firm DD Buffer:    ${prop_firm_max_dd_limit:,.2f} (4.0%)")
    print(f"Trader Profit Split:    {trader_split * 100:.0f}% (USDT to Binance)")

    # Initialize Strategies
    scalper = ScalperStrategy()
    vol_strat = VolatilityStrategy()

    # 1. Engine 1: Scalper on SPY
    sig_scalper_spy = scalper.generate_signal(
        spy_5y,
        {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}
    ).reindex(spy_c.index).fillna(0).clip(lower=0)

    # 2. Engine 2: Scalper on QQQ
    sig_scalper_qqq = scalper.generate_signal(
        qqq_5y,
        {"window": 5, "num_std": 1.25, "exit_at_mean": True, "allow_short": False, "stop_loss_pct": 0.03, "max_hold_bars": 5}
    ).reindex(qqq_c.index).fillna(0).clip(lower=0)

    # 3. Engine 3: Volatility Filter on QQQ
    sig_vol_qqq = vol_strat.generate_signal(
        qqq_5y,
        {"window": 21, "vol_threshold": 0.20}
    ).reindex(qqq_c.index).fillna(0).clip(lower=0)

    # Combined Strategy Execution Simulation:
    # Sizing for a $50k account with a $2,000 drawdown buffer:
    # 1 Micro contract per engine position (MES for SPY, MNQ for QQQ).
    # Multiplier: $10 per 1.00 move in ETF (Micro contract standard).
    # Commission: $1.50 per order.
    engines = [
        {"name": "Scalper SPY", "asset": "SPY", "close": spy_c, "sig": sig_scalper_spy, "mult": 10.0},
        {"name": "Scalper QQQ", "asset": "QQQ", "close": qqq_c, "sig": sig_scalper_qqq, "mult": 10.0},
        {"name": "VolFilter QQQ", "asset": "QQQ", "close": qqq_c, "sig": sig_vol_qqq, "mult": 10.0},
    ]

    all_closed_trades = []
    daily_equity_series = pd.Series(index=spy_c.index, dtype=float)
    account_cash = initial_capital
    comm_per_order = 1.50

    # Engine states
    states = {}
    for eng in engines:
        states[eng["name"]] = {
            "in_pos": 0,
            "entry_price": 0.0,
            "entry_dt": None,
            "bars_held": 0,
        }

    peak_equity = initial_capital
    max_dd_dollars = 0.0
    max_dd_pct = 0.0

    for dt in spy_c.index:
        unrealized_total = 0.0

        for eng in engines:
            name = eng["name"]
            st = states[name]
            pos = int(eng["sig"].loc[dt])
            price = float(eng["close"].loc[dt])
            mult = eng["mult"]

            # Handle entry
            if st["in_pos"] == 0 and pos > 0:
                st["in_pos"] = 1
                st["entry_price"] = price
                st["entry_dt"] = dt
                st["bars_held"] = 0
                account_cash -= comm_per_order

            # Handle existing position
            elif st["in_pos"] == 1:
                st["bars_held"] += 1
                unrealized = (price - st["entry_price"]) * mult
                unrealized_total += unrealized

                # Handle exit
                if pos == 0:
                    realized_pnl = (price - st["entry_price"]) * mult - comm_per_order
                    account_cash += realized_pnl
                    unrealized_total -= unrealized  # settled into cash

                    all_closed_trades.append({
                        "engine": name,
                        "asset": eng["asset"],
                        "entry_date": st["entry_dt"].strftime("%Y-%m-%d"),
                        "exit_date": dt.strftime("%Y-%m-%d"),
                        "year": dt.year,
                        "month": dt.strftime("%Y-%m"),
                        "bars_held": st["bars_held"],
                        "entry_price": round(st["entry_price"], 2),
                        "exit_price": round(price, 2),
                        "pnl_usd": round(realized_pnl, 2),
                        "profitable": realized_pnl > 0,
                    })
                    st["in_pos"] = 0

        # Mark-to-market daily total equity
        current_eq = account_cash + unrealized_total
        daily_equity_series.loc[dt] = current_eq

        if current_eq > peak_equity:
            peak_equity = current_eq
        dd_usd = peak_equity - current_eq
        dd_pct = (dd_usd / peak_equity) * 100.0 if peak_equity > 0 else 0.0

        if dd_usd > max_dd_dollars:
            max_dd_dollars = dd_usd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    # Total Performance Metrics
    final_balance = daily_equity_series.iloc[-1]
    total_net_profit_usd = final_balance - initial_capital
    total_net_profit_pct = (total_net_profit_usd / initial_capital) * 100.0

    trader_takehome_usd = total_net_profit_usd * trader_split
    trader_takehome_ngn = trader_takehome_usd * naira_rate

    avg_monthly_takehome_usd = trader_takehome_usd / (years * 12.0)
    avg_monthly_takehome_ngn = avg_monthly_takehome_usd * naira_rate

    wins = [t for t in all_closed_trades if t["profitable"]]
    losses = [t for t in all_closed_trades if not t["profitable"]]
    win_rate = (len(wins) / len(all_closed_trades) * 100.0) if all_closed_trades else 0.0
    profit_factor = (
        sum(t["pnl_usd"] for t in wins) / abs(sum(t["pnl_usd"] for t in losses))
    ) if losses and sum(t["pnl_usd"] for t in losses) != 0 else 99.0

    # Month-by-month cashflow
    df_trades = pd.DataFrame(all_closed_trades)
    all_months_series = pd.date_range(start=spy_c.index.min(), end=spy_c.index.max(), freq="MS").strftime("%Y-%m")
    
    monthly_pnl = df_trades.groupby("month")["pnl_usd"].sum().reindex(all_months_series, fill_value=0.0)
    monthly_trades_count = df_trades.groupby("month").size().reindex(all_months_series, fill_value=0)

    profitable_months = (monthly_pnl > 0).sum()
    zero_months = (monthly_trades_count == 0).sum()
    loss_months = (monthly_pnl < 0).sum()
    monthly_win_rate = (profitable_months / len(monthly_pnl)) * 100.0

    # Year-by-Year breakdown
    years_list = sorted(list(set(dt.year for dt in spy_c.index)))
    yearly_stats = []

    for yr in years_list:
        sub_trades = [t for t in all_closed_trades if t["year"] == yr]
        yr_pnl = sum(t["pnl_usd"] for t in sub_trades)
        yr_takehome_usd = yr_pnl * trader_split
        yr_takehome_ngn = yr_takehome_usd * naira_rate
        yr_wins = [t for t in sub_trades if t["profitable"]]
        yr_win_rate = (len(yr_wins) / len(sub_trades) * 100.0) if sub_trades else 0.0
        
        # S&P Benchmark that year
        spy_yr = spy_c.loc[spy_c.index.year == yr]
        spy_bnh_ret = ((spy_yr.iloc[-1] - spy_yr.iloc[0]) / spy_yr.iloc[0]) * 100.0 if len(spy_yr) > 1 else 0.0

        yearly_stats.append({
            "year": yr,
            "trades": len(sub_trades),
            "pnl_usd": round(yr_pnl, 2),
            "trader_takehome_usd": round(yr_takehome_usd, 2),
            "trader_takehome_ngn": round(yr_takehome_ngn, 0),
            "win_rate_pct": round(yr_win_rate, 1),
            "spy_benchmark_pct": round(spy_bnh_ret, 1),
        })

    # Display Results
    print("\n" + "=" * 105)
    print("                     SUPER DUAL ENGINE (OPTION 4) 5-YEAR VERIFIED RESULTS")
    print("=" * 105)
    print(f"Starting Capital:                 ${initial_capital:,.2f}")
    print(f"Final Account Balance:            ${final_balance:,.2f}")
    print(f"Total 5-Year Bot Profit:          +${total_net_profit_usd:,.2f} (+{total_net_profit_pct:.2f}%)")
    print(f"Trader Take-Home (85% Split):     ${trader_takehome_usd:,.2f} USD (~₦{trader_takehome_ngn:,.0f} Naira)")
    print(f"Average Monthly Take-Home:        ${avg_monthly_takehome_usd:,.2f} USD / month (~₦{avg_monthly_takehome_ngn:,.0f} Naira / month)")
    print(f"Total Closed Trades:              {len(all_closed_trades)} trades (~{len(all_closed_trades)/years:.1f} trades/year or ~{len(all_closed_trades)/(years*12):.1f} trades/month)")
    print(f"Overall Trade Win Rate:           {win_rate:.1f}% ({len(wins)} wins / {len(losses)} losses)")
    print(f"Profit Factor:                    {profit_factor:.2f}")
    print(f"Max Dollar Drawdown in 5 Years:   ${max_dd_dollars:,.2f} ({max_dd_pct:.2f}%)")
    print(f"Prop Firm Survival Status:        {'100% PASSED & SAFE (Max DD was $' + f'{max_dd_dollars:,.2f}' + ' vs $2,000 limit)' if max_dd_dollars < prop_firm_max_dd_limit else 'FAILED'}")

    print("\n" + "-" * 105)
    print(f"{'Year':<6} | {'Bot Profit ($)':<16} | {'Trader Share ($)':<18} | {'Trader Share (₦)':<22} | {'Trades':<8} | {'Win %':<8} | {'S&P 500 Market'}")
    print("-" * 105)
    for y in yearly_stats:
        market_label = f"{y['spy_benchmark_pct']:+6.1f}%"
        if y['year'] == 2022:
            market_label += " (BEAR CRASH!)"
        print(f"{y['year']:<6} | ${y['pnl_usd']:>14,.2f} | ${y['trader_takehome_usd']:>16,.2f} | ₦{y['trader_takehome_ngn']:>20,.0f} | {y['trades']:<8} | {y['win_rate_pct']:>6.1f}% | {market_label}")
    print("-" * 105)

    print("\nMONTHLY CONSISTENCY TELEMETRY:")
    print(f"  Total Months Analyzed:          {len(monthly_pnl)} months")
    print(f"  Profitable Payout Months:       {profitable_months} months ({monthly_win_rate:.1f}% of months)")
    print(f"  Average Closed Trades/Month:    {len(all_closed_trades)/(years*12):.1f} trades per month (~1 trade every week)")
    print(f"  Average Monthly Bot Profit:     ${(total_net_profit_usd/(years*12)):,.2f} / month")
    print(f"  Best Single Month:              +${monthly_pnl.max():,.2f} (Trader Share: +${monthly_pnl.max()*trader_split:,.2f} / ~₦{monthly_pnl.max()*trader_split*naira_rate:,.0f} NGN)")

    # Multi-Account Scaling Analysis
    print("\n" + "=" * 105)
    print("                     MULTI-ACCOUNT SCALING WITH TRADE COPIER")
    print("=" * 105)
    print(f"{'Scale Tier':<15} | {'Funded Capital':<16} | {'Monthly Take-Home ($)':<24} | {'Monthly Take-Home (₦)':<24} | {'5-Year Total (₦)'}")
    print("-" * 105)
    for accts in [1, 2, 5, 10, 20]:
        m_usd = avg_monthly_takehome_usd * accts
        m_ngn = avg_monthly_takehome_ngn * accts
        tot_ngn = trader_takehome_ngn * accts
        cap = initial_capital * accts
        print(f"{f'{accts} Account(s)':<15} | ${cap:>14,.2f} | ${m_usd:>22,.2f} | ₦{m_ngn:>22,.0f} | ₦{tot_ngn:>20,.0f}")
    print("-" * 105)

    # Save to JSON report
    report = {
        "metadata": {
            "strategy": "Super Dual Engine (Option 4)",
            "initial_capital": initial_capital,
            "start_date": spy_c.index.min().strftime("%Y-%m-%d"),
            "end_date": spy_c.index.max().strftime("%Y-%m-%d"),
            "trading_days": total_days,
            "years": round(years, 2),
            "trader_split": trader_split,
            "naira_rate": naira_rate,
        },
        "performance": {
            "final_balance": round(final_balance, 2),
            "total_net_profit_usd": round(total_net_profit_usd, 2),
            "total_net_profit_pct": round(total_net_profit_pct, 2),
            "trader_takehome_usd": round(trader_takehome_usd, 2),
            "trader_takehome_ngn": round(trader_takehome_ngn, 0),
            "avg_monthly_takehome_usd": round(avg_monthly_takehome_usd, 2),
            "avg_monthly_takehome_ngn": round(avg_monthly_takehome_ngn, 0),
            "total_trades": len(all_closed_trades),
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_usd": round(max_dd_dollars, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "prop_firm_survived": max_dd_dollars < prop_firm_max_dd_limit,
        },
        "yearly_stats": yearly_stats,
        "monthly_pnl": {k: round(v, 2) for k, v in monthly_pnl.items()},
    }

    out_file = Path("results/super_dual_engine_5year_report.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, cls=NumpyEncoder)
    print(f"\nFull 5-year report saved to: {out_file}")


if __name__ == "__main__":
    run_super_dual_engine_5year()
