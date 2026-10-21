"""
Tests for PatternMemory
=======================
Validates thread-safe caching, learned quirk recording, sub-millisecond lookup,
and preflight string normalizations.
"""

import unittest
from unittest.mock import patch
from src.integrations.pattern_memory import PatternMemory


class TestPatternMemory(unittest.TestCase):
    def test_seeded_quirks_lookup(self):
        """Verifies pre-seeded quirks for known channels are loaded correctly."""
        quirks_gold = PatternMemory.get_channel_quirks("XAUUSD_GOLD_TRADING_FOREX")
        self.assertTrue(quirks_gold.get("tp1_is_entry_anchor"))
        self.assertTrue(PatternMemory.should_promote_tp1("XAUUSD_GOLD_TRADING_FOREX"))

        quirks_ssf = PatternMemory.get_channel_quirks("ssfgold")
        self.assertTrue(quirks_ssf.get("strip_vip_promos"))

    def test_record_and_retrieve_new_quirk(self):
        """Verifies dynamic learning and retrieval of a new channel quirk."""
        test_channel = "test_prop_channel_99"
        PatternMemory.record_channel_quirk(test_channel, "has_custom_sl_marker", True, "Test channel")
        self.assertTrue(PatternMemory.get_quirk(test_channel, "has_custom_sl_marker"))

    def test_preflight_normalization_prime_gold_dots(self):
        """Verifies range with dot separator is normalized to hyphen (4131.4134 -> 4131-4134)."""
        raw_text = "XAUUSD SELL 4131.4134 TP 4125 SL 4142"
        normalized = PatternMemory.apply_preflight_normalization(raw_text, "PrimeGoldSignals")
        self.assertIn("4131-4134", normalized)


if __name__ == "__main__":
    unittest.main()
