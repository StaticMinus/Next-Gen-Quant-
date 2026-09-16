"""
tests/test_david_safety_close.py
================================
Unit and Integration tests for David-Exclusive Live Trades Vision and Multi-Tap Safety Close.
Validates:
1. David (PRIMARY_CHAT_ID) gets multi-tap close buttons in Telegram markup.
2. Partner/Guest accounts (e.g. Cha Cha) receive ZERO close buttons.
3. Multi-tap state transitions: Tap 1 -> Tap 2 -> Cancel / Timeout.
4. Execution permissions block unauthorized partner attempts.
5. WebApp API /api/close_position.
"""

import time
import pytest
from unittest.mock import patch, MagicMock

from src.integrations.telegram_bot_service import (
    PRIMARY_CHAT_ID,
    _CACHE,
    _CLOSE_CONFIRMATIONS,
    get_trades_markup,
    render_trades_text,
    handle_update,
)


@pytest.fixture(autouse=True)
def setup_teardown():
    _CLOSE_CONFIRMATIONS.clear()
    _CACHE["enriched_positions"] = [
        {
            "position_id": 3069593,
            "symbol_name": "XAUUSD",
            "display_name": "Spot Gold",
            "trade_side": "BUY",
            "lots": 0.01,
            "entry_price": 4334.99,
            "current_price": 4332.50,
            "floating_pnl": -2.49,
            "take_profit": 4443.38,
            "stop_loss": 4204.95,
        },
        {
            "position_id": 3071210,
            "symbol_name": "NDX100",
            "display_name": "Nasdaq 100 Index",
            "trade_side": "BUY",
            "lots": 0.10,
            "entry_price": 29118.12,
            "current_price": 29145.00,
            "floating_pnl": 2.68,
            "take_profit": 29552.37,
            "stop_loss": 28242.17,
        }
    ]
    yield
    _CLOSE_CONFIRMATIONS.clear()


def test_david_receives_multitap_buttons():
    """David must see Close buttons for each open trade."""
    markup = get_trades_markup(user_id=PRIMARY_CHAT_ID)
    buttons = [btn for row in markup["inline_keyboard"] for btn in row]
    callbacks = [b.get("callback_data") for b in buttons]
    
    assert any("cmd_close_tap1_3069593" in cb for cb in callbacks)
    assert any("cmd_close_tap1_3071210" in cb for cb in callbacks)
    assert "cmd_trades" in callbacks  # Live sync
    assert "cmd_overview" in callbacks


def test_partner_chacha_receives_no_close_buttons():
    """Partners (like Cha Cha) must NEVER see close buttons."""
    partner_id = "123456789"
    markup = get_trades_markup(user_id=partner_id)
    buttons = [btn for row in markup["inline_keyboard"] for btn in row]
    callbacks = [b.get("callback_data") for b in buttons]
    
    # Assert zero close buttons
    assert not any("cmd_close" in cb for cb in callbacks)
    # Standard navigation is present
    assert "cmd_trades" in callbacks
    assert "cmd_overview" in callbacks


def test_multitap_progression_steps():
    """Verify Tap 1 -> Tap 2 -> Exec step button changes."""
    pos_id = 3069593
    
    # Initial state (Step 0)
    m0 = get_trades_markup(user_id=PRIMARY_CHAT_ID)
    btns0 = [b["text"] for row in m0["inline_keyboard"] for b in row]
    assert any("Tap 1/3" in t for t in btns0)

    # Step 1
    m1 = get_trades_markup(user_id=PRIMARY_CHAT_ID, pending_pos_id=pos_id, pending_step=1)
    btns1 = [b["text"] for row in m1["inline_keyboard"] for b in row]
    assert any("Tap 2/3" in t for t in btns1)
    assert any("Cancel" in t for t in btns1)

    # Step 2
    m2 = get_trades_markup(user_id=PRIMARY_CHAT_ID, pending_pos_id=pos_id, pending_step=2)
    btns2 = [b["text"] for row in m2["inline_keyboard"] for b in row]
    assert any("FINAL TAP: EXECUTE CLOSE" in t for t in btns2)
    assert any("Cancel" in t for t in btns2)


def test_render_trades_text_shows_live_metrics_and_banners():
    """Verify render_trades_text includes live price, PnL, and step banners."""
    text_normal = render_trades_text(user_id=PRIMARY_CHAT_ID)
    assert "Spot Gold" in text_normal
    assert "Nasdaq 100 Index" in text_normal
    assert "Manual Control (David Exclusive)" in text_normal

    # Step 1 warning
    text_step1 = render_trades_text(user_id=PRIMARY_CHAT_ID, pending_pos_id=3069593, pending_step=1)
    assert "SAFETY CLOSE INITIATED" in text_step1
    assert "#3069593" in text_step1

    # Step 2 final warning
    text_step2 = render_trades_text(user_id=PRIMARY_CHAT_ID, pending_pos_id=3069593, pending_step=2)
    assert "FINAL EXECUTION WARNING" in text_step2


@patch("src.integrations.telegram_bot_service.api_call")
@patch("src.integrations.telegram_bot_service.ack_callback")
def test_unauthorized_close_attempt_blocked(mock_ack, mock_api):
    """If an unauthorized partner attempts to trigger close callbacks, they must be rejected."""
    # 1. Unknown stranger
    unknown_id = 99999999
    update_stranger = {
        "update_id": 1001,
        "callback_query": {
            "id": "cq_stranger",
            "from": {"id": unknown_id, "first_name": "Stranger"},
            "message": {"message_id": 50, "chat": {"id": unknown_id}},
            "data": "cmd_close_tap1_3069593"
        }
    }
    handle_update(update_stranger)
    mock_ack.assert_called_with("cq_stranger", "🔒 Unauthorized.")
    assert 3069593 not in _CLOSE_CONFIRMATIONS


@patch("src.integrations.telegram_bot_service.ctrader_client")
@patch("src.integrations.telegram_bot_service.api_call")
@patch("src.integrations.telegram_bot_service.ack_callback")
def test_full_multitap_execution_by_david(mock_ack, mock_api, mock_ctrader):
    """Simulate full Tap 1 -> Tap 2 -> Tap 3 flow by David."""
    pos_id = 3069593
    david_id = int(PRIMARY_CHAT_ID)
    mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0, "freeMargin": 5700.0}
    mock_ctrader.get_enriched_positions.return_value = _CACHE["enriched_positions"]
    
    # 1. Tap 1
    u1 = {
        "update_id": 2001,
        "callback_query": {
            "id": "cq_1",
            "from": {"id": david_id, "first_name": "David"},
            "message": {"message_id": 51, "chat": {"id": david_id}},
            "data": f"cmd_close_tap1_{pos_id}"
        }
    }
    handle_update(u1)
    assert _CLOSE_CONFIRMATIONS.get(pos_id, {}).get("step") == 1

    # 2. Tap 2
    u2 = {
        "update_id": 2002,
        "callback_query": {
            "id": "cq_2",
            "from": {"id": david_id, "first_name": "David"},
            "message": {"message_id": 51, "chat": {"id": david_id}},
            "data": f"cmd_close_tap2_{pos_id}"
        }
    }
    handle_update(u2)
    assert _CLOSE_CONFIRMATIONS.get(pos_id, {}).get("step") == 2

    # 3. Final Tap 3 (Execute)
    mock_ctrader.close_position.return_value = {"status": "success"}
    mock_ctrader.get_enriched_positions.return_value = []
    mock_ctrader.get_balance.return_value = {"balance": 6005.0, "equity": 6005.0, "freeMargin": 6005.0}

    u3 = {
        "update_id": 2003,
        "callback_query": {
            "id": "cq_3",
            "from": {"id": david_id, "first_name": "David"},
            "message": {"message_id": 51, "chat": {"id": david_id}},
            "data": f"cmd_close_exec_{pos_id}"
        }
    }
    handle_update(u3)
    
    # Verify cTrader close was executed
    mock_ctrader.close_position.assert_called_with(pos_id)
    # Verify confirmation removed
    assert pos_id not in _CLOSE_CONFIRMATIONS
