"""
AgentQuant V2 — 1-Year Multi-Asset Stress Test (BTC & ETH)
==========================================================
Conducts a full 365-day backtest across Bitcoin (BTCUSD) and Ethereum (ETHUSD)
evaluating the AgentQuant V2 Regime + Market Structure Engine under real broker conditions:
  - Timeframes: 15-Minute (Regime) + 5-Minute (Structure State Machine)
  - Friction: Real cTrader commissions ($34/lot BTC, $10.80/lot ETH), dynamic session spreads (2.5 - 6.0 bps), fill delay
  - Risk Model: $15.00 fixed risk per trade with dynamic lot sizing
  - Target Asymmetry: 2.5R reward-to-risk
  - Outputs: Month-by-month financial ledger, drawdown safety vs FundedNext $180/$360 limits, and expectancy
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.strategies.regime_engine import RegimeEngine
from src.strategies.structure_engine import StructureEngine


def fetch_binance_klines(symbol: str = "BTCUSDT", interval: str = "5m", days: int = 365) -> pd.DataFrame:
    """Fetches continuous OHLCV data from Binance public API with disk caching."""
    cache_dir = ROOT_DIR / "cache" / "1year_crypto"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{symbol}_{interval}_365d.parquet"

    if cache_file.exists():
        print(f"[*] Loading cached {symbol} ({interval}) data from {cache_file.name}...")
        df = pd.read_parquet(cache_file)
        print(f"✅ Loaded {len(df):,} bars ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
        return df

    print(f"[*] Downloading 1-Year ({days} days) {symbol} {interval} bars from exchange API...")
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (days * 86400 * 1000)

    url = "https://api.binance.com/api/v3/klines"
    all_rows = []
    curr_start = start_ms

    while curr_start < now_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": curr_start,
            "limit": 1000
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                print(f"[!] API error {resp.status_code}: {resp.text[:100]}")
                time.sleep(1)
                break
            data = resp.json()
            if not data:
                break
            all_rows.extend(data)
            # Next start time = last bar close + 1ms
            curr_start = data[-1][6] + 1
            time.sleep(0.05)  # respectful rate limit
        except Exception as e:
            print(f"[!] Request failed: {e}")
            break

    if not all_rows:
        raise RuntimeError(f"Failed to fetch historical data for {symbol}")

    records = []
    for r in all_rows:
        records.append({
            "timestamp": pd.to_datetime(r[0], unit="ms", utc=True),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5])
        })

    df = pd.DataFrame(records).drop_duplicates(subset=["timestamp"]).set_index("timestamp").sort_index()
    df.to_parquet(cache_file)
    print(f"💾 Saved {len(df):,} bars to {cache_file}")
    return df


def prepare_multi_timeframe(symbol: str = "BTCUSDT", days: int = 365) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Prepares aligned 5M and 15M datasets."""
    df_5m = fetch_binance_klines(symbol=symbol, interval="5m", days=days)
    df_15m = df_5m.resample("15min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()
    return df_5m, df_15m


def run_1year_v2_simulation(symbol: str = "BTCUSDT", days: int = 365,
                            target_r: float = 2.5, risk_budget_usd: float = 15.0,
                            comm_per_lot: float = 34.0, base_spread_bps: float = 2.5,
                            open_spread_bps: float = 6.0,
                            min_lot: float = 0.01, max_lot: float = 0.08) -> Dict[str, Any]:
    """
    Simulates AgentQuant V2 over 1 full year with realistic fees, spreads, and structural SL.
    """
    sym_clean = symbol.replace("USDT", "USD")
    print(f"\n🔹 Simulating 1-Year AgentQuant V2 on {sym_clean} ({target_r:.1f}R Target, ${risk_budget_usd} Risk)...", flush=True)

    df_5m, df_15m = prepare_multi_timeframe(symbol=symbol, days=days)

    regime_engine = RegimeEngine()
    structure_engine = StructureEngine(target_r_multiple=target_r)

    # 1. Precompute 15M Regimes
    ind_15m = regime_engine.calculate_indicators(df_15m)
    allowed_sides = []
    for _, row in ind_15m.iterrows():
        c = float(row["close"])
        ef = float(row["ema_fast"])
        es = float(row["ema_slow"])
        fs = float(row["ema_fast_slope"])
        cum3 = float(row["cum_ret_3bar"]) if not np.isnan(row["cum_ret_3bar"]) else 0.0
        atrp = float(row["atr_pctile"]) if not np.isnan(row["atr_pctile"]) else 50.0

        if cum3 < -0.015 or (cum3 < -0.010 and atrp >= 85.0) or atrp >= 92.0 or abs(cum3) >= 0.020:
            allowed_sides.append("NONE")
        elif ef > es and c > es and fs > 0.0005:
            allowed_sides.append("BUY_ONLY")
        elif ef < es and c < es and fs < -0.0005:
            allowed_sides.append("SELL_ONLY")
        else:
            allowed_sides.append("RANGE_CHOP")

    regimes_series = pd.Series(allowed_sides, index=df_15m.index)

    # 2. Precompute 5M Swing Points
    r_high, r_low = structure_engine.find_swing_points(df_5m, window=structure_engine.swing_window)
    df_5m_proc = df_5m.copy()
    df_5m_proc["prior_high"] = r_high
    df_5m_proc["prior_low"] = r_low

    trades = []
    in_pos = False
    pos_side = "BUY"
    entry_p = 0.0
    sl_p = 0.0
    tp_p = 0.0
    lots = 0.0
    bars_held = 0
    entry_time = None

    n_5m = len(df_5m_proc)
    for i in range(30, n_5m):
        curr_time = df_5m_proc.index[i]
        bar = df_5m_proc.iloc[i]
        h, l, c = bar["high"], bar["low"], bar["close"]
        hour = curr_time.hour
        is_open = hour in (8, 9, 13, 14)
        spread_bps = open_spread_bps if is_open else base_spread_bps

        if in_pos:
            bars_held += 1
            if pos_side == "BUY":
                if l <= sl_p:
                    exit_p = sl_p - (sl_p * (spread_bps / 10000.0))
                    gross = (exit_p - entry_p) * lots
                    comm = comm_per_lot * lots * 2
                    net = gross - comm
                    trades.append({
                        "entry_time": entry_time, "exit_time": curr_time, "symbol": sym_clean,
                        "side": pos_side, "lots": lots, "entry": entry_p, "exit": exit_p,
                        "pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "STRUCTURAL_SL"
                    })
                    in_pos = False
                elif h >= tp_p:
                    exit_p = tp_p - (tp_p * (spread_bps / 10000.0))
                    gross = (exit_p - entry_p) * lots
                    comm = comm_per_lot * lots * 2
                    net = gross - comm
                    trades.append({
                        "entry_time": entry_time, "exit_time": curr_time, "symbol": sym_clean,
                        "side": pos_side, "lots": lots, "entry": entry_p, "exit": exit_p,
                        "pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "TP_2.5R"
                    })
                    in_pos = False
                elif bars_held >= 24:
                    exit_p = c - (c * (spread_bps / 10000.0))
                    gross = (exit_p - entry_p) * lots
                    comm = comm_per_lot * lots * 2
                    net = gross - comm
                    trades.append({
                        "entry_time": entry_time, "exit_time": curr_time, "symbol": sym_clean,
                        "side": pos_side, "lots": lots, "entry": entry_p, "exit": exit_p,
                        "pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "TIMEOUT"
                    })
                    in_pos = False

            elif pos_side == "SELL":
                if h >= sl_p:
                    exit_p = sl_p + (sl_p * (spread_bps / 10000.0))
                    gross = (entry_p - exit_p) * lots
                    comm = comm_per_lot * lots * 2
                    net = gross - comm
                    trades.append({
                        "entry_time": entry_time, "exit_time": curr_time, "symbol": sym_clean,
                        "side": pos_side, "lots": lots, "entry": entry_p, "exit": exit_p,
                        "pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "STRUCTURAL_SL"
                    })
                    in_pos = False
                elif l <= tp_p:
                    exit_p = tp_p + (tp_p * (spread_bps / 10000.0))
                    gross = (entry_p - exit_p) * lots
                    comm = comm_per_lot * lots * 2
                    net = gross - comm
                    trades.append({
                        "entry_time": entry_time, "exit_time": curr_time, "symbol": sym_clean,
                        "side": pos_side, "lots": lots, "entry": entry_p, "exit": exit_p,
                        "pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "TP_2.5R"
                    })
                    in_pos = False
                elif bars_held >= 24:
                    exit_p = c + (c * (spread_bps / 10000.0))
                    gross = (entry_p - exit_p) * lots
                    comm = comm_per_lot * lots * 2
                    net = gross - comm
                    trades.append({
                        "entry_time": entry_time, "exit_time": curr_time, "symbol": sym_clean,
                        "side": pos_side, "lots": lots, "entry": entry_p, "exit": exit_p,
                        "pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "TIMEOUT"
                    })
                    in_pos = False
            continue

        # Check entry setup
        loc_15m = regimes_series.loc[:curr_time]
        if len(loc_15m) == 0:
            continue
        allowed_side = loc_15m.iloc[-1]
        if allowed_side in ("NONE", "RANGE_CHOP"):
            continue

        sub_5m = df_5m_proc.iloc[max(0, i - 35):i + 1]
        setup = structure_engine.evaluate_setup(sub_5m, allowed_side=allowed_side)
        if setup:
            pos_side = setup.side
            entry_p = setup.retest_entry_price
            sl_p = setup.structural_sl_price
            tp_p = setup.take_profit_price

            lots = structure_engine.calculate_lot_size(
                entry_price=entry_p, sl_price=sl_p, risk_usd=risk_budget_usd,
                symbol=sym_clean, min_lot=min_lot, max_lot=max_lot
            )

            slip = entry_p * (spread_bps / 10000.0)
            entry_p = entry_p + slip if pos_side == "BUY" else entry_p - slip
            in_pos = True
            bars_held = 0
            entry_time = curr_time

    return analyze_annual_results(sym_clean, trades, df_5m)


def analyze_annual_results(symbol: str, trades: List[Dict[str, Any]], df_5m: pd.DataFrame) -> Dict[str, Any]:
    if not trades:
        return {"symbol": symbol, "total_trades": 0, "win_rate_pct": 0.0, "net_profit_usd": 0.0}

    df_t = pd.DataFrame(trades)
    df_t["exit_time"] = pd.to_datetime(df_t["exit_time"])
    df_t.set_index("exit_time", inplace=True)

    pnls = df_t["pnl"]
    wins = df_t[df_t["is_win"]]
    losses = df_t[~df_t["is_win"]]

    total_trades = len(df_t)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total_trades) * 100.0

    avg_win = float(wins["pnl"].mean()) if len(wins) > 0 else 0.0
    avg_loss = float(abs(losses["pnl"].mean())) if len(losses) > 0 else 0.0
    payoff = avg_win / avg_loss if avg_loss > 0 else 0.0

    # Net Expectancy
    expectancy = ((win_rate / 100.0) * avg_win) - (((100.0 - win_rate) / 100.0) * avg_loss)

    total_gross = float(df_t["gross"].sum())
    total_comm = float(df_t["comm"].sum())
    total_net = float(df_t["pnl"].sum())

    gross_wins = float(df_t[df_t["gross"] > 0]["gross"].sum())
    gross_losses = abs(float(df_t[df_t["gross"] < 0]["gross"].sum()))
    pf = gross_wins / gross_losses if gross_losses > 0 else 999.0

    # Equity Curve & Drawdown
    df_t["cum_pnl"] = df_t["pnl"].cumsum()
    peak = df_t["cum_pnl"].cummax()
    drawdowns = df_t["cum_pnl"] - peak
    max_dd = float(drawdowns.min())

    # Daily & Monthly Aggregation
    df_monthly = df_t["pnl"].resample("ME").sum().to_frame()
    df_monthly["trade_count"] = df_t["pnl"].resample("ME").count()
    df_monthly["win_count"] = df_t["is_win"].resample("ME").sum()
    df_monthly["win_rate"] = (df_monthly["win_count"] / df_monthly["trade_count"]) * 100.0

    # Convert to standard dictionary
    monthly_breakdown = []
    for dt, row in df_monthly.iterrows():
        monthly_breakdown.append({
            "month": dt.strftime("%B %Y"),
            "trades": int(row["trade_count"]),
            "win_rate_pct": round(row["win_rate"], 1) if not np.isnan(row["win_rate"]) else 0.0,
            "net_pnl_usd": round(row["pnl"], 2),
            "net_pnl_ngn": round(row["pnl"] * 1650.0, 0)
        })

    # Trade Frequency
    start_date = df_5m.index[0]
    end_date = df_5m.index[-1]
    days_span = max(1, (end_date - start_date).days)
    trades_per_day = total_trades / days_span
    trades_per_week = trades_per_day * 7.0
    trades_per_month = trades_per_day * 30.4

    return {
        "symbol": symbol,
        "period": f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} ({days_span} days)",
        "total_trades": total_trades,
        "trades_per_day": round(trades_per_day, 2),
        "trades_per_week": round(trades_per_week, 1),
        "trades_per_month": round(trades_per_month, 1),
        "wins": win_count,
        "losses": loss_count,
        "win_rate_pct": round(win_rate, 2),
        "avg_win_usd": round(avg_win, 2),
        "avg_loss_usd": round(avg_loss, 2),
        "payoff_ratio": round(payoff, 2),
        "expectancy_per_trade_usd": round(expectancy, 2),
        "profit_factor": round(pf, 2),
        "total_gross_usd": round(total_gross, 2),
        "total_commission_usd": round(total_comm, 2),
        "net_profit_usd": round(total_net, 2),
        "net_profit_ngn": round(total_net * 1650.0, 0),
        "max_drawdown_usd": round(max_dd, 2),
        "fundednext_daily_buffer_safe": abs(max_dd) < 180.0,
        "fundednext_max_buffer_safe": abs(max_dd) < 360.0,
        "monthly_breakdown": monthly_breakdown
    }


def main():
    print("=" * 85)
    print("🚀 AGENTQUANT V2 — 1-YEAR INSTITUTIONAL STRESS TEST (BTC & ETH)")
    print("   Target Model: 15M Regime + 5M Structure + Structural SL + 2.5R Target")
    print("   Risk Model: $15.00 Fixed Risk / Trade | Exchange-Accurate Fees & Spreads")
    print("=" * 85)

    # 1. Run Bitcoin 1-Year Stress Test
    btc_results = run_1year_v2_simulation(
        symbol="BTCUSDT", days=365, target_r=2.5, risk_budget_usd=15.0,
        comm_per_lot=34.0, base_spread_bps=2.5, open_spread_bps=6.0,
        min_lot=0.01, max_lot=0.08
    )

    # 2. Run Ethereum 1-Year Stress Test
    eth_results = run_1year_v2_simulation(
        symbol="ETHUSDT", days=365, target_r=2.5, risk_budget_usd=15.0,
        comm_per_lot=10.80, base_spread_bps=3.0, open_spread_bps=6.5,
        min_lot=0.10, max_lot=1.00
    )

    # Print Master Summary Tables
    for res in (btc_results, eth_results):
        sym = res["symbol"]
        print("\n" + "=" * 85)
        print(f"📊 1-YEAR AUDITED RESULTS: {sym} (V2 REGIME + STRUCTURE 2.5R)")
        print(f"   Window: {res['period']}")
        print("=" * 85)
        print(f"• Total Trades:          {res['total_trades']:,} trades ({res['trades_per_day']} / day | {res['trades_per_week']} / week | {res['trades_per_month']} / mo)")
        print(f"• Win Rate:              {res['win_rate_pct']:.2f}% ({res['wins']} Wins / {res['losses']} Losses)")
        print(f"• Average Winner:        +${res['avg_win_usd']:.2f} USD")
        print(f"• Average Loser:         -${res['avg_loss_usd']:.2f} USD")
        print(f"• Payoff Ratio:          {res['payoff_ratio']:.2f} : 1")
        print(f"• Net Expectancy/Trade:  +${res['expectancy_per_trade_usd']:.2f} USD per trade 🎯")
        print(f"• Profit Factor:         {res['profit_factor']:.2f}")
        print(f"• Total Commission Paid: -${res['total_commission_usd']:,.2f} USD")
        print(f"• Max Account Drawdown:  -${abs(res['max_drawdown_usd']):.2f} USD (FundedNext $180 Daily Buffer: {'✅ SAFE' if res['fundednext_daily_buffer_safe'] else '❌ BREACHED'})")
        print("-" * 85)
        print(f"💰 NET REALIZED PROFIT:   +${res['net_profit_usd']:,.2f} USD (~₦{res['net_profit_ngn']:,.0f} Naira)")
        print("-" * 85)
        print("📅 MONTH-BY-MONTH FINANCIAL LEDGER:")
        print(f"{'Month':<18} {'Trades':<8} {'Win Rate':<10} {'Net USD ($)':<15} {'Net NGN (~₦)':<15}")
        print("-" * 70)
        for m in res["monthly_breakdown"]:
            pnl_str = f"+${m['net_pnl_usd']:,.2f}" if m['net_pnl_usd'] >= 0 else f"-${abs(m['net_pnl_usd']):,.2f}"
            ngn_str = f"+₦{m['net_pnl_ngn']:,.0f}" if m['net_pnl_ngn'] >= 0 else f"-₦{abs(m['net_pnl_ngn']):,.0f}"
            print(f"{m['month']:<18} {m['trades']:<8} {m['win_rate_pct']:>6.1f}%   {pnl_str:<15} {ngn_str:<15}")
        print("=" * 85)

    # Save Combined Results JSON
    out_file = ROOT_DIR / "cache" / "1year_v2_btc_eth_results.json"
    with open(out_file, "w") as f:
        json.dump({"BTCUSD": btc_results, "ETHUSD": eth_results}, f, indent=2)
    print(f"\n💾 Full 1-Year Audit Report persisted to: {out_file}")


if __name__ == "__main__":
    main()
