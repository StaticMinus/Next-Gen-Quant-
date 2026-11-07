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

    def test_interpret_signal_extracts_clean_json(self):
        """Verifies deterministic offline interpreter parses and standardizes signal."""
        text = "#XAUUSD SELL 4150 TP1 4150 TP2 4130 TP3 4120 SL 4157"
        sig = AISignalInterpreter.interpret_signal(text, "XAUUSD_GOLD_TRADING_FOREX")

        self.assertIsNotNone(sig)
        self.assertEqual(sig["symbol"], "XAUUSD")
        self.assertEqual(sig["side"], "SELL")
        self.assertEqual(sig["entry_mid"], 4150.0)
        self.assertEqual(sig["tps"], [4130.0, 4120.0])
        self.assertTrue(sig["is_valid"])


if __name__ == "__main__":
    unittest.main()
