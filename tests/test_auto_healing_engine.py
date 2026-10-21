"""
Tests for AutoHealingEngine
===========================
Validates post-execution self-healing strategies:
1. Mismatched position ID resolution from live broker positions.
2. Slipped TP auto-ratcheting when price surpasses target before amendment (HTTP 400).
3. Emergency isolated Stop Loss anchoring.
"""

import unittest
from unittest.mock import MagicMock
from src.integrations.auto_healing_engine import AutoHealingEngine


class TestAutoHealingEngine(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_client.get_symbol_digits.return_value = 2
        self.mock_client.get_symbol_map.return_value = {"XAUUSD": 41}

    def test_heal_mismatched_position_id(self):
        """Verifies true positionId is resolved from active positions list when wrong ID passed."""
        # Active position list has true positionId 999001
        self.mock_client.get_positions_strict.return_value = [
            {"positionId": 999001, "symbolId": 41, "tradeSide": "SELL", "comment": "Sig_Test_1"}
        ]
        self.mock_client.get_spot_price.return_value = {"bid": 4120.0, "ask": 4120.35}
        self.mock_client.call_tool.return_value = {"result": {"content": [{"text": '{"positionId": 999001}'}]}}
        self.mock_client._parse_content_json.return_value = {"positionId": 999001}

        # Suppose caller passed orderId 888000 instead of positionId
        res = AutoHealingEngine.diagnose_and_heal_amendment(
            ctrader_client=self.mock_client,
            symbol="XAUUSD",
            side="SELL",
            target_pos_id=888000,
            intended_sl=4135.0,
            intended_tp=4110.0,
            comment="Sig_Test_1",
            error_payload="Position not found"
        )

        self.assertTrue(res["healed"])
        self.assertEqual(res["position_id"], 999001)
        # Check call_tool was called with true positionId 999001
        called_args = self.mock_client.call_tool.call_args[0][1]
        self.assertEqual(called_args["positionId"], 999001)

    def test_heal_slipped_tp_ratchet_sell(self):
        """Verifies that if price already dropped past SELL TP, TP is advanced and SL ratcheted."""
        self.mock_client.get_positions_strict.return_value = [
            {"positionId": 999002, "symbolId": 41, "tradeSide": "SELL", "comment": "Sig_Test_2"}
        ]
        # Current Ask has dropped to 4115.0, but intended TP was 4125.0 (TP >= Ask -> HTTP 400)
        self.mock_client.get_spot_price.return_value = {"bid": 4114.7, "ask": 4115.0}
        self.mock_client.call_tool.return_value = {"result": {"content": [{"text": '{"positionId": 999002}'}]}}
        self.mock_client._parse_content_json.return_value = {"positionId": 999002}

        res = AutoHealingEngine.diagnose_and_heal_amendment(
            ctrader_client=self.mock_client,
            symbol="XAUUSD",
            side="SELL",
            target_pos_id=999002,
            intended_sl=4145.0,
            intended_tp=4125.0,  # Invalid: 4125.0 >= 4115.0
            comment="Sig_Test_2",
            error_payload="New TP for SELL position should be <= current ASK price"
        )

        self.assertTrue(res["healed"])
        self.assertEqual(res["strategy"], "SLIPPED_TP_RATCHET")
        # New TP must be strictly below current ask (4115.0)
        self.assertLess(res["take_profit"], 4115.0)

    def test_emergency_isolated_sl(self):
        """Verifies emergency isolated SL anchoring if joint amend fails."""
        self.mock_client.get_positions_strict.return_value = [
            {"positionId": 999003, "symbolId": 41, "tradeSide": "BUY", "comment": "Sig_Test_3"}
        ]
        self.mock_client.get_spot_price.return_value = {"bid": 4120.0, "ask": 4120.35}

        # First amend call (joint SL/TP) fails
        # Second amend call (SL only) succeeds
        self.mock_client.call_tool.side_effect = [
            {"isError": True},
            {"result": {"content": [{"text": '{"positionId": 999003, "stopLoss": 4110.0}'}]}}
        ]
        self.mock_client._parse_content_json.side_effect = [
            None,
            {"positionId": 999003, "stopLoss": 4110.0}
        ]

        res = AutoHealingEngine.diagnose_and_heal_amendment(
            ctrader_client=self.mock_client,
            symbol="XAUUSD",
            side="BUY",
            target_pos_id=999003,
            intended_sl=4110.0,
            intended_tp=4140.0,
            comment="Sig_Test_3"
        )

        self.assertTrue(res["healed"])
        self.assertEqual(res["strategy"], "EMERGENCY_ISOLATED_SL")
        self.assertEqual(res["stop_loss"], 4110.0)


if __name__ == "__main__":
    unittest.main()
