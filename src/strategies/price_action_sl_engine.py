"""
Price Action Stop-Loss (PASL) Engine
===================================
Institutional Price Action Stop Loss calculation based on:
1. Fractal Market Structure (Swing Lows for BUY, Swing Highs for SELL).
2. Volatility Buffer (Average True Range - ATR).
3. Structural Shield Guard: Protects retail trades from stop-hunts by
   anchoring stops behind liquidity wicks rather than arbitrary round numbers.
4. Hard Prop-Firm Ceilings: Guarantees stops never exceed maximum loss limits.
"""

import logging
from typing import Any, Dict, Optional, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger("price_action_sl_engine")


class PriceActionSLEngine:
    @classmethod
    def get_min_noise_floor_distance(cls, symbol: str) -> float:
        """
        Returns the minimum physical Stop-Loss distance required to prevent trades
        from being stopped out by standard bid/ask spread and intraday volatility noise.
        """
        sym_upper = symbol.upper()
        if "XAU" in sym_upper or "GOLD" in sym_upper:
            return 3.50   # Invariant 33: 3.50 pts Gold (35 pips) anti-suffocation floor
        elif "JPY" in sym_upper:
            return 0.15   # 15 pips on JPY pairs (e.g. 0.150 on USDJPY)
        elif any(k in sym_upper for k in ["BTC", "ETH"]):
            return 50.0   # $50 Crypto
        elif any(k in sym_upper for k in ["US30", "NAS100", "SPX", "NDX", "DJ30"]):
            return 25.0   # 25 pts Indices
        else:
            return 0.00150 # 15.0 pips standard Forex (EURUSD, GBPUSD, etc.)

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
        """
        Calculates the Average True Range (ATR) over the last `period` bars.
        Returns the most recent ATR value, or default fallback if data is short.
        """
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
    def calculate_swing_sl(
        cls,
        df: pd.DataFrame,
        side: str,
        entry_price: float,
        symbol: str = "XAUUSD",
        lookback_bars: int = 8,
        atr_buffer_mult: float = 0.25,
        spread_cushion: float = 0.0
    ) -> Tuple[float, float]:
        """
        Calculates Price Action Stop Loss anchored to recent fractal swing structure.

        Args:
            df: Intraday trendbars DataFrame (M5 or M15) with ['open', 'high', 'low', 'close'].
            side: 'BUY' or 'SELL'.
            entry_price: Current market entry price.
            symbol: Asset symbol name.
            lookback_bars: Number of prior bars to scan for the swing point (default 8 bars).
            atr_buffer_mult: Multiplier for ATR buffer placed beyond the swing wick.
            spread_cushion: Live broker spread (Ask - Bid) added to SELL stops to prevent spread-wick outs.

        Returns:
            Tuple[float, float]: (pasl_price, risk_distance)
        """
        side_upper = side.upper()
        sym_upper = symbol.upper()
        digits = 2 if any(k in sym_upper for k in ["XAU", "GOLD", "BTC", "ETH", "SPX", "NDX", "US30", "US2000"]) else 5

        # Minimum physical buffer beyond the wick to prevent spread/noise clipping
        if "XAU" in sym_upper or "GOLD" in sym_upper:
            min_buffer = 0.30  # 30 cents Gold
        elif "JPY" in sym_upper:
            min_buffer = 0.05
        elif any(k in sym_upper for k in ["BTC", "ETH"]):
            min_buffer = 15.0
        else:
            min_buffer = 0.0003  # 3 pips Forex

        # If DataFrame is empty or too short, return synthetic fallback
        if df is None or len(df) < 3:
            default_dist = 8.0 if "XAU" in sym_upper or "GOLD" in sym_upper else 0.0035
            sl = entry_price - default_dist if side_upper == "BUY" else entry_price + default_dist + (max(0.0, spread_cushion) if side_upper == "SELL" else 0.0)
            return round(sl, digits), default_dist

        # Scan the last N completed bars (excluding the currently forming bar at -1)
        scan_df = df.iloc[-(lookback_bars + 1):-1] if len(df) > (lookback_bars + 1) else df.iloc[:-1]
        if scan_df.empty:
            scan_df = df

        atr = cls.calculate_atr(df, period=14)
        dynamic_buffer = max(min_buffer, atr * atr_buffer_mult)

        min_noise = cls.get_min_noise_floor_distance(sym_upper)

        if side_upper == "BUY":
            swing_low = float(scan_df["low"].min())
            pasl = round(swing_low - dynamic_buffer, digits)
            # Ensure PASL is strictly below entry
            if pasl >= entry_price:
                pasl = round(entry_price - dynamic_buffer, digits)
            # Guarantee PASL respects minimum physical noise floor
            if (entry_price - pasl) < min_noise:
                pasl = round(entry_price - min_noise, digits)
            risk_dist = round(abs(entry_price - pasl), digits)
            return pasl, risk_dist
        else:
            swing_high = float(scan_df["high"].max())
            # For SELL orders: cTrader/brokers execute SL at Ask (Bid + spread).
            # Adding spread_cushion protects the position from spread expansion/spikes.
            pasl = round(swing_high + dynamic_buffer + max(0.0, spread_cushion), digits)
            # Ensure PASL is strictly above entry
            if pasl <= entry_price:
                pasl = round(entry_price + dynamic_buffer + max(0.0, spread_cushion), digits)
            # Guarantee PASL respects minimum physical noise floor
            if (pasl - entry_price) < min_noise:
                pasl = round(entry_price + min_noise + max(0.0, spread_cushion), digits)
            risk_dist = round(abs(pasl - entry_price), digits)
            return pasl, risk_dist

    @classmethod
    def reconcile_structural_sl(
        cls,
        provider_sl: Optional[float],
        df_bars: Optional[pd.DataFrame],
        side: str,
        entry_price: float,
        symbol: str,
        max_allowed_distance: float,
        spread_cushion: float = 0.0
    ) -> Tuple[float, str]:
        """
        Reconciles provider-written SL with real-time Price Action market structure.
        Implements the Structural Shield Guard:
          - If provider SL sits inside the liquidity sweep pocket (too tight),
            it extends SL behind the swing wick (so trade isn't prematurely wicked out).
          - If provider omitted SL or paywalled it ("VIP"), it adopts PASL.
          - Never exceeds max_allowed_distance (strict Prop Firm Risk Clamp).
          - For SELL trades, incorporates spread_cushion to protect against Ask-price spread widening.

        Returns:
            Tuple[float, str]: (final_safe_sl, reasoning_label)
        """
        side_upper = side.upper()
        sym_upper = symbol.upper()
        digits = 2 if any(k in sym_upper for k in ["XAU", "GOLD", "BTC", "ETH", "SPX", "NDX", "US30", "US2000"]) else 5

        # 1. Calculate Price Action Stop Loss if bars are available
        pasl = None
        if df_bars is not None and not df_bars.empty:
            try:
                pasl, _ = cls.calculate_swing_sl(
                    df_bars, side_upper, entry_price, symbol=sym_upper, spread_cushion=spread_cushion
                )
            except Exception:
                pasl = None

        min_noise = cls.get_min_noise_floor_distance(sym_upper)

        # 2. Determine initial candidate SL
        if provider_sl is None or provider_sl <= 0:
            if pasl is not None:
                candidate_sl = pasl
                reason = "PASL_SYNTHESIZED"
            else:
                fallback_dist = min(8.0 if "XAU" in sym_upper or "GOLD" in sym_upper else 0.0035, max_allowed_distance)
                candidate_sl = entry_price - fallback_dist if side_upper == "BUY" else entry_price + fallback_dist + (max(0.0, spread_cushion) if side_upper == "SELL" else 0.0)
                reason = "DEFAULT_SYNTHESIZED"
        else:
            candidate_sl = float(provider_sl)
            reason = "PROVIDER_EXACT"

            # 3. Apply Asymmetric Structural Guard if PASL is available
            # INVARIANT: NEVER WIDEN PROVIDER SL.
            # INVARIANT: NEVER TIGHTEN PROVIDER SL INTO THE SUB-NOISE ZONE.
            # If provider set a valid SL, only tighten if PASL is outside the
            # asset's noise floor (>= min_noise_floor_distance from entry)
            # AND the underlying fractal structure itself was genuinely outside noise.
            if pasl is not None:
                pasl_dist = abs(entry_price - pasl)
                natural_swing_valid = False
                if df_bars is not None and not df_bars.empty:
                    lookback_bars = 8
                    scan_df = df_bars.iloc[-(lookback_bars + 1):-1] if len(df_bars) > (lookback_bars + 1) else df_bars.iloc[:-1]
                    if not scan_df.empty:
                        atr = cls.calculate_atr(df_bars, period=14)
                        dynamic_buf = max(0.50 if "XAU" in sym_upper or "GOLD" in sym_upper else 0.0005, atr * 0.25)
                        if side_upper == "BUY":
                            raw_pasl = float(scan_df["low"].min()) - dynamic_buf
                            if (entry_price - raw_pasl) >= min_noise:
                                natural_swing_valid = True
                        else:
                            raw_pasl = float(scan_df["high"].max()) + dynamic_buf + max(0.0, spread_cushion)
                            if (raw_pasl - entry_price) >= min_noise:
                                natural_swing_valid = True

                if pasl_dist >= min_noise and natural_swing_valid:
                    if side_upper == "BUY":
                        if candidate_sl < pasl < entry_price:
                            candidate_sl = pasl
                            reason = "STRUCTURAL_SHIELD_TIGHTENED"
                    else:
                        if entry_price < pasl < candidate_sl:
                            candidate_sl = pasl
                            reason = "STRUCTURAL_SHIELD_TIGHTENED"
                else:
                    logger.debug(
                        f"🛡️ [PASL Noise Floor Guard] Discarded PASL tightening {pasl}: "
                        f"distance {pasl_dist:.5f} is below noise floor {min_noise:.5f} or swing is inside noise. Preserving provider SL {candidate_sl}."
                    )

        # 4. Strict Prop-Firm Risk Clamp
        if side_upper == "BUY":
            hard_floor = round(entry_price - max_allowed_distance, digits)
            if candidate_sl < hard_floor:
                final_sl = hard_floor
                reason = f"{reason}_CLAMPED_MAX_RISK"
            else:
                final_sl = candidate_sl
            # Safety check: SL must be strictly below entry
            if final_sl >= entry_price:
                final_sl = round(entry_price - (max_allowed_distance * 0.5), digits)
        else:
            hard_ceiling = round(entry_price + max_allowed_distance, digits)
            if candidate_sl > hard_ceiling:
                final_sl = hard_ceiling
                reason = f"{reason}_CLAMPED_MAX_RISK"
            else:
                final_sl = candidate_sl
            # Safety check: SL must be strictly above entry
            if final_sl <= entry_price:
                final_sl = round(entry_price + (max_allowed_distance * 0.5), digits)

        return round(final_sl, digits), reason

    @classmethod
    def calculate_m5_trailing_sl(
        cls,
        df: Optional[pd.DataFrame],
        side: str,
        entry_price: float,
        current_sl: float,
        current_price: float,
        symbol: str = "XAUUSD",
        lookback_bars: int = 6,
        spread_cushion: float = 0.0
    ) -> Optional[float]:
        """
        Calculates an institutional M5 market structure trailing stop loss.

        Institutional Principle:
        Instead of trailing an arbitrary fixed number of pips that gets hunted during normal
        pullbacks, trail behind confirmed M5 fractal swing pivots (Higher Lows in uptrends,
        Lower Highs in downtrends).

        Rules:
        - For BUY:
          Scans recent completed M5 bars for the lowest wick of the most recent consolidation base / swing low.
          Places new SL at (swing_low - ATR buffer).
          Must strictly ratchet HIGHER than current_sl + (min_buffer * 0.5) to advance.
          Must be safely below current_price - min_buffer.
        - For SELL:
          Scans recent completed M5 bars for the highest wick of the most recent consolidation base / swing high.
          Places new SL at (swing_high + ATR buffer + spread_cushion).
          Must strictly ratchet LOWER than current_sl - (min_buffer * 0.5) to advance.
          Must be safely above current_price + min_buffer.

        Returns:
            Optional[float]: New trailing stop price if valid ratchet structure exists, else None.
        """
        if df is None or not isinstance(df, pd.DataFrame) or len(df) < 3:
            return None

        side_upper = side.upper()
        sym_upper = symbol.upper()
        digits = 2 if any(k in sym_upper for k in ["XAU", "GOLD", "BTC", "ETH", "SPX", "NDX", "US30", "US2000"]) else 5

        if "XAU" in sym_upper or "GOLD" in sym_upper:
            min_buffer = 0.30
        elif "JPY" in sym_upper:
            min_buffer = 0.05
        elif any(k in sym_upper for k in ["BTC", "ETH"]):
            min_buffer = 15.0
        else:
            min_buffer = 0.0003

        # Exclude currently forming bar
        scan_df = df.iloc[-(lookback_bars + 1):-1] if len(df) > (lookback_bars + 1) else df.iloc[:-1]
        if scan_df.empty:
            scan_df = df

        atr = cls.calculate_atr(df, period=14)
        dynamic_buffer = max(min_buffer, atr * 0.20)

        if side_upper == "BUY":
            swing_low = float(scan_df["low"].min())
            candidate_sl = round(swing_low - dynamic_buffer, digits)

            # Ratchet conditions:
            # 1. Must improve on current_sl by at least half a buffer
            # 2. Must be safely below current spot price
            if candidate_sl > current_sl + (min_buffer * 0.5) and candidate_sl <= (current_price - min_buffer):
                return candidate_sl
            return None
        else:
            swing_high = float(scan_df["high"].max())
            candidate_sl = round(swing_high + dynamic_buffer + max(0.0, spread_cushion), digits)

            # Ratchet conditions:
            # 1. Must improve on current_sl (ratchet downwards) by at least half a buffer
            # 2. Must be safely above current spot price
            if candidate_sl < current_sl - (min_buffer * 0.5) and candidate_sl >= (current_price + min_buffer):
                return candidate_sl
            return None
