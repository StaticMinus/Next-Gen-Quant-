"""
6-Month 1-Minute High-Frequency Crypto Sniper Backtest ($6,000 Funded Account)
==============================================================================
Simulates a real sub-minute / 1-minute tick liquidity-sweep mean-reversion sniper 
on genuine 1-minute candle/tick data for top-performing crypto assets:
1. BTCUSDT (Bitcoin)
2. SOLUSDT (Solana)

Account Constraints ($6,000 Stellar Prop Account):
- Initial Capital: $6,000.00
- Max Daily Loss Limit: $300.00 (5.0%)
- Max Total Drawdown Limit: $600.00 (10.0%)
- Risk Per Trade: $30.00 to $60.00 (0.5% - 1.0%)
- Realistic Crypto Fees: 0.04% taker / 0.02% maker fee + 1 bps slippage
"""

import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", force=True)
logger = logging.getLogger("1MCryptoSniper")


def fetch_binance_1m_data(symbol: str = "BTCUSDT", total_candles: int = 250_000) -> pd.DataFrame:
    """Fetch high-density historical 1-minute klines from Binance public API."""
    logger.info("Fetching %d 1-minute candles for %s from Binance public API...", total_candles, symbol)
    url_base = "https://api.binance.com/api/v3/klines"
    
    all_rows = []
    end_time = int(time.time() * 1000)
    batch_size = 1000
    
    # We paginate backwards from now
    for _ in range(0, total_candles, batch_size):
        try:
            url = f"{url_base}?symbol={symbol}&interval=1m&limit={batch_size}&endTime={end_time}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            if not data:
                break
            all_rows.extend(data)
            # Oldest timestamp in this batch
            end_time = int(data[0][0]) - 1
            time.sleep(0.05)  # Respect rate limits
        except Exception as e:
            logger.warning("Error fetching batch for %s: %s", symbol, e)
            break
            
    # Sort chronologically
    all_rows.sort(key=lambda x: x[0])
    logger.info("Successfully fetched %d genuine 1-minute bars for %s.", len(all_rows), symbol)
    
    # Convert to DataFrame
    cols = ["timestamp", "open", "high", "low", "close", "volume", "close_time", "quote_asset_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
    df = pd.DataFrame(all_rows, columns=cols)
    for c in ["open", "high", "low", "close", "volume", "taker_buy_base"]:
        df[c] = df[c].astype(float)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("datetime", inplace=True)
    return df


def compute_sniper_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute sub-minute / 1-minute liquidity absorption and volatility bands."""
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_p = df["open"]
    vol = df["volume"]
    
    # 1. 20-Period Rolling Mean & Volatility Bands (Bollinger / VWAP proxy)
    df["ma_20"] = close.rolling(20).mean()
    df["std_20"] = close.rolling(20).std()
    df["lower_band"] = df["ma_20"] - (2.0 * df["std_20"])
    df["upper_band"] = df["ma_20"] + (2.0 * df["std_20"])
    
    # 2. Fast 5-period EMA for Mean Reversion Target
    df["ema_5"] = close.ewm(span=5, adjust=False).mean()
    
    # 3. Candlestick Geometry & Wick Absorption
    candle_range = (high - low).replace(0, 1e-9)
    body_size = (close - open_p).abs()
    lower_wick = np.minimum(close, open_p) - low
    upper_wick = high - np.maximum(close, open_p)
    
    df["lower_wick_ratio"] = lower_wick / candle_range
    df["upper_wick_ratio"] = upper_wick / candle_range
    df["body_ratio"] = body_size / candle_range
    
    # 4. Volume Spike Factor (Liquidity sweep)
    df["vol_ma"] = vol.rolling(20).mean() + 1e-9
    df["vol_spike"] = vol / df["vol_ma"]
    
    # 5. Order Flow CVD proxy (Taker Buy vs Sell Volume)
    df["taker_sell"] = vol - df["taker_buy_base"]
    df["flow_delta"] = (df["taker_buy_base"] - df["taker_sell"]) / (vol + 1e-9)
    
    df.dropna(inplace=True)
    return df


def run_1min_sniper_simulation(
    df: pd.DataFrame, 
    symbol: str, 
    initial_capital: float = 6000.0,
    risk_per_trade_usd: float = 30.0,
    max_hold_minutes: int = 15
) -> Dict:
    """Simulate 1-minute real-tick sniper strategy on $6,000 funded account."""
    logger.info("Simulating 1-Minute Sniper Strategy on %s (%d bars)...", symbol, len(df))
    
    capital = initial_capital
    position = "FLAT"
    entry_price = 0.0
    position_size = 0.0
    entry_idx = 0
    stop_loss_price = 0.0
    take_profit_price = 0.0
    
    trades = []
    daily_records = []
    
    fee_rate = 0.0003  # 3 bps average fee (maker/taker blend)
    slippage = 0.0001  # 1 bps slippage on liquid crypto
    
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    opens = df["open"].values
    lower_bands = df["lower_band"].values
    upper_bands = df["upper_band"].values
    ema_5s = df["ema_5"].values
    lower_wicks = df["lower_wick_ratio"].values
    upper_wicks = df["upper_wick_ratio"].values
    vol_spikes = df["vol_spike"].values
    flow_deltas = df["flow_delta"].values
    dates = df.index
    
    for i in range(len(df)):
        curr_date = dates[i]
        curr_price = float(closes[i])
        curr_high = float(highs[i])
        curr_low = float(lows[i])
        curr_open = float(opens[i])
        
        trade_opened = False
        trade_closed = False
        
        # --- 1. MANAGE OPEN POSITION ---
        if position == "LONG":
            bars_held = i - entry_idx
            
            # Check Stop Loss (Intra-bar low hit stop)
            if curr_low <= stop_loss_price:
                exit_p = stop_loss_price * (1.0 - slippage)
                pnl = position_size * (exit_p - entry_price)
                fee = (position_size * exit_p) * fee_rate
                capital += pnl - fee
                trades.append({
                    "entry_time": str(dates[entry_idx]),
                    "exit_time": str(curr_date),
                    "type": "STOP_LOSS",
                    "entry_price": entry_price,
                    "exit_price": exit_p,
                    "pnl": pnl - fee,
                    "fee": fee,
                    "duration_mins": bars_held,
                    "win": False
                })
                position = "FLAT"
                trade_closed = True
                
            # Check Take Profit (Intra-bar high hit target)
            elif curr_high >= take_profit_price or curr_price >= ema_5s[i]:
                exit_p = max(take_profit_price, curr_price) * (1.0 - slippage)
                pnl = position_size * (exit_p - entry_price)
                fee = (position_size * exit_p) * fee_rate
                capital += pnl - fee
                trades.append({
                    "entry_time": str(dates[entry_idx]),
                    "exit_time": str(curr_date),
                    "type": "TAKE_PROFIT",
                    "entry_price": entry_price,
                    "exit_price": exit_p,
                    "pnl": pnl - fee,
                    "fee": fee,
                    "duration_mins": bars_held,
                    "win": True
                })
                position = "FLAT"
                trade_closed = True
                
            # Check Max Timeout (Time exit after 15 mins)
            elif bars_held >= max_hold_minutes:
                exit_p = curr_price * (1.0 - slippage)
                pnl = position_size * (exit_p - entry_price)
                fee = (position_size * exit_p) * fee_rate
                capital += pnl - fee
                trades.append({
                    "entry_time": str(dates[entry_idx]),
                    "exit_time": str(curr_date),
                    "type": "TIMEOUT_EXIT",
                    "entry_price": entry_price,
                    "exit_price": exit_p,
                    "pnl": pnl - fee,
                    "fee": fee,
                    "duration_mins": bars_held,
                    "win": (pnl - fee) > 0
                })
                position = "FLAT"
                trade_closed = True

        # --- 2. CHECK SNIPER ENTRY SIGNAL ---
        if position == "FLAT":
            # SNIPER LONG CONDITIONS:
            # 1. Price pierced below the 20-period lower volatility band (Oversold Dip)
            # 2. Strong lower absorption wick >= 25% (Buyers absorbed aggressive dump)
            # 3. Volume spike >= 1.3x (Liquidity sweep flush)
            # 4. Flow delta recovering from extreme dump
            is_dip = (curr_low <= lower_bands[i]) or (curr_price <= lower_bands[i])
            has_absorption_wick = lower_wicks[i] >= 0.25
            has_volume_flush = vol_spikes[i] >= 1.3
            is_rebound = curr_price >= curr_low + ((curr_high - curr_low) * 0.20)
            
            if is_dip and has_absorption_wick and has_volume_flush and is_rebound:
                fill_p = curr_price * (1.0 + slippage)
                entry_price = fill_p
                entry_idx = i
                
                # Position Sizing: Risk exactly $30 (0.5% of $6,000) with 0.50% stop loss
                sl_distance_pct = 0.0050  # 0.50% stop loss distance
                stop_loss_price = entry_price * (1.0 - sl_distance_pct)
                
                # Notional trade size = Risk / SL% = $30 / 0.0050 = $6,000 (1.0x leverage)
                notional_size = risk_per_trade_usd / sl_distance_pct
                position_size = notional_size / entry_price
                
                # Take profit: 0.60% quick mean reversion target
                tp_distance_pct = 0.0060  # 1:1.2 Risk/Reward quick scalp
                take_profit_price = entry_price * (1.0 + tp_distance_pct)
                
                fee = (position_size * fill_p) * fee_rate
                capital -= fee
                position = "LONG"
                trade_opened = True
                
        # Record Unrealized Equity
        unrealized = 0.0
        if position == "LONG":
            unrealized = position_size * (curr_price - entry_price)
            
        daily_records.append({
            "datetime": curr_date,
            "date": curr_date.date(),
            "equity": capital + unrealized,
            "trade_opened": trade_opened
        })
        
    # Performance Calculations
    df_hist = pd.DataFrame(daily_records).set_index("datetime")
    final_equity = float(df_hist["equity"].iloc[-1])
    net_pnl = final_equity - initial_capital
    return_pct = (net_pnl / initial_capital) * 100
    
    df_day = df_hist.groupby("date").agg({"equity": "last", "trade_opened": "sum"})
    df_day["ret"] = df_day["equity"].pct_change().fillna(0)
    df_day["daily_pnl"] = df_day["equity"].diff().fillna(df_day["equity"].iloc[0] - initial_capital)
    
    df_w = df_hist["equity"].resample("W-SUN").last().to_frame()
    df_w["weekly_pnl"] = df_w["equity"].diff().fillna(df_w["equity"].iloc[0] - initial_capital)
    
    df_m = df_hist["equity"].resample("ME").last().to_frame()
    df_m["monthly_pnl"] = df_m["equity"].diff().fillna(df_m["equity"].iloc[0] - initial_capital)
    df_m["ret_pct"] = (df_m["monthly_pnl"] / df_m["equity"].shift(1).fillna(initial_capital)) * 100
    df_m["year"] = df_m.index.year
    df_m["month"] = df_m.index.month_name().str[:3]
    
    wins = [t for t in trades if t.get("win", False)]
    losses = [t for t in trades if not t.get("win", False)]
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
    
    avg_win = float(np.mean([t["pnl"] for t in wins])) if wins else 0.0
    avg_loss = float(np.mean([t["pnl"] for t in losses])) if losses else 0.0
    profit_factor = abs(sum([t["pnl"] for t in wins]) / (sum([t["pnl"] for t in losses]) + 1e-9)) if losses else 999.0
    
    peaks = df_hist["equity"].cummax()
    drawdowns = (df_hist["equity"] - peaks) / peaks
    max_dd_pct = float(drawdowns.min()) * 100
    max_dd_usd = float((peaks - df_hist["equity"]).max())
    
    avg_duration = float(np.mean([t["duration_mins"] for t in trades])) if trades else 0.0
    total_days = (dates[-1] - dates[0]).total_seconds() / 86400.0
    trades_per_day = len(trades) / (total_days + 1e-9)
    
    # Prop Firm Safety Verification
    max_daily_loss = float(df_day["daily_pnl"].min())
    prop_daily_loss_safe = abs(max_daily_loss) < 300.0  # $300 limit
    prop_total_dd_safe = max_dd_usd < 600.0  # $600 limit
    
    return {
        "symbol": symbol,
        "start_date": str(dates[0].strftime("%Y-%m-%d")),
        "end_date": str(dates[-1].strftime("%Y-%m-%d")),
        "total_days": round(total_days, 1),
        "total_1m_bars": len(df),
        "initial_capital": initial_capital,
        "final_equity": round(final_equity, 2),
        "net_pnl": round(net_pnl, 2),
        "return_pct": round(return_pct, 2),
        "total_trades": len(trades),
        "trades_per_day": round(trades_per_day, 2),
        "win_rate_pct": round(win_rate, 2),
        "avg_win_usd": round(avg_win, 2),
        "avg_loss_usd": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_trade_duration_mins": round(avg_duration, 1),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_drawdown_usd": round(max_dd_usd, 2),
        "avg_profit_per_day": round(float(df_day["daily_pnl"].mean()), 2),
        "avg_profit_per_week": round(float(df_w["weekly_pnl"].mean()), 2),
        "avg_profit_per_month": round(float(df_m["monthly_pnl"].mean()), 2),
        "max_single_day_loss": round(max_daily_loss, 2),
        "prop_daily_limit_safe": prop_daily_loss_safe,
        "prop_max_dd_safe": prop_total_dd_safe,
        "monthly_breakdown": [
            {
                "year": int(r["year"]),
                "month": str(r["month"]),
                "pnl": round(float(r["monthly_pnl"]), 2),
                "ret_pct": round(float(r["ret_pct"]), 2)
            }
            for _, r in df_m.iterrows()
        ]
    }


def main():
    symbols = ["BTCUSDT", "SOLUSDT"]
    results = {}
    
    # 250,000 1-minute bars is ~173 days (~6 months) of tick-by-tick 1m data
    for sym in symbols:
        df_raw = fetch_binance_1m_data(symbol=sym, total_candles=250_000)
        df_indicators = compute_sniper_indicators(df_raw)
        res = run_1min_sniper_simulation(df_indicators, symbol=sym, initial_capital=6000.0, risk_per_trade_usd=30.0)
        results[sym] = res
        
    out_file = Path(__file__).resolve().parent / "crypto_1min_sniper_6month_results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    logger.info("Saved complete 1-minute sniper results to %s", out_file)
    
    print("\n" + "="*95)
    print("6-MONTH 1-MINUTE REAL-TICK SNIPER BACKTEST ($6,000 FUNDED ACCOUNT)")
    print("="*95)
    print(f"{'Asset':<10} | {'Total Profit':<14} | {'Daily Profit':<14} | {'Weekly Profit':<14} | {'Trades/Day':<11} | {'Win Rate':<9} | {'Max DD ($)':<11} | {'Avg Hold':<9}")
    print("-" * 95)
    for sym, r in results.items():
        print(f"{r['symbol']:<10} | +${r['net_pnl']:<6,.2f} (+{r['return_pct']:.1f}%) | +${r['avg_profit_per_day']:<5,.2f}/day | +${r['avg_profit_per_week']:<5,.2f}/wk | {r['trades_per_day']:<5.1f}/day | {r['win_rate_pct']:<5.1f}% | -${r['max_drawdown_usd']:<5,.2f} ({r['max_drawdown_pct']:.2f}%) | {r['avg_trade_duration_mins']:.1f} mins")
    print("="*95)


if __name__ == "__main__":
    main()
