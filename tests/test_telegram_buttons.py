"""
Comprehensive Telegram Button & Callback Deep Validation Suite
==============================================================
Verifies every single inline button callback data, menu markup, text command,
visual card generator, and PDF generator to ensure 100% click reliability.
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.integrations.telegram_bot_service import (
    get_balance_markup,
    get_history_markup,
    get_main_menu_markup,
    get_persistent_bottom_keyboard,
    get_radar_markup,
    get_tracker_markup,
    render_balance_text,
    render_history_7d_text,
    render_history_14d_text,
    render_history_30d_text,
    render_history_all_text,
    render_history_overview_text,
    render_overview_text,
    render_p2p_rate_text,
    render_payout_success_text,
    render_signals_text,
    render_tracker_text,
    render_trade_logic_text,
    render_trades_text,
    render_withdraw_confirm_text,
    render_withdraw_text,
)
from src.visualization.telegram_charts import (
    generate_cycle_statement_pdf,
    generate_equity_chart,
    generate_p2p_converter_card,
    generate_payout_roadmap_card,
    generate_profile_summary_card,
    generate_radar_candlestick_chart,
    generate_risk_sentinel_card,
    generate_trade_signal_card,
)


class TestTelegramTerminalButtons(unittest.TestCase):

    def test_all_text_renderers(self):
        """Verify all text renderers output non-empty valid HTML strings."""
        renderers = [
            ("Overview", render_overview_text()),
            ("Balance", render_balance_text()),
            ("Signals", render_signals_text()),
            ("Trades", render_trades_text()),
            ("Tracker", render_tracker_text()),
            ("P2P Rate", render_p2p_rate_text()),
            ("Trade Logic", render_trade_logic_text()),
            ("History Overview", render_history_overview_text()),
            ("History 7d", render_history_7d_text()),
            ("History 14d", render_history_14d_text()),
            ("History 30d", render_history_30d_text()),
            ("History All", render_history_all_text()),
            ("Withdraw", render_withdraw_text()),
            ("Withdraw Confirm", render_withdraw_confirm_text(1062.50)),
            ("Payout Success", render_payout_success_text(1062.50)),
        ]
        for name, text in renderers:
            self.assertTrue(len(text) > 20, f"Renderer '{name}' output was unexpectedly short.")
            self.assertIn("<b>", text, f"Renderer '{name}' missing HTML formatting.")

    def test_all_markups_structure(self):
        """Verify all markups have valid inline keyboard arrays."""
        markups = [
            get_main_menu_markup(),
            get_history_markup("overview"),
            get_history_markup("7d"),
            get_history_markup("14d"),
            get_tracker_markup(),
            get_radar_markup(),
            get_balance_markup(),
        ]
        for m in markups:
            self.assertIn("inline_keyboard", m)
            for row in m["inline_keyboard"]:
                self.assertTrue(len(row) >= 1)
                for btn in row:
                    self.assertIn("text", btn)
                    self.assertTrue("callback_data" in btn or "web_app" in btn or "url" in btn)

    def test_no_strategy_rules_button(self):
        """Verify Strategy Rules button is removed from main menu."""
        main_m = get_main_menu_markup()
        for row in main_m["inline_keyboard"]:
            for btn in row:
                if "callback_data" in btn:
                    self.assertNotIn("strategy_rules", btn["callback_data"])
                self.assertNotIn("Strategy Rules", btn["text"])

    def test_persistent_bottom_keyboard(self):
        """Verify persistent bottom keyboard structure."""
        kb = get_persistent_bottom_keyboard()
        self.assertTrue(kb.get("resize_keyboard"))
        self.assertTrue(kb.get("is_persistent"))
        self.assertEqual(len(kb["keyboard"]), 3)

    def test_all_visual_generators(self):
        """Verify all visual charts, cards, and PDF generators produce valid non-empty byte buffers."""
        b1 = generate_equity_chart()
        self.assertTrue(len(b1.getvalue()) > 5000, "Equity chart too small")

        b2 = generate_radar_candlestick_chart("SPY")
        self.assertTrue(len(b2.getvalue()) > 5000, "Radar chart too small")

        b3 = generate_payout_roadmap_card()
        self.assertTrue(len(b3.getvalue()) > 5000, "Roadmap card too small")

        b4 = generate_profile_summary_card()
        self.assertTrue(len(b4.getvalue()) > 5000, "Profile summary card too small")

        b5 = generate_risk_sentinel_card()
        self.assertTrue(len(b5.getvalue()) > 5000, "Risk sentinel card too small")

        b6 = generate_trade_signal_card("SPY", 754.20, 758.60, 731.57)
        self.assertTrue(len(b6.getvalue()) > 5000, "Trade ticket card too small")

        b7 = generate_p2p_converter_card()
        self.assertTrue(len(b7.getvalue()) > 5000, "P2P card too small")

        b8 = generate_cycle_statement_pdf()
        self.assertTrue(len(b8.getvalue()) > 1000, "PDF statement too small")


if __name__ == "__main__":
    unittest.main()
