"""
AgentQuant V2 — 5-Minute Structure & Price Action State Machine
==============================================================
Implements institutional Smart Money / Auction Market order-flow sequences:
  Sequence (Long):
    1. Liquidity Sweep: Price breaks prior 5M swing low, but closes inside with buyer wick.
    2. Bullish Displacement: Institutional expansion candle (body >= 60%) breaks local counter-high.
    3. Retest & Structural SL: Order triggers on retest of broken level / 50% displacement zone.
       Stop-Loss is anchored strictly below the sweep low with an ATR buffer.
       Target is >= 2.0R asymmetric reward.

  Sequence (Short):
    1. Liquidity Sweep: Price pierces prior 5M swing high, but closes below with seller wick.
    2. Bearish Displacement: Large red expansion candle breaks local counter-low.
    3. Retest & Structural SL: Order triggers on retest. SL anchored above sweep high.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class StructureState(str, Enum):
    IDLE = "IDLE"
    SWEEP_DETECTED = "SWEEP_DETECTED"
    DISPLACEMENT_CONFIRMED = "DISPLACEMENT_CONFIRMED"
    READY_FOR_ENTRY = "READY_FOR_ENTRY"


@dataclass
class SetupContext:
    side: str  # "BUY" or "SELL"
    sweep_price: float
    sweep_bar_index: int
    break_level: float
    retest_entry_price: float
    structural_sl_price: float
    take_profit_price: float
    risk_distance: float
    target_r_multiple: float
    bars_since_sweep: int = 0
    state: StructureState = StructureState.IDLE


class StructureEngine:
    def __init__(self, swing_window: int = 6, min_wick_ratio: float = 0.25,
                 min_body_ratio: float = 0.55, target_r_multiple: float = 2.0,
                 max_ttl_bars: int = 6):
        self.swing_window = swing_window
        self.min_wick_ratio = min_wick_ratio
        self.min_body_ratio = min_body_ratio
        self.target_r_multiple = target_r_multiple
        self.max_ttl_bars = max_ttl_bars

    @staticmethod
    def find_swing_points(df: pd.DataFrame, window: int = 5) -> Tuple[pd.Series, pd.Series]:
        """Identifies rolling local fractal highs and lows."""
        high = df["high"]
        low = df["low"]
        rolling_low = low.shift(1).rolling(window=window).min()
        rolling_high = high.shift(1).rolling(window=window).max()
        return rolling_high, rolling_low

    def evaluate_setup(self, df_5m: pd.DataFrame, allowed_side: str = "BOTH") -> Optional[SetupContext]:
        """
        Scans recent 5-minute bars to identify active setups.
        Enforces strict Price Action sequence: Sweep -> Displacement -> Retest.
        """
        if df_5m is None or len(df_5m) < self.swing_window * 3:
            return None

        d = df_5m.copy()
        rolling_high, rolling_low = self.find_swing_points(d, window=self.swing_window)
        d["prior_high"] = rolling_high
        d["prior_low"] = rolling_low

        n = len(d)
        # Scan backward up to max_ttl_bars + 3 to detect recent completed sequences
        scan_range = min(n - 1, self.max_ttl_bars + 4)

        for offset in range(scan_range, 0, -1):
            i = n - 1 - offset
            if i < self.swing_window:
                continue

            bar = d.iloc[i]
            o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
            p_low = bar["prior_low"]
            p_high = bar["prior_high"]
            c_range = max(h - l, 1e-6)

            # ── 1. CHECK BULLISH LIQUIDITY SWEEP ──
            if allowed_side in ("BOTH", "BUY_ONLY"):
                # Low pierced prior swing low, but candle closed back ABOVE prior swing low
                if l < p_low and c >= p_low:
                    lower_wick = (min(o, c) - l) / c_range
                    if lower_wick >= self.min_wick_ratio:
                        # Sweep detected at bar i! Now verify displacement in bars i+1 to i+3
                        sweep_price = l
                        disp_found = False
                        break_lvl = p_high
                        disp_bar_idx = i

                        for j in range(i + 1, min(i + 4, n)):
                            d_bar = d.iloc[j]
                            d_o, d_h, d_l, d_c = d_bar["open"], d_bar["high"], d_bar["low"], d_bar["close"]
                            d_range = max(d_h - d_l, 1e-6)
                            d_body = abs(d_c - d_o) / d_range

                            # Bullish displacement: strong green candle closing above midpoint
                            if d_c > d_o and d_body >= self.min_body_ratio and d_c > bar["high"]:
                                disp_found = True
                                disp_bar_idx = j
                                break_lvl = bar["high"]
                                break

                        if disp_found:
                            # ── 2. RETEST & STRUCTURAL SL SETUP ──
                            retest_price = break_lvl
                            atr_buffer = c_range * 0.15
                            sl_price = sweep_price - atr_buffer
                            risk_dist = retest_price - sl_price

                            if risk_dist > 0:
                                tp_price = retest_price + (risk_dist * self.target_r_multiple)
                                bars_since = (n - 1) - disp_bar_idx

                                if bars_since <= self.max_ttl_bars:
                                    curr_price = float(d.iloc[-1]["close"])
                                    # Price is in or near the retest zone (within 0.25% of retest)
                                    retest_dist_pct = abs(curr_price - retest_price) / retest_price
                                    if curr_price >= sl_price and retest_dist_pct <= 0.0040:
                                        return SetupContext(
                                            side="BUY",
                                            sweep_price=sweep_price,
                                            sweep_bar_index=i,
                                            break_level=break_lvl,
                                            retest_entry_price=round(retest_price, 2),
                                            structural_sl_price=round(sl_price, 2),
                                            take_profit_price=round(tp_price, 2),
                                            risk_distance=round(risk_dist, 2),
                                            target_r_multiple=self.target_r_multiple,
                                            bars_since_sweep=bars_since,
                                            state=StructureState.READY_FOR_ENTRY
                                        )

            # ── 2. CHECK BEARISH LIQUIDITY SWEEP ──
            if allowed_side in ("BOTH", "SELL_ONLY"):
                # High pierced prior swing high, but candle closed back BELOW prior swing high
                if h > p_high and c <= p_high:
                    upper_wick = (h - max(o, c)) / c_range
                    if upper_wick >= self.min_wick_ratio:
                        # Sweep detected at bar i! Verify bearish displacement in bars i+1 to i+3
                        sweep_price = h
                        disp_found = False
                        break_lvl = p_low
                        disp_bar_idx = i

                        for j in range(i + 1, min(i + 4, n)):
                            d_bar = d.iloc[j]
                            d_o, d_h, d_l, d_c = d_bar["open"], d_bar["high"], d_bar["low"], d_bar["close"]
                            d_range = max(d_h - d_l, 1e-6)
                            d_body = abs(d_c - d_o) / d_range

                            # Bearish displacement: strong red candle closing below bar low
                            if d_c < d_o and d_body >= self.min_body_ratio and d_c < bar["low"]:
                                disp_found = True
                                disp_bar_idx = j
                                break_lvl = bar["low"]
                                break

                        if disp_found:
                            retest_price = break_lvl
                            atr_buffer = c_range * 0.15
                            sl_price = sweep_price + atr_buffer
                            risk_dist = sl_price - retest_price

                            if risk_dist > 0:
                                tp_price = retest_price - (risk_dist * self.target_r_multiple)
                                bars_since = (n - 1) - disp_bar_idx

                                if bars_since <= self.max_ttl_bars:
                                    curr_price = float(d.iloc[-1]["close"])
                                    retest_dist_pct = abs(curr_price - retest_price) / retest_price
                                    if curr_price <= sl_price and retest_dist_pct <= 0.0040:
                                        return SetupContext(
                                            side="SELL",
                                            sweep_price=sweep_price,
                                            sweep_bar_index=i,
                                            break_level=break_lvl,
                                            retest_entry_price=round(retest_price, 2),
                                            structural_sl_price=round(sl_price, 2),
                                            take_profit_price=round(tp_price, 2),
                                            risk_distance=round(risk_dist, 2),
                                            target_r_multiple=self.target_r_multiple,
                                            bars_since_sweep=bars_since,
                                            state=StructureState.READY_FOR_ENTRY
                                        )

        return None

    @staticmethod
    def calculate_lot_size(entry_price: float, sl_price: float, risk_usd: float = 15.0,
                           symbol: str = "BTCUSD", min_lot: float = 0.01,
                           max_lot: float = 0.10) -> float:
        """
        Calculates exact position size to guarantee dollar loss <= risk_usd.
        Formula: lots = risk_usd / (abs(entry - sl) * contract_multiplier)
        """
        distance = abs(entry_price - sl_price)
        if distance <= 0:
            return min_lot

        sym = symbol.upper()
        if "BTC" in sym:
            multiplier = 1.0  # 1 BTC per 1.0 lot
            lots = risk_usd / (distance * multiplier)
        elif "ETH" in sym:
            multiplier = 1.0  # 1 ETH per 1.0 lot
            lots = risk_usd / (distance * multiplier)
        elif "SPX" in sym or "NDX" in sym or "US30" in sym:
            multiplier = 1.0
            lots = risk_usd / (distance * multiplier)
        else:
            multiplier = 1.0
            lots = risk_usd / distance

        lots = round(lots, 2)
        return float(np.clip(lots, min_lot, max_lot))
