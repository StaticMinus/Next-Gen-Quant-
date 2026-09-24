"""
AgentQuant V2 — 15-Minute Regime Engine
========================================
Analyzes higher-timeframe (15M) market conditions before any trade is evaluated.
Classifies the market into 4 distinct macro regimes:
  1. BULLISH_TREND: EMA20 > EMA50, slope positive -> Long pullbacks only
  2. BEARISH_TREND: EMA20 < EMA50, slope negative -> Short rallies only
  3. RANGE_BOUND: EMAs compressed/flat, low trend strength -> Boundary mean-reversion
  4. VOLATILITY_EXPANSION_SHOCK: Extreme ATR expansion / waterfall dump -> NO TRADE (100% Cash)
"""

from enum import Enum
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


class MarketRegime(str, Enum):
    BULLISH_TREND = "BULLISH_TREND"
    BEARISH_TREND = "BEARISH_TREND"
    RANGE_BOUND = "RANGE_BOUND"
    VOLATILITY_EXPANSION_SHOCK = "VOLATILITY_EXPANSION_SHOCK"


class RegimeEngine:
    def __init__(self, ema_fast_period: int = 20, ema_slow_period: int = 50,
                 atr_period: int = 14, shock_percentile_threshold: float = 85.0):
        self.ema_fast_period = ema_fast_period
        self.ema_slow_period = ema_slow_period
        self.atr_period = atr_period
        self.shock_percentile_threshold = shock_percentile_threshold

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Computes technical regime features on 15M bars."""
        d = df.copy()
        col_map = {str(c).lower(): c for c in d.columns}
        close = d[col_map.get("close", "close")]
        high = d[col_map.get("high", "high")]
        low = d[col_map.get("low", "low")]

        # Exponential Moving Averages
        d["ema_fast"] = close.ewm(span=self.ema_fast_period, adjust=False).mean()
        d["ema_slow"] = close.ewm(span=self.ema_slow_period, adjust=False).mean()

        # EMA Slopes (over 3 bars)
        d["ema_fast_slope"] = (d["ema_fast"] - d["ema_fast"].shift(3)) / d["ema_fast"].shift(3)
        d["ema_slow_slope"] = (d["ema_slow"] - d["ema_slow"].shift(3)) / d["ema_slow"].shift(3)

        # True Range and ATR
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        d["atr"] = tr.rolling(window=self.atr_period, min_periods=self.atr_period).mean()

        # ATR Rolling Percentile (last 60 bars ~ 15 hours)
        rolling_window = min(60, len(d))
        d["atr_pctile"] = d["atr"].rolling(window=rolling_window, min_periods=10).apply(
            lambda x: (x.iloc[-1] > x).mean() * 100.0 if len(x) > 0 else 50.0, raw=False
        )

        # 3-bar cumulative momentum
        d["cum_ret_3bar"] = (close - close.shift(3)) / close.shift(3)
        return d

    def classify(self, df_15m: pd.DataFrame) -> Dict[str, Any]:
        """
        Classifies current market regime from 15-minute bars.
        Returns regime name, permitted trade direction, ATR, and diagnostic metrics.
        """
        if df_15m is None or len(df_15m) < self.ema_slow_period:
            return {
                "regime": MarketRegime.RANGE_BOUND.value,
                "allowed_side": "NONE",
                "reason": "INSUFFICIENT_BARS",
                "atr": 0.0,
                "atr_percentile": 50.0,
                "ema_fast": 0.0,
                "ema_slow": 0.0,
            }

        ind = self.calculate_indicators(df_15m)
        curr = ind.iloc[-1]

        close = float(curr["close"])
        ema_fast = float(curr["ema_fast"])
        ema_slow = float(curr["ema_slow"])
        fast_slope = float(curr["ema_fast_slope"])
        atr = float(curr["atr"])
        atr_pctile = float(curr["atr_pctile"]) if not np.isnan(curr["atr_pctile"]) else 50.0
        cum_3bar = float(curr["cum_ret_3bar"]) if not np.isnan(curr["cum_ret_3bar"]) else 0.0

        # Check for Volatility Expansion / Shock (e.g. news crash, waterfall dump, pump)
        # Condition: 3-bar dump > 1.5% OR (3-bar momentum > 1.0% with high ATR) OR extreme ATR percentile
        is_waterfall_dump = cum_3bar < -0.015 or (cum_3bar < -0.010 and atr_pctile >= self.shock_percentile_threshold)
        is_shock_expansion = atr_pctile >= 92.0 or abs(cum_3bar) >= 0.020

        if is_waterfall_dump or is_shock_expansion:
            return {
                "regime": MarketRegime.VOLATILITY_EXPANSION_SHOCK.value,
                "allowed_side": "NONE",
                "reason": f"Extreme volatility shock: ATR at {atr_pctile:.1f}%ile, 3-bar move: {cum_3bar*100:.2f}%",
                "atr": atr,
                "atr_percentile": atr_pctile,
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
            }

        # Check for Strong Trends
        ema_spread_pct = abs(ema_fast - ema_slow) / close

        # Bullish Trend: Fast EMA above Slow EMA, Price above Slow EMA, positive slope
        if ema_fast > ema_slow and close > ema_slow and fast_slope > 0.0005:
            return {
                "regime": MarketRegime.BULLISH_TREND.value,
                "allowed_side": "BUY_ONLY",
                "reason": f"Bullish 15M trend: EMA20 > EMA50 (+{fast_slope*100:.3f}% slope)",
                "atr": atr,
                "atr_percentile": atr_pctile,
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
            }

        # Bearish Trend: Fast EMA below Slow EMA, Price below Slow EMA, negative slope
        if ema_fast < ema_slow and close < ema_slow and fast_slope < -0.0005:
            return {
                "regime": MarketRegime.BEARISH_TREND.value,
                "allowed_side": "SELL_ONLY",
                "reason": f"Bearish 15M trend: EMA20 < EMA50 ({fast_slope*100:.3f}% slope)",
                "atr": atr,
                "atr_percentile": atr_pctile,
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
            }

        # Range-bound Market (Chop / Compression)
        return {
            "regime": MarketRegime.RANGE_BOUND.value,
            "allowed_side": "BOTH",
            "reason": f"Consolidation range: EMAs compressed ({ema_spread_pct*100:.2f}% spread)",
            "atr": atr,
            "atr_percentile": atr_pctile,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
        }
