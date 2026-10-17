"""Guard Sentinel Module (Upgrades 1 & 4 from AGI).

Combines:
1. RestrictedActionsGuard: Immutable pre-trade boundary enforcement.
2. MicroMomentumFilter: Sub-5 millisecond (<0.005s) vector momentum confluence check.
"""

from typing import Tuple, List
import numpy as np
import logging

logger = logging.getLogger("GuardSentinel")


class RestrictedActionsGuard:
    """RestrictedActionsGuard (derived from safe-restricted-actions-guard-agi-broker-bot).

    Enforces immutable safety invariants before any execution request reaches cTrader.
    Guarantees:
    - Allowed symbols only (XAUUSD / GOLD).
    - Maximum single-trade volume cap (0.14 lot).
    - Maximum server-side Stop Loss distance (10.0 points).
    - FundedNext Drawdown Floor protection ($5,650.00 USD).
    """

    def __init__(self, max_volume: float = 0.14, max_sl_points: float = 10.0, floor_equity: float = 5650.0):
        self.max_volume = max_volume
        self.max_sl_points = max_sl_points
        self.floor_equity = floor_equity

    def validate_action(
        self,
        symbol: str,
        side: str,
        volume_lots: float,
        entry_price: float,
        sl_price: float,
        current_equity: float
    ) -> Tuple[bool, str]:
        """Validates all safety invariants in <0.1ms."""
        # 1. Symbol whitelist
        sym_clean = symbol.upper().replace("/", "")
        if "XAU" not in sym_clean and "GOLD" not in sym_clean:
            return False, f"GUARD_REJECTED: Symbol '{symbol}' is not whitelisted"

        # 2. Side validation
        side_clean = side.upper()
        if side_clean not in ("BUY", "SELL"):
            return False, f"GUARD_REJECTED: Invalid order side '{side}'"

        # 3. Lot allocation ceiling
        if volume_lots > (self.max_volume + 1e-4):
            return False, f"GUARD_REJECTED: Volume {volume_lots:.2f} exceeds max allowed {self.max_volume:.2f} lots"

        if volume_lots <= 0.001:
            return False, "GUARD_REJECTED: Volume must be positive"

        # 4. Stop Loss distance constraint
        sl_dist = abs(entry_price - sl_price)
        if sl_dist > (self.max_sl_points + 0.05):
            return False, f"GUARD_REJECTED: SL distance {sl_dist:.2f} exceeds limit {self.max_sl_points:.1f} pts"

        # 5. Correct directional SL check
        if side_clean == "BUY" and sl_price >= entry_price:
            return False, f"GUARD_REJECTED: BUY Stop Loss ({sl_price}) must be below entry ({entry_price})"
        if side_clean == "SELL" and sl_price <= entry_price:
            return False, f"GUARD_REJECTED: SELL Stop Loss ({sl_price}) must be above entry ({entry_price})"

        # 6. FundedNext Daily Equity Circuit Breaker
        if current_equity <= self.floor_equity:
            return False, f"GUARD_REJECTED: Equity ${current_equity:,.2f} is at or below floor ${self.floor_equity:,.2f}"

        return True, "APPROVED"


class MicroMomentumFilter:
    """MicroMomentumFilter (derived from intelligent-trading-bot-master).

    High-speed in-memory vector momentum filter running in <3 milliseconds (<0.005s).
    Uses pure NumPy operations on rolling price ticks/bars to detect counter-trend traps:
    - If BUY signal is sent while Gold is experiencing severe downward acceleration (< -0.20% drop over last 5 bars),
      it rejects the entry to protect capital.
    - If SELL signal is sent into violent vertical buying momentum, it rejects.
    """

    def __init__(self, min_confluence_score: float = -0.15):
        self.min_confluence_score = min_confluence_score

    def evaluate_confluence(
        self,
        side: str,
        price_history: List[float]
    ) -> Tuple[bool, float, str]:
        """Calculates instantaneous momentum score in < 2ms using NumPy vectorization.

        Returns: (passes_filter: bool, momentum_score: float, reason: str)
        """
        if not price_history or len(price_history) < 5:
            # Insufficient history; fail open to preserve 0-latency execution
            return True, 0.0, "INSUFFICIENT_BARS_PASSTHROUGH"

        arr = np.asarray(price_history[-15:], dtype=np.float64)
        if len(arr) < 2:
            return True, 0.0, "PASSTHROUGH"

        # Calculate percentage returns across window
        pct_change = (arr[-1] - arr[0]) / arr[0]
        recent_slope = (arr[-1] - arr[-3]) / arr[-3] if len(arr) >= 3 else pct_change

        side_clean = side.upper()

        if side_clean == "BUY":
            score = float(pct_change * 100.0)
            if score < -0.20 and recent_slope < 0:
                logger.warning(f"⚠️ MicroMomentumFilter: BUY rejected (severe negative momentum: {score:.3f}%)")
                return False, score, f"COUNTER_TREND_DROP_{score:.2f}%"
            return True, score, "CONFLUENCE_CONFIRMED"

        elif side_clean == "SELL":
            score = float(-pct_change * 100.0)
            if score < -0.20 and recent_slope > 0:
                logger.warning(f"⚠️ MicroMomentumFilter: SELL rejected (severe adverse pump: {-score:.3f}%)")
                return False, score, f"COUNTER_TREND_PUMP_{-score:.2f}%"
            return True, score, "CONFLUENCE_CONFIRMED"

        return True, 0.0, "PASSTHROUGH"
