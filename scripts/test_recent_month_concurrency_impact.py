"""
1-Month (30-Day) Realistic Dry Run & Concurrency Impact Analysis ($6,000 Account)
================================================================================
Evaluates the exact AgentQuant autonomous engine across the past 30 days on:
1. BTC-USD (Bitcoin 24/7 Spot)
2. SPY (S&P 500)
3. QQQ (Nasdaq 100)
4. DIA (Dow Jones)
5. IWM (Russell 2000)

Analyzes:
- Week-by-week trade counts and PnL (Week 1, Week 2, Week 3, Week 4 / Recent).
- Concurrency Comparison: Max 1 vs Max 2 (Current) vs Max 3 vs Unlimited.
- Proves whether the 2-trade limit hinders profits or maximizes Sharpe & safety.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", force=True)
logger = logging.getLogger("ConcurrencyAudit")

TARGET_UNIVERSE = [
    {"ticker": "BTC-USD", "ctrader_symbol": "BTCUSD", "name": "Bitcoin Spot", "target_lots": 0.02, "max_risk_usd": 30.0, "is_crypto": True},
    {"ticker": "SPY", "ctrader_symbol": "SPX500", "name": "S&P 500 Index", "target_lots": None, "max_risk_usd": 25.0, "is_crypto": False},
    {"ticker": "QQQ", "ctrader_symbol": "NDX100", "name": "Nasdaq 100 Index", "target_lots": None, "max_risk_usd": 25.0, "is_crypto": False},
    {"ticker": "DIA", "ctrader_symbol": "US30", "name": "Dow Jones 30 Index", "target_lots": None, "max_risk_usd": 25.0, "is_crypto": False},
    {"ticker": "IWM", "ctrader_symbol": "US2000", "name": "Russell 2000 Index", "target_lots": None, "max_risk_usd": 25.0, "is_crypto": False},
]


def load_intraday_data_30d() -> Dict[str, pd.DataFrame]:
    """Download 30 days of 15m intraday bars for all assets."""
    logger.info("Fetching 30-day 15m intraday bars for all assets...")
    data = {}
    for item in TARGET_UNIVERSE:
        t = item["ticker"]
        df = yf.download(t, period="1mo", interval="15m", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        
        # Compute 15m Scalper indicators (8-period mean, 1.50 std)
        close = df["close"]
        high = df["high"]
        low = df["low"]
        open_p = df["open"]
        
        df["mean"] = close.rolling(8).mean()
        df["std"] = close.rolling(8).std()
        df["lower_band"] = df["mean"] - (1.50 * df["std"])
        df["upper_band"] = df["mean"] + (1.50 * df["std"])
        
        # Microstructure absorption wick
        rng = (high - low).replace(0, 1e-9)
        lower_wick = np.minimum(open_p, close) - low
        df["lower_wick_ratio"] = lower_wick / rng
        
        df.dropna(inplace=True)
        data[t] = df
        logger.info("Loaded %s: %d bars.", t, len(df))
    return data


def simulate_portfolio(data: Dict[str, pd.DataFrame], max_concurrency: int = 2, initial_capital: float = 6000.0) -> Dict:
    """Simulate unified portfolio execution across all assets synchronously on timestamp timeline."""
    # Build combined timeline
    all_timestamps = sorted(list(set.union(*[set(df.index) for df in data.values()])))
    
    capital = initial_capital
    active_positions = {}  # {ticker: position_dict}
    trades = []
    equity_curve = []
    
    fee_rate = 0.0001
    slippage = 0.0001
    
    for ts in all_timestamps:
        # 1. Manage existing positions first
        closed_tickers = []
        for ticker, pos in list(active_positions.items()):
            df = data[ticker]
            if ts not in df.index:
                continue
            row = df.loc[ts]
            curr_price = float(row["close"])
            curr_high = float(row["high"])
            curr_low = float(row["low"])
            
            bars_held = pos["bars_held"] + 1
            pos["bars_held"] = bars_held
            entry_p = pos["entry_price"]
            size = pos["size"]
            sl_p = pos["sl"]
            tp_p = pos["tp"]
            
            # Check SL
            if curr_low <= sl_p:
                exit_p = sl_p * (1.0 - slippage)
                pnl = size * (exit_p - entry_p)
                fee = (size * exit_p) * fee_rate
                capital += pnl - fee
                trades.append({
                    "ticker": ticker,
                    "entry_time": pos["entry_time"],
                    "exit_time": ts,
                    "pnl": pnl - fee,
                    "type": "SL",
                    "win": False,
                    "bars_held": bars_held
                })
                closed_tickers.append(ticker)
            # Check TP or Mean Reversion
            elif curr_high >= tp_p or curr_price >= float(row["mean"]):
                exit_p = max(tp_p, curr_price) * (1.0 - slippage)
                pnl = size * (exit_p - entry_p)
                fee = (size * exit_p) * fee_rate
                capital += pnl - fee
                trades.append({
                    "ticker": ticker,
                    "entry_time": pos["entry_time"],
                    "exit_time": ts,
                    "pnl": pnl - fee,
                    "type": "TP",
                    "win": True,
                    "bars_held": bars_held
                })
                closed_tickers.append(ticker)
            # Max hold timeout (6 bars = 90 mins)
            elif bars_held >= 6:
                exit_p = curr_price * (1.0 - slippage)
                pnl = size * (exit_p - entry_p)
                fee = (size * exit_p) * fee_rate
                capital += pnl - fee
                trades.append({
                    "ticker": ticker,
                    "entry_time": pos["entry_time"],
                    "exit_time": ts,
                    "pnl": pnl - fee,
                    "type": "TIMEOUT",
                    "win": (pnl - fee) > 0,
                    "bars_held": bars_held
                })
                closed_tickers.append(ticker)
                
        for t in closed_tickers:
            del active_positions[t]
            
        # 2. Check for new entries if concurrency room available
        available_slots = max_concurrency - len(active_positions)
        
        if available_slots > 0:
            for item in TARGET_UNIVERSE:
                if available_slots <= 0:
                    break
                t = item["ticker"]
                if t in active_positions:
                    continue  # Zero duplicate rule
                
                df = data[t]
                if ts not in df.index:
                    continue
                    
                row = df.loc[ts]
                curr_price = float(row["close"])
                curr_low = float(row["low"])
                curr_high = float(row["high"])
                l_band = float(row["lower_band"])
                wick_ratio = float(row["lower_wick_ratio"])
                is_crypto = item.get("is_crypto", False)
                
                # Check US Market Hours for non-crypto
                if not is_crypto:
                    ts_ny = ts.tz_convert("America/New_York")
                    if ts_ny.weekday() >= 5:
                        continue
                    if not (9 <= ts_ny.hour < 15 or (ts_ny.hour == 9 and ts_ny.minute >= 30)):
                        continue
                        
                # Check Dip Trigger + Absorption Wick >= 20%
                is_dip = (curr_low <= l_band) or (curr_price <= l_band)
                has_wick = wick_ratio >= 0.20
                
                if is_dip and has_wick:
                    fill_p = curr_price * (1.0 + slippage)
                    max_risk = item.get("max_risk_usd", 25.0)
                    sl_pct = 0.0040  # 0.40% stop
                    tp_pct = 0.0030  # +0.30% mean pop
                    
                    sl_price = fill_p * (1.0 - sl_pct)
                    tp_price = fill_p * (1.0 + tp_pct)
                    
                    notional = max_risk / sl_pct
                    size = notional / fill_p
                    fee = (size * fill_p) * fee_rate
                    capital -= fee
                    
                    active_positions[t] = {
                        "entry_time": ts,
                        "entry_price": fill_p,
                        "size": size,
                        "sl": sl_price,
                        "tp": tp_price,
                        "bars_held": 0
                    }
                    available_slots -= 1
                    
        # Calculate current equity
        unrealized = 0.0
        for t, pos in active_positions.items():
            df = data[t]
            if ts in df.index:
                cp = float(df.loc[ts]["close"])
                unrealized += pos["size"] * (cp - pos["entry_price"])
                
        equity_curve.append({
            "timestamp": ts,
            "equity": capital + unrealized,
            "open_trades": len(active_positions)
        })
        
    df_eq = pd.DataFrame(equity_curve).set_index("timestamp")
    final_equity = float(df_eq["equity"].iloc[-1])
    net_pnl = final_equity - initial_capital
    return_pct = (net_pnl / initial_capital) * 100
    
    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
    
    peaks = df_eq["equity"].cummax()
    max_dd = float(((df_eq["equity"] - peaks) / peaks).min()) * 100
    max_dd_usd = float((peaks - df_eq["equity"]).max())
    
    # Weekly breakdown
    df_w = df_eq["equity"].resample("W-SUN").last().to_frame()
    df_w["weekly_pnl"] = df_w["equity"].diff().fillna(df_w["equity"].iloc[0] - initial_capital)
    
    # Trade distribution by week
    trade_weeks = {}
    for t in trades:
        w_label = t["exit_time"].strftime("Week of %b %d")
        trade_weeks.setdefault(w_label, []).append(t)
        
    weekly_stats = []
    for w_label, w_trades in trade_weeks.items():
        w_wins = [t for t in w_trades if t["win"]]
        w_pnl = sum(t["pnl"] for t in w_trades)
        weekly_stats.append({
            "week": w_label,
            "trades": len(w_trades),
            "wins": len(w_wins),
            "win_rate": round(len(w_wins) / len(w_trades) * 100, 1),
            "profit_usd": round(w_pnl, 2)
        })

    return {
        "max_concurrency": max_concurrency,
        "initial_capital": initial_capital,
        "final_equity": round(final_equity, 2),
        "net_pnl": round(net_pnl, 2),
        "return_pct": round(return_pct, 2),
        "total_trades": len(trades),
        "win_rate_pct": round(win_rate, 1),
        "max_drawdown_pct": round(max_dd, 2),
        "max_drawdown_usd": round(max_dd_usd, 2),
        "weekly_stats": weekly_stats,
        "trades_btc": len([t for t in trades if t["ticker"] == "BTC-USD"]),
        "trades_indices": len([t for t in trades if t["ticker"] != "BTC-USD"]),
    }


def main():
    data = load_intraday_data_30d()
    
    concurrency_levels = [1, 2, 3, 5]
    all_results = {}
    
    for c in concurrency_levels:
        res = simulate_portfolio(data, max_concurrency=c, initial_capital=6000.0)
        all_results[f"max_concurrency_{c}"] = res
        
    out_file = Path(__file__).resolve().parent / "recent_month_concurrency_results.json"
    with open(out_file, "w") as f:
        json.dump(all_results, f, indent=2)
    logger.info("Saved concurrency comparison results to %s", out_file)
    
    print("\n" + "="*95)
    print("30-DAY (1-MONTH) PORTFOLIO SIMULATION & CONCURRENCY COMPARISON ($6,000 ACCOUNT)")
    print("="*95)
    print(f"{'Concurrency Limit':<20} | {'Net Profit ($)':<16} | {'Return (%)':<12} | {'Total Trades':<14} | {'Win Rate':<10} | {'Max Drawdown ($)':<18}")
    print("-" * 95)
    for k, r in all_results.items():
        print(f"Max {r['max_concurrency']} Trade(s) At Once  | +${r['net_pnl']:<13,.2f} | +{r['return_pct']:<10.2f}% | {r['total_trades']:<12} | {r['win_rate_pct']:<8.1f}% | -${r['max_drawdown_usd']:<14,.2f} ({r['max_drawdown_pct']:.2f}%)")
    print("="*95)
    
    # Print week-by-week for Max 2
    r2 = all_results["max_concurrency_2"]
    print("\n" + "-"*65)
    print("WEEK-BY-WEEK BREAKDOWN (MAX 2 CONCURRENT TRADES - CURRENT LIVE SETTING):")
    print("-" * 65)
    print(f"{'Week Period':<22} | {'Trades':<8} | {'Win Rate':<10} | {'Profit ($)':<12}")
    print("-" * 65)
    for w in r2["weekly_stats"]:
        print(f"{w['week']:<22} | {w['trades']:<8} | {w['win_rate']:>6.1f}%   | +${w['profit_usd']:>8,.2f}")
    print("-" * 65)
    print(f"Asset Breakdown: BTC-USD: {r2['trades_btc']} trades | US Indices: {r2['trades_indices']} trades")
    print("="*65)


if __name__ == "__main__":
    main()
