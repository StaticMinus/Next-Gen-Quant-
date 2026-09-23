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
        self.patcher_broadcast = patch("src.integrations.autonomous_executor.broadcast_telegram_ticket")
        self.mock_broadcast = self.patcher_broadcast.start()
        self.mock_ctrader = MagicMock()
        self.mock_ctrader.get_spot_price.return_value = {"ask": 709.50, "bid": 709.40}
        self.engine = AutonomousExecutionEngine(ctrader_client=self.mock_ctrader)
        # Mock active market session timestamp (Wednesday 11:00 AM EST)
        self.active_dt = pd.Timestamp("2026-09-16 11:00:00", tz="America/New_York")

    def tearDown(self):
        self.patcher_broadcast.stop()

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

    def test_float_scale_multiplier_avoids_rounding_error_rejection(self):
        """Verify that exact float scale multiplier (e.g. SPX/SPY ~10.035) allows valid dips without integer rounding error."""
        self.mock_ctrader.session_id = "test_session"
        self.mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
        self.mock_ctrader.get_positions.return_value = []
        self.mock_ctrader.get_symbol_map.return_value = {"SPX500": 113}

        # 15m candle indexed at 11:30 closes at 11:45
        idx = pd.date_range("2026-09-16 09:30", periods=9, freq="15min", tz="America/New_York")
        # 8 baseline bars at 580, then a dip bar with open 580, high 580, low 568, close 570
        prices_close = [580.0] * 8 + [570.0]
        prices_open = [580.0] * 8 + [579.0]
        prices_high = [581.0] * 8 + [580.0]
        prices_low = [579.0] * 8 + [568.0] # wick = (570 - 568) / (580 - 568) = 2/12 = 16.7% (>15% microstructure)
        mock_df = pd.DataFrame({
            "close": prices_close, "open": prices_open, "high": prices_high, "low": prices_low, "volume": [1000]*9
        }, index=idx)

        # Real index ratio is ~10.035: SPY is 570.0 -> SPX500 ask is 5720.0
        self.mock_ctrader.get_spot_price.return_value = {"ask": 5720.0, "bid": 5719.5}

        with patch("src.integrations.autonomous_executor.fetch_intraday_bars", return_value=mock_df):
            eval_time = idx[-1] + pd.Timedelta(minutes=15, seconds=30)
            trades = self.engine.run_cycle(dry_run=True, dt_override=eval_time)
            self.assertGreater(len(trades), 0, "Valid dip on SPX500 must NOT be blocked by integer scale rounding")
            self.assertEqual(trades[0]["symbol"], "SPX500")

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

    def test_spread_shield_blocks_wide_spread(self):
        """Verify that when spread > 0.03% (3 bps), order entry is blocked."""
        # Bid = 5000.0, Ask = 5002.5 -> Spread = 2.5 / 5001.25 = 0.05% (> 0.03%)
        spot_wide = {"bid": 5000.0, "ask": 5002.5}
        is_ok, spread_pct, reason = self.engine.check_spread_shield("SPX500", spot_wide)
        self.assertFalse(is_ok)
        self.assertIn("SPREAD_TOO_WIDE", reason)

        # Bid = 5000.0, Ask = 5000.5 -> Spread = 0.5 / 5000.25 = 0.01% (< 0.03%)
        spot_tight = {"bid": 5000.0, "ask": 5000.5}
        is_ok2, spread_pct2, reason2 = self.engine.check_spread_shield("SPX500", spot_tight)
        self.assertTrue(is_ok2)
        self.assertEqual(reason2, "SPREAD_OPTIMAL")

    def test_dynamic_atr_tp_sizing(self):
        """Verify that take-profit scales dynamically between 0.20% and 0.40% based on ATR."""
        idx = pd.date_range("2026-09-16 09:30", periods=20, freq="15min")
        # Low volatility: range = 1.0 on price 5000 (~0.02% ATR)
        low_vol_df = pd.DataFrame({
            "high": [5001.0] * 20,
            "low": [5000.0] * 20,
            "close": [5000.5] * 20,
            "open": [5000.2] * 20,
        }, index=idx)
        tp_low = self.engine.compute_dynamic_atr_target(low_vol_df)
        self.assertAlmostEqual(tp_low, 0.0020, places=4, msg="Low volatility should hit min 0.20% TP")

        # High volatility: range = 50.0 on price 5000 (~1.0% ATR)
        high_vol_df = pd.DataFrame({
            "high": [5050.0] * 20,
            "low": [5000.0] * 20,
            "close": [5025.0] * 20,
            "open": [5010.0] * 20,
        }, index=idx)
        tp_high = self.engine.compute_dynamic_atr_target(high_vol_df)
        self.assertAlmostEqual(tp_high, 0.0040, places=4, msg="High volatility should clamp to max 0.40% TP")

    def test_macro_trend_regime_blocks_downtrend(self):
        """Verify that if price is significantly below EMA50, long entry is rejected."""
        idx = pd.date_range("2026-09-16 09:30", periods=40, freq="15min")
        # Waterfall dump: prices dropping from 500 to 450
        prices = [500.0 - i * 1.5 for i in range(40)]
        downtrend_df = pd.DataFrame({"close": prices}, index=idx)
        is_ok, reason = self.engine.check_macro_trend_regime(downtrend_df)
        self.assertFalse(is_ok)
        self.assertIn("WATERFALL_DOWNTREND", reason)

    def test_two_strike_daily_circuit_breaker(self):
        """Verify that 2 losses in a single day halt trading and block execution."""
        from src.integrations.risk_guardian import guardian
        guardian.resume_trading()
        guardian.state["daily_losses_count"] = 0
        guardian.state["daily_loss_total"] = 0.0

        # Loss 1
        res1 = guardian.record_trade_result(is_loss=True, pnl_usd=-25.0)
        self.assertEqual(res1["daily_losses_count"], 1)
        self.assertFalse(res1["trading_halted"])

        # Loss 2 -> should trigger circuit breaker halt
        res2 = guardian.record_trade_result(is_loss=True, pnl_usd=-25.0)
        self.assertEqual(res2["status"], "HALTED")
        self.assertTrue(guardian.state["trading_halted"])
        self.assertIn("Daily 2-Strike", guardian.state["halt_reason"])

        # Reset guardian state after test
        guardian.resume_trading()
        guardian.state["daily_losses_count"] = 0
        guardian.state["daily_loss_total"] = 0.0
        guardian.save_state()

    def test_ctrader_client_amend_and_partial_close(self):
        """Verify amend_position_sl and close_partial_position helper methods."""
        from src.integrations.ctrader_mcp_client import CTraderMCPClient
        client = CTraderMCPClient()
        client.call_tool = MagicMock(return_value={"result": {"content": [{"type": "text", "text": "{\"positionId\": 101}"}]}})
        client.get_positions = MagicMock(return_value=[{"positionId": 101, "volume": 1000}])
        client.get_positions_strict = MagicMock(return_value=[{"positionId": 101, "volume": 1000}])

        # Amend SL to BE
        res = client.amend_position_sl(101, 5020.50)
        self.assertIsNotNone(res)
        client.call_tool.assert_called_with("amend_position", {"positionId": 101, "stopLoss": 5020.50})

        # Close 50%
        res_close = client.close_partial_position(101, fraction=0.5)
        self.assertIsNotNone(res_close)
        client.call_tool.assert_called_with("close_position", {"positionId": 101, "volume": 500})

        # Verify order ACK
        self.assertTrue(client.verify_order_ack("ACTIVE"))
        self.assertTrue(client.verify_order_ack(101))

    def test_bar_freshness_from_candle_close(self):
        """Verify that a 15m bar evaluated 30s after close passes freshness check, while a bar > 5m after close is rejected."""
        self.mock_ctrader.session_id = "test_session"
        self.mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
        self.mock_ctrader.get_positions.return_value = []
        self.mock_ctrader.get_symbol_map.return_value = {"SPX500": 113}

        # 15m candle indexed at 11:30 closes at 11:45
        idx = pd.date_range("2026-09-16 09:30", periods=9, freq="15min", tz="America/New_York")
        prices = [500.0] * 8 + [490.0] # Dip on 11:30 bar
        mock_df = pd.DataFrame({"close": prices, "open": prices, "high": prices, "low": prices}, index=idx)
        self.mock_ctrader.get_spot_price.return_value = {"ask": 490.00, "bid": 489.90}

        with patch("src.integrations.autonomous_executor.fetch_intraday_bars", return_value=mock_df):
            # Evaluated at 11:45:30 (30 seconds after close -> Fresh!)
            fresh_eval_time = idx[-1] + pd.Timedelta(minutes=15, seconds=30)
            trades_fresh = self.engine.run_cycle(dry_run=True, dt_override=fresh_eval_time)
            self.assertGreater(len(trades_fresh), 0, "15m candle evaluated 30s after close must PASS freshness check")

            # Evaluated at 11:51:00 (6 minutes after close -> Stale! max_allowed = 300s)
            stale_eval_time = idx[-1] + pd.Timedelta(minutes=21)
            trades_stale = self.engine.run_cycle(dry_run=True, dt_override=stale_eval_time)
            self.assertEqual(len(trades_stale), 0, "15m candle evaluated 6m after close must be REJECTED as stale")

if __name__ == "__main__":
    unittest.main()


