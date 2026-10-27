"""
Unit tests for CADCHF Decimal Precision, Informal Forecast Rejection, and Anti-Suffocation Shields
"""

import pytest
from src.integrations.ctrader_mcp_client import CTraderMCPClient
from src.integrations.telegram_multi_signal_copier import MultiChannelSignalParser, TelegramMultiSignalCopier


def test_get_symbol_digits_forex_crosses():
    """Verify get_symbol_digits accurately resolves 5 decimals for FX crosses and 3 for JPY."""
    client = CTraderMCPClient()
    
    # Forex crosses without USD/EUR/GBP
    assert client.get_symbol_digits("CADCHF") == 5
    assert client.get_symbol_digits("AUDCAD") == 5
    assert client.get_symbol_digits("NZDCAD") == 5
    assert client.get_symbol_digits("AUDNZD") == 5
    
    # JPY crosses
    assert client.get_symbol_digits("CHFJPY") == 3
    assert client.get_symbol_digits("CADJPY") == 3
    assert client.get_symbol_digits("USDJPY") == 3
    assert client.get_symbol_digits("EURJPY") == 3
    
    # Forex majors
    assert client.get_symbol_digits("EURUSD") == 5
    assert client.get_symbol_digits("GBPUSD") == 5
    assert client.get_symbol_digits("USDCAD") == 5
    
    # Metals, Indices, Crypto
    assert client.get_symbol_digits("XAUUSD") == 2
    assert client.get_symbol_digits("GOLD") == 2
    assert client.get_symbol_digits("BTCUSD") == 2
    assert client.get_symbol_digits("SPX500") == 2
    assert client.get_symbol_digits("US30") == 1


def test_informal_forecast_rejection():
    """Verify that informal market forecasts and outlooks without explicit SL are rejected."""
    raw_cadchf_post = """📈CADCHF Will Go Lower From Resistance! Sell!🔻
- - - - - - - - 
Here is our detailed technical review for CADCHF.

The market is on a crucial zone of supply 0.589.

The above-mentioned technicals clearly indicate the dominance of sellers on the market. I recommend shorting the instrument, aiming at 0.587 level.
- - - - - - - - 
#freeforecast #cadchf
- - - - - - - -
🌐 Free Copy Trading: Link
📲Join VIP via Bot: Link 
❓Official Contact: @signalprovidercontact"""

    sig = MultiChannelSignalParser.parse_message(raw_cadchf_post, "signalsproviderfx")
    assert sig is None, "Informal commentary with #freeforecast and no explicit SL must be rejected"


def test_legitimate_signal_acceptance():
    """Verify that legitimate signals with explicit SL on CADCHF are parsed cleanly."""
    valid_cadchf_signal = """#CADCHF SELL NOW @ 0.5890
SL: 0.5925
TP1: 0.5860
TP2: 0.5830"""

    sig = MultiChannelSignalParser.parse_message(valid_cadchf_signal, "signalsproviderfx")
    assert sig is not None
    assert sig["is_valid"] is True
    assert sig["symbol"] == "CADCHF"
    assert sig["side"] == "SELL"
    assert sig["entry_mid"] == 0.5890
    assert sig["sl"] == 0.5925
    assert 0.5860 in sig["tps"]


def test_at_price_does_not_match_aiming_at():
    """Verify that 'aiming at' or 'target at' is not misclassified as an entry price."""
    text_aiming = "Sell CADCHF from resistance, aiming at 0.587 level. #freeforecast"
    sig = MultiChannelSignalParser.parse_message(text_aiming, "signalsproviderfx")
    assert sig is None


def test_anti_suffocation_guard():
    """Verify Invariant 36: orders with SL inside noise floor are aborted before execution."""
    copier = TelegramMultiSignalCopier(dry_run=True)
    copier.ctrader.get_trendbars_dataframe = lambda *args, **kwargs: None
    copier.ctrader.get_spot_price = lambda *args, **kwargs: {"bid": 0.58996, "ask": 0.58998}
    
    # Signal with SL only 3 pips away (0.59020 vs spot 0.58996 -> dist 0.00024 < min_noise_floor 0.00150)
    suffocated_sig = {
        "channel": "test_ch",
        "symbol": "CADCHF",
        "side": "SELL",
        "entry_min": 0.5899,
        "entry_max": 0.5901,
        "entry_mid": 0.5900,
        "sl": 0.59020,
        "tps": [0.5850],
        "type": "DIRECT"
    }
    
    res = copier.execute_signal(suffocated_sig, spot_price=0.58996)
    assert res is None, "Order must be aborted when SL is inside the physical noise floor"
    
    # Safe signal with SL 35 pips away (0.59350 vs spot 0.58996 -> dist 0.00354 > min_noise_floor 0.00150)
    safe_sig = {
        "channel": "test_ch",
        "symbol": "CADCHF",
        "side": "SELL",
        "entry_min": 0.5898,
        "entry_max": 0.5901,
        "entry_mid": 0.5900,
        "sl": 0.59350,
        "tps": [0.5850],
        "type": "DIRECT"
    }
    res_safe = copier.execute_signal(safe_sig, spot_price=0.58996)
    assert res_safe is not None, "Order with safe structural SL must be executed"
    assert len(res_safe) > 0
