"""
Institutional Order Block & Price Action Stop-Loss (OB-PASL) Engine
===================================================================
Detects institutional Order Blocks (SMC / Smart Money Concepts) on intraday
trendbars (M5/M15) to calculate true structural invalidation Stop-Loss levels.

Core Logic:
1. Bullish Order Block (for BUY setups):
   The last down-close (bearish) candle immediately preceding an impulsive
   bullish displacement (breakout candle with large body or FVG).
   Institutional accumulation defends this block; invalidation sits below OB Low.

2. Bearish Order Block (for SELL setups):
   The last up-close (bullish) candle immediately preceding an impulsive
   bearish displacement (breakout candle with large body or FVG).
   Institutional distribution defends this block; invalidation sits above OB High.

3. Invalidation & Buffer Rules:
   - BUY Invalidation: OB_low - (ATR * 0.25)
   - SELL Invalidation: OB_high + (ATR * 0.25) + spread_cushion
   - Invariant 33: Distance must respect the minimum noise floor (>= 3.50 pts Gold / 15 pips Forex).
   - Capital Protection: Strictly clamped to maximum allowed prop-firm distance.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("order_block_engine")


@dataclass
class OrderBlock:
    side: str  # "BULLISH" (for BUY) or "BEARISH" (for SELL)
    bar_index: int
    timestamp: Any
    high: float
    low: float
    open: float
    close: float
    displacement_size: float
    fvg_size: float
    mitigated: bool
    invalidation_price: float
    distance_from_entry: float = 0.0


class OrderBlockEngine:
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
        """Calculates Average True Range over the lookback window."""
        if df is None or len(df) < 2:
            return 0.50

        high = df["high"]
        low = df["low"]
        close = df["close"]

        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        rolling_atr = tr.rolling(window=min(period, len(df)), min_periods=1).mean()
        val = float(rolling_atr.iloc[-1])
        return val if val > 0 else 0.50

    @classmethod
    def detect_order_blocks(
        cls,
        df: pd.DataFrame,
        side: str,
        lookback_bars: int = 25,
        min_body_ratio: float = 0.55
    ) -> List[OrderBlock]:
        """
        Scans trendbars to detect institutional Order Blocks.
        
        Args:
            df: Trendbars DataFrame with ['open', 'high', 'low', 'close']
            side: 'BUY' (detects Bullish Order Blocks) or 'SELL' (detects Bearish Order Blocks)
            lookback_bars: Number of recent completed bars to scan
            min_body_ratio: Minimum body / range ratio for the displacement candle
        
        Returns:
            List[OrderBlock] sorted with most recent first
        """
        if df is None or len(df) < 5:
            return []

        side_upper = side.upper()
        n = len(df)
        start_idx = max(1, n - lookback_bars)
        atr = cls.calculate_atr(df, period=14)
        order_blocks = []

        # We evaluate candles up to the penultimate bar (n-2) to ensure completed displacement
        for i in range(n - 2, start_idx - 1, -1):
            bar = df.iloc[i]
            next_bar = df.iloc[i + 1]

            b_open, b_high, b_low, b_close = bar["open"], bar["high"], bar["low"], bar["close"]
            n_open, n_high, n_low, n_close = next_bar["open"], next_bar["high"], next_bar["low"], next_bar["close"]

            n_range = max(n_high - n_low, 1e-6)
            n_body = abs(n_close - n_open)
            n_body_ratio = n_body / n_range

            # ── BULLISH ORDER BLOCK (for BUY) ──
            # Origin: Bearish candle (or small consolidation candle)
            # Displacement: Strong green candle breaking above the origin high
            if side_upper == "BUY":
                is_origin_candle = (b_close <= b_open) or (b_close < n_open)
                is_bullish_displacement = (
                    n_close > n_open
                    and (n_body_ratio >= min_body_ratio or n_body >= atr * 0.9)
                    and n_close > b_high
                )

                if is_origin_candle and is_bullish_displacement:
                    # Check for Fair Value Gap (FVG) between bar i-1 and bar i+1 if available
                    fvg = 0.0
                    if i > 0:
                        prev_bar = df.iloc[i - 1]
                        if next_bar["low"] > prev_bar["high"]:
                            fvg = next_bar["low"] - prev_bar["high"]

                    # Check mitigation: Has subsequent price dipped completely through this OB low?
                    mitigated = False
                    if (i + 2) < n:
                        subsequent_lows = df.iloc[i + 2:]["low"]
                        if not subsequent_lows.empty and float(subsequent_lows.min()) < b_low:
                            mitigated = True

                    ts = bar.name if hasattr(bar, "name") else i
                    ob = OrderBlock(
                        side="BULLISH",
                        bar_index=i,
                        timestamp=ts,
                        high=float(b_high),
                        low=float(b_low),
                        open=float(b_open),
                        close=float(b_close),
                        displacement_size=float(n_body),
                        fvg_size=float(fvg),
                        mitigated=mitigated,
                        invalidation_price=float(b_low)
                    )
                    order_blocks.append(ob)

            # ── BEARISH ORDER BLOCK (for SELL) ──
            # Origin: Bullish candle (or small consolidation candle)
            # Displacement: Strong red candle breaking below the origin low
            elif side_upper == "SELL":
                is_origin_candle = (b_close >= b_open) or (b_close > n_open)
                is_bearish_displacement = (
                    n_close < n_open
                    and (n_body_ratio >= min_body_ratio or n_body >= atr * 0.9)
                    and n_close < b_low
                )

                if is_origin_candle and is_bearish_displacement:
                    # Check for Downside FVG between bar i-1 and bar i+1
                    fvg = 0.0
                    if i > 0:
                        prev_bar = df.iloc[i - 1]
                        if next_bar["high"] < prev_bar["low"]:
                            fvg = prev_bar["low"] - next_bar["high"]

                    # Check mitigation: Has subsequent price spiked completely through this OB high?
                    mitigated = False
                    if (i + 2) < n:
                        subsequent_highs = df.iloc[i + 2:]["high"]
                        if not subsequent_highs.empty and float(subsequent_highs.max()) > b_high:
                            mitigated = True

                    ts = bar.name if hasattr(bar, "name") else i
                    ob = OrderBlock(
                        side="BEARISH",
                        bar_index=i,
                        timestamp=ts,
                        high=float(b_high),
                        low=float(b_low),
                        open=float(b_open),
                        close=float(b_close),
                        displacement_size=float(n_body),
                        fvg_size=float(fvg),
                        mitigated=mitigated,
                        invalidation_price=float(b_high)
                    )
                    order_blocks.append(ob)

        return order_blocks

    @classmethod
    def calculate_order_block_sl(
        cls,
        df: pd.DataFrame,
        side: str,
        entry_price: float,
        symbol: str,
        min_noise_distance: float,
        max_allowed_distance: float,
        spread_cushion: float = 0.0,
        lookback_bars: int = 25
    ) -> Tuple[Optional[float], Optional[OrderBlock], str]:
        """
        Determines the institutional Order Block Stop-Loss price.

        Selection Criteria:
        1. Filters for unmitigated Order Blocks in the structural trade direction.
        2. Selects the nearest Order Block whose invalidation is outside the noise floor (>= min_noise_distance).
        3. If the nearest Order Block is inside the noise floor (< min_noise_distance),
           steps back to the preceding parent Order Block to prevent market noise suffocation (Invariant 33).
        4. Capped at max_allowed_distance for prop-firm compliance.

        Returns:
            Tuple[Optional[float], Optional[OrderBlock], str]:
            (calculated_sl_price, selected_order_block, reasoning_label)
        """
        if df is None or len(df) < 5:
            return None, None, "NO_BAR_DATA"

        side_upper = side.upper()
        sym_upper = symbol.upper()
        digits = 2 if any(k in sym_upper for k in ["XAU", "GOLD", "BTC", "ETH", "SPX", "NDX", "US30", "US2000"]) else 5

        atr = cls.calculate_atr(df, period=14)
        atr_buffer = atr * 0.25

        # Dynamic physical buffer beyond the wick
        if "XAU" in sym_upper or "GOLD" in sym_upper:
            min_buf = max(0.40, atr_buffer)
        elif "JPY" in sym_upper:
            min_buf = max(0.05, atr_buffer)
        elif any(k in sym_upper for k in ["BTC", "ETH"]):
            min_buf = max(15.0, atr_buffer)
        else:
            min_buf = max(0.0003, atr_buffer)

        detected_obs = cls.detect_order_blocks(df, side_upper, lookback_bars=lookback_bars)
        if not detected_obs:
            return None, None, "NO_ORDER_BLOCK_FOUND"

        # Prioritize fresh unmitigated Order Blocks first
        unmitigated_obs = [ob for ob in detected_obs if not ob.mitigated]
        scan_list = unmitigated_obs if unmitigated_obs else detected_obs

        candidate_ob: Optional[OrderBlock] = None
        candidate_sl: Optional[float] = None
        reason: str = "NO_VALID_STRUCTURAL_OB"

        for ob in scan_list:
            if side_upper == "BUY":
                # For BUY: Order Block must be at or below entry price
                if ob.low > entry_price:
                    continue

                raw_sl = round(ob.low - min_buf, digits)
                dist = round(entry_price - raw_sl, digits)

                # Invariant 33: Anti-Suffocation Guard.
                # If OB is too close to entry (< min_noise_distance), continue to parent OB
                if dist < min_noise_distance:
                    logger.debug(f"🛡️ [OB Anti-Suffocation] Bullish OB @ {ob.low} (dist: {dist:.2f}) inside noise floor {min_noise_distance:.2f}. Stepping to parent OB.")
                    continue

                # If OB is within max prop firm risk clamp
                candidate_ob = ob
                candidate_ob.distance_from_entry = dist
                candidate_sl = raw_sl
                reason = "BULLISH_ORDER_BLOCK_ANCHORED"
                break

            elif side_upper == "SELL":
                # For SELL: Order Block must be at or above entry price
                if ob.high < entry_price:
                    continue

                raw_sl = round(ob.high + min_buf + max(0.0, spread_cushion), digits)
                dist = round(raw_sl - entry_price, digits)

                # Invariant 33: Anti-Suffocation Guard.
                if dist < min_noise_distance:
                    logger.debug(f"🛡️ [OB Anti-Suffocation] Bearish OB @ {ob.high} (dist: {dist:.2f}) inside noise floor {min_noise_distance:.2f}. Stepping to parent OB.")
                    continue

                candidate_ob = ob
                candidate_ob.distance_from_entry = dist
                candidate_sl = raw_sl
                reason = "BEARISH_ORDER_BLOCK_ANCHORED"
                break

        if candidate_sl is not None:
            # Enforce strict prop-firm ceiling
            if side_upper == "BUY":
                hard_floor = round(entry_price - max_allowed_distance, digits)
                if candidate_sl < hard_floor:
                    candidate_sl = hard_floor
                    reason = f"{reason}_CLAMPED_MAX_RISK"
            else:
                hard_ceiling = round(entry_price + max_allowed_distance, digits)
                if candidate_sl > hard_ceiling:
                    candidate_sl = hard_ceiling
                    reason = f"{reason}_CLAMPED_MAX_RISK"

            return candidate_sl, candidate_ob, reason

        return None, None, reason
