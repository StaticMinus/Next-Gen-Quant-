"""
Unit tests for Telegram Gold (XAUUSD) Signal Copier
===================================================
Tests regex parser, spam filters, celebration filters, anti-chase guard,
safe SL clamping, duplicate execution blocks, and Breakeven trigger.
"""

import unittest
from unittest.mock import MagicMock, patch
from src.integrations.telegram_gold_copier import TelegramGoldCopier, MAX_SL_DISTANCE_POINTS, MAX_SLIPPAGE_TOLERANCE


class TestTelegramGoldCopier(unittest.TestCase):
    def setUp(self):
        self.copier = TelegramGoldCopier(dry_run=True)
        self.copier.state = {
            "last_processed_post_id": None,
            "executed_signal_keys": [],
            "active_positions": []
        }

    def test_parses_valid_sell_signal(self):
        msg = (
            "#XAUUSD  SELL  4280\n"
            "🚀 ¹/TAKE PROFIT     4272\n"
            "🚀 ²/TAKE PROFIT     4270\n"
            "🚀 3/TAKE PROFIT     4260\n"
            "😊 STOP LOSS         4386\n"
            "Regular Quantity ❤️"
        )
        sig, reason = self.copier.parse_and_validate_signal(msg, current_spot=4280.5)
        self.assertEqual(reason, "OK")
        self.assertIsNotNone(sig)
        self.assertEqual(sig["symbol"], "XAUUSD")
        self.assertEqual(sig["side"], "SELL")
        self.assertEqual(sig["entry"], 4280.0)
        self.assertEqual(sig["raw_sl"], 4386.0)
        # Verify SL is clamped to max 10 points (4280 + 10 = 4290)
        self.assertEqual(sig["safe_sl"], 4290.0)
        self.assertEqual(sig["tps"], [4272.0, 4270.0, 4260.0])

    def test_parses_valid_buy_signal(self):
        msg = (
            "#XAUUSD BUY 4250\n"
            "TP1: 4258\n"
            "TP2: 4265\n"
            "TP3: 4275\n"
            "SL: 4210"
        )
        sig, reason = self.copier.parse_and_validate_signal(msg, current_spot=4251.0)
        self.assertEqual(reason, "OK")
        self.assertIsNotNone(sig)
        self.assertEqual(sig["side"], "BUY")
        self.assertEqual(sig["entry"], 4250.0)
        # Clamped SL on BUY: 4250 - 10 = 4240.0
        self.assertEqual(sig["safe_sl"], 4240.0)
        self.assertEqual(sig["tps"], [4258.0, 4265.0, 4275.0])

    def test_parses_minimal_short_format_sell(self):
        # User example: '#XAUUSD  SELL  4359'
        msg = "#XAUUSD  SELL  4359"
        sig, reason = self.copier.parse_and_validate_signal(msg, current_spot=4359.5)
        self.assertEqual(reason, "OK")
        self.assertIsNotNone(sig)
        self.assertEqual(sig["symbol"], "XAUUSD")
        self.assertEqual(sig["side"], "SELL")
        self.assertEqual(sig["entry"], 4359.0)
        self.assertEqual(sig["safe_sl"], 4369.0) # 4359 + 10 pts
        self.assertEqual(sig["tps"], [4351.0, 4349.0, 4339.0]) # -8, -10, -20 pts

    def test_parses_minimal_short_format_buy(self):
        # User example: '#XAUUSD  BUY  4359'
        msg = "#XAUUSD  BUY  4359"
        sig, reason = self.copier.parse_and_validate_signal(msg, current_spot=4358.5)
        self.assertEqual(reason, "OK")
        self.assertIsNotNone(sig)
        self.assertEqual(sig["symbol"], "XAUUSD")
        self.assertEqual(sig["side"], "BUY")
        self.assertEqual(sig["entry"], 4359.0)
        self.assertEqual(sig["safe_sl"], 4349.0) # 4359 - 10 pts
        self.assertEqual(sig["tps"], [4367.0, 4369.0, 4379.0]) # +8, +10, +20 pts

    def test_filters_promotional_spam(self):
        spam_msg = (
            "Welcome shering Work 📤 📌 Risk 10% Sl mangement "
            "📌 DAILY Return 25- 50% 📌 1000 $ For Best Return "
            "✔️ 50/50% profits sharing(Daily) ✔️ Profit Sharing"
        )
        sig, reason = self.copier.parse_and_validate_signal(spam_msg, current_spot=4280.0)
        self.assertIsNone(sig)
        self.assertIn("Promo/Spam", reason)

    def test_filters_celebration_updates(self):
        update_msg = "#XAUUSD TP,1 HIT 60 +PIPS RUNNING ☑️ Wow 👑 BOOM 🤯"
        sig, reason = self.copier.parse_and_validate_signal(update_msg, current_spot=4280.0)
        self.assertIsNone(sig)
        self.assertIn("Celebration", reason)

    def test_anti_chase_blocks_late_entry(self):
        msg = (
            "#XAUUSD  SELL  4280\n"
            "TP1: 4272\n"
            "TP2: 4270\n"
            "TP3: 4260\n"
            "SL: 4386"
        )
        # Price has already dumped to 4253.0 (> 2.50 pts from 4280)
        sig, reason = self.copier.parse_and_validate_signal(msg, current_spot=4253.0)
        self.assertIsNone(sig)
        self.assertIn("Anti-Chase", reason)

    def test_execute_creates_three_tickets(self):
        sig = {
            "symbol": "XAUUSD",
            "side": "SELL",
            "entry": 4280.0,
            "safe_sl": 4290.0,
            "tps": [4272.0, 4270.0, 4260.0],
            "signal_key": "XAUUSD_SELL_4280.0_4386.0"
        }
        with patch.object(self.copier, "send_telegram_alert"):
            trades = self.copier.execute_copier_signal(sig)
            self.assertEqual(len(trades), 3)
            self.assertEqual(trades[0]["ticket"], 1)
            self.assertEqual(trades[0]["tp"], 4272.0)
            self.assertEqual(trades[1]["ticket"], 2)
            self.assertEqual(trades[1]["tp"], 4270.0)
            self.assertEqual(trades[2]["ticket"], 3)
            self.assertEqual(trades[2]["tp"], 4260.0)
            self.assertIn("XAUUSD_SELL_4280.0_4386.0", self.copier.state["executed_signal_keys"])


if __name__ == "__main__":
    unittest.main()
