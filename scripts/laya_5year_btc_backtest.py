"""
Laya 5-Year Bitcoin (BTC-USD) Backtest & Performance Breakdown
=============================================================
Evaluates Laya (ModernBERT-large 421M System 1 Decision Engine) across 5+ years of Bitcoin market history (2021-2026).

Optimized for high-throughput execution:
- 12.5+ bars/sec batch processing
- max_len=128 for 16x attention acceleration
- Full trade accounting with realistic fees & slippage
- Granular breakdown: Trades/Day, Profit/Week, and Profit/Month
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
logger = logging.getLogger("Laya5YearBacktest")


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute moving averages, momentum, RSI, and volatility for 5-year daily BTC data."""
    df = df.copy()
    close = df["Close"].squeeze()
    
    # Returns
    df["ret_1d"] = close.pct_change(1)
    df["ret_7d"] = close.pct_change(7)
    df["ret_30d"] = close.pct_change(30)
    
    # Moving Averages
    df["sma_20"] = close.rolling(20).mean()
    df["sma_50"] = close.rolling(50).mean()
    df["sma_200"] = close.rolling(200).mean()
    
    # RSI (14 period)
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df["rsi_14"] = 100 - (100 / (1 + rs))
    
    # Drop warm-up rows (first 200 days for 200-SMA)
    df = df.iloc[200:].copy()
    return df


def build_narrative_state(row: pd.Series) -> Dict[str, str]:
    """Convert technical metrics into compact structured natural language states for Laya."""
    price = float(row["Close"])
    ret_1d = float(row["ret_1d"]) * 100
    ret_7d = float(row["ret_7d"]) * 100
    ret_30d = float(row["ret_30d"]) * 100
    rsi = float(row["rsi_14"])
    sma_50 = float(row["sma_50"])
    sma_200 = float(row["sma_200"])
    
    # Trend regime assessment
    if price > sma_50 > sma_200:
        regime = "strong golden cross bull market trend"
    elif price < sma_50 < sma_200:
        regime = "severe death cross bear market breakdown"
    elif price > sma_200 and ret_30d > 0:
        regime = "recovery continuation above 200 SMA"
    elif price < sma_200 and ret_30d < 0:
        regime = "macro downtrend below 200 SMA"
    else:
        regime = "sideways consolidation range"
        
    return {
        "asset": "BTC/USDT",
        "price": f"${price:,.0f}",
        "momentum": f"1d: {ret_1d:+.1f}%, 7d: {ret_7d:+.1f}%, 30d: {ret_30d:+.1f}%, RSI: {rsi:.0f}",
        "regime": regime
    }


def define_trading_questions() -> Dict:
    """Define single high-speed trading question evaluated by Laya."""
    return {
        "signal": {
            "type": "choice",
            "instructions": "Determine the optimal trading posture for Bitcoin based on macro trend and momentum.",
            "criteria": {
                "LONG": "bullish momentum, golden cross uptrend, or recovery bounce",
                "SHORT": "bearish momentum, death cross downtrend, or breakdown",
                "CASH": "neutral sideways consolidation or high uncertainty"
            }
        }
    }


def run_5year_backtest(
    start_date: str = "2021-01-01",
    end_date: str = "2026-09-22",
    initial_capital: float = 100_000.0,
    batch_size: int = 16,
    fee_rate: float = 0.0005,  # 5 bps taker fee
    slippage: float = 0.0002   # 2 bps slippage
) -> Dict:
    logger.info("Initializing Laya Agent (ModernBERT-large 421M params)...")
    agent = Agent("convaiinnovations/laya")
    questions = define_trading_questions()
    
    logger.info("Downloading historical BTC-USD data from %s to %s...", start_date, end_date)
    df_raw = yf.download("BTC-USD", start="2020-05-01", end=end_date, interval="1d", progress=False)
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)
        
    df = compute_indicators(df_raw)
    df = df.loc[df.index >= start_date].copy()
    num_bars = len(df)
    logger.info("Total backtest bars: %d trading days (~%.1f years)", num_bars, num_bars / 365.25)
    
    # Pre-build states
    states = [build_narrative_state(row) for _, row in df.iterrows()]
    
    # Run batched inference
    logger.info("Executing accelerated batched inference across %d bars (batch_size=%d, max_len=128)...", num_bars, batch_size)
    t_start = time.perf_counter()
    all_predictions = []
    
    for i in range(0, num_bars, batch_size):
        chunk = states[i : i + batch_size]
        res = agent.predict_batch(chunk, questions, max_len=128, head_max_len=48)
        all_predictions.extend(res)
        done = min(i + batch_size, num_bars)
        if (i // batch_size) % 10 == 0 or done == num_bars:
            pct = (done / num_bars) * 100
            elapsed = time.perf_counter() - t_start
            cur_speed = done / (elapsed + 1e-9)
            logger.info("  Processed %d / %d bars (%.1f%%) - Speed: %.1f bars/s...", done, num_bars, pct, cur_speed)
            
    t_end = time.perf_counter()
    total_infer_time = t_end - t_start
    throughput = num_bars / total_infer_time
    ms_per_bar = (total_infer_time / num_bars) * 1000
    logger.info("Inference complete in %.2f seconds (%.2f ms/bar, %.1f bars/second throughput)", total_infer_time, ms_per_bar, throughput)
    
    # ── SIMULATION & TRADE ACCOUNTING ──────────────────────────────────────────
    capital = initial_capital
    position = "FLAT"  # LONG, SHORT, FLAT
    entry_price = 0.0
    position_size = 0.0
    
    trades = []
    daily_records = []
    
    dates = df.index
    closes = df["Close"].values
    
    for idx in range(num_bars):
        current_date = dates[idx]
        curr_price = float(closes[idx])
        pred = all_predictions[idx]["answers"]
        
        target_dir = pred["signal"]["choice"]
        confidence = float(pred["signal"]["confidence"])
        
        # Position sizing: 25% of capital per position
        allocated_capital = capital * 0.25
        trade_opened_today = False
        
        # Execute Transitions
        if target_dir != position:
            # 1. Close existing position
            if position == "LONG":
                exit_price = curr_price * (1.0 - slippage)
                trade_pnl = position_size * (exit_price - entry_price)
                fee = (position_size * exit_price) * fee_rate
                capital += trade_pnl - fee
                trades.append({
                    "date": str(current_date.date()),
                    "type": "CLOSE_LONG",
                    "price": exit_price,
                    "gross_pnl": trade_pnl,
                    "net_pnl": trade_pnl - fee,
                    "fee": fee
                })
                position = "FLAT"
                position_size = 0.0
                
            elif position == "SHORT":
                exit_price = curr_price * (1.0 + slippage)
                trade_pnl = position_size * (entry_price - exit_price)
                fee = (position_size * exit_price) * fee_rate
                capital += trade_pnl - fee
                trades.append({
                    "date": str(current_date.date()),
                    "type": "CLOSE_SHORT",
                    "price": exit_price,
                    "gross_pnl": trade_pnl,
                    "net_pnl": trade_pnl - fee,
                    "fee": fee
                })
                position = "FLAT"
                position_size = 0.0

            # 2. Open new position
            if target_dir == "LONG":
                fill_price = curr_price * (1.0 + slippage)
                position_size = allocated_capital / fill_price
                entry_price = fill_price
                fee = (position_size * fill_price) * fee_rate
                capital -= fee
                trades.append({
                    "date": str(current_date.date()),
                    "type": "OPEN_LONG",
                    "price": fill_price,
                    "size": position_size,
                    "fee": fee
                })
                position = "LONG"
                trade_opened_today = True
                
            elif target_dir == "SHORT":
                fill_price = curr_price * (1.0 - slippage)
                position_size = allocated_capital / fill_price
                entry_price = fill_price
                fee = (position_size * fill_price) * fee_rate
                capital -= fee
                trades.append({
                    "date": str(current_date.date()),
                    "type": "OPEN_SHORT",
                    "price": fill_price,
                    "size": position_size,
                    "fee": fee
                })
                position = "SHORT"
                trade_opened_today = True

        # Mark-to-market equity
        unrealized = 0.0
        if position == "LONG":
            unrealized = position_size * (curr_price - entry_price)
        elif position == "SHORT":
            unrealized = position_size * (entry_price - curr_price)
            
        equity = capital + unrealized
        daily_records.append({
            "date": current_date,
            "close": curr_price,
            "equity": equity,
            "cash": capital,
            "position": position,
            "trade_opened": trade_opened_today
        })

    # Close remaining position at final bar
    if position != "FLAT":
        final_price = float(closes[-1])
        if position == "LONG":
            exit_p = final_price * (1.0 - slippage)
            pnl = position_size * (exit_p - entry_price)
            fee = position_size * exit_p * fee_rate
            capital += pnl - fee
        else:
            exit_p = final_price * (1.0 + slippage)
            pnl = position_size * (entry_price - exit_p)
            fee = position_size * exit_p * fee_rate
            capital += pnl - fee
        daily_records[-1]["equity"] = capital

    # ── GRANULAR BREAKDOWN CALCULATIONS ───────────────────────────────────────
    df_daily = pd.DataFrame(daily_records).set_index("date")
    df_daily["equity_return"] = df_daily["equity"].pct_change().fillna(0)
    
    # 1. Trades Opened Per Day
    total_trades_opened = df_daily["trade_opened"].sum()
    avg_trades_per_day = float(total_trades_opened) / num_bars
    days_with_trades = int(total_trades_opened)
    days_without_trades = num_bars - days_with_trades
    
    # 2. Weekly Profit Breakdown
    df_weekly = df_daily["equity"].resample("W-SUN").last().to_frame()
    df_weekly["prev_equity"] = df_weekly["equity"].shift(1).fillna(initial_capital)
    df_weekly["weekly_pnl"] = df_weekly["equity"] - df_weekly["prev_equity"]
    df_weekly["weekly_return_pct"] = (df_weekly["weekly_pnl"] / df_weekly["prev_equity"]) * 100
    
    total_weeks = len(df_weekly)
    positive_weeks = int((df_weekly["weekly_pnl"] > 0).sum())
    negative_weeks = int((df_weekly["weekly_pnl"] < 0).sum())
    weekly_win_rate = (positive_weeks / total_weeks) * 100 if total_weeks > 0 else 0
    avg_weekly_profit = float(df_weekly["weekly_pnl"].mean())
    best_week_profit = float(df_weekly["weekly_pnl"].max())
    worst_week_profit = float(df_weekly["weekly_pnl"].min())

    # 3. Monthly Profit Breakdown (Year x Month Grid)
    df_monthly = df_daily["equity"].resample("ME").last().to_frame()
    df_monthly["prev_equity"] = df_monthly["equity"].shift(1).fillna(initial_capital)
    df_monthly["monthly_pnl"] = df_monthly["equity"] - df_monthly["prev_equity"]
    df_monthly["monthly_return_pct"] = (df_monthly["monthly_pnl"] / df_monthly["prev_equity"]) * 100
    df_monthly["year"] = df_monthly.index.year
    df_monthly["month"] = df_monthly.index.month_name().str[:3]
    
    total_months = len(df_monthly)
    positive_months = int((df_monthly["monthly_pnl"] > 0).sum())
    monthly_win_rate = (positive_months / total_months) * 100 if total_months > 0 else 0
    avg_monthly_profit = float(df_monthly["monthly_pnl"].mean())
    best_month_profit = float(df_monthly["monthly_pnl"].max())
    worst_month_profit = float(df_monthly["monthly_pnl"].min())
    
    # 4. Overall Portfolio Stats
    final_equity = float(df_daily["equity"].iloc[-1])
    total_net_pnl = final_equity - initial_capital
    total_return_pct = (total_net_pnl / initial_capital) * 100
    
    closed_trades = [t for t in trades if "CLOSE" in t["type"]]
    winning_trades = [t for t in closed_trades if t["net_pnl"] > 0]
    losing_trades = [t for t in closed_trades if t["net_pnl"] <= 0]
    trade_win_rate = (len(winning_trades) / len(closed_trades) * 100) if closed_trades else 0
    total_fees_paid = sum(t.get("fee", 0) for t in trades)
    
    gross_gains = sum(t["net_pnl"] for t in winning_trades)
    gross_losses = abs(sum(t["net_pnl"] for t in losing_trades))
    profit_factor = float(gross_gains / (gross_losses + 1e-9))
    
    # Drawdown
    peaks = df_daily["equity"].cummax()
    drawdowns = (df_daily["equity"] - peaks) / peaks
    max_drawdown_pct = float(drawdowns.min()) * 100
    
    # Sharpe Ratio
    daily_rets = df_daily["equity_return"]
    sharpe = float((daily_rets.mean() / (daily_rets.std() + 1e-9)) * np.sqrt(365))
    
    # Buy & Hold Benchmark
    btc_start_price = float(closes[0])
    btc_end_price = float(closes[-1])
    btc_buy_hold_return = ((btc_end_price - btc_start_price) / btc_start_price) * 100

    results = {
        "period": f"{start_date} to {end_date}",
        "trading_days": num_bars,
        "speed_metrics": {
            "total_inference_time_sec": total_infer_time,
            "avg_ms_per_bar": ms_per_bar,
            "throughput_bars_per_sec": throughput,
            "batch_size": batch_size
        },
        "daily_trade_frequency": {
            "total_trades_opened": int(total_trades_opened),
            "avg_trades_opened_per_day": avg_trades_per_day,
            "days_with_new_trade": days_with_trades,
            "days_holding_or_flat": days_without_trades
        },
        "weekly_profit_metrics": {
            "total_weeks": total_weeks,
            "positive_weeks": positive_weeks,
            "negative_weeks": negative_weeks,
            "weekly_win_rate_pct": weekly_win_rate,
            "avg_profit_per_week": avg_weekly_profit,
            "best_week_profit": best_week_profit,
            "worst_week_profit": worst_week_profit
        },
        "monthly_profit_metrics": {
            "total_months": total_months,
            "positive_months": positive_months,
            "negative_months": total_months - positive_months,
            "monthly_win_rate_pct": monthly_win_rate,
            "avg_profit_per_month": avg_monthly_profit,
            "best_month_profit": best_month_profit,
            "worst_month_profit": worst_month_profit,
            "monthly_table": [
                {
                    "year": int(row["year"]),
                    "month": str(row["month"]),
                    "pnl": float(row["monthly_pnl"]),
                    "return_pct": float(row["monthly_return_pct"])
                }
                for _, row in df_monthly.iterrows()
            ]
        },
        "portfolio_summary": {
            "initial_capital": initial_capital,
            "final_equity": final_equity,
            "net_profit": total_net_pnl,
            "total_return_pct": total_return_pct,
            "total_orders": len(trades),
            "closed_trades": len(closed_trades),
            "trade_win_rate_pct": trade_win_rate,
            "profit_factor": profit_factor,
            "total_fees_paid": total_fees_paid,
            "max_drawdown_pct": max_drawdown_pct,
            "sharpe_ratio": sharpe,
            "btc_buy_and_hold_return_pct": btc_buy_hold_return
        }
    }
    
    out_file = Path(__file__).resolve().parent / "laya_5year_btc_results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    logger.info("Saved 5-year results to: %s", out_file)
    
    print("\n" + "="*85)
    print("LAYA 5-YEAR BITCOIN BACKTEST RESULTS (2021 - 2026)")
    print("="*85)
    print(f"Time Period            : {start_date} to {end_date} ({num_bars} Daily Bars)")
    print(f"Inference Speed        : {ms_per_bar:.2f} ms/bar | {throughput:.1f} bars/sec (Batch size {batch_size})")
    print(f"Total Computation Time : {total_infer_time:.2f} seconds for 5.7 YEARS of decisions")
    print("-"*85)
    print("PORTFOLIO PERFORMANCE")
    print(f"Initial Capital        : ${initial_capital:,.2f}")
    print(f"Final Capital          : ${final_equity:,.2f}")
    print(f"Net Profit             : ${total_net_pnl:+,.2f} ({total_return_pct:+.2f}%)")
    print(f"BTC Buy & Hold Return  : {btc_buy_hold_return:+.2f}%")
    print(f"Profit Factor          : {profit_factor:.2f}")
    print(f"Trade Win Rate         : {trade_win_rate:.1f}% ({len(winning_trades)} wins / {len(closed_trades)} trades)")
    print(f"Total Fees Paid        : ${total_fees_paid:,.2f}")
    print(f"Max Drawdown           : {max_drawdown_pct:.2f}%")
    print(f"Sharpe Ratio           : {sharpe:.2f}")
    print("-"*85)
    print("DAILY TRADE FREQUENCY")
    print(f"Total Trades Opened    : {total_trades_opened}")
    print(f"Avg Trades Opened/Day  : {avg_trades_per_day:.3f} trades/day (1 trade every {1/avg_trades_per_day:.1f} days)")
    print(f"Days With Trade Entry  : {days_with_trades} days")
    print(f"Days In Position/Flat  : {days_without_trades} days")
    print("-"*85)
    print("WEEKLY PROFIT METRICS")
    print(f"Total Calendar Weeks   : {total_weeks} weeks")
    print(f"Profitable Weeks       : {positive_weeks} / {total_weeks} ({weekly_win_rate:.1f}%)")
    print(f"Avg Profit Per Week    : ${avg_weekly_profit:+,.2f}")
    print(f"Best Week              : ${best_week_profit:+,.2f}")
    print(f"Worst Week             : ${worst_week_profit:+,.2f}")
    print("-"*85)
    print("MONTHLY PROFIT METRICS")
    print(f"Total Calendar Months  : {total_months} months")
    print(f"Profitable Months      : {positive_months} / {total_months} ({monthly_win_rate:.1f}%)")
    print(f"Avg Profit Per Month   : ${avg_monthly_profit:+,.2f}")
    print(f"Best Month             : ${best_month_profit:+,.2f}")
    print(f"Worst Month            : ${worst_month_profit:+,.2f}")
    print("="*85)
    
    return results


if __name__ == "__main__":
    run_5year_backtest()
