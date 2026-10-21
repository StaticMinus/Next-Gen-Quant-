"""
Tests for AISignalInterpreter
=============================
Validates semantic signal extraction, model cascade fallback, and quirk discovery.
"""

import unittest
from unittest.mock import patch, MagicMock
from src.integrations.ai_signal_interpreter import AISignalInterpreter


class TestAISignalInterpreter(unittest.TestCase):
    def test_prefilter_ignores_non_trading_text(self):
        """Verifies text without action and asset candidates returns None immediately without network call."""
        text = "Hello team, tomorrow we will have a meeting at 10 AM regarding our marketing budget."
        sig = AISignalInterpreter.interpret_signal(text, "any_channel")
        self.assertIsNone(sig)

    @patch("src.integrations.ai_signal_interpreter.requests.post")
    def test_interpret_signal_extracts_clean_json(self, mock_post):
        """Verifies model output is parsed, standardized, and quirk recorded."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"symbol": "XAUUSD", "side": "SELL", "entry_mid": 4150.0, "sl": 4157.0, "tps": [4130.0, 4120.0], "quirk_detected": "tp1_at_entry"}\n```'
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        text = "#XAUUSD SELL 4150 TP1 4150 TP2 4130 TP3 4120 SL 4157"
        with patch.object(AISignalInterpreter, "is_available", return_value=True):
            sig = AISignalInterpreter.interpret_signal(text, "XAUUSD_GOLD_TRADING_FOREX")

        self.assertTrue(mock_post.called)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["symbol"], "XAUUSD")
        self.assertEqual(sig["side"], "SELL")
        self.assertEqual(sig["entry_mid"], 4150.0)
        self.assertEqual(sig["tps"], [4130.0, 4120.0])
        self.assertTrue(sig["is_valid"])


if __name__ == "__main__":
    unittest.main()
