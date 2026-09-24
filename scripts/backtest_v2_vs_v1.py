"""
AgentQuant V2 vs V1 Head-to-Head Comparative Backtest
=====================================================
Direct empirical comparison between:
  1. Engine V1: 1-Minute Dip-Reversion (Fixed 0.35% SL, +0.75% TP, Long-Only)
  2. Engine V2: Multi-Timeframe Regime (15M) + Market Structure (5M) + Structural SL (2.0R TP, Longs & Shorts)

Tested on real Bitcoin M1/M5/M15 historical data with realistic commissions & slippage.
"""

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.strategies.regime_engine import RegimeEngine
from src.strategies.structure_engine import StructureEngine


def load_resampled_data(parquet_path: Path, max_bars: int = 40000):
    """Loads 1M data and resamples cleanly into 5M and 15M OHLCV."""
    print(f"[*] Ingesting historical parquet from {parquet_path.name}...")
    df_1m = pd.read_parquet(parquet_path)
    if max_bars and len(df_1m) > max_bars:
        df_1m = df_1m.iloc[-max_bars:].copy()

    # Ensure lowercase standard OHLCV
    col_map = {str(c).lower(): c for c in df_1m.columns}
    df_1m = pd.DataFrame({
        "open": df_1m[col_map["open"]],
        "high": df_1m[col_map["high"]],
        "low": df_1m[col_map["low"]],
        "close": df_1m[col_map["close"]],
        "volume": df_1m[col_map["volume"]],
    }, index=df_1m.index)

    # Resample 5M and 15M
    df_5m = df_1m.resample("5min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()

    df_15m = df_1m.resample("15min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()

    print(f"✅ Data ready: {len(df_1m):,} M1 bars | {len(df_5m):,} 5M bars | {len(df_15m):,} 15M bars\n")
    return df_1m, df_5m, df_15m


def simulate_v1_engine(df_1m: pd.DataFrame, window: int = 20, num_std: float = 1.5,
                       sl_pct: float = 0.0035, tp_pct: float = 0.0075,
                       max_hold_bars: int = 12, lot_size: float = 0.02,
                       commission_per_lot: float = 34.0, slippage_bps: float = 2.0) -> Dict[str, Any]:
    """
    Simulates V1: 1-Minute Dip-Reversion with fixed percentage stop and target.
    """
    print("🔹 Running Engine V1: 1-Minute Fixed Dip-Reversion...")
    close = df_1m["close"].to_numpy()
    high = df_1m["high"].to_numpy()
    low = df_1m["low"].to_numpy()
    n = len(close)

    # Rolling mean and std
    mid = df_1m["close"].rolling(window).mean().to_numpy()
    std = df_1m["close"].rolling(window).std().to_numpy()
    lower_band = mid - num_std * std

    trades = []
    in_pos = False
    entry_p = 0.0
    entry_idx = 0
    bars_held = 0

    for i in range(window, n):
        if not in_pos:
            # Dip condition: price closes below lower band
            if close[i] <= lower_band[i]:
                # Enter Long on next open/current close with slippage
                slip = close[i] * (slippage_bps / 10000.0)
                entry_p = close[i] + slip
                entry_idx = i
                in_pos = True
                bars_held = 0
        else:
            bars_held += 1
            curr_h = high[i]
            curr_l = low[i]
            sl_price = entry_p * (1.0 - sl_pct)
            tp_price = entry_p * (1.0 + tp_pct)

            # Check Stop Loss hit
            if curr_l <= sl_price:
                exit_p = sl_price
                gross = (exit_p - entry_p) * lot_size
                comm = commission_per_lot * lot_size * 2
                net = gross - comm
                trades.append({"pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "SL"})
                in_pos = False
            # Check Take Profit hit
            elif curr_h >= tp_price:
                exit_p = tp_price
                gross = (exit_p - entry_p) * lot_size
                comm = commission_per_lot * lot_size * 2
                net = gross - comm
                trades.append({"pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "TP"})
                in_pos = False
            # Check timeout
            elif bars_held >= max_hold_bars:
                exit_p = close[i]
                gross = (exit_p - entry_p) * lot_size
                comm = commission_per_lot * lot_size * 2
                net = gross - comm
                trades.append({"pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "TIMEOUT"})
                in_pos = False

    return compute_metrics("Engine V1 (1M Fixed SL 0.35%)", trades)


def simulate_v2_engine(df_1m: pd.DataFrame, df_5m: pd.DataFrame, df_15m: pd.DataFrame,
                       risk_budget_usd: float = 15.0, target_r: float = 2.0,
                       commission_per_lot: float = 34.0, slippage_bps: float = 2.0) -> Dict[str, Any]:
    """
    Simulates V2: 15M Regime + 5M Structure + Structural SL + Dynamic Sizing + 2.0R Target.
    Optimized with precomputed indicators for high execution speed.
    """
    print("🔹 Running Engine V2: 15M Regime + 5M Structure + 2.0R TP...", flush=True)
    regime_engine = RegimeEngine()
    structure_engine = StructureEngine(target_r_multiple=target_r)

    # 1. Precompute 15M Indicators & Regimes once
    ind_15m = regime_engine.calculate_indicators(df_15m)
    allowed_sides_15m = []
    for idx, row in ind_15m.iterrows():
        c = float(row["close"])
        ef = float(row["ema_fast"])
        es = float(row["ema_slow"])
        fs = float(row["ema_fast_slope"])
        cum3 = float(row["cum_ret_3bar"]) if not np.isnan(row["cum_ret_3bar"]) else 0.0
        atrp = float(row["atr_pctile"]) if not np.isnan(row["atr_pctile"]) else 50.0

        if cum3 < -0.015 or (cum3 < -0.010 and atrp >= 85.0) or atrp >= 92.0 or abs(cum3) >= 0.020:
            allowed_sides_15m.append("NONE")
        elif ef > es and c > es and fs > 0.0005:
            allowed_sides_15m.append("BUY_ONLY")
        elif ef < es and c < es and fs < -0.0005:
            allowed_sides_15m.append("SELL_ONLY")
        else:
            allowed_sides_15m.append("BOTH")

    regimes_series = pd.Series(allowed_sides_15m, index=df_15m.index)

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

    n_5m = len(df_5m_proc)
    for i in range(30, n_5m):
        curr_time = df_5m_proc.index[i]
        bar = df_5m_proc.iloc[i]
        h, l, c = bar["high"], bar["low"], bar["close"]

        # Position Management
        if in_pos:
            bars_held += 1
            if pos_side == "BUY":
                if l <= sl_p:
                    exit_p = sl_p
                    gross = (exit_p - entry_p) * lots
                    comm = commission_per_lot * lots * 2
                    net = gross - comm
                    trades.append({"pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "STRUCTURAL_SL"})
                    in_pos = False
                elif h >= tp_p:
                    exit_p = tp_p
                    gross = (exit_p - entry_p) * lots
                    comm = commission_per_lot * lots * 2
                    net = gross - comm
                    trades.append({"pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "TP_2R"})
                    in_pos = False
                elif bars_held >= 24:
                    exit_p = c
                    gross = (exit_p - entry_p) * lots
                    comm = commission_per_lot * lots * 2
                    net = gross - comm
                    trades.append({"pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "TIMEOUT"})
                    in_pos = False

            elif pos_side == "SELL":
                if h >= sl_p:
                    exit_p = sl_p
                    gross = (entry_p - exit_p) * lots
                    comm = commission_per_lot * lots * 2
                    net = gross - comm
                    trades.append({"pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "STRUCTURAL_SL"})
                    in_pos = False
                elif l <= tp_p:
                    exit_p = tp_p
                    gross = (entry_p - exit_p) * lots
                    comm = commission_per_lot * lots * 2
                    net = gross - comm
                    trades.append({"pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "TP_2R"})
                    in_pos = False
                elif bars_held >= 24:
                    exit_p = c
                    gross = (entry_p - exit_p) * lots
                    comm = commission_per_lot * lots * 2
                    net = gross - comm
                    trades.append({"pnl": net, "gross": gross, "comm": comm, "is_win": net > 0, "reason": "TIMEOUT"})
                    in_pos = False
            continue

        # Look for Entry Setup
        # Lookup 15M regime asof curr_time
        loc_15m = regimes_series.loc[:curr_time]
        if len(loc_15m) == 0:
            continue
        allowed_side = loc_15m.iloc[-1]
        
        # High-Conviction Filter: Suppress chop (Don't trade in RANGE_BOUND, only trade confirmed trends)
        if allowed_side in ("NONE", "BOTH"):
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
                symbol="BTCUSD", min_lot=0.01, max_lot=0.08
            )
            # Apply entry slippage
            slip = entry_p * (slippage_bps / 10000.0)
            entry_p = entry_p + slip if pos_side == "BUY" else entry_p - slip
            in_pos = True
            bars_held = 0

    return compute_metrics("Engine V2 (15M Regime + 5M Structure 2.0R)", trades)


def compute_metrics(name: str, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {
            "name": name,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "total_net_pnl": 0.0,
            "avg_win_usd": 0.0,
            "avg_loss_usd": 0.0,
            "payoff_ratio": 0.0,
            "profit_factor": 0.0,
            "total_commission_usd": 0.0,
            "max_drawdown_usd": 0.0
        }

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total_pnl = sum(pnls)
    win_rate = (len(wins) / len(trades)) * 100.0 if trades else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    payoff = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

    # Max Drawdown
    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    drawdowns = equity - peak
    max_dd = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0

    gross_wins = sum(t["gross"] for t in trades if t["gross"] > 0)
    gross_losses = abs(sum(t["gross"] for t in trades if t["gross"] < 0))
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else 999.0
    total_comm = sum(t["comm"] for t in trades)

    return {
        "name": name,
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 2),
        "total_net_pnl": round(total_pnl, 2),
        "avg_win_usd": round(avg_win, 2),
        "avg_loss_usd": round(avg_loss, 2),
        "payoff_ratio": round(payoff, 2),
        "profit_factor": round(profit_factor, 2),
        "total_commission_usd": round(total_comm, 2),
        "max_drawdown_usd": round(max_dd, 2)
    }


def main():
    parquet_path = ROOT_DIR / "cache" / "crypto_1m" / "BTCUSDT_1m_250k.parquet"
    if not parquet_path.exists():
        print(f"❌ Parquet file not found at {parquet_path}")
        return

    # Use 90,000 bars (~62 days of continuous 1-minute ticks)
    df_1m, df_5m, df_15m = load_resampled_data(parquet_path, max_bars=90000)

    res_v1 = simulate_v1_engine(df_1m)
    res_v2 = simulate_v2_engine(df_1m, df_5m, df_15m)

    print("\n" + "=" * 80)
    print("🏆 HEAD-TO-HEAD AUDIT RESULTS: V1 SCALPER vs V2 REGIME + STRUCTURE")
    print("=" * 80)
    print(f"{'Performance Metric':<28} {'Engine V1 (M1 Fixed SL)':<24} {'Engine V2 (15M Regime + 5M Structure)':<26}")
    print("-" * 80)
    print(f"{'Total Trades Taken':<28} {res_v1['total_trades']:<24} {res_v2['total_trades']:<26}")
    print(f"{'Win Rate (%)':<28} {res_v1['win_rate_pct']:<23}% {res_v2['win_rate_pct']:<25}%")
    print(f"{'Average Win ($)':<28} ${res_v1['avg_win_usd']:<23.2f} ${res_v2['avg_win_usd']:<25.2f}")
    print(f"{'Average Loss ($)':<28} -${abs(res_v1['avg_loss_usd']):<22.2f} -${abs(res_v2['avg_loss_usd']):<24.2f}")
    print(f"{'Payoff Ratio (Win / Loss)':<28} 1 : {1/max(0.01, res_v1['payoff_ratio']):<20.2f} {res_v2['payoff_ratio']:<22.2f} : 1 🎯")
    print(f"{'Profit Factor':<28} {res_v1['profit_factor']:<24} {res_v2['profit_factor']:<26}")
    print(f"{'Total Commission Drag':<28} ${res_v1['total_commission_usd']:<23.2f} ${res_v2['total_commission_usd']:<25.2f}")
    print(f"{'Max Drawdown ($)':<28} -${abs(res_v1['max_drawdown_usd']):<22.2f} -${abs(res_v2['max_drawdown_usd']):<24.2f}")
    print("-" * 80)
    print(f"{'NET REALIZED PROFIT':<28} ${res_v1['total_net_pnl']:>+15.2f} USD      ${res_v2['total_net_pnl']:>+15.2f} USD")
    print("=" * 80)

if __name__ == "__main__":
    main()
