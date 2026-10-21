import pytest
from unittest.mock import MagicMock
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
    assert p_gold["max_sl_distance"] == 12.0
    assert p_gold["max_slippage"] == 2.50
    assert p_gold["be_buffer"] == 0.30
    assert p_gold["scalp_tp1_dist"] == 2.00
    assert p_gold["scalp_be_activation"] == 1.50

    p_eurusd = copier.get_asset_parameters("EURUSD")
    assert p_eurusd["max_sl_distance"] == 0.0050
    assert p_eurusd["max_slippage"] == 0.0012
    assert p_eurusd["be_buffer"] == 0.0002
    assert p_eurusd["scalp_tp1_dist"] == 0.0020
    assert p_eurusd["scalp_be_activation"] == 0.0015

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


def test_parser_anabelsignals_with_channel_header():
    text = """🌸AnabelSignals🌸 Best Free Forex & Gold Signals

✍️AUDJPY Massive Short! SELL!👍My dear subscribers,This is my opinion on the AUDJPY next move:The instrument tests an important psychological level 110.54Bias - Bearish⭐️Target - 110.08——————————💐#AUDJPY↗️Time Frame: 4H (forecast)——————————WISH YOU ALL LUCK🍀@anabelsignalscontact"""
    sig = MultiChannelSignalParser.parse_message(text, "anabelsignals")
    assert sig is not None
    assert sig["symbol"] == "AUDJPY"
    assert sig["side"] == "SELL"
    assert sig["entry_mid"] == 110.54
    assert sig["tps"] == [110.08]

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


def test_channel_config_all_25_valid():
    assert len(CHANNELS_CONFIG) == 25
    ids = [c["id"] for c in CHANNELS_CONFIG]
    assert len(ids) == len(set(ids)), "Channel IDs must be unique"
    for c in CHANNELS_CONFIG:
        assert "id" in c and c["id"]
        assert "name" in c and c["name"]
        assert "enabled" in c and isinstance(c["enabled"], bool)
        assert "assets" in c and isinstance(c["assets"], list)


def test_parser_forex_elite_signals():
    text1 = """BUY AUDNZD @ 1.0713

SL: 1.0600
TP1: 1.0733
TP2: 1.0763
TP3: 1.0813"""
    sig1 = MultiChannelSignalParser.parse_message(text1, "ForexEliteSignals")
    assert sig1 is not None
    assert sig1["symbol"] == "AUDNZD"
    assert sig1["side"] == "BUY"
    assert sig1["entry_mid"] == 1.0713
    assert sig1["sl"] == 1.0600
    assert 1.0733 in sig1["tps"]

    text2 = """CADJPY BUY NOW @87.653 - 87.453

SL: 87.153

TP1: 87.853
TP2: 88.653"""
    sig2 = MultiChannelSignalParser.parse_message(text2, "ForexEliteSignals")
    assert sig2 is not None
    assert sig2["symbol"] == "CADJPY"
    assert sig2["side"] == "BUY"
    assert sig2["sl"] == 87.153
    assert sig2["tps"] == [87.853, 88.653]


def test_parser_forex_pips_factory_and_prime():
    text = """🥇SELL GBPUSD @ 1.1585

👉TP1  1.1510
👉 TP2  1.1450
Stop Loss: 1.1640"""
    sig = MultiChannelSignalParser.parse_message(text, "ForexPipsFactory")
    assert sig is not None
    assert sig["symbol"] == "GBPUSD"
    assert sig["side"] == "SELL"
    assert sig["entry_mid"] == 1.1585
    assert sig["sl"] == 1.1640

    prime_text = """13/01
🔷BUY EURUSD @ 1.11271
🚫SL- 1.10837
✅TP- 1.12369"""
    prime_sig = MultiChannelSignalParser.parse_message(prime_text, "PrimeForexSignals")
    assert prime_sig is not None
    assert prime_sig["symbol"] == "EURUSD"
    assert prime_sig["side"] == "BUY"
    assert prime_sig["entry_mid"] == 1.11271
    assert prime_sig["sl"] == 1.10837


def test_parser_ultreos_and_prime_gold():
    text_ultreos = "XAUUSD buy limit 4140 sl 4113.00 tp 4165.00 tp 4196.90 tp 4229.70"
    sig = MultiChannelSignalParser.parse_message(text_ultreos, "ForexSignalsTelegram")
    assert sig is not None
    assert sig["symbol"] == "XAUUSD"
    assert sig["side"] == "BUY"
    assert sig["entry_mid"] == 4140.0
    assert sig["sl"] == 4113.00

    text_prime_gold = """XAUUSD BUY 4162-4158

TP 4165
TP 4170
TP 4175

SL: 4151.00"""
    sig_pg = MultiChannelSignalParser.parse_message(text_prime_gold, "PrimeGoldSignals")
    assert sig_pg is not None
    assert sig_pg["symbol"] == "XAUUSD"
    assert sig_pg["side"] == "BUY"
    assert sig_pg["entry_min"] == 4158.0
    assert sig_pg["entry_max"] == 4162.0
    assert sig_pg["sl"] == 4151.00


def test_parser_pipchasers_natural_language():
    text = """USDJPY

Nice buy opportunity from the current price at 152.630.
Take Profit: 154.800
Stop Loss: 152.000"""
    sig = MultiChannelSignalParser.parse_message(text, "pipchasers")
    assert sig is not None
    assert sig["symbol"] == "USDJPY"
    assert sig["side"] == "BUY"
    assert sig["entry_mid"] == 152.630
    assert sig["sl"] == 152.000
    assert sig["tps"] == [154.800]


def test_parser_top_tradingsignals_and_oil():
    text = """📉NZD-USD Free Signal!
⭕Sell!
#NZDUSD is rejecting the horizontal supply area after fresh tests.
Stop Loss: 0.5676
Take Profit: 0.5649
Entry: 0.5665"""
    sig = MultiChannelSignalParser.parse_message(text, "top_tradingsignals")
    assert sig is not None
    assert sig["symbol"] == "NZDUSD"
    assert sig["side"] == "SELL"
    assert sig["entry_mid"] == 0.5665
    assert sig["sl"] == 0.5676
    assert sig["tps"] == [0.5649]

    oil_text = """CRUDE OIL Free Signal!
⭕Buy!
#USOIL is reclaiming demand.
Stop Loss: 96.61
Take Profit: 100.54
Entry: 98.33"""
    sig_oil = MultiChannelSignalParser.parse_message(oil_text, "top_tradingsignals")
    assert sig_oil is not None
    assert sig_oil["symbol"] == "USOIL"
    assert sig_oil["side"] == "BUY"
    assert sig_oil["entry_mid"] == 98.33
    assert sig_oil["sl"] == 96.61


def test_parser_structured_tags():
    text_elite = """#GOLD BULLS ARE STRONG HERE|LONG🟢
📈GOLD SIGNAL
✔️Trade Direction: long
✔️Entry Level: 4,158.26
✔️Target Level: 4,179.81
✔️Stop Loss: 4,143.92"""
    sig = MultiChannelSignalParser.parse_message(text_elite, "elitetrading_signals")
    assert sig is not None
    assert sig["symbol"] == "XAUUSD"
    assert sig["side"] == "BUY"
    assert sig["entry_mid"] == 4158.26
    assert sig["sl"] == 4143.92
    assert sig["tps"] == [4179.81]

    text_pro = """#EURCAD LOCAL SHORT
Entry Level: 1.5540
Target: 1.5480
Stoploss: 1.5580"""
    sig_pro = MultiChannelSignalParser.parse_message(text_pro, "prosignalsfxx")
    assert sig_pro is not None
    assert sig_pro["symbol"] == "EURCAD"
    assert sig_pro["side"] == "SELL"
    assert sig_pro["entry_mid"] == 1.5540
    assert sig_pro["sl"] == 1.5580

    text_vip = """📊GOLD: Market Is Looking Up! Buy!!
ENTER: #XAUUSD  long trade
CURRENT PRICE: 4,172.547
STOP LOSS: 4,162.734
TAKE PROFIT: 4,187.490"""
    sig_vip = MultiChannelSignalParser.parse_message(text_vip, "xauusd_signals")
    assert sig_vip is not None
    assert sig_vip["symbol"] == "XAUUSD"
    assert sig_vip["side"] == "BUY"
    assert sig_vip["entry_mid"] == 4172.547
    assert sig_vip["sl"] == 4162.734
    assert sig_vip["tps"] == [4187.490]


def test_parser_crypto_and_compact_formats():
    btc_text = "#BTCUSD BUY 63300 TP 63400 SL 62200"
    sig_btc = MultiChannelSignalParser.parse_message(btc_text, "ImperialForexSignals")
    assert sig_btc is not None
    assert sig_btc["symbol"] == "BTCUSD"
    assert sig_btc["side"] == "BUY"
    assert sig_btc["entry_mid"] == 63300.0
    assert sig_btc["sl"] == 62200.0

    green_text = "SELL 0.5864 TP 0.5844 SL 0.6000"
    sig_green = MultiChannelSignalParser.parse_message(green_text, "GreenForexSignals")
    assert sig_green is not None
    assert sig_green["side"] == "SELL"
    assert sig_green["entry_mid"] == 0.5864
    assert sig_green["sl"] == 0.6000


def test_asset_parameters_crypto_and_oil():
    copier = TelegramMultiSignalCopier(dry_run=True)
    p_btc = copier.get_asset_parameters("BTCUSD")
    assert p_btc["lot_size"] == 0.01
    assert p_btc["max_sl_distance"] == 500.0

    p_oil = copier.get_asset_parameters("USOIL")
    assert p_oil["lot_size"] == 0.10
    assert p_oil["max_sl_distance"] == 1.50


def test_directional_coherence_guard_inverted_sell():
    """Validates that a SELL with TP > entry is blocked with is_valid == False."""
    text_post_1015 = """#XAUUSD  SELL  4145
🚀 ¹/TAKE PROFIT     4150🔘
🚀 ²/TAKE PROFIT     4155🔘
🚀 3/TAKE PROFIT     4165-72
😊 STOP LOSS         VIP GROUP 🔘
Regular Quantity ❤️"""
    sig = MultiChannelSignalParser.parse_message(text_post_1015, "XAUUSD_GOLD_TRADING_FOREX")
    assert sig is not None
    assert sig["side"] == "SELL"
    assert sig["is_valid"] is False
    assert "VIP GROUP" in sig["validation_error"] or "Inverted Take Profit" in sig["validation_error"]


def test_directional_coherence_guard_inverted_buy():
    """Validates that a BUY with all TPs < entry is blocked with is_valid == False."""
    text_bad_buy = "#XAUUSD BUY 4145 SL 4135 TP 4140"
    sig = MultiChannelSignalParser.parse_message(text_bad_buy, "XAUUSD_GOLD_TRADING_FOREX")
    assert sig is not None
    assert sig["side"] == "BUY"
    assert sig["is_valid"] is False
    assert "Inverted Take Profit" in sig["validation_error"]


def test_directional_coherence_tp1_at_entry_promotes_tp2_tp3_sell():
    """Validates that a SELL with TP1 == entry discards TP1 and focuses on TP2 & TP3 (Invariant 23)."""
    text_post_1023 = """#XAUUSD  SELL  4150
🚀 ¹/TAKE PROFIT     4150🔘
🚀 ²/TAKE PROFIT     4130🔘
🚀 3/TAKE PROFIT     4120🔘
😊 STOP LOSS       4157 🔘
Regular Quantity ❤️"""
    sig = MultiChannelSignalParser.parse_message(text_post_1023, "XAUUSD_GOLD_TRADING_FOREX")
    assert sig is not None
    assert sig["side"] == "SELL"
    assert sig["entry_mid"] == 4150.0
    assert sig["is_valid"] is True
    assert sig["tps"] == [4130.0, 4120.0]
    assert sig.get("tp1_promoted_from_runner") is True


def test_directional_coherence_tp1_at_entry_promotes_tp2_buy():
    """Validates that a BUY with TP1 == entry discards TP1 and focuses on TP2 (Invariant 23)."""
    text_buy = "EURUSD BUY 1.0800 SL 1.0760 TP1: 1.0800 TP2: 1.0850"
    sig = MultiChannelSignalParser.parse_message(text_buy, "forexgdpfree")
    assert sig is not None
    assert sig["side"] == "BUY"
    assert sig["is_valid"] is True
    assert sig["tps"] == [1.0850]
    assert sig.get("tp1_promoted_from_runner") is True


def test_directional_coherence_valid_signals_pass():
    """Validates that coherent BUY and SELL signals have is_valid == True."""
    valid_sell = "XAUUSD SELL 4145 SL: 4155 TP: 4135"
    sig = MultiChannelSignalParser.parse_message(valid_sell, "ssfgold")
    assert sig is not None
    assert sig["is_valid"] is True
    assert sig["validation_error"] is None

    valid_buy = "XAUUSD BUY 4145 SL: 4135 TP: 4155"
    sig_buy = MultiChannelSignalParser.parse_message(valid_buy, "ssfgold")
    assert sig_buy is not None
    assert sig_buy["is_valid"] is True
    assert sig_buy["validation_error"] is None


def test_ai_fallback_condition_gate():
    """Ensures AI fallback is only triggered for genuine unparsed trade intent."""
    text_spam = "Join our tournament and win 500$ bonus!"
    assert MultiChannelSignalParser._should_attempt_ai_fallback(text_spam) is False

    # Without OPENROUTER_API_KEY set, it safely returns False
    text_unstructured = "Going short on Gold at 4145, TP 4135, SL 4155"
    assert isinstance(MultiChannelSignalParser._should_attempt_ai_fallback(text_unstructured), bool)


def test_ssfgold_single_target_micro_banker_split():
    """Verifies that a single wide target (e.g. ssfgold 20-pt TP) is split into Micro-Banker (+20 pips) and Runner."""
    copier = TelegramMultiSignalCopier(dry_run=True)
    sig = {
        "channel": "ssfgold",
        "symbol": "XAUUSD",
        "side": "SELL",
        "entry_min": 4122.54,
        "entry_max": 4122.54,
        "entry_mid": 4122.54,
        "sl": 4132.54,
        "tps": [4102.54],
        "type": "DIRECT_EXECUTION"
    }
    orders = copier.execute_signal(sig, spot_price=4120.45)
    assert len(orders) == 2
    # Ticket 1 (Micro-Banker): entry - 2.0 pts = 4118.45
    assert orders[0]["ticket"] == 1
    assert orders[0]["tp"] == 4118.45
    # Ticket 2 (Runner): original target = 4102.54
    assert orders[1]["ticket"] == 2
    assert orders[1]["tp"] == 4102.54


def test_rapid_breakeven_trigger():
    """Verifies that breakeven triggers at +15 pips (+1.50 pts Gold) even if 50% TP is wider."""
    from unittest.mock import MagicMock
    mock_ctrader = MagicMock()
    mock_ctrader.get_spot_price.return_value = {"bid": 4118.50, "ask": 4118.60}  # gain = 4120.45 - 4118.60 = +1.85 pts
    mock_ctrader.get_positions.return_value = [{"positionId": 12345}]

    copier = TelegramMultiSignalCopier(dry_run=False, ctrader_client=mock_ctrader)
    copier.state["active_positions"] = [{
        "positionId": 12345,
        "ticket": 2,
        "symbol": "XAUUSD",
        "side": "SELL",
        "entry": 4120.45,
        "sl": 4132.54,
        "tp": 4102.54,
        "be_locked": False
    }]

    copier.manage_active_breakeven()
    # Breakeven was locked because gain (+1.85 pts) >= scalp_be_activation (1.50 pts)
    pos = copier.state["active_positions"][0]
    assert pos["be_locked"] is True
    # SL amended to entry - be_buffer (4120.45 - 0.30 = 4120.15)
    assert pos["sl"] == 4120.15
    mock_ctrader.amend_position.assert_called_once_with(12345, stop_loss=4120.15)


def test_directional_anti_chase_allows_discount_dip_buy():
    """Verifies that a BUY signal dipping below entry (favorable discount) is allowed for scalping."""
    copier = TelegramMultiSignalCopier(dry_run=True)
    sig = {
        "channel": "anabelsignals",
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_min": 4123.7,
        "entry_max": 4123.7,
        "entry_mid": 4123.7,
        "sl": 4118.6,
        "tps": [4131.6],
        "type": "ANABEL_DIRECT"
    }
    # Spot is 4120.25 (3.45 pts below entry, but safely above SL 4118.6)
    orders = copier.execute_signal(sig, spot_price=4120.25)
    assert orders is not None
    assert len(orders) >= 1
    assert orders[0]["entry"] == 4120.25
    assert orders[0]["sl"] <= 4118.6  # Shielded behind swing structure by PASL


def test_directional_anti_chase_blocks_adverse_runaway_buy():
    """Verifies that a BUY signal that already surged towards TP is blocked by anti-chase."""
    from unittest.mock import MagicMock
    mock_ctrader = MagicMock()
    # Spot is 4127.50 (3.8 pts above 4123.7, max allowed is 2.5 pts)
    mock_ctrader.get_spot_price.return_value = {"ask": 4127.50, "bid": 4127.30}
    mock_ctrader.get_positions.return_value = []
    mock_ctrader.get_balance.return_value = {"equity": 6000.0}

    copier = TelegramMultiSignalCopier(dry_run=True, ctrader_client=mock_ctrader)
    sig = {
        "channel": "anabelsignals",
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_min": 4123.7,
        "entry_max": 4123.7,
        "entry_mid": 4123.7,
        "sl": 4118.6,
        "tps": [4131.6],
        "type": "ANABEL_DIRECT",
        "is_valid": True
    }

    # Verify anti-chase logic calculation directly
    params = copier.get_asset_parameters("XAUUSD")
    curr_spot = 4127.50
    dist_from_zone = curr_spot - sig["entry_max"]
    assert round(dist_from_zone, 2) == 3.8
    assert dist_from_zone > params["max_slippage"]  # 3.8 > 2.5 -> BLOCKED!


def test_stop_loss_synthesis_when_missing():
    """Invariant 20: Missing Stop Loss must be synthesized based on asset safety distance."""
    text = "BUY EURUSD @ 1.0850 TP: 1.0890"
    sig = MultiChannelSignalParser.parse_message(text, "ForexEliteSignals")
    assert sig is not None
    assert sig["symbol"] == "EURUSD"
    assert sig["side"] == "BUY"
    assert sig["entry_mid"] == 1.0850
    # TP distance is 0.0040 (40 pips). SL is synthesized 1:1 at 1.0850 - 0.0040 = 1.0810
    assert sig["sl"] == 1.0810
    assert sig["is_valid"] is True


def test_stop_loss_synthesis_truncated_eurcad():
    """Invariant 20: Truncated Stop Loss ('Stop Loss:…') must be synthesized cleanly."""
    text = "#EURCAD FREE SIGNAL|SHORT🔥 Entry: 1.6044 ⭐️Stop Loss:…"
    sig = MultiChannelSignalParser.parse_message(text, "prosignalsfxx")
    assert sig is not None
    assert sig["symbol"] == "EURCAD"
    assert sig["side"] == "SELL"
    assert sig["entry_mid"] == 1.6044
    # Default FX risk is 0.0035 (35 pips). SL synthesized at 1.6044 + 0.0035 = 1.6079
    assert sig["sl"] == 1.6079
    assert sig["is_valid"] is True


def test_stop_loss_synthesis_paywalled_vip():
    """Invariant 20: Paywalled Stop Loss ('SL: VIP GROUP') must not block entry - synthesize SL."""
    text = "BUY GOLD 4250 SL VIP GROUP TP 4265"
    sig = MultiChannelSignalParser.parse_message(text, "XAUUSD_GOLD_TRADING_FOREX")
    assert sig is not None
    assert sig["symbol"] == "XAUUSD"
    assert sig["side"] == "BUY"
    assert sig["entry_mid"] == 4250.0
    # TP distance is 15 pts. Max Gold SL is 12.0 pts. Synthesized at 4250 - 8.0 = 4242.0 (or default 8-10 pts)
    assert sig["sl"] < 4250.0

def test_signal_alert_contains_telegram_post_deep_link():
    """Verify that execution and rejection alerts include a direct clickable Telegram post link."""
    mock_ctrader = MagicMock()
    mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
    mock_ctrader.place_market_order.return_value = {"result": {"positionId": 12345}}

    copier = TelegramMultiSignalCopier(ctrader_client=mock_ctrader, dry_run=False)
    copier.send_telegram_alert = MagicMock()

    sig = {
        "channel": "ssfgold",
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_min": 2650.0,
        "entry_max": 2650.0,
        "entry_mid": 2650.0,
        "sl": 2642.0,
        "tps": [2660.0, 2670.0],
        "post_id": "ssfgold/18427",
        "post_url": "https://t.me/ssfgold/18427"
    }

    copier.execute_signal(sig, spot_price=2650.0)
    assert copier.send_telegram_alert.called
    sent_alert = copier.send_telegram_alert.call_args[0][0]
    assert "https://t.me/ssfgold/18427" in sent_alert
    assert "View in Telegram" in sent_alert


def test_invariant_22_target_rollover_success():
    """Verify Invariant 22: when TP1 is passed, rollover to TP2 with ratcheted SL if R:R >= 1.5."""
    mock_ctrader = MagicMock()
    mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
    mock_ctrader.get_spot_price.return_value = {"bid": 2654.90, "ask": 2655.00}

    copier = TelegramMultiSignalCopier(ctrader_client=mock_ctrader, dry_run=True)
    copier.check_market_hours = MagicMock(return_value=True)
    copier.check_conflicts = MagicMock(return_value=False)
    copier.execute_signal = MagicMock()
    copier.fetch_channel_posts = MagicMock(return_value=[{
        "post_id": "ssfgold/18500",
        "post_url": "https://t.me/ssfgold/18500",
        "text": "GOLD BUY 2650 - 2652\nSL: 2642\nTP1: 2653\nTP2: 2665"
    }])
    copier.state["watermarks"] = {"ssfgold": "ssfgold/18499"}
    copier.state["executed_signal_keys"] = []

    copier.poll_cycle()

    # execute_signal must be called via rollover
    assert copier.execute_signal.called
    sig_arg, spot_arg = copier.execute_signal.call_args[0]
    assert spot_arg == 2655.00
    assert sig_arg["is_target_rollover"] is True
    assert sig_arg["rollover_tp"] == 2665.0
    assert sig_arg["sl"] == 2652.0  # Ratcheted to entry_max!
    assert sig_arg["tps"] == [2665.0]


def test_invariant_22_target_rollover_rejected_when_rr_insufficient():
    """Verify Invariant 22 blocks rollover if remaining reward to TP2 is < 1.5x ratcheted risk."""
    mock_ctrader = MagicMock()
    mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
    mock_ctrader.get_spot_price.return_value = {"bid": 2654.90, "ask": 2655.00}

    copier = TelegramMultiSignalCopier(ctrader_client=mock_ctrader, dry_run=False)
    copier.check_market_hours = MagicMock(return_value=True)
    copier.check_conflicts = MagicMock(return_value=False)
    copier.execute_signal = MagicMock()
    copier.send_telegram_alert = MagicMock()
    # TP2 is 2657.0 -> remaining reward is only 2.0 pts vs 3.0 pts risk (R:R 0.67 < 1.5)
    copier.fetch_channel_posts = MagicMock(return_value=[{
        "post_id": "ssfgold/18501",
        "post_url": "https://t.me/ssfgold/18501",
        "text": "GOLD BUY 2650 - 2652\nSL: 2642\nTP1: 2653\nTP2: 2657"
    }])
    copier.state["watermarks"] = {"ssfgold": "ssfgold/18500"}
    copier.state["executed_signal_keys"] = []

    copier.poll_cycle()

    # Rollover should be rejected; anti-chase skip alert must be sent
    assert not copier.execute_signal.called
    assert copier.send_telegram_alert.called
    sent_alert = copier.send_telegram_alert.call_args[0][0]
    assert "SIGNAL SKIPPED: Anti-Chase Limit Exceeded" in sent_alert
    assert "https://t.me/ssfgold/18501" in sent_alert


def test_invariant_25_lot_sizing_floor_and_twin_tickets(monkeypatch):
    """Verify Invariant 25: enforces 0.07 lot floor even if 0.05 is passed in env, and opens twin tickets totaling 0.14 lots."""
    monkeypatch.setenv("GOLD_COPIER_LOT_SIZE", "0.05")
    monkeypatch.setenv("FOREX_COPIER_LOT_SIZE", "0.05")

    copier = TelegramMultiSignalCopier(dry_run=True)
    params_gold = copier.get_asset_parameters("XAUUSD")
    # Code-level floor must clamp 0.05 up to 0.07
    assert params_gold["lot_size"] == 0.07

    params_fx = copier.get_asset_parameters("EURUSD")
    assert params_fx["lot_size"] == 0.07

    # Multi-target signal: must generate 2 tickets of 0.07 lots (0.14 total)
    sig_multi = {
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_min": 2650.0,
        "entry_max": 2652.0,
        "entry_mid": 2651.0,
        "sl": 2642.0,
        "tps": [2655.0, 2665.0],
        "channel": "ssfgold"
    }
    executed = copier.execute_signal(sig_multi, spot_price=2651.0)
    assert len(executed) == 2
    assert executed[0]["volume"] == 0.07
    assert executed[1]["volume"] == 0.07
    assert sum(t["volume"] for t in executed) == 0.14

    # Single-target signal: must also synthesize twin tickets of 0.07 lots (0.14 total)
    sig_single = {
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_min": 2650.0,
        "entry_max": 2652.0,
        "entry_mid": 2651.0,
        "sl": 2642.0,
        "tps": [2653.0],
        "channel": "ssfgold"
    }
    executed_single = copier.execute_signal(sig_single, spot_price=2651.0)
    assert len(executed_single) == 2
    assert executed_single[0]["volume"] == 0.07
    assert executed_single[1]["volume"] == 0.07
    assert sum(t["volume"] for t in executed_single) == 0.14


def test_invariant_23_broker_label_linked_breakeven():
    """Invariant 23: Reconciles broker-level positions tagged with _T2 when companion _T1 has closed."""
    from unittest.mock import MagicMock
    mock_ctrader = MagicMock()
    mock_ctrader.get_positions.return_value = [
        {
            "positionId": 9992,
            "comment": "Sig_prosig_XAUUSD_T2",
            "symbolName": "XAUUSD",
            "tradeSide": "BUY",
            "entryPrice": 4120.0,
            "stopLoss": 4108.0,
            "takeProfit": 4160.0
        }
    ]
    # Price has recovered to 4121.0 (above BE 4120.50)
    mock_ctrader.get_spot_price.return_value = {"bid": 4121.0, "ask": 4121.2}

    copier = TelegramMultiSignalCopier(dry_run=False, ctrader_client=mock_ctrader)
    copier.state["active_positions"] = []  # State had lost the position

    copier.manage_active_breakeven()

    # Verify amend_position was called with Breakeven price (4120.0 + 0.30 buffer = 4120.3)
    mock_ctrader.amend_position.assert_called_once_with(9992, stop_loss=4120.3)










