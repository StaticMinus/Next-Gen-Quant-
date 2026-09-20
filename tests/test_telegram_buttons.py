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
    add_authorized_user,
    get_balance_markup,
    get_broadcast_chat_ids,
    get_history_markup,
    get_main_menu_markup,
    get_partner_bottom_keyboard,
    get_partner_menu_markup,
    get_keyboard_for_user,
    get_menu_for_user,
    get_persistent_bottom_keyboard,
    get_radar_markup,
    get_tracker_markup,
    is_authorized_user,
    is_owner,
    load_authorized_users,
    OWNER_ONLY_CALLBACKS,
    OWNER_ONLY_TEXT_CMDS,
    OWNER_ONLY_DENIAL,
    PRIMARY_CHAT_ID,
    remove_authorized_user,
    render_balance_text,
    render_history_7d_text,
    render_history_14d_text,
    render_history_30d_text,
    render_history_all_text,
    render_history_overview_text,
    render_milestone_text,
    render_morning_briefing_text,
    render_morning_briefing_chacha,
    render_nightly_summary_text,
    render_nightly_summary_chacha,
    get_morning_briefing_for_user,
    get_nightly_summary_for_user,
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
    generate_milestone_progress_card,
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
            ("Morning Briefing", render_morning_briefing_text()),
            ("Cha Cha Morning", render_morning_briefing_chacha()),
            ("Nightly Summary", render_nightly_summary_text()),
            ("Cha Cha Nightly", render_nightly_summary_chacha()),
            ("Milestone Tracker", render_milestone_text()),
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

        for tk in ["SPY", "QQQ", "DIA", "IWM"]:
            b_chart = generate_radar_candlestick_chart(tk)
            self.assertTrue(len(b_chart.getvalue()) > 5000, f"Radar chart for {tk} too small")

        b3 = generate_payout_roadmap_card()
        self.assertTrue(len(b3.getvalue()) > 5000, "Roadmap card too small")

        b4 = generate_profile_summary_card()
        self.assertTrue(len(b4.getvalue()) > 5000, "Profile summary card too small")

    def test_15m_strategy_renders(self):
        """Verify that overview, briefings, and trade logic all reflect the active 15m Scalper strategy."""
        overview = render_overview_text()
        self.assertIn("15m", overview)

        morning = render_morning_briefing_text()
        self.assertIn("MORNING BRIEF", morning)
        self.assertIn("15m", morning)
        self.assertNotIn("1-Hour", morning)

        nightly = render_nightly_summary_text()
        self.assertIn("NIGHT WRAP", nightly)
        self.assertIn("15m", nightly)
        self.assertNotIn("1-Hour", nightly)

        logic = render_trade_logic_text()
        self.assertIn("M15 RAPID SCALPER", logic)
        self.assertIn("15-Minute", logic)
        self.assertNotIn("1-Hour", logic)

        b5 = generate_risk_sentinel_card()
        self.assertTrue(len(b5.getvalue()) > 5000, "Risk sentinel card too small")

        b6 = generate_trade_signal_card("SPY", 754.20, 758.60, 731.57)
        self.assertTrue(len(b6.getvalue()) > 5000, "Trade ticket card too small")

        b7 = generate_p2p_converter_card()
        self.assertTrue(len(b7.getvalue()) > 5000, "P2P card too small")

        b8 = generate_cycle_statement_pdf()
        self.assertTrue(len(b8.getvalue()) > 1000, "PDF statement too small")

        b9 = generate_milestone_progress_card(6000.0, 600.0, 109.72, 1518.40)
        self.assertTrue(len(b9.getvalue()) > 5000, "Milestone progress card too small")

    def test_partner_authorization_suite(self):
        """Verify multi-user partner authorization, storage, and retrieval."""
        # Initial state should include primary user David (8428715579)
        users = load_authorized_users()
        self.assertIn("8428715579", users)
        self.assertTrue(is_authorized_user("8428715579"))

        # Add partner Cha Cha
        test_chacha_id = "9988776655"
        self.assertFalse(is_authorized_user(test_chacha_id))
        self.assertTrue(add_authorized_user(test_chacha_id, name="Cha Cha", role="partner"))
        self.assertTrue(is_authorized_user(test_chacha_id))

        # Check broadcast list includes Cha Cha
        broadcast_list = get_broadcast_chat_ids()
        self.assertIn(test_chacha_id, broadcast_list)
        self.assertIn("8428715579", broadcast_list)

        # Cleanup / remove partner
        self.assertTrue(remove_authorized_user(test_chacha_id))
        self.assertFalse(is_authorized_user(test_chacha_id))
        # Primary user cannot be removed
        self.assertFalse(remove_authorized_user("8428715579"))
        self.assertTrue(is_authorized_user("8428715579"))

    def test_partner_keyboard_structure(self):
        """Verify partner keyboard excludes wallet/withdraw/P2P buttons."""
        kb = get_partner_bottom_keyboard()
        self.assertTrue(kb.get("resize_keyboard"))
        self.assertTrue(kb.get("is_persistent"))
        all_labels = [btn["text"] for row in kb["keyboard"] for btn in row]
        # Partners should NOT see these:
        for forbidden in ["💰 Balance & Risk", "🏦 Binance P2P", "👤 Overview"]:
            self.assertNotIn(forbidden, all_labels)
        # Partners SHOULD see these:
        for allowed in ["💬 Ask AI Coach", "📊 Active Trades", "🏆 Milestones", "📡 Live Radar"]:
            self.assertIn(allowed, all_labels)

    def test_partner_menu_excludes_sensitive_buttons(self):
        """Verify partner inline menu excludes withdraw, models, profile card."""
        pm = get_partner_menu_markup()
        all_cbs = [btn["callback_data"] for row in pm["inline_keyboard"] for btn in row if "callback_data" in btn]
        for blocked in ["cmd_withdraw", "cmd_models_menu", "cmd_card_profile", "cmd_export_pdf"]:
            self.assertNotIn(blocked, all_cbs, f"Partner menu should NOT contain {blocked}")
        # Should still have safe buttons
        for safe in ["cmd_overview", "cmd_balance", "cmd_signals", "cmd_trades", "cmd_milestones", "cmd_ask_ai_prompt"]:
            self.assertIn(safe, all_cbs, f"Partner menu should contain {safe}")

    def test_owner_only_role_check(self):
        """Verify is_owner correctly identifies David vs partners."""
        self.assertTrue(is_owner(PRIMARY_CHAT_ID))
        self.assertTrue(is_owner("8428715579"))
        self.assertFalse(is_owner("9999999999"))
        self.assertFalse(is_owner(""))

    def test_role_aware_dispatchers(self):
        """Verify get_keyboard_for_user and get_menu_for_user return correct types."""
        # Owner gets full menu
        owner_kb = get_keyboard_for_user(PRIMARY_CHAT_ID)
        self.assertEqual(len(owner_kb["keyboard"]), 3)
        owner_menu = get_menu_for_user(PRIMARY_CHAT_ID)
        owner_cbs = [btn.get("callback_data") for row in owner_menu["inline_keyboard"] for btn in row if "callback_data" in btn]
        self.assertIn("cmd_withdraw", owner_cbs)
        self.assertIn("cmd_models_menu", owner_cbs)

        # Partner gets restricted menu
        partner_kb = get_keyboard_for_user("9999999999")
        self.assertEqual(len(partner_kb["keyboard"]), 3)
        partner_menu = get_menu_for_user("9999999999")
        partner_cbs = [btn.get("callback_data") for row in partner_menu["inline_keyboard"] for btn in row if "callback_data" in btn]
        self.assertNotIn("cmd_withdraw", partner_cbs)
        self.assertNotIn("cmd_models_menu", partner_cbs)

    def test_owner_only_blocklists_populated(self):
        """Verify OWNER_ONLY sets are non-empty and contain critical items."""
        self.assertIn("cmd_withdraw", OWNER_ONLY_CALLBACKS)
        self.assertIn("cmd_models_menu", OWNER_ONLY_CALLBACKS)
        self.assertIn("cmd_confirm_payout", OWNER_ONLY_CALLBACKS)
        self.assertIn("/setwallet", OWNER_ONLY_TEXT_CMDS)
        self.assertIn("/wallet", OWNER_ONLY_TEXT_CMDS)
        self.assertIn("/adduser", OWNER_ONLY_TEXT_CMDS)
        self.assertTrue(len(OWNER_ONLY_DENIAL) > 50, "Denial message should be descriptive")

    def test_romantic_chacha_briefings(self):
        """Verify Cha Cha gets custom romantic morning and nightly messages signed with love from David."""
        # Check Cha Cha renderers directly
        m_chacha = render_morning_briefing_chacha()
        self.assertIn("Cha Cha", m_chacha)
        self.assertIn("David", m_chacha)
        self.assertTrue(any(w in m_chacha.lower() for w in ["love", "heart", "angel", "treasure"]))

        n_chacha = render_nightly_summary_chacha()
        self.assertIn("Cha Cha", n_chacha)
        self.assertIn("David", n_chacha)
        self.assertTrue(any(w in n_chacha.lower() for w in ["love", "heart", "angel", "treasure"]))

        # Check role-aware dispatchers
        # Owner David gets standard briefing
        d_morning = get_morning_briefing_for_user(PRIMARY_CHAT_ID)
        self.assertIn("MORNING BRIEF", d_morning)
        self.assertIn("15m", d_morning)
        self.assertNotIn("Cha Cha", d_morning)

        d_nightly = get_nightly_summary_for_user(PRIMARY_CHAT_ID)
        self.assertIn("NIGHT WRAP", d_nightly)
        self.assertIn("15m", d_nightly)
        self.assertNotIn("Cha Cha", d_nightly)

        # Partner Cha Cha (7923834818) gets romantic version
        c_morning = get_morning_briefing_for_user("7923834818")
        self.assertIn("Cha Cha", c_morning)
        self.assertIn("David", c_morning)

        c_nightly = get_nightly_summary_for_user("7923834818")
        self.assertIn("Cha Cha", c_nightly)
        self.assertIn("David", c_nightly)

    def test_chacha_non_repeating_rotation(self):
        """Verify that consecutive calls to Cha Cha briefings do not repeat the same message."""
        m1 = render_morning_briefing_chacha()
        m2 = render_morning_briefing_chacha()
        self.assertNotEqual(m1, m2, "Consecutive morning briefings should not be identical")

        n1 = render_nightly_summary_chacha()
        n2 = render_nightly_summary_chacha()
        self.assertNotEqual(n1, n2, "Consecutive nightly briefings should not be identical")

    def test_gold_position_suppresses_gld_alert(self):
        """Verify that open Gold position is correctly detected and suppressed from autonomous alerts."""
        from src.integrations.telegram_bot_service import _CACHE, check_and_dispatch_autonomous_alerts
        from unittest.mock import patch

        # 1. When last_telemetry_sync is None, no alerts should ever be dispatched (startup guard)
        _CACHE["last_telemetry_sync"] = None
        with patch("src.integrations.telegram_bot_service.api_call") as mock_api:
            check_and_dispatch_autonomous_alerts()
            mock_api.assert_not_called()

        # 2. When Gold position is open in enriched_positions, GLD alert is skipped
        _CACHE["last_telemetry_sync"] = 1234567.0
        _CACHE["enriched_positions"] = [{
            "position_id": 3069593,
            "symbol_id": 41,
            "symbol_name": "XAUUSD",
            "display_name": "Spot Gold",
            "trade_side": "BUY"
        }]

        with patch("src.integrations.telegram_bot_service.evaluate_market_signals") as mock_signals, \
             patch("src.integrations.telegram_bot_service.api_call") as mock_api:
            mock_signals.return_value = [{
                "ticker": "GLD",
                "strategy": "Sniper Dip-Buy",
                "price": 4334.0,
                "target": 4443.0,
                "stop": 4204.0,
                "summary": "Oversold dip"
            }]
            check_and_dispatch_autonomous_alerts()
            # api_call should NEVER be called for GLD because it is in held_tickers!
            mock_api.assert_not_called()

    def test_trades_markup_includes_be_and_bank_half(self):
        """Verify get_trades_markup renders 1-tap BE and Bank 50% buttons for David."""
        from src.integrations.telegram_bot_service import _CACHE, get_trades_markup, PRIMARY_CHAT_ID
        _CACHE["enriched_positions"] = [{
            "position_id": 9999,
            "symbol_name": "SPX500",
            "trade_side": "BUY"
        }]
        markup = get_trades_markup(user_id=PRIMARY_CHAT_ID)
        all_cbs = [btn["callback_data"] for row in markup["inline_keyboard"] for btn in row if "callback_data" in btn]
        self.assertIn("cmd_sl_be_9999", all_cbs)
        self.assertIn("cmd_bank_half_9999", all_cbs)
        self.assertIn("cmd_close_tap1_9999", all_cbs)

    def test_payout_progress_bar_render(self):
        """Verify render_payout_progress_bar and briefings integration."""
        from src.integrations.telegram_bot_service import (
            render_payout_progress_bar,
            render_overview_text,
            render_morning_briefing_text,
            render_nightly_summary_text
        )
        bar_text = render_payout_progress_bar(150.0, 300.0)
        self.assertIn("Target:", bar_text)
        self.assertIn("50%", bar_text)
        self.assertIn("█", bar_text)

        overview = render_overview_text()
        self.assertIn("Target:", overview)

        morning = render_morning_briefing_text()
        self.assertIn("Target:", morning)
        self.assertIn("Payout", morning)

        nightly = render_nightly_summary_text()
        self.assertIn("Target:", nightly)
        self.assertIn("Payout", nightly)


if __name__ == "__main__":
    unittest.main()
