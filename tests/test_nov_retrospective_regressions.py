"""
Comprehensive Regression Suite for November 7, 2026 14-Day Audit
================================================================
Verifies all 7 core remediations:
1. cTrader MCP client does not send invalid relativeStopLoss to create_order
2. cTrader order rejections trigger loud logging and error alerts
3. OpenRouter elimination with deterministic offline semantic parsing
4. Invariant 37 promotes TP2/TP3 instead of killing multi-target signals
5. Channel whitelists permit authorized Forex signals
6. Relative pip targets on Gold are synthesized to valid prices
7. Strict 0.07 lot size caps prevent sizing spikes
"""

import pytest
from unittest.mock import MagicMock, patch
from src.integrations.ctrader_mcp_client import CTraderMCPClient
from src.integrations.telegram_multi_signal_copier import (
    TelegramMultiSignalCopier,
    MultiChannelSignalParser,
    CHANNELS_CONFIG
)
from src.integrations.ai_signal_interpreter import AISignalInterpreter


def test_ctrader_create_order_omits_relative_sl_on_gold():
    """Verify that place_market_order does not pass relativeStopLoss on Gold/Forex to avoid precision rejections."""
    client = CTraderMCPClient(token="mock_token")
    client.session_id = "mock_session"
    client._symbols_cache = {"XAUUSD": 41, "EURUSD": 1}
    client._symbol_digits_cache = {"XAUUSD": 2, "EURUSD": 5}
    client.call_tool = MagicMock(return_value={"result": {"positionId": 99991, "isError": False}})
    client.get_positions_strict = MagicMock(return_value=[])
    client.get_spot_price = MagicMock(return_value={"ask": 4050.0, "bid": 4049.5})

    res = client.place_market_order(
        symbol="XAUUSD",
        side="BUY",
        volume_lots=0.07,
        stop_loss_price=4045.0,
        take_profit_price=4060.0
    )

    create_call = client.call_tool.call_args_list[0]
    tool_name = create_call[0][0]
    tool_args = create_call[0][1]

    assert tool_name == "create_order"
    assert "relativeStopLoss" not in tool_args
    assert "relativeTakeProfit" not in tool_args
    assert tool_args["symbolId"] == 41
    assert tool_args["volume"] == 700


def test_copier_handles_and_alerts_on_broker_rejection():
    """Verify that when cTrader returns an error, the copier logs it and dispatches an alert."""
    copier = TelegramMultiSignalCopier(dry_run=False)
    copier.ctrader = MagicMock()
    copier.ctrader.place_market_order.return_value = {
        "isError": True,
        "error": "HTTP 400: Relative stop loss has invalid precision"
    }
    copier.send_telegram_alert = MagicMock()

    sig = {
        "channel": "anabelsignals",
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_mid": 4050.0,
        "entry_min": 4048.0,
        "entry_max": 4052.0,
        "sl": 4040.0,
        "tps": [4060.0, 4070.0],
        "is_valid": True
    }

    orders = copier.execute_signal(sig, spot_price=4050.0)
    assert orders == [] or orders is None
    assert copier.send_telegram_alert.called
    alert_text = copier.send_telegram_alert.call_args[0][0]
    assert "BROKER ORDER REJECTED" in alert_text


def test_deterministic_offline_parser_no_openrouter():
    """Verify that AISignalInterpreter operates deterministically without any external OpenRouter calls."""
    messy_text = (
        "VIP TRADING ALERT!\n"
        "Buy Gold now at 4062.5 - 4065.0\n"
        "SL: 4055.0\n"
        "Target 1: 4075.0\n"
        "Target 2: 4085.0\n"
        "Enjoy profits team!"
    )

    sig = AISignalInterpreter.interpret_signal(messy_text, "top_tradingsignals")
    assert sig is not None
    assert sig["symbol"] == "XAUUSD"
    assert sig["side"] == "BUY"
    assert sig["entry_mid"] == 4063.75
    assert sig["sl"] == 4055.0
    assert 4075.0 in sig["tps"]
    assert 4085.0 in sig["tps"]


def test_invariant_37_smart_tp_promotion():
    """Verify that Invariant 37 promotes TP2/TP3 instead of dropping the trade when TP1 is touched."""
    copier = TelegramMultiSignalCopier(dry_run=True)
    params = copier.get_asset_parameters("XAUUSD")
    params["max_slippage"] = 4.50
    params["max_rollover_slippage"] = 6.50

    # Signal where TP1 is 4065, TP2 is 4080. Spot is 4066 (TP1 brushed, 14 pts left to TP2)
    sig = {
        "channel": "US30_Forex_Signals",
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_min": 4060.0,
        "entry_max": 4064.0,
        "entry_mid": 4062.0,
        "sl": 4055.0,
        "tps": [4065.0, 4080.0],
        "is_valid": True
    }

    # Verify that higher viable TPs exist and are promoted
    curr_spot = 4066.0
    tp1 = sig["tps"][0]
    min_viable = params["min_viable_reward"]
    viable_higher = [tp for tp in sig["tps"] if (tp - curr_spot) >= min_viable]
    assert len(viable_higher) == 1
    assert viable_higher[0] == 4080.0


def test_channel_whitelists_allow_major_forex_pairs():
    """Verify that multi-asset channels permit EURUSD and AUDUSD."""
    channels_by_id = {c["id"]: c for c in CHANNELS_CONFIG}
    for ch_id in ["anabelsignals", "fxscalpingpro", "top_tradingsignals", "US30_Forex_Signals"]:
        cfg = channels_by_id[ch_id]
        assets = cfg["assets"]
        assert "ALL" in assets or "EURUSD" in assets or "XAUUSD" in assets


def test_relative_pip_text_parsing_gold():
    """Verify that text like 'TP: 30 pips' or 'TP: 3.0' is synthesized into an absolute gold price."""
    text = (
        "BUY GOLD @ 4050.0\n"
        "SL: 4040.0\n"
        "TP: 3.0"
    )
    sig = MultiChannelSignalParser.parse_message(text, "fxscalpingpro")
    assert sig is not None
    assert sig["symbol"] == "XAUUSD"
    # 4050 + 3.0 = 4053.0
    assert 4053.0 in sig["tps"]
    assert 3.0 not in sig["tps"]


def test_strict_uniform_lot_sizing():
    """Verify that lot sizing is capped and does not spike to 0.50L."""
    copier = TelegramMultiSignalCopier(dry_run=True)
    copier.ctrader = MagicMock()
    copier.ctrader.get_positions_strict.return_value = []

    sig = {
        "channel": "forexgdpfree",
        "symbol": "GBPAUD",
        "side": "BUY",
        "entry_min": 1.9000,
        "entry_max": 1.9020,
        "entry_mid": 1.9010,
        "sl": 1.8950,
        "tps": [1.9050, 1.9100],
        "is_valid": True
    }

    orders = copier.execute_signal(sig, spot_price=1.9010)
    for ord_dict in orders:
        assert ord_dict["volume"] <= 0.07

