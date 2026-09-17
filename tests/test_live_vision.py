"""
tests/test_live_vision.py
=========================
Unit & regression tests for Live Account & Position Vision (Context-Aware Intelligence):
  1. cTrader position enrichment logic (symbol mapping, spot quotes, PnL, TP/SL distances).
  2. AI Coach system prompt dynamic telemetry injection.
  3. Telegram Bot /trades rendering with enriched telemetry.
  4. Interactive 1-tap trade action buttons generation.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.integrations.ctrader_mcp_client import CTraderMCPClient
from src.integrations.telegram_ai_coach import build_system_prompt
from src.integrations.telegram_bot_service import (
    _CACHE,
    get_trades_markup,
    render_trades_text,
)


class TestLiveVision(unittest.TestCase):

    def setUp(self):
        self.mock_enriched_positions = [
            {
                "position_id": 3069593,
                "symbol_id": 41,
                "symbol_name": "XAUUSD",
                "display_name": "Spot Gold",
                "trade_side": "BUY",
                "volume_raw": 100,
                "lots": 0.01,
                "entry_price": 4334.99,
                "current_price": 4328.50,
                "take_profit": 4443.38,
                "stop_loss": 4204.95,
                "floating_pnl": -6.49,
                "floating_pnl_pct": -0.15,
                "dist_to_tp_usd": 114.88,
                "dist_to_tp_pct": 2.65,
                "dist_to_sl_usd": 123.55,
                "dist_to_sl_pct": 2.85,
            }
        ]

    def test_build_system_prompt_enriched_telemetry(self):
        """Verify build_system_prompt dynamically injects exact enriched position data and risk buffers."""
        telemetry = {
            "equity": 5993.51,
            "capital": 6000.0,
            "free_margin": 5704.50,
            "cycle_profit": 0.0,
            "enriched_positions": self.mock_enriched_positions,
            "live_p2p_rate": 1518.40,
        }
        prompt = build_system_prompt(telemetry)

        # Assertions
        self.assertIn("XAUUSD #3069593", prompt)
        self.assertIn("Entry $4,334.99", prompt)
        self.assertIn("Spot $4,328.50", prompt)
        self.assertIn("PnL $-6.49", prompt)
        self.assertIn("TP $4,443.38", prompt)
        self.assertIn("SL $4,204.95", prompt)
        self.assertIn("Remaining Daily Loss Cushion: $173.51", prompt)

    def test_render_trades_text_enriched(self):
        """Verify render_trades_text formats the clear, friendly position card for Gold."""
        with patch("src.integrations.telegram_bot_service.ctrader_client.get_enriched_positions", return_value=self.mock_enriched_positions):
            _CACHE["enriched_positions"] = self.mock_enriched_positions
            _CACHE["capital"] = 6000.0
            _CACHE["equity"] = 5993.51

            output = render_trades_text()

        self.assertIn("Spot Gold (XAUUSD)", output)
        self.assertIn("#3069593", output)
        self.assertIn("0.01 lot", output)
        self.assertIn("$4,334.99", output)
        self.assertIn("$4,328.50", output)
        self.assertIn("$4,443.38", output)
        self.assertIn("$4,204.95", output)
        self.assertIn("Total Floating:", output)

    def test_get_trades_markup_safety_no_execution_buttons(self):
        """Verify get_trades_markup strictly removes all trade execution buttons for user safety."""
        _CACHE["enriched_positions"] = self.mock_enriched_positions
        _CACHE["qqq_dist"] = -0.14
        _CACHE["qqq_signal"] = "🚨 <b>DIP TRIGGERED</b>"

        markup = get_trades_markup()
        self.assertIn("inline_keyboard", markup)

        callbacks = [btn["callback_data"] for row in markup["inline_keyboard"] for btn in row]

        # Verify NO close position callback or trade entry callback exists
        self.assertNotIn("cmd_close_pos_3069593", callbacks)
        self.assertNotIn("cmd_exec_setup_qqq", callbacks)
        # Verify only safe navigation callbacks exist
        self.assertIn("cmd_trades", callbacks)
        self.assertIn("cmd_overview", callbacks)

    def test_ctrader_get_enriched_positions_mocked(self):
        """Verify CTraderMCPClient.get_enriched_positions calculates mathematical fields correctly."""
        client = CTraderMCPClient()
        client.get_positions = MagicMock(return_value=[
            {
                "positionId": 999111,
                "symbolId": 112,
                "tradeSide": "BUY",
                "volume": 10,  # 0.10 lots on index
                "entryPrice": 29000.0,
                "stopLoss": 28130.0,
                "takeProfit": 29435.0,
            }
        ])
        client.get_symbol_map = MagicMock(return_value={"NDX100": 112})
        client.get_spot_price = MagicMock(return_value={
            "symbol": "NDX100",
            "symbolId": 112,
            "bid": 29050.0,
            "ask": 29052.0
        })

        enriched = client.get_enriched_positions()
        self.assertEqual(len(enriched), 1)
        pos = enriched[0]

        self.assertEqual(pos["symbol_name"], "NDX100")
        self.assertEqual(pos["display_name"], "Nasdaq 100 Index")
        self.assertEqual(pos["lots"], 0.10)
        self.assertEqual(pos["current_price"], 29050.0)
        # 29050 - 29000 = +50 points * 0.10 lots * 1 contract = +$5.00 USD
        self.assertAlmostEqual(pos["floating_pnl"], 5.0, places=2)
        # Dist to TP: 29435 - 29050 = 385 points * 0.10 = $38.50 USD
        self.assertAlmostEqual(pos["dist_to_tp_usd"], 38.50, places=2)
        # Dist to SL: 29050 - 28130 = 920 points * 0.10 = $92.00 USD
        self.assertAlmostEqual(pos["dist_to_sl_usd"], 92.00, places=2)


if __name__ == "__main__":
    unittest.main()
