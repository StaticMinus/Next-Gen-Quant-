import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from src.integrations.telegram_multi_signal_copier import (
    TelegramMultiSignalCopier,
    MultiChannelSignalParser
)

def test_forexgdp_parser_3_targets():
    text = """🔽Forex Signal
BUY EURUSD now at 1.0850 till 1.0860
Target 1 : 1.0890
Target 2 : 1.0930
Target 3 : 1.0980
Stop loss: 1.0800"""
    sig = MultiChannelSignalParser.parse_message(text, "forexgdpfree")
    assert sig is not None
    assert sig["symbol"] == "EURUSD"
    assert sig["side"] == "BUY"
    assert len(sig["tps"]) == 3
    assert sig["tps"] == [1.0890, 1.0930, 1.0980]
    assert sig["sl"] == 1.0800


def test_forexgdp_sizing_050_lots_3tickets():
    """Forex GDP signals should execute 3 tickets with 0.50 lots each (1.50 lots total)."""
    copier = TelegramMultiSignalCopier(dry_run=True)
    copier.state["active_positions"] = []
    
    sig = {
        "channel": "forexgdpfree",
        "symbol": "EURUSD",
        "side": "BUY",
        "entry_min": 1.0850,
        "entry_max": 1.0850,
        "entry_mid": 1.0850,
        "sl": 1.0800,
        "tps": [1.0890, 1.0930, 1.0980],
        "type": "FOREX_GDP_DIRECT"
    }

    orders = copier.execute_signal(sig, spot_price=1.0850)
    assert orders is not None
    assert len(orders) == 3
    assert all(o["volume"] == 0.50 for o in orders)
    assert sum(o["volume"] for o in orders) == pytest.approx(1.50)
    assert orders[0]["ticket"] == 1 and orders[0]["tp"] == 1.0890
    assert orders[1]["ticket"] == 2 and orders[1]["tp"] == 1.0930
    assert orders[2]["ticket"] == 3 and orders[2]["tp"] == 1.0980


def test_non_forexgdp_channel_keeps_standard_007_lots():
    """Non-Forex GDP channels must continue executing standard 0.07 lots per ticket."""
    copier = TelegramMultiSignalCopier(dry_run=True)
    copier.state["active_positions"] = []

    sig = {
        "channel": "fxscalpingpro",
        "symbol": "EURUSD",
        "side": "BUY",
        "entry_min": 1.0850,
        "entry_max": 1.0850,
        "entry_mid": 1.0850,
        "sl": 1.0810,
        "tps": [1.0870, 1.0900],
        "type": "SCALP_SIGNAL"
    }

    orders = copier.execute_signal(sig, spot_price=1.0850)
    assert orders is not None
    assert len(orders) == 2
    assert all(o["volume"] == 0.07 for o in orders)
    assert sum(o["volume"] for o in orders) == pytest.approx(0.14)


def test_forexgdp_capacity_degradation_when_slots_limited():
    """When broker capacity only has 2 or 1 slot available, gracefully allocate available tickets."""
    copier = TelegramMultiSignalCopier(dry_run=True)
    copier.max_concurrent_positions = 6

    # 4 active positions already running -> 2 slots free
    copier.state["active_positions"] = [{"positionId": i} for i in range(4)]
    
    sig = {
        "channel": "forexgdpfree",
        "symbol": "GBPUSD",
        "side": "BUY",
        "entry_min": 1.2500,
        "entry_max": 1.2500,
        "entry_mid": 1.2500,
        "sl": 1.2440,
        "tps": [1.2550, 1.2600, 1.2650],
        "type": "FOREX_GDP_DIRECT"
    }

    orders_2slots = copier.execute_signal(sig, spot_price=1.2500)
    assert len(orders_2slots) == 2
    assert orders_2slots[0]["ticket"] == 1 and orders_2slots[0]["tp"] == 1.2550
    assert orders_2slots[1]["ticket"] == 2 and orders_2slots[1]["tp"] == 1.2650  # Runner TP3
    assert all(o["volume"] == 0.50 for o in orders_2slots)

    # 5 active positions already running -> 1 slot free
    copier.state["active_positions"] = [{"positionId": i} for i in range(5)]
    orders_1slot = copier.execute_signal(sig, spot_price=1.2500)
    assert len(orders_1slot) == 1
    assert orders_1slot[0]["ticket"] == 1 and orders_1slot[0]["tp"] == 1.2550
    assert orders_1slot[0]["volume"] == 0.50


def test_forexgdp_multistage_companion_breakeven_and_tp1_lock():
    """
    Test Multi-Stage Companion Protection:
    Stage 1: T1 closes -> T2 and T3 advance SL to Breakeven (entry + buffer).
    Stage 2: T2 closes -> T3 advances SL to lock profit at TP1.
    """
    copier = TelegramMultiSignalCopier(dry_run=False)
    copier.ctrader = MagicMock()
    copier.send_telegram_alert = MagicMock()

    entry = 1.0850
    tp1 = 1.0890
    tp2 = 1.0930
    tp3 = 1.0980
    sl = 1.0800

    t1 = {
        "positionId": 101,
        "ticket": 1,
        "symbol": "EURUSD",
        "side": "BUY",
        "entry": entry,
        "sl": sl,
        "tp": tp1,
        "be_locked": False,
        "time": datetime.now(timezone.utc).isoformat()
    }
    t2 = {
        "positionId": 102,
        "ticket": 2,
        "symbol": "EURUSD",
        "side": "BUY",
        "entry": entry,
        "sl": sl,
        "tp": tp2,
        "be_locked": False,
        "time": datetime.now(timezone.utc).isoformat()
    }
    t3 = {
        "positionId": 103,
        "ticket": 3,
        "symbol": "EURUSD",
        "side": "BUY",
        "entry": entry,
        "sl": sl,
        "tp": tp3,
        "be_locked": False,
        "time": datetime.now(timezone.utc).isoformat()
    }

    copier.state["active_positions"] = [t1, t2, t3]

    # --- STAGE 1: T1 closed, T2 & T3 still live on broker ---
    copier.ctrader.get_positions.return_value = [
        {"positionId": 102, "symbolName": "EURUSD", "tradeSide": "BUY", "entryPrice": entry, "stopLoss": sl, "takeProfit": tp2},
        {"positionId": 103, "symbolName": "EURUSD", "tradeSide": "BUY", "entryPrice": entry, "stopLoss": sl, "takeProfit": tp3}
    ]
    # Spot 1.0870 is above BE (1.0852) but below trailing activation (1.0890)
    copier.ctrader.get_spot_price.return_value = {"bid": 1.0870, "ask": 1.0871}

    copier.manage_active_breakeven()

    # Verify both T2 and T3 were amended to Breakeven
    amend_calls = copier.ctrader.amend_position.call_args_list
    assert len(amend_calls) == 2
    amended_pos_ids = {call[0][0] for call in amend_calls}
    assert amended_pos_ids == {102, 103}
    assert t2["be_locked"] is True
    assert t3["be_locked"] is True
    assert t2["sl"] == pytest.approx(1.0852)
    assert t3["sl"] == pytest.approx(1.0852)

    # --- STAGE 2: T2 also closes, only T3 live on broker ---
    copier.ctrader.amend_position.reset_mock()
    copier.ctrader.get_positions.return_value = [
        {"positionId": 103, "symbolName": "EURUSD", "tradeSide": "BUY", "entryPrice": entry, "stopLoss": t3["sl"], "takeProfit": tp3}
    ]
    # Spot 1.0910 is above TP1 (1.0890)
    copier.ctrader.get_spot_price.return_value = {"bid": 1.0910, "ask": 1.0911}

    copier.manage_active_breakeven()

    # Verify T3 SL was advanced to lock profit at TP1
    assert copier.ctrader.amend_position.call_count == 1
    call_args = copier.ctrader.amend_position.call_args[0]
    assert call_args[0] == 103
    assert copier.ctrader.amend_position.call_args[1]["stop_loss"] == tp1
    assert t3["t2_locked"] is True
    assert t3["sl"] == tp1


def test_forexgdp_swing_timeout_closes_after_48h():
    """Verify that positions exceeding 48 hours are automatically closed at market."""
    copier = TelegramMultiSignalCopier(dry_run=False)
    copier.ctrader = MagicMock()
    copier.send_telegram_alert = MagicMock()

    old_time = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
    pos = {
        "positionId": 201,
        "ticket": 2,
        "symbol": "GBPJPY",
        "side": "BUY",
        "entry": 190.00,
        "sl": 189.00,
        "tp": 192.00,
        "time": old_time
    }
    copier.state["active_positions"] = [pos]
    copier.ctrader.get_positions.return_value = [{"positionId": 201}]

    copier.manage_active_breakeven()

    copier.ctrader.close_position.assert_called_once_with(201)
    assert pos not in copier.state["active_positions"]
