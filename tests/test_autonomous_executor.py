import unittest
from unittest.mock import MagicMock, patch
from src.integrations.autonomous_executor import AutonomousExecutionEngine, MAX_CONCURRENT_POSITIONS

class TestAutonomousExecutionEngine(unittest.TestCase):
    def setUp(self):
        self.mock_ctrader = MagicMock()
        self.mock_ctrader.get_spot_price.return_value = {"ask": 709.50, "bid": 709.40}
        self.engine = AutonomousExecutionEngine(ctrader_client=self.mock_ctrader)

    def test_blocks_when_portfolio_at_max_capacity(self):
        """Verify that when 2 positions are active, no new trades are placed."""
        self.mock_ctrader.session_id = "test_session"
        self.mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
        # Simulate 2 existing open positions
        self.mock_ctrader.get_positions.return_value = [
            {"positionId": 1, "symbolId": 41, "symbolName": "XAUUSD"},
            {"positionId": 2, "symbolId": 101, "symbolName": "NDX100"}
        ]
        trades = self.engine.run_cycle(dry_run=True)
        self.assertEqual(len(trades), 0, "Should NOT execute any trade when at 2 positions limit")

    def test_blocks_when_risk_guardian_halted(self):
        """Verify that when Risk Guardian has halted trading, no trades are executed."""
        self.mock_ctrader.session_id = "test_session"
        self.mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 5800.0}
        self.mock_ctrader.get_positions.return_value = []
        with patch.dict("src.integrations.autonomous_executor.guardian.state", {"trading_halted": True}):
            trades = self.engine.run_cycle(dry_run=True)
            self.assertEqual(len(trades), 0, "Should NOT execute when trading is halted")

    def test_skips_duplicate_held_symbols(self):
        """Verify that an asset already in portfolio is never duplicated."""
        self.mock_ctrader.session_id = "test_session"
        self.mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
        self.mock_ctrader.get_symbol_map.return_value = {"XAUUSD": 41, "NDX100": 101, "SPX500": 102}
        # Only 1 position: XAUUSD
        self.mock_ctrader.get_positions.return_value = [
            {"positionId": 1, "symbolId": 41, "symbolName": "XAUUSD"}
        ]
        # Any trade executed must NOT be XAUUSD / Gold
        trades = self.engine.run_cycle(dry_run=True)
        for t in trades:
            self.assertNotEqual(t["symbol"], "XAUUSD")
            self.assertNotEqual(t["ticker"], "GLD")

if __name__ == "__main__":
    unittest.main()
