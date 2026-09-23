"""
1-Year US Market (S&P 500, Nasdaq 100, Dow Jones) Head-to-Head Backtest: Laya vs Jev Trader
==========================================================================================
Evaluates both Laya (Candlestick Pattern & Narrative Decision Engine) and Jev Trader 
(Candlestick Microstructure & Order Flow Engine) on:
1. SPY (S&P 500 ETF)
2. QQQ (Nasdaq 100 ETF)
3. DIA (Dow Jones Industrial Average ETF)

Features candlestick pattern extraction:
- Hammer / Shooting Star (Pinbar Wick Rejections)
- Bullish / Bearish Engulfing
- Inside Bar (Volatility Contraction)
- Range position & Candle Body / Wick ratios
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

# Add laya to sys.path
laya_path = Path(__file__).resolve().parent.parent / "laya-main_2" / "laya-main"
if str(laya_path) not in sys.path:
    sys.path.insert(0, str(laya_path))

import laya
from laya import Agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", force=True)
logger = logging.getLogger("USIndicesBacktest")


def extract_candlestick_features(df: pd.DataFrame) -> pd.DataFrame:
    """Extract quantitative and pattern metrics from OHLCV candlestick data."""
    df = df.copy()
    open_p = df["Open"].squeeze()
    high = df["High"].squeeze()
    low = df["Low"].squeeze()
    close = df["Close"].squeeze()
    vol = df["Volume"].squeeze()
    
    # Candle geometry
    candle_range = (high - low).replace(0, 1e-9)
    body_size = (close - open_p).abs()
    upper_wick = high - np.maximum(close, open_p)
    lower_wick = np.minimum(close, open_p) - low
    
    df["body_ratio"] = body_size / candle_range
    df["upper_wick_ratio"] = upper_wick / candle_range
    df["lower_wick_ratio"] = lower_wick / candle_range
    df["range_pos"] = ((close - low) - (high - close)) / candle_range  # -1 to +1
    
    # Returns in Basis Points
    df["ret_1_bps"] = close.pct_change(1) * 10_000
    df["ret_5_bps"] = close.pct_change(5) * 10_000
    df["ret_20_bps"] = close.pct_change(20) * 10_000
    
    # Moving Averages
    df["sma_20"] = close.rolling(20).mean()
    df["sma_50"] = close.rolling(50).mean()
    
    # Volume MA
    df["vol_ratio"] = vol / (vol.rolling(20).mean() + 1e-9)
    
    # Candlestick Pattern Classification
    patterns = []
    for i in range(len(df)):
        b_ratio = df["body_ratio"].iloc[i]
        u_ratio = df["upper_wick_ratio"].iloc[i]
        l_ratio = df["lower_wick_ratio"].iloc[i]
        is_green = close.iloc[i] >= open_p.iloc[i]
        v_rat = df["vol_ratio"].iloc[i]
        
        if l_ratio > 0.60 and b_ratio < 0.30:
            pat = "Bullish Hammer (strong lower wick rejection)"
        elif u_ratio > 0.60 and b_ratio < 0.30:
            pat = "Bearish Shooting Star (strong upper wick rejection)"
        elif b_ratio > 0.75 and is_green and v_rat > 1.3:
            pat = "Strong Bullish Marubozu expansion candle"
        elif b_ratio > 0.75 and not is_green and v_rat > 1.3:
            pat = "Strong Bearish Breakdown candle"
        elif i > 0 and b_ratio > 0.60 and is_green and close.iloc[i] > high.iloc[i-1]:
            pat = "Bullish Engulfing pattern"
        elif i > 0 and b_ratio > 0.60 and not is_green and close.iloc[i] < low.iloc[i-1]:
            pat = "Bearish Engulfing pattern"
        else:
            pat = "Standard consolidation candle"
        patterns.append(pat)
        
    df["candle_pattern"] = patterns
    
    # CVD Flow for Jev
    estimated_buy_vol = vol * ((close - low) / candle_range)
    estimated_sell_vol = vol * ((high - close) / candle_range)
    cvd_raw = (estimated_buy_vol - estimated_sell_vol).rolling(20).sum()
    total_vol = (estimated_buy_vol + estimated_sell_vol).rolling(20).sum() + 1e-9
    df["cvd_flow"] = (cvd_raw / total_vol).clip(-1.0, 1.0)
    
    df.dropna(inplace=True)
    return df


def serialize_laya_candle_state(ticker: str, row: pd.Series) -> Dict[str, str]:
    """Build narrative candlestick state for Laya."""
    price = float(row["Close"])
    pat = str(row["candle_pattern"])
    ret5 = float(row["ret_5_bps"]) / 100
    ret20 = float(row["ret_20_bps"]) / 100
    sma50 = float(row["sma_50"])
    
    trend = "above 50-SMA (bullish structure)" if price >= sma50 else "below 50-SMA (bearish structure)"
    
    return {
        "asset": ticker,
        "price": f"${price:,.2f}",
        "candlestick": pat,
        "momentum": f"5-bar return: {ret5:+.2f}%, 20-bar return: {ret20:+.2f}%",
        "structure": trend
    }


def laya_questions() -> Dict:
    return {
        "signal": {
            "type": "choice",
            "instructions": "Determine trading posture based on candlestick patterns, support/resistance, and momentum.",
            "criteria": {
                "LONG": "bullish candlestick confirmation, hammer rejection, or uptrend breakout",
                "SHORT": "bearish candlestick breakdown, shooting star rejection, or downtrend continuation",
                "CASH": "neutral consolidation or no clear candlestick edge"
            }
        }
    }


def run_laya_backtest_on_asset(df: pd.DataFrame, ticker: str, agent: Agent, initial_capital: float = 100_000.0) -> Dict:
    logger.info("Running Laya 1-Year Candlestick Backtest on %s (%d bars)...", ticker, len(df))
    questions = laya_questions()
    states = [serialize_laya_candle_state(ticker, row) for _, row in df.iterrows()]
    
    # Batched inference
    t0 = time.perf_counter()
    all_predictions = []
    batch_size = 32
    for i in range(0, len(states), batch_size):
        chunk = states[i : i + batch_size]
        res = agent.predict_batch(chunk, questions, max_len=128, head_max_len=48)
        all_predictions.extend(res)
    infer_time = time.perf_counter() - t0
    
    # Simulation
    capital = initial_capital
    position = "FLAT"
    entry_price = 0.0
    position_size = 0.0
    trades = []
    daily_records = []
    
    dates = df.index
    closes = df["Close"].values
    fee_rate = 0.0001  # 1 bps US equity commission
    slippage = 0.0001  # 1 bps slippage
    
    for idx in range(len(df)):
        curr_date = dates[idx]
        curr_price = float(closes[idx])
        pred = all_predictions[idx]["answers"]["signal"]
        action = pred["choice"]
        
        trade_opened = False
        alloc = capital * 0.30
        
        if action == "LONG" and position != "LONG":
            if position == "SHORT":
                exit_p = curr_price * (1.0 + slippage)
                pnl = position_size * (entry_price - exit_p)
                fee = (position_size * exit_p) * fee_rate
                capital += pnl - fee
                trades.append({"type": "CLOSE_SHORT", "pnl": pnl - fee, "fee": fee})
                position = "FLAT"
            fill_p = curr_price * (1.0 + slippage)
            position_size = alloc / fill_p
            entry_price = fill_p
            fee = (position_size * fill_p) * fee_rate
            capital -= fee
            trades.append({"type": "OPEN_LONG", "fee": fee})
            position = "LONG"
            trade_opened = True
            
        elif action == "SHORT" and position != "SHORT":
            if position == "LONG":
                exit_p = curr_price * (1.0 - slippage)
                pnl = position_size * (exit_p - entry_price)
                fee = (position_size * exit_p) * fee_rate
                capital += pnl - fee
                trades.append({"type": "CLOSE_LONG", "pnl": pnl - fee, "fee": fee})
                position = "FLAT"
            fill_p = curr_price * (1.0 - slippage)
            position_size = alloc / fill_p
            entry_price = fill_p
            fee = (position_size * fill_p) * fee_rate
            capital -= fee
            trades.append({"type": "OPEN_SHORT", "fee": fee})
            position = "SHORT"
            trade_opened = True
            
        unrealized = 0.0
        if position == "LONG":
            unrealized = position_size * (curr_price - entry_price)
        elif position == "SHORT":
            unrealized = position_size * (entry_price - curr_price)
            
        daily_records.append({
            "datetime": curr_date,
            "date": curr_date.date(),
            "equity": capital + unrealized,
            "trade_opened": trade_opened
        })
        
    df_hist = pd.DataFrame(daily_records).set_index("datetime")
    final_equity = float(df_hist["equity"].iloc[-1])
    net_pnl = final_equity - initial_capital
    ret_pct = (net_pnl / initial_capital) * 100
    
    # Aggregate by day
    df_day = df_hist.groupby("date").agg({"equity": "last", "trade_opened": "sum"})
    df_day["ret"] = df_day["equity"].pct_change().fillna(0)
    
    closed = [t for t in trades if "CLOSE" in t["type"]]
    wins = [t for t in closed if t["pnl"] > 0]
    win_rate = (len(wins) / len(closed) * 100) if closed else 0
    
    peaks = df_hist["equity"].cummax()
    max_dd = float(((df_hist["equity"] - peaks) / peaks).min()) * 100
    sharpe = float((df_day["ret"].mean() / (df_day["ret"].std() + 1e-9)) * np.sqrt(252))
    
    buy_hold = ((float(closes[-1]) - float(closes[0])) / float(closes[0])) * 100
    
    # Weekly & Monthly
    df_w = df_hist["equity"].resample("W-SUN").last().to_frame()
    df_w["pnl"] = df_w["equity"].diff().fillna(df_w["equity"].iloc[0] - initial_capital)
    
    df_m = df_hist["equity"].resample("ME").last().to_frame()
    df_m["pnl"] = df_m["equity"].diff().fillna(df_m["equity"].iloc[0] - initial_capital)
    df_m["ret_pct"] = (df_m["pnl"] / df_m["equity"].shift(1).fillna(initial_capital)) * 100
    df_m["year"] = df_m.index.year
    df_m["month"] = df_m.index.month_name().str[:3]

    return {
        "model": "Laya (Candle Pattern Engine)",
        "ticker": ticker,
        "bars": len(df),
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "net_pnl": net_pnl,
        "return_pct": ret_pct,
        "buy_hold_return_pct": buy_hold,
        "total_trades": len(closed),
        "avg_trades_per_day": float(df_day["trade_opened"].sum()) / len(df_day),
        "win_rate_pct": win_rate,
        "max_drawdown_pct": max_dd,
        "sharpe_ratio": sharpe,
        "weekly_win_rate_pct": float((df_w["pnl"] > 0).sum()) / len(df_w) * 100,
        "avg_weekly_profit": float(df_w["pnl"].mean()),
        "monthly_win_rate_pct": float((df_m["pnl"] > 0).sum()) / len(df_m) * 100,
        "avg_monthly_profit": float(df_m["pnl"].mean()),
        "monthly_table": [
            {"year": int(r["year"]), "month": str(r["month"]), "pnl": float(r["pnl"]), "ret_pct": float(r["ret_pct"])}
            for _, r in df_m.iterrows()
        ],
        "infer_time_sec": infer_time
    }


def run_jev_backtest_on_asset(df: pd.DataFrame, ticker: str, initial_capital: float = 100_000.0) -> Dict:
    logger.info("Running Jev Trader 1-Year Candlestick Microstructure Backtest on %s (%d bars)...", ticker, len(df))
    capital = initial_capital
    position = "FLAT"
    entry_price = 0.0
    position_size = 0.0
    trades = []
    daily_records = []
    
    dates = df.index
    closes = df["Close"].values
    fee_rate = 0.0001
    slippage = 0.0001
    
    for idx in range(len(df)):
        curr_date = dates[idx]
        curr_price = float(closes[idx])
        row = df.iloc[idx]
        
        # Jev formula with candle range position
        ret20 = float(row["ret_20_bps"])
        range_pos = float(row["range_pos"])
        flow = float(row["cvd_flow"])
        
        signal = (ret20 / 10.0) + (range_pos * 1.5) + (flow * 2.0)
        buy_prob = 1.0 / (1.0 + np.exp(-np.clip(signal, -10, 10)))
        
        trade_opened = False
        alloc = capital * 0.30
        
        if buy_prob >= 0.55 and position != "LONG":
            if position == "SHORT":
                exit_p = curr_price * (1.0 + slippage)
                pnl = position_size * (entry_price - exit_p)
                fee = (position_size * exit_p) * fee_rate
                capital += pnl - fee
                trades.append({"type": "CLOSE_SHORT", "pnl": pnl - fee, "fee": fee})
                position = "FLAT"
            fill_p = curr_price * (1.0 + slippage)
            position_size = alloc / fill_p
            entry_price = fill_p
            fee = (position_size * fill_p) * fee_rate
            capital -= fee
            trades.append({"type": "OPEN_LONG", "fee": fee})
            position = "LONG"
            trade_opened = True
            
        elif buy_prob <= 0.45 and position != "SHORT":
            if position == "LONG":
                exit_p = curr_price * (1.0 - slippage)
                pnl = position_size * (exit_p - entry_price)
                fee = (position_size * exit_p) * fee_rate
                capital += pnl - fee
                trades.append({"type": "CLOSE_LONG", "pnl": pnl - fee, "fee": fee})
                position = "FLAT"
            fill_p = curr_price * (1.0 - slippage)
            position_size = alloc / fill_p
            entry_price = fill_p
            fee = (position_size * fill_p) * fee_rate
            capital -= fee
            trades.append({"type": "OPEN_SHORT", "fee": fee})
            position = "SHORT"
            trade_opened = True
            
        unrealized = 0.0
        if position == "LONG":
            unrealized = position_size * (curr_price - entry_price)
        elif position == "SHORT":
            unrealized = position_size * (entry_price - curr_price)
            
        daily_records.append({
            "datetime": curr_date,
            "date": curr_date.date(),
            "equity": capital + unrealized,
            "trade_opened": trade_opened
        })
        
    df_hist = pd.DataFrame(daily_records).set_index("datetime")
    final_equity = float(df_hist["equity"].iloc[-1])
    net_pnl = final_equity - initial_capital
    ret_pct = (net_pnl / initial_capital) * 100
    
    df_day = df_hist.groupby("date").agg({"equity": "last", "trade_opened": "sum"})
    df_day["ret"] = df_day["equity"].pct_change().fillna(0)
    
    closed = [t for t in trades if "CLOSE" in t["type"]]
    wins = [t for t in closed if t["pnl"] > 0]
    win_rate = (len(wins) / len(closed) * 100) if closed else 0
    
    peaks = df_hist["equity"].cummax()
    max_dd = float(((df_hist["equity"] - peaks) / peaks).min()) * 100
    sharpe = float((df_day["ret"].mean() / (df_day["ret"].std() + 1e-9)) * np.sqrt(252))
    buy_hold = ((float(closes[-1]) - float(closes[0])) / float(closes[0])) * 100
    
    df_w = df_hist["equity"].resample("W-SUN").last().to_frame()
    df_w["pnl"] = df_w["equity"].diff().fillna(df_w["equity"].iloc[0] - initial_capital)
    
    df_m = df_hist["equity"].resample("ME").last().to_frame()
    df_m["pnl"] = df_m["equity"].diff().fillna(df_m["equity"].iloc[0] - initial_capital)
    df_m["ret_pct"] = (df_m["pnl"] / df_m["equity"].shift(1).fillna(initial_capital)) * 100
    df_m["year"] = df_m.index.year
    df_m["month"] = df_m.index.month_name().str[:3]

    return {
        "model": "Jev Trader (Candle Flow Engine)",
        "ticker": ticker,
        "bars": len(df),
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "net_pnl": net_pnl,
        "return_pct": ret_pct,
        "buy_hold_return_pct": buy_hold,
        "total_trades": len(closed),
        "avg_trades_per_day": float(df_day["trade_opened"].sum()) / len(df_day),
        "win_rate_pct": win_rate,
        "max_drawdown_pct": max_dd,
        "sharpe_ratio": sharpe,
        "weekly_win_rate_pct": float((df_w["pnl"] > 0).sum()) / len(df_w) * 100,
        "avg_weekly_profit": float(df_w["pnl"].mean()),
        "monthly_win_rate_pct": float((df_m["pnl"] > 0).sum()) / len(df_m) * 100,
        "avg_monthly_profit": float(df_m["pnl"].mean()),
        "monthly_table": [
            {"year": int(r["year"]), "month": str(r["month"]), "pnl": float(r["pnl"]), "ret_pct": float(r["ret_pct"])}
            for _, r in df_m.iterrows()
        ]
    }


def main():
    agent = Agent("convaiinnovations/laya")
    assets = {
        "S&P 500 (SPY)": "SPY",
        "Nasdaq 100 (QQQ)": "QQQ",
        "Dow Jones (DIA)": "DIA"
    }
    
    all_results = {}
    
    for name, ticker in assets.items():
        logger.info("=== EVALUATING %s (%s) ===", name, ticker)
        df_raw = yf.download(ticker, period="1y", interval="1h", progress=False)
        if isinstance(df_raw.columns, pd.MultiIndex):
            df_raw.columns = df_raw.columns.get_level_values(0)
        df_candles = extract_candlestick_features(df_raw)
        
        res_laya = run_laya_backtest_on_asset(df_candles, ticker, agent)
        res_jev = run_jev_backtest_on_asset(df_candles, ticker)
        
        all_results[ticker] = {
            "name": name,
            "laya": res_laya,
            "jev": res_jev
        }
        
    out_path = Path(__file__).resolve().parent / "us_indices_1year_laya_vs_jev_results.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    logger.info("Saved complete US market results to: %s", out_path)
    
    print("\n" + "="*95)
    print("1-YEAR US MARKET (SPY, QQQ, DIA) HEAD-TO-HEAD BACKTEST: LAYA VS JEV TRADER")
    print("="*95)
    print(f"{'Asset':<18} | {'Model':<24} | {'Net Return':<12} | {'Trades/Day':<10} | {'Win Rate':<10} | {'Max DD':<10} | {'Sharpe':<8}")
    print("-" * 95)
    
    for ticker, res in all_results.items():
        name = res["name"]
        l = res["laya"]
        j = res["jev"]
        print(f"{name:<18} | {l['model']:<24} | {l['return_pct']:>+6.2f}% (${l['net_pnl']:>+7,.0f}) | {l['avg_trades_per_day']:>6.2f}/day | {l['win_rate_pct']:>6.1f}% | {l['max_drawdown_pct']:>6.2f}% | {l['sharpe_ratio']:>6.2f}")
        print(f"{name:<18} | {j['model']:<24} | {j['return_pct']:>+6.2f}% (${j['net_pnl']:>+7,.0f}) | {j['avg_trades_per_day']:>6.2f}/day | {j['win_rate_pct']:>6.1f}% | {j['max_drawdown_pct']:>6.2f}% | {j['sharpe_ratio']:>6.2f}")
        print(f"{'  Benchmark':<18} | {'Buy & Hold (Passive)':<24} | {l['buy_hold_return_pct']:>+6.2f}% | {'-':>10} | {'-':>10} | {'-':>10} | {'-':>8}")
        print("-" * 95)
    print("="*95)


if __name__ == "__main__":
    main()
