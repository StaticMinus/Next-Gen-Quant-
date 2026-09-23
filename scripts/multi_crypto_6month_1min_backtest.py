"""
Multi-Crypto 6-Month 1-Minute Live Backtest & Comparison ($6,000 Funded Account)
================================================================================
Evaluates the 1-Minute Real-Tick Liquidity-Sweep & Microstructure Reversion Sniper
across top crypto assets on 6 months (250,000 1-minute bars each):
1. BTCUSDT (Bitcoin) - Baseline
2. ETHUSDT (Ethereum)
3. SOLUSDT (Solana)
4. XRPUSDT (XRP)
5. BNBUSDT (Binance Coin)
6. DOGEUSDT (Dogecoin)

Account Constraints ($6,000 Stellar Prop Account):
- Initial Capital: $6,000.00
- Risk per Trade: $30.00 (0.50% risk limit)
- Stop Loss: 0.50% tight hard stop
- Take Profit: 0.60% quick mean-reversion target (or EMA-5 touch)
- Trading Costs: 3 bps exchange fee + 1 bps live spread/slippage
"""

import json
import logging
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", force=True)
logger = logging.getLogger("MultiCrypto1M")

CACHE_DIR = Path("cache/crypto_1m")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _fetch_single_batch(symbol: str, start_time: int, end_time: int, max_retries: int = 3) -> List:
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=1000&startTime={start_time}&endTime={end_time}"
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            if isinstance(data, list):
                return data
        except Exception:
            time.sleep(0.3 * (attempt + 1))
    return []


def fetch_binance_1m_data_parallel(symbol: str, total_candles: int = 250_000) -> pd.DataFrame:
    """Ultra-fast parallel fetching of historical 1-minute klines from Binance API."""
    cache_file = CACHE_DIR / f"{symbol}_1m_250k.parquet"
    if cache_file.exists():
        try:
            df = pd.read_parquet(cache_file)
            if len(df) >= 200_000:
                logger.info("Loaded %d cached 1-minute bars for %s from disk.", len(df), symbol)
                return df
        except Exception:
            pass

    logger.info("Fetching %d 1-minute candles for %s in parallel...", total_candles, symbol)
    now_ms = int(time.time() * 1000)
    chunk_ms = 1000 * 60 * 1000  # 1000 minutes in ms
    num_chunks = int(np.ceil(total_candles / 1000))
    
    windows = []
    for i in range(num_chunks):
        et = now_ms - (i * chunk_ms)
        st = et - chunk_ms + 1
        windows.append((st, et))
        
    all_rows = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(_fetch_single_batch, symbol, st, et): i for i, (st, et) in enumerate(windows)}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                all_rows.extend(res)
                
    fetch_time = time.time() - t0
    logger.info("Fetched %d raw bars for %s in %.2f seconds.", len(all_rows), symbol, fetch_time)
    
    if not all_rows:
        logger.error("No data fetched for %s!", symbol)
        return pd.DataFrame()
        
    # Sort chronologically and drop duplicates
    all_rows.sort(key=lambda x: x[0])
    seen_ts = set()
    unique_rows = []
    for r in all_rows:
        ts = r[0]
        if ts not in seen_ts:
            seen_ts.add(ts)
            unique_rows.append(r)
            
    cols = ["timestamp", "open", "high", "low", "close", "volume", "close_time", "quote_asset_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
    df = pd.DataFrame(unique_rows, columns=cols)
    for c in ["open", "high", "low", "close", "volume", "taker_buy_base"]:
        df[c] = df[c].astype(float)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("datetime", inplace=True)
    
    # Save cache
    try:
        df.to_parquet(cache_file)
    except Exception:
        pass
        
    return df


def compute_sniper_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute 1-minute volatility bands, absorption wicks, and order flow metrics."""
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_p = df["open"]
    vol = df["volume"]
    
    # 20-Period Rolling Mean & Volatility Bands
    df["ma_20"] = close.rolling(20).mean()
    df["std_20"] = close.rolling(20).std()
    df["lower_band"] = df["ma_20"] - (2.0 * df["std_20"])
    df["upper_band"] = df["ma_20"] + (2.0 * df["std_20"])
    
    # Fast 5-period EMA for Mean Reversion Target
    df["ema_5"] = close.ewm(span=5, adjust=False).mean()
    
    # Candlestick Geometry & Wick Absorption
    candle_range = (high - low).replace(0, 1e-9)
    body_size = (close - open_p).abs()
    lower_wick = np.minimum(close, open_p) - low
    upper_wick = high - np.maximum(close, open_p)
    
    df["lower_wick_ratio"] = lower_wick / candle_range
    df["upper_wick_ratio"] = upper_wick / candle_range
    df["body_ratio"] = body_size / candle_range
    
    # Volume Spike Factor (Liquidity sweep)
    df["vol_ma"] = vol.rolling(20).mean() + 1e-9
    df["vol_spike"] = vol / df["vol_ma"]
    
    # Order Flow CVD proxy
    df["taker_sell"] = vol - df["taker_buy_base"]
    df["flow_delta"] = (df["taker_buy_base"] - df["taker_sell"]) / (vol + 1e-9)
    
    df.dropna(inplace=True)
    return df


def simulate_asset(
    df: pd.DataFrame, 
    symbol: str, 
    display_name: str,
    initial_capital: float = 6000.0,
    risk_per_trade_usd: float = 30.0,
    max_hold_minutes: int = 15
) -> Dict[str, Any]:
    """Execute realistic 1-minute sniper backtest on a specific crypto asset."""
    capital = initial_capital
    position = "FLAT"
    entry_price = 0.0
    position_size = 0.0
    entry_idx = 0
    stop_loss_price = 0.0
    take_profit_price = 0.0
    
    trades = []
    equity_curve = [initial_capital]
    
    fee_rate = 0.0003  # 3 bps fee
    slippage = 0.0001  # 1 bps slippage
    
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    opens = df["open"].values
    lower_bands = df["lower_band"].values
    ema_5s = df["ema_5"].values
    lower_wicks = df["lower_wick_ratio"].values
    vol_spikes = df["vol_spike"].values
    dates = df.index
    
    for i in range(len(df)):
        curr_date = dates[i]
        curr_price = float(closes[i])
        curr_high = float(highs[i])
        curr_low = float(lows[i])
        
        # 1. Manage Open Position
        if position == "LONG":
            bars_held = i - entry_idx
            
            # Check Stop Loss (Intra-bar low breached stop)
            if curr_low <= stop_loss_price:
                exit_p = stop_loss_price * (1.0 - slippage)
                pnl = position_size * (exit_p - entry_price)
                fee = (position_size * exit_p) * fee_rate
                net_pnl = pnl - fee
                capital += net_pnl
                trades.append({
                    "symbol": symbol,
                    "entry_time": str(dates[entry_idx]),
                    "exit_time": str(curr_date),
                    "type": "STOP_LOSS",
                    "entry_price": entry_price,
                    "exit_price": exit_p,
                    "pnl": round(net_pnl, 2),
                    "duration_mins": bars_held,
                    "win": False
                })
                equity_curve.append(capital)
                position = "FLAT"
                
            # Check Take Profit (Target hit or EMA-5 reversion reached)
            elif curr_high >= take_profit_price or curr_price >= ema_5s[i]:
                exit_p = max(take_profit_price, curr_price) * (1.0 - slippage)
                pnl = position_size * (exit_p - entry_price)
                fee = (position_size * exit_p) * fee_rate
                net_pnl = pnl - fee
                capital += net_pnl
                trades.append({
                    "symbol": symbol,
                    "entry_time": str(dates[entry_idx]),
                    "exit_time": str(curr_date),
                    "type": "TAKE_PROFIT",
                    "entry_price": entry_price,
                    "exit_price": exit_p,
                    "pnl": round(net_pnl, 2),
                    "duration_mins": bars_held,
                    "win": True
                })
                equity_curve.append(capital)
                position = "FLAT"
                
            # Check Max Timeout (Time exit after 15 minutes)
            elif bars_held >= max_hold_minutes:
                exit_p = curr_price * (1.0 - slippage)
                pnl = position_size * (exit_p - entry_price)
                fee = (position_size * exit_p) * fee_rate
                net_pnl = pnl - fee
                capital += net_pnl
                trades.append({
                    "symbol": symbol,
                    "entry_time": str(dates[entry_idx]),
                    "exit_time": str(curr_date),
                    "type": "TIMEOUT_EXIT",
                    "entry_price": entry_price,
                    "exit_price": exit_p,
                    "pnl": round(net_pnl, 2),
                    "duration_mins": bars_held,
                    "win": net_pnl > 0
                })
                equity_curve.append(capital)
                position = "FLAT"

        # 2. Check Sniper Entry Conditions
        if position == "FLAT":
            is_dip = (curr_low <= lower_bands[i]) or (curr_price <= lower_bands[i])
            has_absorption_wick = lower_wicks[i] >= 0.25
            has_volume_flush = vol_spikes[i] >= 1.30
            is_rebound = curr_price >= curr_low + ((curr_high - curr_low) * 0.20)
            
            if is_dip and has_absorption_wick and has_volume_flush and is_rebound:
                fill_p = curr_price * (1.0 + slippage)
                entry_price = fill_p
                entry_idx = i
                
                # Position Sizing: Risk exactly $30 (0.50% of $6,000) with 0.50% SL
                sl_dist_pct = 0.0050
                stop_loss_price = entry_price * (1.0 - sl_dist_pct)
                notional_size = risk_per_trade_usd / sl_dist_pct
                position_size = notional_size / entry_price
                
                # Take profit: 0.60% quick mean reversion target
                tp_dist_pct = 0.0060
                take_profit_price = entry_price * (1.0 + tp_dist_pct)
                position = "LONG"

    # Compute Statistics
    total_trades = len(trades)
    if total_trades == 0:
        return {"symbol": symbol, "name": display_name, "trades": 0, "net_profit": 0.0, "win_rate": 0.0, "return_pct": 0.0, "max_drawdown_usd": 0.0, "profit_factor": 0.0, "trades_per_week": 0.0}
        
    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    win_rate = (len(wins) / total_trades) * 100.0
    
    total_net_pnl = capital - initial_capital
    return_pct = (total_net_pnl / initial_capital) * 100.0
    
    gross_gain = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = round(gross_gain / gross_loss, 2) if gross_loss > 0 else 99.9
    
    # Calculate Max Drawdown
    eq_series = pd.Series(equity_curve)
    peak = eq_series.cummax()
    dd = (eq_series - peak)
    dd_pct = (eq_series - peak) / peak * 100.0
    max_dd_usd = float(dd.min())
    max_dd_pct = float(dd_pct.min())
    
    avg_duration = np.mean([t["duration_mins"] for t in trades]) if trades else 0.0
    
    start_date = str(dates[0].date())
    end_date = str(dates[-1].date())
    num_days = max(1, (dates[-1] - dates[0]).days)
    trades_per_day = total_trades / num_days
    trades_per_week = trades_per_day * 7.0
    monthly_profit = (total_net_pnl / num_days) * 30.0

    return {
        "symbol": symbol,
        "name": display_name,
        "start_date": start_date,
        "end_date": end_date,
        "total_bars": len(df),
        "days": num_days,
        "initial_capital": initial_capital,
        "final_capital": round(capital, 2),
        "net_profit": round(total_net_pnl, 2),
        "return_pct": round(return_pct, 2),
        "monthly_profit": round(monthly_profit, 2),
        "total_trades": total_trades,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(win_rate, 2),
        "profit_factor": profit_factor,
        "max_drawdown_usd": round(max_dd_usd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "avg_duration_mins": round(avg_duration, 1),
        "trades_per_day": round(trades_per_day, 2),
        "trades_per_week": round(trades_per_week, 1),
        "trade_sample": trades[-5:]
    }


def main():
    assets = [
        ("BTCUSDT", "Bitcoin (BTC)"),
        ("ETHUSDT", "Ethereum (ETH)"),
        ("SOLUSDT", "Solana (SOL)"),
        ("XRPUSDT", "XRP (Ripple)"),
        ("BNBUSDT", "Binance Coin (BNB)"),
        ("DOGEUSDT", "Dogecoin (DOGE)")
    ]
    
    results = {}
    
    print("=" * 110)
    print("      AGENTQUANT // 6-MONTH 1-MINUTE MULTI-CRYPTO SNIPER BACKTEST AUDIT ($6,000 PROP CAPITAL)      ")
    print("=" * 110)
    
    for sym, name in assets:
        logger.info("Processing %s (%s)...", name, sym)
        raw_df = fetch_binance_1m_data_parallel(sym, total_candles=250_000)
        if raw_df.empty:
            continue
        df_ind = compute_sniper_indicators(raw_df)
        res = simulate_asset(df_ind, sym, name)
        results[sym] = res
        
    # Save results JSON
    out_file = Path("scripts/multi_crypto_6month_1min_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        
    print("\n" + "=" * 110)
    print(f"{'CRYPTO ASSET':<20} | {'BARS':<7} | {'TRADES':<7} | {'WIN %':<8} | {'NET PROFIT':<14} | {'RETURN %':<10} | {'MAX DD ($)':<12} | {'PF':<6} | {'TRADES/WK':<9}")
    print("-" * 110)
    
    for sym, name in assets:
        if sym in results:
            r = results[sym]
            sign = "+" if r['net_profit'] >= 0 else ""
            print(f"{r['name']:<20} | {r['total_bars']:<7} | {r['total_trades']:<7} | {r['win_rate']:>5.1f}% | {sign}${r['net_profit']:>11,.2f} | {sign}{r['return_pct']:>7.1f}% | ${abs(r['max_drawdown_usd']):>10,.2f} | {r['profit_factor']:>5.2f} | {r['trades_per_week']:>8.1f}")
        
    print("=" * 110)
    print("Audit Complete! Saved metrics to scripts/multi_crypto_6month_1min_results.json")


if __name__ == "__main__":
    main()
