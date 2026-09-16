"""
tests/test_max_concurrency_lock.py
==================================
Validates that:
1. place_market_order hard-blocks when account has >= 2 active positions.
2. place_market_order fails closed (blocks order) when broker telemetry is unverified.
3. place_market_order blocks duplicate trades for an already-held asset.
4. place_market_order rejects invalid ETF pricing (< 1000) for Spot Gold.
5. AutonomousExecutionEngine aborts cycle cleanly without placing trades on telemetry offline.
"""

import unittest
from unittest.mock import MagicMock, patch

from src.integrations.ctrader_mcp_client import CTraderMCPClient, RiskViolationError
from src.integrations.autonomous_executor import AutonomousExecutionEngine, MAX_CONCURRENT_POSITIONS
from src.integrations.risk_guardian import guardian


class TestMaxConcurrencyLock(unittest.TestCase):
    def setUp(self):
        self.client = CTraderMCPClient()
        self.client.session_id = "mock_session_123"
        self.client._symbols_cache = {"XAUUSD": 41, "NDX100": 112, "SPX500": 113}

    @patch.object(CTraderMCPClient, "get_positions_strict")
    def test_place_market_order_blocked_when_two_positions_open(self, mock_get_pos):
        """Must raise RiskViolationError when 2 positions already exist."""
        mock_get_pos.return_value = [
            {"positionId": 101, "symbolId": 41, "symbolName": "XAUUSD"},
            {"positionId": 102, "symbolId": 112, "symbolName": "NDX100"},
        ]
        with self.assertRaises(RiskViolationError) as ctx:
            self.client.place_market_order("SPX500", "BUY", 0.10)
        self.assertIn("CONCURRENCY VIOLATION", str(ctx.exception))
        self.assertIn("2/2 active positions", str(ctx.exception))

    @patch.object(CTraderMCPClient, "get_positions_strict")
    def test_place_market_order_blocked_when_telemetry_unverified(self, mock_get_pos):
        """Must fail closed (raise RiskViolationError) if broker telemetry returns None."""
        mock_get_pos.return_value = None  # Simulated connection or SSE error
        with self.assertRaises(RiskViolationError) as ctx:
            self.client.place_market_order("SPX500", "BUY", 0.10)
        self.assertIn("Cannot verify broker positions", str(ctx.exception))

    @patch.object(CTraderMCPClient, "get_positions_strict")
    def test_place_market_order_blocked_on_duplicate_asset(self, mock_get_pos):
        """Must raise RiskViolationError if attempting to buy an already-held asset."""
        mock_get_pos.return_value = [
            {"positionId": 101, "symbolId": 41, "symbolName": "XAUUSD"}
        ]
        with self.assertRaises(RiskViolationError) as ctx:
            self.client.place_market_order("XAUUSD", "BUY", 0.01)
        self.assertIn("DUPLICATE ASSET VIOLATION", str(ctx.exception))

    @patch.object(CTraderMCPClient, "get_positions_strict")
    def test_place_market_order_rejects_etf_price_for_gold(self, mock_get_pos):
        """Must reject ETF price (< 1000) for Spot Gold SL/TP."""
        mock_get_pos.return_value = []
        with self.assertRaises(RiskViolationError) as ctx:
            self.client.place_market_order("XAUUSD", "BUY", 0.01, stop_loss_price=382.33)
        self.assertIn("INVALID PRICE FOR XAUUSD", str(ctx.exception))

    @patch.object(CTraderMCPClient, "get_positions_strict")
    @patch.object(CTraderMCPClient, "get_balance")
    def test_autonomous_executor_fails_closed_when_telemetry_offline(self, mock_bal, mock_get_pos):
        """Autonomous execution engine must abort without placing trades if telemetry is None."""
        mock_bal.return_value = {"balance": 6000.0, "equity": 6000.0}
        mock_get_pos.return_value = None  # Offline telemetry

        engine = AutonomousExecutionEngine(ctrader_client=self.client)
        trades = engine.run_cycle(dry_run=True)
        self.assertEqual(len(trades), 0, "Engine must execute ZERO trades when telemetry is unverified")

    @patch.object(CTraderMCPClient, "get_positions_strict")
    @patch.object(CTraderMCPClient, "get_balance")
    def test_autonomous_executor_strictly_caps_at_two(self, mock_bal, mock_get_pos):
        """Autonomous execution engine must never trade if active_count >= 2."""
        mock_bal.return_value = {"balance": 6000.0, "equity": 6000.0}
        mock_get_pos.return_value = [
            {"positionId": 101, "symbolId": 41},
            {"positionId": 102, "symbolId": 112},
        ]

        engine = AutonomousExecutionEngine(ctrader_client=self.client)
        trades = engine.run_cycle(dry_run=True)
        self.assertEqual(len(trades), 0, "Engine must execute ZERO trades when 2 positions already exist")


if __name__ == "__main__":
    unittest.main()
