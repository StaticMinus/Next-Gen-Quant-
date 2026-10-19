import pytest
from src.integrations.telegram_multi_signal_copier import (
    MultiChannelSignalParser,
    TelegramMultiSignalCopier,
    CHANNELS_CONFIG
)

def test_parser_ssfgold_direct():
    text = "XAUUSD BUY 4179.76  SL:  4169.76 TP:  4199.76 --Trade by William"
    sig = MultiChannelSignalParser.parse_message(text, "ssfgold")
    assert sig is not None
    assert sig["symbol"] == "XAUUSD"
    assert sig["side"] == "BUY"
    assert sig["entry_mid"] == 4179.76
    assert sig["sl"] == 4169.76
    assert sig["tps"] == [4199.76]
    assert sig["type"] == "DIRECT_EXECUTION"

def test_parser_ssfgold_pending_stop():
    text = "XAUUSD BUY STOP 4177.4  SL:  4167.4 TP:  4197.4 --Trade by William"
    sig = MultiChannelSignalParser.parse_message(text, "ssfgold")
    assert sig is not None
    assert sig["symbol"] == "XAUUSD"
    assert sig["side"] == "BUY"
    assert sig["entry_mid"] == 4177.4
    assert sig["sl"] == 4167.4
    assert sig["tps"] == [4197.4]
    assert sig["type"] == "DIRECT_EXECUTION"

def test_parser_forexgdp_gold():
    text = """🔽Gold Signal
SELL XAUUSD now at any price between 4173 till 4183
Target 1 : 4153
Target 2 : 4130
Target 3: 4110
Stop loss: 4205"""
    sig = MultiChannelSignalParser.parse_message(text, "forexgdpfree")
    assert sig is not None
    assert sig["symbol"] == "XAUUSD"
    assert sig["side"] == "SELL"
    assert sig["entry_min"] == 4173.0
    assert sig["entry_max"] == 4183.0
    assert sig["entry_mid"] == 4178.0
    assert sig["sl"] == 4205.0
    assert sig["tps"] == [4153.0, 4130.0, 4110.0]

def test_parser_forexgdp_forex():
    text = """🔽Forex Signal
Sell AUDNZD at any price between 1.2348 till 1.2375
Target 1: 1.2300
Target 2: 1.2235
Stop loss: 1.2436"""
    sig = MultiChannelSignalParser.parse_message(text, "forexgdpfree")
    assert sig is not None
    assert sig["symbol"] == "AUDNZD"
    assert sig["side"] == "SELL"
    assert sig["entry_min"] == 1.2348
    assert sig["entry_max"] == 1.2375
    assert sig["sl"] == 1.2436
    assert sig["tps"] == [1.2300, 1.2235]

def test_parser_learn2trade_forex():
    text = """📡 FREE SIGNAL | GBP/USD — SHORT 🔴
📍 Entry: 1.3255 – 1.3285
🎯 TP1: 1.3140
🎯 TP2: 1.3050
🛑 SL: 1.3350"""
    sig = MultiChannelSignalParser.parse_message(text, "learn2tradenews")
    assert sig is not None
    assert sig["symbol"] == "GBPUSD"
    assert sig["side"] == "SELL"
    assert sig["entry_min"] == 1.3255
    assert sig["entry_max"] == 1.3285
    assert sig["sl"] == 1.3350
    assert sig["tps"] == [1.3140, 1.3050]

def test_parser_anabelsignals_gold():
    text = """✍️GOLD What Next? BUY!
The instrument tests an important psychological level 4175.9
Bias - Bullish
——————————
⭐️Target - 4184.7
⭐️Recommended Stop Loss - 4170.0
——————————
💐#GOLD
↗️Time Frame : 30m (signal)"""
    sig = MultiChannelSignalParser.parse_message(text, "anabelsignals")
    assert sig is not None
    assert sig["symbol"] == "XAUUSD"
    assert sig["side"] == "BUY"
    assert sig["entry_mid"] == 4175.9
    assert sig["sl"] == 4170.0
    assert sig["tps"] == [4184.7]

def test_parser_rejects_spam_and_locked():
    spam1 = "📊AutoTrading Tournament📊 🔔 #Tournament 500$ To 8000$ in 4 Days"
    assert MultiChannelSignalParser.parse_message(spam1, "XAUUSD_GOLD_TRADING_FOREX") is None

    locked = "🔒 VIP FOREX SIGNAL DELIVERED (locked) ... Join Prophet VIP"
    assert MultiChannelSignalParser.parse_message(locked, "learn2tradenews") is None

    recap = "📊 Weekend Market Brief — 26 Sept 2026 Macro and geopolitical risk"
    assert MultiChannelSignalParser.parse_message(recap, "learn2tradenews") is None

def test_asset_parameters_gold_vs_forex():
    copier = TelegramMultiSignalCopier(dry_run=True)
    p_gold = copier.get_asset_parameters("XAUUSD")
    assert p_gold["max_sl_distance"] == 10.0
    assert p_gold["max_slippage"] == 2.50
    assert p_gold["be_buffer"] == 0.30

    p_eurusd = copier.get_asset_parameters("EURUSD")
    assert p_eurusd["max_sl_distance"] == 0.0050
    assert p_eurusd["max_slippage"] == 0.0012
    assert p_eurusd["be_buffer"] == 0.0002

    p_eurjpy = copier.get_asset_parameters("EURJPY")
    assert p_eurjpy["max_sl_distance"] == 0.60
    assert p_eurjpy["max_slippage"] == 0.15

def test_conflict_detection():
    copier = TelegramMultiSignalCopier(dry_run=True)
    copier.state["active_positions"] = [
        {"symbol": "XAUUSD", "side": "BUY", "positionId": 9999}
    ]
    # Opposing side should flag a conflict
    assert copier.check_conflicts("XAUUSD", "SELL") is True
    # Same side is not a directional conflict
    assert copier.check_conflicts("XAUUSD", "BUY") is False
    # Different asset is not a conflict
    assert copier.check_conflicts("EURUSD", "SELL") is False

def test_parser_anabelsignals_forecast_auto_sl():
    text = """✍️EURCAD Massive Long! BUY!
The market is trading on 1.6036 pivot level.
⭐️Target - 1.6056
—————————
💐#EURCAD
↗️Time Frame: 4H (forecast)"""
    sig = MultiChannelSignalParser.parse_message(text, "anabelsignals")
    assert sig is not None
    assert sig["symbol"] == "EURCAD"
    assert sig["side"] == "BUY"
    assert sig["entry_mid"] == 1.6036
    assert sig["tps"] == [1.6056]
    # Verified: Auto-calculated SL is attached (entry - dist = 1.6036 - 0.0020 = 1.6016)
    assert sig["sl"] == pytest.approx(1.6016, rel=1e-3)

def test_2_ticket_split_execution():
    copier = TelegramMultiSignalCopier(dry_run=True)
    sig = {
        "channel": "forexgdpfree",
        "symbol": "CADJPY",
        "side": "SELL",
        "entry_min": 111.40,
        "entry_max": 111.65,
        "entry_mid": 111.52,
        "sl": 112.30,
        "tps": [110.93, 110.30, 109.50],
        "type": "ZONE_EXECUTION"
    }
    orders = copier.execute_signal(sig, spot_price=111.50)
    assert orders[0]["ticket"] == 1
    assert orders[0]["volume"] == 0.07  # 0.07 lots Banker
    assert orders[0]["tp"] == 110.93  # Banker banks TP1
    assert orders[1]["ticket"] == 2
    assert orders[1]["volume"] == 0.07  # 0.07 lots Runner (0.07 x 2)
    assert orders[1]["tp"] == 109.50  # Runner targets deepest target (tps[-1])

def test_dry_run_suppresses_telegram_alert():
    from unittest.mock import patch
    copier = TelegramMultiSignalCopier(dry_run=True)
    sig = {
        "channel": "ssfgold",
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_min": 2650.0,
        "entry_max": 2650.0,
        "entry_mid": 2650.0,
        "sl": 2640.0,
        "tps": [2660.0],
        "type": "DIRECT_EXECUTION"
    }
    with patch.object(copier, "send_telegram_alert") as mock_alert:
        orders = copier.execute_signal(sig, spot_price=2650.0)
        assert orders is not None
        mock_alert.assert_not_called()  # Invariant verified: Zero false alerts in dry run

def test_dynamic_trailing_stop_ratchet():
    from unittest.mock import MagicMock
    mock_ctrader = MagicMock()
    copier = TelegramMultiSignalCopier(dry_run=False, ctrader_client=mock_ctrader)

    pos_id = 998877
    copier.state["active_positions"] = [{
        "positionId": pos_id,
        "ticket": 2,
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry": 2650.00,
        "sl": 2650.30,  # Already at Breakeven + buffer
        "tp": 2680.00,  # Deepest swing target
        "channel": "ssfgold",
        "be_locked": True,
        "time": "2026-10-19T10:00:00"
    }]

    mock_ctrader.get_positions.return_value = [{"positionId": pos_id}]
    # Spot moves up +6.0 pts to 2656.00 (above trailing activation of 4.0 pts)
    mock_ctrader.get_spot_price.return_value = {"bid": 2656.00, "ask": 2656.20}

    copier.manage_active_breakeven()

    # Gold trailing distance is 3.0 pts: 2656.00 - 3.00 = 2653.00
    mock_ctrader.amend_position.assert_called_with(pos_id, stop_loss=2653.00)
    assert copier.state["active_positions"][0]["sl"] == 2653.00

    # Ensure ratcheting invariant: price pullback to 2654.50 must NOT lower SL
    mock_ctrader.reset_mock()
    mock_ctrader.get_spot_price.return_value = {"bid": 2654.50, "ask": 2654.70}
    copier.manage_active_breakeven()
    mock_ctrader.amend_position.assert_not_called()
    assert copier.state["active_positions"][0]["sl"] == 2653.00



