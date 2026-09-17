import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from src.integrations.autonomous_executor import (
    AutonomousExecutionEngine,
    MAX_CONCURRENT_POSITIONS,
    TIMEFRAME_CONFIGS,
    fetch_intraday_bars
)

class TestAutonomousExecutionEngine(unittest.TestCase):
    def setUp(self):
        self.mock_ctrader = MagicMock()
        self.mock_ctrader.get_spot_price.return_value = {"ask": 709.50, "bid": 709.40}
        self.engine = AutonomousExecutionEngine(ctrader_client=self.mock_ctrader)
        # Mock active market session timestamp (Wednesday 11:00 AM EST)
        self.active_dt = pd.Timestamp("2026-09-16 11:00:00", tz="America/New_York")

    def test_blocks_when_portfolio_at_max_capacity(self):
        """Verify that when 2 positions are active, no new trades are placed."""
        self.mock_ctrader.session_id = "test_session"
        self.mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
        # Simulate 2 existing open positions
        self.mock_ctrader.get_positions.return_value = [
            {"positionId": 1, "symbolId": 113, "symbolName": "SPX500"},
            {"positionId": 2, "symbolId": 112, "symbolName": "NDX100"}
        ]
        trades = self.engine.run_cycle(dry_run=True, dt_override=self.active_dt)
        self.assertEqual(len(trades), 0, "Should NOT execute any trade when at 2 positions limit")

    def test_blocks_when_risk_guardian_halted(self):
        """Verify that when Risk Guardian has halted trading, no trades are executed."""
        self.mock_ctrader.session_id = "test_session"
        self.mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 5800.0}
        self.mock_ctrader.get_positions.return_value = []
        with patch.dict("src.integrations.autonomous_executor.guardian.state", {"trading_halted": True}):
            trades = self.engine.run_cycle(dry_run=True, dt_override=self.active_dt)
            self.assertEqual(len(trades), 0, "Should NOT execute when trading is halted")

    def test_skips_duplicate_held_symbols(self):
        """Verify that an asset already in portfolio is never duplicated."""
        self.mock_ctrader.session_id = "test_session"
        self.mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
        self.mock_ctrader.get_symbol_map.return_value = {"SPX500": 113, "NDX100": 112}
        # Only 1 position: SPX500
        self.mock_ctrader.get_positions.return_value = [
            {"positionId": 1, "symbolId": 113, "symbolName": "SPX500"}
        ]
        trades = self.engine.run_cycle(dry_run=True, dt_override=self.active_dt)
        for t in trades:
            self.assertNotEqual(t["symbol"], "SPX500")

    def test_outside_active_entry_window_skips_entries(self):
        """Verify that outside 10:00 - 14:30 EST, no new trades are placed."""
        self.mock_ctrader.session_id = "test_session"
        self.mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
        self.mock_ctrader.get_positions.return_value = []
        
        # 04:00 AM EST (Pre-market)
        early_dt = pd.Timestamp("2026-09-16 04:00:00", tz="America/New_York")
        trades = self.engine.run_cycle(dry_run=True, dt_override=early_dt)
        self.assertEqual(len(trades), 0, "Must not trade in pre-market")

        # 02:45 PM EST (After 2:30 PM cutoff)
        late_dt = pd.Timestamp("2026-09-16 14:45:00", tz="America/New_York")
        trades_late = self.engine.run_cycle(dry_run=True, dt_override=late_dt)
        self.assertEqual(len(trades_late), 0, "Must not enter trades after 2:30 PM cutoff")

    def test_smart_eod_banks_profitable_trades(self):
        """Verify that at 15:50 EST, positions in profit are closed to bank cash."""
        self.mock_ctrader.session_id = "test_session"
        self.mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
        self.mock_ctrader.get_positions.return_value = [
            {"positionId": 999, "symbolId": 113, "symbolName": "SPX500", "entryPrice": 5000.0, "tradeSide": "BUY"}
        ]
        # Spot price is 5010.0 (+0.20% in profit)
        self.mock_ctrader.get_spot_price.return_value = {"bid": 5010.0, "ask": 5010.5}
        self.mock_ctrader.close_position.return_value = {"positionId": 999, "volume": 0}
        
        eod_dt = pd.Timestamp("2026-09-16 15:55:00", tz="America/New_York")
        with patch("src.integrations.autonomous_executor.ALLOW_OVERNIGHT_HOLD", False):
            closed = self.engine.check_and_execute_same_day_flatten(
                self.mock_ctrader.get_positions(), dt_ny=eod_dt
            )
        self.assertIn(999, closed)
        self.mock_ctrader.close_position.assert_called_with(999)

    def test_smart_eod_protects_negative_trades_from_forced_loss(self):
        """Verify that at 15:50 EST, positions in minor drawdown are NOT force-closed at a loss."""
        self.mock_ctrader.session_id = "test_session"
        self.mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
        self.mock_ctrader.get_positions.return_value = [
            {"positionId": 888, "symbolId": 113, "symbolName": "SPX500", "entryPrice": 5000.0, "tradeSide": "BUY"}
        ]
        # Spot price is 4995.0 (-0.10% dip, within SL)
        self.mock_ctrader.get_spot_price.return_value = {"bid": 4995.0, "ask": 4995.5}
        self.mock_ctrader.close_position.reset_mock()
        
        eod_dt = pd.Timestamp("2026-09-16 15:55:00", tz="America/New_York")
        closed = self.engine.check_and_execute_same_day_flatten(
            self.mock_ctrader.get_positions(), dt_ny=eod_dt
        )
        self.assertEqual(len(closed), 0, "Must NEVER force-close a negative position at a loss")
        self.mock_ctrader.close_position.assert_not_called()

    def test_anti_late_trade_price_tolerance(self):
        """Verify that if live spot price has bounced > 0.10% above the dip trigger, order is rejected."""
        self.mock_ctrader.session_id = "test_session"
        self.mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
        self.mock_ctrader.get_positions.return_value = []
        self.mock_ctrader.get_symbol_map.return_value = {"SPX500": 113, "NDX100": 112}
        
        # Mock hourly data with a dip
        idx = pd.date_range("2026-09-16 09:30", periods=25, freq="1h", tz="America/New_York")
        prices = [500.0] * 24 + [490.0] # Dip on last bar
        mock_df = pd.DataFrame({"close": prices, "open": prices, "high": prices, "low": prices}, index=idx)
        
        # Dip level is ~492. Spot price is 505.00 (> 0.10% higher)
        self.mock_ctrader.get_spot_price.return_value = {"ask": 505.00, "bid": 504.90}
        
        with patch("src.integrations.autonomous_executor.fetch_intraday_bars", return_value=mock_df):
            trades = self.engine.run_cycle(dry_run=True, dt_override=idx[-1] + pd.Timedelta(minutes=1))
            self.assertEqual(len(trades), 0, "Should reject trade when price is chased above tolerance")

if __name__ == "__main__":
    unittest.main()
