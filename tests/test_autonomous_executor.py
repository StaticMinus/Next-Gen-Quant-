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
        with patch("src.integrations.autonomous_executor.ALLOW_OVERNIGHT_HOLD", True):
            closed = self.engine.check_and_execute_same_day_flatten(
                self.mock_ctrader.get_positions(), dt_ny=eod_dt
            )
        self.assertEqual(len(closed), 0, "Must NEVER force-close a negative position at a loss when overnight hold is enabled")
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

    def test_m15_timeframe_config(self):
        """Verify M15 Scalper A configuration settings."""
        self.assertIn("15m", TIMEFRAME_CONFIGS)
        cfg = TIMEFRAME_CONFIGS["15m"]
        self.assertEqual(cfg["interval"], "15m")
        self.assertEqual(cfg["window"], 8)
        self.assertEqual(cfg["num_std"], 1.50)
        self.assertEqual(cfg["max_hold_bars"], 6)
        self.assertEqual(cfg["target_profit_pct"], 0.0025)
        self.assertEqual(cfg["time_decay_bars"], 3)

    @patch("src.integrations.autonomous_executor.broadcast_telegram_ticket")
    def test_time_decay_profit_banking(self, mock_broadcast):
        """Verify that holding >= 45 mins in profit triggers auto-close and banks cash."""
        import time
        now = time.time()
        self.mock_ctrader.get_symbol_map.return_value = {"SPX500": 113}
        self.mock_ctrader.close_position.return_value = {"positionId": 777}
        self.mock_ctrader.get_spot_price.return_value = {"bid": 5015.0, "ask": 5015.5} # +0.30% in profit

        # Record position entered 50 minutes ago
        self.engine.state["open_positions_meta"] = {
            "777": {"entry_time": now - 3000, "entry_price": 5000.0, "symbol": "SPX500"}
        }
        positions = [
            {"positionId": 777, "symbolId": 113, "symbolName": "SPX500", "entryPrice": 5000.0, "tradeSide": "BUY"}
        ]
        closed = self.engine.check_and_manage_active_positions(positions)
        self.assertIn(777, closed)
        self.mock_ctrader.close_position.assert_called_with(777)

    @patch("src.integrations.autonomous_executor.broadcast_telegram_ticket")
    def test_smart_recovery_banks_when_green_at_90m(self, mock_broadcast):
        """Verify that at >= 90 mins, if trade is green, it banks profit."""
        import time
        now = time.time()
        self.mock_ctrader.get_symbol_map.return_value = {"SPX500": 113}
        self.mock_ctrader.close_position.return_value = {"positionId": 778}
        self.mock_ctrader.get_spot_price.return_value = {"bid": 5010.0, "ask": 5010.5} # +0.20% green

        # Record position entered 95 minutes ago (5700s)
        self.engine.state["open_positions_meta"] = {
            "778": {"entry_time": now - 5700, "entry_price": 5000.0, "symbol": "SPX500"}
        }
        positions = [
            {"positionId": 778, "symbolId": 113, "symbolName": "SPX500", "entryPrice": 5000.0, "tradeSide": "BUY"}
        ]
        closed = self.engine.check_and_manage_active_positions(positions)
        self.assertIn(778, closed)
        self.mock_ctrader.close_position.assert_called_with(778)

    @patch("src.integrations.autonomous_executor.broadcast_telegram_ticket")
    def test_smart_recovery_lets_red_trade_breathe_at_90m(self, mock_broadcast):
        """Verify that at >= 90 mins, if trade is red, it is NOT force-closed; it is allowed to breathe."""
        import time
        now = time.time()
        self.mock_ctrader.get_symbol_map.return_value = {"SPX500": 113}
        self.mock_ctrader.close_position.reset_mock()
        self.mock_ctrader.get_spot_price.return_value = {"bid": 4995.0, "ask": 4995.5} # -0.10% in drawdown

        # Record position entered 95 minutes ago (5700s)
        self.engine.state["open_positions_meta"] = {
            "779": {"entry_time": now - 5700, "entry_price": 5000.0, "symbol": "SPX500"}
        }
        positions = [
            {"positionId": 779, "symbolId": 113, "symbolName": "SPX500", "entryPrice": 5000.0, "tradeSide": "BUY"}
        ]
        closed = self.engine.check_and_manage_active_positions(positions)
        self.assertEqual(len(closed), 0, "Must let negative position breathe at 90m")
        self.mock_ctrader.close_position.assert_not_called()

    @patch("src.integrations.autonomous_executor.broadcast_telegram_ticket")
    def test_eod_flattens_breathing_trade_at_1545_est(self, mock_broadcast):
        """Verify that at 15:45 EST (8:45 PM WAT), any breathing position is flattened so it never sits overnight."""
        self.mock_ctrader.get_symbol_map.return_value = {"SPX500": 113}
        self.mock_ctrader.close_position.return_value = {"positionId": 780}
        self.mock_ctrader.get_spot_price.return_value = {"bid": 4992.0, "ask": 4992.5}
        positions = [
            {"positionId": 780, "symbolId": 113, "symbolName": "SPX500", "entryPrice": 5000.0, "tradeSide": "BUY"}
        ]
        eod_dt = pd.Timestamp("2026-09-18 15:46:00", tz="America/New_York") # 8:46 PM WAT
        closed = self.engine.check_and_execute_same_day_flatten(positions, dt_ny=eod_dt)
        self.assertIn(780, closed)
        self.mock_ctrader.close_position.assert_called_with(780)

    def test_microstructure_rejection_filter(self):
        """Verify that falling knife red candles are rejected, while hammer/rejection wicks pass."""
        # 1. Falling knife candle: Open=100, High=100, Low=90, Close=91 (lower wick = 1/10 = 10% < 15%)
        knife_df = pd.DataFrame([{
            "open": 100.0, "high": 100.0, "low": 90.0, "close": 91.0, "volume": 500
        }])
        is_rej, ratio, reason = self.engine.check_microstructure_rejection("SPX500", knife_df)
        self.assertFalse(is_rej, "Should reject falling knife candle")
        self.assertEqual(reason, "FALLING_KNIFE_REJECTED")

        # 2. Hammer / Absorption wick: Open=98, High=100, Low=90, Close=99 (lower wick = 8/10 = 80% >= 30%)
        hammer_df = pd.DataFrame([{
            "open": 98.0, "high": 100.0, "low": 90.0, "close": 99.0, "volume": 500
        }])
        is_rej, ratio, reason = self.engine.check_microstructure_rejection("SPX500", hammer_df)
        self.assertTrue(is_rej, "Should confirm hammer/absorption wick")
        self.assertEqual(reason, "REJECTION_CONFIRMED")

    def test_atomic_market_order_submission(self):
        """Verify that place_market_order submits relative SL/TP directly in create_order."""
        from src.integrations.ctrader_mcp_client import CTraderMCPClient
        client = CTraderMCPClient()
        client.call_tool = MagicMock()
        client.get_positions_strict = MagicMock(return_value=[])
        client.get_symbol_map = MagicMock(return_value={"SPX500": 113})
        client._parse_content_json = MagicMock(return_value={"orderId": 5555})

        res = client.place_market_order(
            symbol="SPX500",
            side="BUY",
            volume_lots=0.10,
            relative_sl_points=200,
            relative_tp_points=150,
            stop_loss_price=4980.0,
            take_profit_price=5015.0
        )
        self.assertEqual(res["orderId"], 5555)
        # Verify create_order was called with relativeStopLoss and relativeTakeProfit
        client.call_tool.assert_called_once()
        call_name = client.call_tool.call_args[0][0]
        call_args = client.call_tool.call_args[0][1]
        self.assertEqual(call_name, "create_order")
        self.assertEqual(call_args["relativeStopLoss"], 200)
        self.assertEqual(call_args["relativeTakeProfit"], 150)

    def test_place_limit_order(self):
        """Verify that place_limit_order submits a resting LIMIT order with display SL/TP and expiry."""
        from src.integrations.ctrader_mcp_client import CTraderMCPClient
        client = CTraderMCPClient()
        client.call_tool = MagicMock()
        client.get_positions_strict = MagicMock(return_value=[])
        client.get_pending_orders = MagicMock(return_value=[])
        client.get_symbol_map = MagicMock(return_value={"SPX500": 113})
        client._parse_content_json = MagicMock(return_value={"orderId": 6666})

        res = client.place_limit_order(
            symbol="SPX500",
            side="BUY",
            volume_lots=0.10,
            limit_price=4990.0,
            stop_loss_price=4970.0,
            take_profit_price=5010.0,
            expiry_seconds=1800
        )
        self.assertEqual(res["orderId"], 6666)
        client.call_tool.assert_called_once()
        call_name = client.call_tool.call_args[0][0]
        call_args = client.call_tool.call_args[0][1]
        self.assertEqual(call_name, "create_order")
        self.assertEqual(call_args["orderType"], "LIMIT")
        self.assertEqual(call_args["limitPrice"], 4990.0)
        self.assertEqual(call_args["stopLoss"], 4970.0)
        self.assertEqual(call_args["takeProfit"], 5010.0)
        self.assertEqual(call_args["timeInForce"], "GOOD_TILL_DATE")

    def test_trendbars_dataframe_parsing(self):
        """Verify that get_trendbars_dataframe parses raw cTrader trendbars correctly into OHLCV."""
        from src.integrations.ctrader_mcp_client import CTraderMCPClient
        client = CTraderMCPClient()
        client.get_symbol_map = MagicMock(return_value={"SPX500": 113})
        raw_trendbars = {
            "trendbars": [
                {
                    "timestamp": 1789764300000,
                    "open": 765911000,
                    "high": 766048000,
                    "low": 765683000,
                    "close": 765710000,
                    "volume": 616
                }
            ]
        }
        client.call_tool = MagicMock(return_value=raw_trendbars)
        client._parse_content_json = MagicMock(return_value=raw_trendbars)

        df = client.get_trendbars_dataframe("SPX500", period="M_15", count=1)
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 1)
        self.assertAlmostEqual(df.iloc[0]["open"], 7659.11, places=2)
        self.assertAlmostEqual(df.iloc[0]["high"], 7660.48, places=2)
        self.assertAlmostEqual(df.iloc[0]["low"], 7656.83, places=2)
        self.assertAlmostEqual(df.iloc[0]["close"], 7657.10, places=2)
        self.assertEqual(df.iloc[0]["volume"], 616)

if __name__ == "__main__":
    unittest.main()

