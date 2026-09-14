"""
Scalper Strategy — Fast-execution mean-reversion & momentum scalp
================================================================

Designed for small-account growth ($50 - $1000) and active trading.
Uses short lookback windows (3-10 days), tight standard deviation bands (0.8 - 1.5 sigma),
fast exit at the moving-average mean, stop-loss protection, and max holding periods.
"""

import logging
from typing import Any, Dict

import numpy as np
import pandas as pd

from src.strategies.base import Strategy, _get_close

logger = logging.getLogger(__name__)


class ScalperStrategy(Strategy):
    """
    High-frequency daily scalper strategy.

    Parameters:
        window (int): Rolling window for moving average & volatility (default: 5).
        num_std (float): Band width in standard deviations (default: 1.0).
        exit_at_mean (bool): Take profit when price returns to mean (default: True).
        allow_short (bool): Generate short signals on upper band touches (default: False).
        stop_loss_pct (float): Maximum loss allowed per trade before exiting (default: 0.03 = 3%).
        max_hold_bars (int): Maximum bars to hold a trade before timeout exit (default: 5).
    """

    def generate_signal(self, df: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
        close = _get_close(df)
        window = int(params.get("window", 5))
        num_std = float(params.get("num_std", 1.0))
        exit_at_mean = bool(params.get("exit_at_mean", True))
        allow_short = bool(params.get("allow_short", False))
        stop_loss_pct = float(params.get("stop_loss_pct", 0.03))
        short_stop_loss_pct = float(params.get("short_stop_loss_pct", stop_loss_pct))
        max_hold_bars = int(params.get("max_hold_bars", 5))
        trend_filter = bool(params.get("trend_filter", False))
        trend_window = int(params.get("trend_window", 50))

        # Rolling statistics
        mid = close.rolling(window, min_periods=window).mean()
        std = close.rolling(window, min_periods=window).std()
        upper = mid + num_std * std
        lower = mid - num_std * std

        trend_ma = close.rolling(trend_window, min_periods=trend_window).mean() if trend_filter else pd.Series(np.nan, index=close.index)

        n = len(close)
        close_arr = close.to_numpy(dtype=float)
        mid_arr = mid.to_numpy(dtype=float)
        upper_arr = upper.to_numpy(dtype=float)
        lower_arr = lower.to_numpy(dtype=float)
        trend_arr = trend_ma.to_numpy(dtype=float)

        sig_arr = np.zeros(n, dtype=int)
        current_pos = 0
        bars_held = 0
        entry_price = 0.0

        for i in range(n):
            c = close_arr[i]
            m = mid_arr[i]
            u = upper_arr[i]
            lower_val = lower_arr[i]
            t = trend_arr[i]

            if np.isnan(m) or np.isnan(lower_val) or np.isnan(u):
                sig_arr[i] = 0
                continue

            # Position management / exits
            if current_pos == 1:
                bars_held += 1
                # Take profit condition
                tp = (c >= m) if exit_at_mean else (c >= u)
                # Stop loss condition
                sl = (stop_loss_pct > 0 and c <= entry_price * (1.0 - stop_loss_pct))
                # Time limit condition
                timeout = (max_hold_bars > 0 and bars_held >= max_hold_bars)

                if tp or sl or timeout:
                    current_pos = 0
                    bars_held = 0
                    entry_price = 0.0

            elif current_pos == -1:
                bars_held += 1
                # Take profit condition
                tp = (c <= m) if exit_at_mean else (c <= lower_val)
                # Stop loss condition (uses dedicated short_stop_loss_pct if provided)
                sl = (short_stop_loss_pct > 0 and c >= entry_price * (1.0 + short_stop_loss_pct))
                # Time limit condition
                timeout = (max_hold_bars > 0 and bars_held >= max_hold_bars)

                if tp or sl or timeout:
                    current_pos = 0
                    bars_held = 0
                    entry_price = 0.0

            # Entry conditions (only if currently flat)
            if current_pos == 0:
                can_long = (not trend_filter) or np.isnan(t) or (c >= t)
                can_short = allow_short and ((not trend_filter) or np.isnan(t) or (c <= t))

                if c < lower_val and can_long:
                    current_pos = 1
                    bars_held = 0
                    entry_price = c
                elif c > u and can_short:
                    current_pos = -1
                    bars_held = 0
                    entry_price = c

            sig_arr[i] = current_pos

        return pd.Series(sig_arr, index=df.index, dtype=int)

    @property
    def param_schema(self) -> Dict[str, Any]:
        return {
            "window": {"type": "int", "min": 2, "max": 30},
            "num_std": {"type": "float", "min": 0.5, "max": 3.0},
            "exit_at_mean": {"type": "bool"},
            "allow_short": {"type": "bool"},
            "stop_loss_pct": {"type": "float", "min": 0.005, "max": 0.15},
            "max_hold_bars": {"type": "int", "min": 1, "max": 30},
        }
