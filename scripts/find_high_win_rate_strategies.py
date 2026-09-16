"""
High Win Rate Strategy Explorer (80% - 85%+)
============================================
Searches AgentQuant's arsenal and quantitative literature for models that achieve 80% to 85%+ win rates
on US Equities (SPY & QQQ) across 10 years (2016 - 2026 / 2,514 trading days).
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.strategies.base import _get_close

def run_explorer():
    cache_dir = Path("cache")
    df_spy = pd.read_csv(cache_dir / "SPY_10y.csv", index_col=0, parse_dates=True)
    df_qqq = pd.read_csv(cache_dir / "QQQ_10y.csv", index_col=0, parse_dates=True)

    c_spy = _get_close(df_spy)
    c_qqq = _get_close(df_qqq)

    contract_mult = 10.0
    comm = 1.50

    results = []

    def evaluate_strategy(name, asset, close_series, entries, exits, stop_loss_pct=0.03, max_hold=5):
        trades = []
        in_pos = False
        entry_price = 0.0
        entry_idx = None
        bars = 0

        for dt in close_series.index:
            p = float(close_series.loc[dt])
            entry_sig = bool(entries.loc[dt]) if dt in entries.index else False
            exit_sig = bool(exits.loc[dt]) if dt in exits.index else False

            if not in_pos:
                if entry_sig:
                    in_pos = True
                    entry_price = p
                    entry_idx = dt
                    bars = 0
            else:
                bars += 1
                stop_hit = p <= (entry_price * (1.0 - stop_loss_pct))
                time_stop = bars >= max_hold

                if exit_sig or stop_hit or time_stop:
                    exit_price = p
                    pnl = (exit_price - entry_price) * contract_mult - (comm * 2)
                    trades.append({
                        "entry_dt": entry_idx,
                        "exit_dt": dt,
                        "entry_p": entry_price,
                        "exit_p": exit_price,
                        "pnl": pnl,
                        "bars": bars,
                        "win": pnl > 0
                    })
                    in_pos = False

        if not trades:
            return None

        total_t = len(trades)
        wins = sum(1 for t in trades if t["win"])
        win_rate = (wins / total_t) * 100.0
        tot_pnl = sum(t["pnl"] for t in trades)
        avg_bars = np.mean([t["bars"] for t in trades])
        t_per_year = total_t / (len(close_series) / 252.0)

        # Max Drawdown
        cum = np.cumsum([t["pnl"] for t in trades])
        peak = np.maximum.accumulate(cum)
        dd = peak - cum
        max_dd = np.max(dd) if len(dd) > 0 else 0.0

        return {
            "name": name,
            "asset": asset,
            "win_rate": round(win_rate, 1),
            "trades": total_t,
            "trades_per_yr": round(t_per_year, 1),
            "trades_per_mo": round(t_per_year / 12.0, 2),
            "tot_pnl": round(tot_pnl, 2),
            "avg_pnl_trade": round(tot_pnl / total_t, 2),
            "max_dd": round(max_dd, 2),
            "avg_bars": round(avg_bars, 1)
        }

    # 1. Baseline: Balanced Scalper (5d, 1.25s)
    for asset, c in [("SPY", c_spy), ("QQQ", c_qqq)]:
        m5 = c.rolling(5).mean()
        s5 = c.rolling(5).std()
        l_band = m5 - 1.25 * s5
        entries = c <= l_band
        exits = c >= m5
        res = evaluate_strategy("Baseline Scalper (5d, 1.25s)", asset, c, entries, exits)
        if res: results.append(res)

    # 2. Deeper Dip Scalper (5d, 1.50s)
    for asset, c in [("SPY", c_spy), ("QQQ", c_qqq)]:
        m5 = c.rolling(5).mean()
        s5 = c.rolling(5).std()
        l_band = m5 - 1.50 * s5
        entries = c <= l_band
        exits = c >= m5
        res = evaluate_strategy("Deep Dip Scalper (5d, 1.50s)", asset, c, entries, exits)
        if res: results.append(res)

    # 3. Extreme Dip Scalper (5d, 1.75s)
    for asset, c in [("SPY", c_spy), ("QQQ", c_qqq)]:
        m5 = c.rolling(5).mean()
        s5 = c.rolling(5).std()
        l_band = m5 - 1.75 * s5
        entries = c <= l_band
        exits = c >= m5
        res = evaluate_strategy("Ultra Dip Scalper (5d, 1.75s)", asset, c, entries, exits)
        if res: results.append(res)

    # 4. Bull-Market Trend Filtered Scalper (5d, 1.25s + Price > 200 SMA)
    for asset, c in [("SPY", c_spy), ("QQQ", c_qqq)]:
        sma200 = c.rolling(200).mean()
        m5 = c.rolling(5).mean()
        s5 = c.rolling(5).std()
        l_band = m5 - 1.25 * s5
        entries = (c <= l_band) & (c > sma200)
        exits = c >= m5
        res = evaluate_strategy("Bull-Filter Scalper (5d, 1.25s + 200 SMA)", asset, c, entries, exits)
        if res: results.append(res)

    # 5. Bull-Market Deep Dip Scalper (5d, 1.50s + Price > 200 SMA)
    for asset, c in [("SPY", c_spy), ("QQQ", c_qqq)]:
        sma200 = c.rolling(200).mean()
        m5 = c.rolling(5).mean()
        s5 = c.rolling(5).std()
        l_band = m5 - 1.50 * s5
        entries = (c <= l_band) & (c > sma200)
        exits = c >= m5
        res = evaluate_strategy("Bull Deep Scalper (5d, 1.50s + 200 SMA)", asset, c, entries, exits)
        if res: results.append(res)

    # 6. Classic Bollinger Reversion (15d, 2.0s)
    for asset, c in [("SPY", c_spy), ("QQQ", c_qqq)]:
        m15 = c.rolling(15).mean()
        s15 = c.rolling(15).std()
        l_band = m15 - 2.0 * s15
        entries = c <= l_band
        exits = c >= m15
        res = evaluate_strategy("Classic Bollinger Reversion (15d, 2.0s)", asset, c, entries, exits)
        if res: results.append(res)

    # 7. Connors 2-Period RSI (< 10) + 200 SMA (The Quant Holy Grail)
    for asset, c in [("SPY", c_spy), ("QQQ", c_qqq)]:
        delta = c.diff()
        gain = (delta.where(delta > 0, 0)).rolling(2).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(2).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi2 = 100 - (100 / (1 + rs))
        sma200 = c.rolling(200).mean()
        sma5 = c.rolling(5).mean()
        entries = (rsi2 < 10) & (c > sma200)
        exits = c >= sma5
        res = evaluate_strategy("Connors RSI(2) < 10 + 200 SMA", asset, c, entries, exits, max_hold=5)
        if res: results.append(res)

    # 8. Connors Ultra-Oversold RSI(2) < 5 + 200 SMA
    for asset, c in [("SPY", c_spy), ("QQQ", c_qqq)]:
        delta = c.diff()
        gain = (delta.where(delta > 0, 0)).rolling(2).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(2).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi2 = 100 - (100 / (1 + rs))
        sma200 = c.rolling(200).mean()
        sma5 = c.rolling(5).mean()
        entries = (rsi2 < 5) & (c > sma200)
        exits = c >= sma5
        res = evaluate_strategy("Connors Ultra-Oversold RSI(2) < 5 + 200 SMA", asset, c, entries, exits, max_hold=5)
        if res: results.append(res)

    # 9. Low-Vol Regime Filter Scalper (21d Vol < 18%)
    for asset, c in [("SPY", c_spy), ("QQQ", c_qqq)]:
        vol21 = c.pct_change().rolling(21).std() * (252 ** 0.5)
        m5 = c.rolling(5).mean()
        s5 = c.rolling(5).std()
        l_band = m5 - 1.25 * s5
        entries = (c <= l_band) & (vol21 < 0.18)
        exits = c >= m5
        res = evaluate_strategy("Low-Vol Scalper (5d, 1.25s + Vol<18%)", asset, c, entries, exits)
        if res: results.append(res)

    df_res = pd.DataFrame(results).sort_values(by="win_rate", ascending=False)
    
    print("=" * 115)
    print("           AGENTQUANT ARSENAL: HIGH WIN RATE STRATEGY DISCOVERY (10 YEARS: 2016 - 2026)")
    print("=" * 115)
    print(f"{'Strategy Name':<42} {'Asset':<6} {'Win Rate':<10} {'Trades':<8} {'Tr/Mo':<8} {'Total PnL':<12} {'Max DD':<10}")
    print("-" * 115)
    for _, r in df_res.iterrows():
        star = "🌟 80%+" if r["win_rate"] >= 80.0 else ("✨ 85%+" if r["win_rate"] >= 85.0 else "")
        print(f"{r['name']:<42} {r['asset']:<6} {r['win_rate']:>5.1f}%     {r['trades']:<8} {r['trades_per_mo']:<8.2f} ${r['tot_pnl']:<11,.2f} ${r['max_dd']:<9,.2f} {star}")
    print("=" * 115)

if __name__ == "__main__":
    run_explorer()
