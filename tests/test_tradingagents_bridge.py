"""
Unit tests for TradingAgents Bridge and Dry Runner
"""

from unittest.mock import MagicMock, patch
import pytest

from src.integrations.tradingagents_bridge import TradingAgentsBridge
from src.integrations.tradingagents_dry_runner import TradingAgentsRunner


def test_symbol_resolution():
    bridge = TradingAgentsBridge()
    ticker, asset_type, name = bridge.resolve_symbol("BTCUSD")
    assert ticker == "BTC-USD"
    assert asset_type == "crypto"

    ticker_gold, asset_type_gold, name_gold = bridge.resolve_symbol("XAUUSD")
    assert ticker_gold == "GC=F"
    assert asset_type_gold == "commodity"

    # Forex Majors
    for fx_sym in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"):
        t, a, n = bridge.resolve_symbol(fx_sym)
        assert t == f"{fx_sym}=X"
        assert a == "forex"
        assert len(n) > 0


def test_calculate_lot_and_stops_forex():
    runner = TradingAgentsRunner(dry_run=True)
    # 5-decimal standard pair: EURUSD
    eur_stops = runner.calculate_lot_and_stops(
        symbol="EURUSD",
        action="BUY",
        spot_price=1.12000,
        extracted_targets={"stop_loss": None, "take_profit": None}
    )
    assert eur_stops["ticket1"]["lot_size"] == 0.05
    assert eur_stops["ticket2"]["lot_size"] == 0.07
    assert eur_stops["lot_size"] == 0.05
    assert eur_stops["stop_loss"] == 1.11750  # 25 pips below 1.12000
    assert eur_stops["take_profit"] == 1.12400  # 40 pips TP1
    assert eur_stops["ticket2"]["take_profit"] == 1.12750  # 75 pips TP2 runner
    assert eur_stops["est_risk_usd"] <= 35.0  # Safe for $180 daily limit

    # 3-decimal JPY pair: USDJPY
    jpy_stops = runner.calculate_lot_and_stops(
        symbol="USDJPY",
        action="SELL",
        spot_price=155.000,
        extracted_targets={"stop_loss": None, "take_profit": None}
    )
    assert jpy_stops["ticket1"]["lot_size"] == 0.05
    assert jpy_stops["ticket2"]["lot_size"] == 0.07
    assert jpy_stops["stop_loss"] == 155.300  # 30 pips above
    assert jpy_stops["est_risk_usd"] <= 35.0


def test_rating_to_action():
    bridge = TradingAgentsBridge()
    assert bridge._rating_to_action("Buy") == "BUY"
    assert bridge._rating_to_action("Overweight") == "BUY"
    assert bridge._rating_to_action("Sell") == "SELL"
    assert bridge._rating_to_action("Underweight") == "SELL"
    assert bridge._rating_to_action("Hold") == "HOLD"
    assert bridge._rating_to_action("REVIEW") == "HOLD"


def test_price_targets_extraction():
    bridge = TradingAgentsBridge()
    text = "We recommend an entry with Stop-Loss at $2650.50 and Target Price: $2750.00."
    targets = bridge._extract_price_targets(text)
    assert targets["stop_loss"] == 2650.50
    assert targets["take_profit"] == 2750.00


def test_calculate_lot_and_stops():
    runner = TradingAgentsRunner(dry_run=True)
    # Test Gold Sizing
    gold_stops = runner.calculate_lot_and_stops(
        symbol="XAUUSD",
        action="BUY",
        spot_price=4000.0,
        extracted_targets={"stop_loss": 3980.0, "take_profit": 4040.0}
    )
    assert gold_stops["ticket1"]["lot_size"] == 0.05
    assert gold_stops["ticket2"]["lot_size"] == 0.07
    assert gold_stops["stop_loss"] <= 4000.0
    assert gold_stops["est_risk_usd"] <= 35.0  # Mathematically clamped to <= $35.00


def test_runner_dry_run_cycle():
    mock_bridge = MagicMock()
    mock_bridge.analyze_symbol.return_value = {
        "success": True,
        "broker_symbol": "BTCUSD",
        "rating": "Buy",
        "action": "BUY",
        "decision_text": "Strong breakout momentum confirmed by multiple analysts.",
        "extracted_targets": {"stop_loss": None, "take_profit": None},
        "bull_summary": "Institutional accumulation on-chain.",
        "bear_summary": "Short-term funding rate elevated.",
    }

    mock_ctrader = MagicMock()
    mock_ctrader.initialize.return_value = True
    mock_ctrader.get_balance.return_value = {"balance": 6079.57, "equity": 6079.57}
    mock_ctrader.get_positions.return_value = []
    mock_ctrader.get_spot_price.return_value = {"bid": 80500.0, "ask": 80510.0}

    runner = TradingAgentsRunner(
        bridge=mock_bridge,
        ctrader_client=mock_ctrader,
        dry_run=True
    )

    with patch.object(runner, "send_telegram_ticket") as mock_tg:
        result = runner.run_cycle_for_symbol("BTCUSD")
        assert result["success"] is True
        ticket = result["ticket"]
        assert ticket["action"] == "BUY"
        assert ticket["status"] == "SIMULATED_FILLED"
        assert ticket["dry_run"] is True
        mock_tg.assert_called_once()


def test_config_max_tokens_budgeted():
    bridge = TradingAgentsBridge()
    assert bridge.config["max_tokens"] == 1500


def test_runner_live_order_keyword_args():
    mock_bridge = MagicMock()
    mock_bridge.analyze_symbol.return_value = {
        "success": True,
        "broker_symbol": "BTCUSD",
        "rating": "Buy",
        "action": "BUY",
        "decision_text": "Strong breakout momentum confirmed by multiple analysts.",
        "extracted_targets": {"stop_loss": 80300.0, "take_profit": 82000.0},
        "bull_summary": "Accumulation.",
        "bear_summary": "None.",
    }

    mock_ctrader = MagicMock()
    mock_ctrader.initialize.return_value = True
    mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
    mock_ctrader.get_positions.return_value = []
    mock_ctrader.get_spot_price.return_value = {"bid": 80500.0, "ask": 80510.0}
    mock_ctrader.place_market_order.return_value = {"orderId": 9999, "isError": False}

    runner = TradingAgentsRunner(
        bridge=mock_bridge,
        ctrader_client=mock_ctrader,
        dry_run=False
    )

    with patch.object(runner, "send_telegram_ticket"):
        result = runner.run_cycle_for_symbol("BTCUSD")
        assert result["success"] is True
        assert mock_ctrader.place_market_order.call_count == 2
        t1_ticket = result["ticket"]["ticket1"]
        t2_ticket = result["ticket"]["ticket2"]
        mock_ctrader.place_market_order.assert_any_call(
            symbol="BTCUSD",
            side="BUY",
            volume_lots=0.05,
            stop_loss_price=t1_ticket["stop_loss"],
            take_profit_price=t1_ticket["take_profit"],
            comment="TradingAgents-Buy-T1"
        )
        mock_ctrader.place_market_order.assert_any_call(
            symbol="BTCUSD",
            side="BUY",
            volume_lots=0.07,
            stop_loss_price=t2_ticket["stop_loss"],
            take_profit_price=t2_ticket["take_profit"],
            comment="TradingAgents-Buy-T2"
        )

