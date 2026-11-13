"""
Regression Suite for November 13, 2026 Loss Audit (-$124.55 whipsaw morning)
============================================================================
Verifies the remediations for the two unmanaged provider-SL stop-outs and the
legal stop-and-reverse double hit that the Nov 9 fixes did not cover:

1. Invariant 44 — Structural SL Authority ("Structure Wins, Else Skip"):
   - L8 (fxscalpingpro BUY 3902.86, provider SL 3899.1): a 3.76 pt stop sitting dead
     center of the 3894-3899 whipsaw band passed the old shield on arithmetic alone
     (3.76 >= 3.50 floor) and was instantly stopped (-$52.60). Under Invariant 44 the
     provider SL sits INSIDE the M5 swing structure => re-anchor or skip.
   - L7 (fxscalpingpro SELL 3869.45 -> 3896.45, provider SL 3903.9): the shield
     short-circuited the OB engine, so the stop was never vetted against structure.
     Structure authority must now govern provider SLs too.
2. Invariant 45 — Anti-Whipsaw Circuit Breaker + Daily Loss Halt:
   - 28 minutes after the 10:06 BUY was stopped, a different channel was allowed to
     SELL 7.4 pts lower (conflict arbiter only blocks LIVE opposing positions).
   - Two full-SL losses on the same symbol in one session must pause that symbol.
   - A -$150 realized day must halt new entries (management continues).
"""

import time
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.strategies.price_action_sl_engine import PriceActionSLEngine
from src.integrations.telegram_multi_signal_copier import TelegramMultiSignalCopier


def _ohlc(lows, highs, spread_cushion_bars=True):
    """Builds an M5 OHLC frame with open=close (bodyless bars: no OB detection side effects)."""
    n = len(lows)
    mids = [(lo + hi) / 2.0 for lo, hi in zip(lows, highs)]
    timestamps = pd.date_range("2026-11-13 05:00", periods=n, freq="5min")
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": mids,
        "high": highs,
        "low": lows,
        "close": mids,
        "volume": [100] * n
    }).set_index("timestamp")


def test_structure_authority_skips_nov13_in_band_buy():
    """
    L8 Root Cause (10:06:53 UTC): fxscalpingpro BUY XAUUSD @ 3902.86, provider SL 3899.10.
    The morning band had oscillated 3894-3899 five times; the swing low 3893.5 puts the
    structural stop ~10 pts away — beyond the 8.0 pt Gold risk budget. The old shield
    preserved the in-band stop (distance 3.76 >= 3.50 floor) and it was stopped instantly.
    Invariant 44: provider SL INSIDE structure + unfitting structure => UNPROTECTABLE.
    """
    df = _ohlc(
        lows=[3896.0, 3894.5, 3893.5, 3895.0, 3897.0, 3899.0, 3901.0, 3902.5],
        highs=[3899.0, 3897.5, 3896.5, 3898.0, 3900.0, 3902.0, 3903.5, 3904.0],
    )

    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=3899.10,
        df_bars=df,
        side="BUY",
        entry_price=3902.86,
        symbol="XAUUSD",
        max_allowed_distance=8.0,
        spread_cushion=0.0,
    )

    assert sl is None, f"In-band provider SL 3899.10 must not survive, got {sl}"
    assert reason == "STRUCTURE_UNPROTECTABLE"


def test_structure_authority_reanchors_sell_inside_order_block():
    """
    L7 mechanism (06:56:33 UTC): fxscalpingpro SELL XAUUSD @ 3896.45. The old Provider SL
    Shield short-circuited the Order Block engine, so the stop was never vetted against
    the bearish OB above the entry. Invariant 44: a provider SL sitting INSIDE the OB
    structure (below OB high + buffer) MUST be re-anchored to the structural level when
    it fits the 8.0 pt budget — giving the trade the room that saved the 08:02 SELL.
    """
    df = pd.DataFrame([
        {"timestamp": "2026-11-13 05:00", "open": 3895.5, "high": 3896.5, "low": 3894.5, "close": 3896.0, "volume": 100},
        {"timestamp": "2026-11-13 05:05", "open": 3899.5, "high": 3902.5, "low": 3899.0, "close": 3901.5, "volume": 100},  # Bullish origin (OB)
        {"timestamp": "2026-11-13 05:10", "open": 3901.5, "high": 3902.0, "low": 3898.0, "close": 3898.5, "volume": 100},  # Bearish displacement below origin low
        {"timestamp": "2026-11-13 05:15", "open": 3898.5, "high": 3899.5, "low": 3897.5, "close": 3898.0, "volume": 100},
        {"timestamp": "2026-11-13 05:20", "open": 3898.0, "high": 3899.0, "low": 3897.0, "close": 3897.5, "volume": 100},
        {"timestamp": "2026-11-13 05:25", "open": 3897.5, "high": 3898.5, "low": 3896.5, "close": 3897.0, "volume": 100},
        {"timestamp": "2026-11-13 05:30", "open": 3897.0, "high": 3898.0, "low": 3896.0, "close": 3896.5, "volume": 100},
        {"timestamp": "2026-11-13 05:35", "open": 3896.5, "high": 3897.5, "low": 3895.5, "close": 3896.0, "volume": 100},
        {"timestamp": "2026-11-13 05:40", "open": 3896.0, "high": 3897.0, "low": 3895.0, "close": 3896.45, "volume": 100},  # Forming bar (excluded)
    ]).set_index("timestamp")

    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=3902.90,  # INSIDE the OB structure (OB high 3902.5 + buffer => ~3903.8)
        df_bars=df,
        side="SELL",
        entry_price=3896.45,
        symbol="XAUUSD",
        max_allowed_distance=8.0,
        spread_cushion=0.10,
    )

    assert reason.startswith("STRUCTURE_AUTHORITATIVE_ORDER_BLOCK"), f"Expected OB authority, got {reason}"
    assert sl is not None and sl >= 3903.70, f"Expected re-anchor beyond OB high + buffer, got {sl}"
    assert (sl - 3896.45) <= 8.0, f"Structural stop must fit the 8.0 pt budget, got {sl - 3896.45}"


def test_nov13_provider_sl_beyond_structure_preserved():
    """
    Invariant 39 intent survives Invariant 44: when the provider stop is already beyond
    the deepest structural wick and within budget, it is preserved EXACTLY — no
    micro-tightening, no widening. (Nov 9 Morning Loss 1 regression guard.)
    """
    df = _ohlc(
        lows=[4122.5, 4122.16, 4123.0, 4125.0, 4126.0, 4127.0],
        highs=[4125.0, 4126.0, 4127.0, 4128.0, 4128.5, 4129.0],
    )

    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=4120.11,
        df_bars=df,
        side="BUY",
        entry_price=4126.78,
        symbol="XAUUSD",
        max_allowed_distance=8.0,
    )

    assert reason == "PROVIDER_EXACT"
    assert sl == 4120.11


def test_unprotectable_sl_skips_order_in_execute_signal():
    """
    Copier integration: when Invariant 44 returns STRUCTURE_UNPROTECTABLE, execute_signal
    must abort BEFORE any broker order is placed (Invariant 12 transparency: skip logged,
    no silent drop, no order).
    """
    mock_ctrader = MagicMock()
    mock_ctrader.get_trendbars_dataframe.return_value = _ohlc(
        lows=[3896.0, 3894.5, 3893.5, 3895.0, 3897.0, 3899.0, 3901.0, 3902.5],
        highs=[3899.0, 3897.5, 3896.5, 3898.0, 3900.0, 3902.0, 3903.5, 3904.0],
    )
    mock_ctrader.get_spot_price.return_value = {"bid": 3902.80, "ask": 3902.90}

    copier = TelegramMultiSignalCopier(dry_run=True, ctrader_client=mock_ctrader)
    sig = {
        "channel": "fxscalpingpro",
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_min": 3902.5,
        "entry_max": 3903.0,
        "entry_mid": 3902.86,
        "sl": 3899.10,
        "tps": [3904.86, 3913.69],
        "type": "DIRECT_EXECUTION",
    }

    orders = copier.execute_signal(sig, spot_price=3902.86)

    assert orders is None, "Unprotectable trade must return None"
    mock_ctrader.place_market_order.assert_not_called()


def test_whipsaw_opposite_direction_block():
    """
    Invariant 45 (Nov 13 10:06 -> 10:35): 28 minutes after the BUY was stopped, a
    different channel was allowed to SELL 7.4 pts lower — the arbiter only blocks LIVE
    opposing positions. After a full-SL loss on a symbol, opposite-direction entries
    must be blocked for 90 minutes; same-direction entries remain allowed.
    """
    copier = TelegramMultiSignalCopier(dry_run=True, ctrader_client=MagicMock())
    now = time.time()
    copier.state["full_loss_log"] = [
        {"position_id": "p1", "symbol": "XAUUSD", "side": "SELL", "net_pnl": -104.30, "ts": now - 30 * 60}
    ]

    # Opposite of the stopped SELL => blocked
    buy_reason = copier.check_whipsaw_breaker("XAUUSD", "BUY")
    assert buy_reason is not None and "opposite" in buy_reason.lower()

    # Same direction as the stopped SELL => allowed
    assert copier.check_whipsaw_breaker("XAUUSD", "SELL") is None

    # Opposite direction but outside the 90 min window => allowed again
    copier.state["full_loss_log"][0]["ts"] = now - 91 * 60
    assert copier.check_whipsaw_breaker("XAUUSD", "BUY") is None


def test_whipsaw_two_loss_symbol_pause():
    """
    Invariant 45: two full-SL losses on the same symbol within a 6h session must pause
    ALL new entries on that symbol for 4 hours (the Nov 9 morning trio pattern), while
    other symbols stay tradeable and the pause expires afterwards.
    """
    copier = TelegramMultiSignalCopier(dry_run=True, ctrader_client=MagicMock())
    now = time.time()
    copier.state["full_loss_log"] = [
        {"position_id": "p1", "symbol": "XAUUSD", "side": "SELL", "net_pnl": -104.30, "ts": now - 2 * 3600},
        {"position_id": "p2", "symbol": "XAUUSD", "side": "BUY", "net_pnl": -52.60, "ts": now - 1 * 3600},
    ]

    reason = copier.check_whipsaw_breaker("XAUUSD", "BUY")
    assert reason is not None and "paused" in reason.lower()
    # Other symbols unaffected
    assert copier.check_whipsaw_breaker("EURUSD", "BUY") is None

    # Pause expires: both losses outside the 6h session window and 90 min block window
    copier.state["full_loss_log"] = [
        {"position_id": "p1", "symbol": "XAUUSD", "side": "SELL", "net_pnl": -104.30, "ts": now - 7 * 3600},
        {"position_id": "p2", "symbol": "XAUUSD", "side": "BUY", "net_pnl": -52.60, "ts": now - 6.5 * 3600},
    ]
    assert copier.check_whipsaw_breaker("XAUUSD", "BUY") is None


def test_daily_loss_halt_blocks_entries_and_management_continues():
    """
    Invariant 45: realized net P/L <= -$150 in the UTC day must arm the daily halt
    (blocks all new entries) while open-position management keeps running — the Nov 12
    lesson: bleeding days must be capped, but survivors must still be protected to BE.
    """
    now = time.time()
    deals = [
        {"position_id": "p1", "symbol_name": "XAUUSD", "trade_side": "BUY", "net_pnl": -104.30, "exit_timestamp": now - 3600},
        {"position_id": "p2", "symbol_name": "XAUUSD", "trade_side": "BUY", "net_pnl": -52.60, "exit_timestamp": now - 1800},
    ]
    fake_ctrader = MagicMock()
    fake_ctrader.get_closed_deals.return_value = deals

    copier = TelegramMultiSignalCopier(dry_run=True, ctrader_client=fake_ctrader)
    copier.refresh_loss_guards()

    # Halt armed until next UTC midnight
    assert float(copier.state.get("daily_halt_until") or 0) > now
    reason = copier.check_whipsaw_breaker("XAUUSD", "BUY")
    assert reason is not None and "daily loss halt" in reason.lower()
    reason_sell = copier.check_whipsaw_breaker("EURUSD", "SELL")
    assert reason_sell is not None and "daily loss halt" in reason_sell.lower()

    # Management continues: a BE-eligible position still gets amended under the halt
    mgmt_ctrader = MagicMock()
    mgmt_ctrader.get_trendbars_dataframe.return_value = _ohlc(
        lows=[4120.0, 4121.0, 4122.0, 4125.0, 4126.0, 4127.0],
        highs=[4123.0, 4124.0, 4125.0, 4128.0, 4129.0, 4130.0],
    )
    mgmt_ctrader.get_positions.return_value = [{"positionId": 777}]
    mgmt_ctrader.get_spot_price.return_value = {"bid": 4129.50, "ask": 4129.70}
    mgmt_copier = TelegramMultiSignalCopier(dry_run=False, ctrader_client=mgmt_ctrader)
    mgmt_copier.state["daily_halt_until"] = now + 3600  # halt ACTIVE
    mgmt_copier.state["active_positions"] = [{
        "positionId": 777, "ticket": 2, "symbol": "XAUUSD", "side": "BUY",
        "entry": 4120.00, "sl": 4120.30, "tp": 4140.00, "be_locked": True
    }]

    mgmt_copier.manage_active_breakeven()

    mgmt_ctrader.amend_position.assert_called_once()


def test_swing_channel_macro_sl_bypass_preserved():
    """
    Invariant 38 survives Invariant 44: swing channels trade macro (higher-timeframe)
    provider stops. A provider SL sitting inside M5 structure MUST still be preserved
    for an authorized swing channel — M5 micro-structure does not govern swing trades.
    """
    lows = [1.86800, 1.86790, 1.86779, 1.86810, 1.86830, 1.86850]
    highs = [1.87000, 1.87020, 1.87040, 1.87030, 1.87050, 1.87060]
    df = _ohlc(lows, highs)

    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=1.86800,  # 23.8 pips, inside the M5 swing (cross noise floor 35 pips)
        df_bars=df,
        side="BUY",
        entry_price=1.87038,
        symbol="GBPCAD",
        max_allowed_distance=0.0070,
        is_swing_channel=True,
    )

    assert reason == "PROVIDER_EXACT"
    assert sl == 1.86800


def test_refresh_loss_guards_dedupes_and_ignores_small_losses():
    """
    Invariant 45 log hygiene: full-SL losses are deduped by position_id across refresh
    cycles, and small losses (commission-sized, e.g. the -$14.6 USDJPY scratch) do NOT
    arm the whipsaw breaker.
    """
    now = time.time()
    deals = [
        {"position_id": "p1", "symbol_name": "XAUUSD", "trade_side": "SELL", "net_pnl": -104.30, "exit_timestamp": now - 600},
        {"position_id": "p2", "symbol_name": "USDJPY", "trade_side": "SELL", "net_pnl": -14.60, "exit_timestamp": now - 300},
    ]
    fake_ctrader = MagicMock()
    fake_ctrader.get_closed_deals.return_value = deals

    copier = TelegramMultiSignalCopier(dry_run=True, ctrader_client=fake_ctrader)
    copier.refresh_loss_guards()
    copier.refresh_loss_guards()  # Second cycle over the same deals

    log = copier.state.get("full_loss_log") or []
    assert len(log) == 1, f"Expected deduped single full-loss record, got {len(log)}"
    assert log[0]["symbol"] == "XAUUSD"

    # A small loss alone never enters the log, so it never arms the breaker
    small_only = MagicMock()
    small_only.get_closed_deals.return_value = [deals[1]]
    copier_small = TelegramMultiSignalCopier(dry_run=True, ctrader_client=small_only)
    copier_small.refresh_loss_guards()
    assert (copier_small.state.get("full_loss_log") or []) == []
    assert copier_small.check_whipsaw_breaker("USDJPY", "BUY") is None

    # No daily halt: -$118.90 day total is inside the -$150 limit
    assert float(copier.state.get("daily_halt_until") or 0) == 0
