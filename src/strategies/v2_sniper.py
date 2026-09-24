"""
AgentQuant V2 — Master Regime + Structure Sniper Strategy
=========================================================
Unifies:
  1. 15M Regime Engine (The Boss: Bullish / Bearish / Range / Shock)
  2. 5M Structure Engine (The Setup: Sweep -> Displacement -> Retest)
  3. 1M Execution Trigger (The Entry: Limit order at retest with sub-pip precision)
  4. Structural SL + Dynamic Lot Sizing (Fixed $ Risk / Distance)
  5. Asymmetric 2.0R Take Profit Target
"""

import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from src.strategies.base import Strategy, _get_close
from src.strategies.regime_engine import RegimeEngine, MarketRegime
from src.strategies.structure_engine import StructureEngine, SetupContext, StructureState

logger = logging.getLogger("v2_sniper")


class V2SniperStrategy(Strategy):
    """
    AgentQuant V2 Multi-Timeframe Regime + Market Structure Strategy.
    """

    def __init__(self, target_r_multiple: float = 2.0, max_risk_usd: float = 15.0):
        self.regime_engine = RegimeEngine()
        self.structure_engine = StructureEngine(target_r_multiple=target_r_multiple)
        self.target_r_multiple = target_r_multiple
        self.max_risk_usd = max_risk_usd

    @property
    def param_schema(self) -> Dict[str, Any]:
        return {
            "target_r_multiple": {"type": "float", "min": 1.5, "max": 3.5},
            "max_risk_usd": {"type": "float", "min": 5.0, "max": 50.0},
        }

    def generate_signal(self, df: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
        """
        Standard single-timeframe fallback (conforms to Strategy interface).
        For full multi-timeframe power, use evaluate_multitimeframe().
        """
        setup = self.structure_engine.evaluate_setup(df, allowed_side="BOTH")
        sig = pd.Series(0, index=df.index)
        if setup:
            sig.iloc[-1] = 1 if setup.side == "BUY" else -1
        return sig

    def evaluate_multitimeframe(self, df_15m: pd.DataFrame, df_5m: pd.DataFrame,
                                df_1m: Optional[pd.DataFrame] = None,
                                symbol: str = "BTCUSD",
                                max_risk_usd: Optional[float] = None) -> Dict[str, Any]:
        """
        Full AgentQuant V2 evaluation pipeline:
          Step 1: Check 15M Regime.
          Step 2: Check 5M Market Structure (Sweep -> Displacement -> Retest).
          Step 3: Calculate Structural SL & Dynamic Lot Size.
          Step 4: Generate Execution Payload.
        """
        risk_budget = max_risk_usd if max_risk_usd is not None else self.max_risk_usd

        # ── STEP 1: 15M REGIME FILTER (THE BOSS) ──
        regime_info = self.regime_engine.classify(df_15m)
        regime = regime_info["regime"]
        allowed_side = regime_info["allowed_side"]

        if regime == MarketRegime.VOLATILITY_EXPANSION_SHOCK.value or allowed_side == "NONE":
            return {
                "action": "NO_TRADE",
                "reason": f"REGIME_FILTER: {regime_info['reason']}",
                "regime": regime_info,
                "setup": None
            }

        # ── STEP 2: 5M MARKET STRUCTURE EVALUATION ──
        setup = self.structure_engine.evaluate_setup(df_5m, allowed_side=allowed_side)
        if not setup:
            return {
                "action": "WAITING",
                "reason": f"No active structure setup matching 15M {allowed_side} regime.",
                "regime": regime_info,
                "setup": None
            }

        # ── STEP 3: STRUCTURAL SL & DYNAMIC SIZING ──
        entry_price = setup.retest_entry_price
        sl_price = setup.structural_sl_price
        tp_price = setup.take_profit_price
        risk_dist = setup.risk_distance

        lots = self.structure_engine.calculate_lot_size(
            entry_price=entry_price,
            sl_price=sl_price,
            risk_usd=risk_budget,
            symbol=symbol
        )

        # ── STEP 4: 1M REAL-TIME TICK CONFIRMATION ──
        curr_price = float(df_1m.iloc[-1]["close"]) if df_1m is not None and len(df_1m) > 0 else float(df_5m.iloc[-1]["close"])
        dist_to_entry_pct = abs(curr_price - entry_price) / entry_price

        # Check if entry is actionable (within 0.35% of retest entry)
        if dist_to_entry_pct > 0.0035:
            return {
                "action": "SETUP_PENDING",
                "reason": f"Setup confirmed, awaiting retest fill (current: ${curr_price:.2f}, target: ${entry_price:.2f})",
                "regime": regime_info,
                "setup": setup,
                "lots": lots
            }

        dollar_reward = round(abs(tp_price - entry_price) * lots, 2)
        dollar_risk = round(abs(entry_price - sl_price) * lots, 2)

        return {
            "action": setup.side,  # "BUY" or "SELL"
            "symbol": symbol,
            "lots": lots,
            "entry_price": entry_price,
            "stop_loss_price": sl_price,
            "take_profit_price": tp_price,
            "risk_distance_usd": round(risk_dist, 2),
            "dollar_risk": dollar_risk,
            "dollar_reward": dollar_reward,
            "r_multiple": self.target_r_multiple,
            "regime": regime_info,
            "setup": setup,
            "status": "READY_TO_SUBMIT"
        }
