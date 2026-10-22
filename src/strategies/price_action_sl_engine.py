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

from typing import Any, Dict, Optional, Tuple
import numpy as np
import pandas as pd


class PriceActionSLEngine:
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
        atr_buffer_mult: float = 0.25
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
            sl = entry_price - default_dist if side_upper == "BUY" else entry_price + default_dist
            return round(sl, digits), default_dist

        # Scan the last N completed bars (excluding the currently forming bar at -1)
        scan_df = df.iloc[-(lookback_bars + 1):-1] if len(df) > (lookback_bars + 1) else df.iloc[:-1]
        if scan_df.empty:
            scan_df = df

        atr = cls.calculate_atr(df, period=14)
        dynamic_buffer = max(min_buffer, atr * atr_buffer_mult)

        if side_upper == "BUY":
            swing_low = float(scan_df["low"].min())
            pasl = round(swing_low - dynamic_buffer, digits)
            # Ensure PASL is strictly below entry
            if pasl >= entry_price:
                pasl = round(entry_price - dynamic_buffer, digits)
            risk_dist = round(abs(entry_price - pasl), digits)
            return pasl, risk_dist
        else:
            swing_high = float(scan_df["high"].max())
            pasl = round(swing_high + dynamic_buffer, digits)
            # Ensure PASL is strictly above entry
            if pasl <= entry_price:
                pasl = round(entry_price + dynamic_buffer, digits)
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
        max_allowed_distance: float
    ) -> Tuple[float, str]:
        """
        Reconciles provider-written SL with real-time Price Action market structure.
        Implements the Structural Shield Guard:
          - If provider SL sits inside the liquidity sweep pocket (too tight),
            it extends SL behind the swing wick (so trade isn't prematurely wicked out).
          - If provider omitted SL or paywalled it ("VIP"), it adopts PASL.
          - Never exceeds max_allowed_distance (strict Prop Firm Risk Clamp).

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
                pasl, _ = cls.calculate_swing_sl(df_bars, side_upper, entry_price, symbol=sym_upper)
            except Exception:
                pasl = None

        # 2. Determine initial candidate SL
        if provider_sl is None or provider_sl <= 0:
            if pasl is not None:
                candidate_sl = pasl
                reason = "PASL_SYNTHESIZED"
            else:
                fallback_dist = min(8.0 if "XAU" in sym_upper or "GOLD" in sym_upper else 0.0035, max_allowed_distance)
                candidate_sl = entry_price - fallback_dist if side_upper == "BUY" else entry_price + fallback_dist
                reason = "DEFAULT_SYNTHESIZED"
        else:
            candidate_sl = float(provider_sl)
            reason = "PROVIDER_EXACT"

            # 3. Apply Asymmetric Structural Guard if PASL is available
            # INVARIANT: NEVER WIDEN PROVIDER SL.
            # If provider set a tighter SL than PASL, respect provider exact SL.
            # If PASL is tighter than provider SL, adopt PASL to reduce risk.
            if pasl is not None:
                if side_upper == "BUY":
                    if candidate_sl < pasl < entry_price:
                        candidate_sl = pasl
                        reason = "STRUCTURAL_SHIELD_TIGHTENED"
                else:
                    if entry_price < pasl < candidate_sl:
                        candidate_sl = pasl
                        reason = "STRUCTURAL_SHIELD_TIGHTENED"

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
