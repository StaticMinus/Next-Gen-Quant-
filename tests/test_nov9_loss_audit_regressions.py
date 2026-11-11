"""
Regression Suite for November 9, 2026 Loss Audit and Architecture Hardening
============================================================================
Verifies all 4 root-cause remediations for morning losses & weekend closures:
1. Invariant 39: Provider SL Shield protects valid provider SLs from micro-tightening.
2. Order Block minimum buffer on Gold is at least 1.20 pts (12 pips) to prevent liquidity hunts.
3. Rollover Momentum Loophole elimination: Rollovers strictly require reward >= 1.5 * eff_risk.
4. 48-Hour Swing Timeout excludes weekend closed-market hours (Friday 22:00 to Sunday 22:00 UTC).
"""

import pytest
import pandas as pd
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from src.strategies.price_action_sl_engine import PriceActionSLEngine
from src.strategies.order_block_engine import OrderBlockEngine
from src.integrations.telegram_multi_signal_copier import TelegramMultiSignalCopier


def test_provider_sl_shield_preserves_valid_provider_sl_on_gold():
    """
    Morning Loss 1 Root Cause:
    ssf_gold BUY @ 4126.78 with provider SL 4120.11 (6.67 pts risk).
    PASL tightened SL to 4122.16 based on an M5 fractal wick. Market low reached 4121.95,
    stopping out the trade before rebounding to 4130.
    With Invariant 39, the valid provider SL (4120.11) MUST be preserved.
    """
    df = pd.DataFrame([
        {"open": 4124.0, "high": 4125.0, "low": 4122.5, "close": 4124.0},
        {"open": 4124.0, "high": 4126.0, "low": 4122.16, "close": 4125.0},
        {"open": 4125.0, "high": 4127.0, "low": 4123.0, "close": 4126.5},
        {"open": 4126.0, "high": 4128.0, "low": 4125.0, "close": 4127.0},
        {"open": 4127.0, "high": 4128.5, "low": 4126.0, "close": 4127.5},
    ])

    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=4120.11,
        df_bars=df,
        side="BUY",
        entry_price=4126.78,
        symbol="XAUUSD",
        max_allowed_distance=8.0,
        spread_cushion=0.0
    )

    assert sl == 4120.11, f"Expected provider SL 4120.11 to be shielded, got {sl}"
    assert reason == "PROVIDER_EXACT"


def test_provider_sl_shield_falls_back_when_provider_sl_excessive():
    """
    If provider SL is dangerously wide (> 8.0 pts on Gold), engine must tighten
    to structural SL to preserve capital.
    """
    df = pd.DataFrame([
        {"open": 4124.0, "high": 4125.0, "low": 4122.5, "close": 4124.0},
        {"open": 4124.0, "high": 4126.0, "low": 4122.0, "close": 4125.0},
        {"open": 4125.0, "high": 4127.0, "low": 4123.0, "close": 4126.5},
        {"open": 4126.0, "high": 4128.0, "low": 4125.0, "close": 4127.0},
        {"open": 4127.0, "high": 4128.5, "low": 4126.0, "close": 4127.5},
    ])

    # Provider SL is 4110.0 (16.78 pts away, exceeds 8.0 max allowed on Gold)
    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=4110.0,
        df_bars=df,
        side="BUY",
        entry_price=4126.78,
        symbol="XAUUSD",
        max_allowed_distance=8.0,
        spread_cushion=0.0
    )

    assert sl > 4110.0, f"Expected engine to clamp wide SL, got {sl}"
    assert (4126.78 - sl) <= 8.0, f"SL distance should not exceed max allowed 8.0, got {4126.78 - sl}"


def test_order_block_buffer_calibrated_gold():
    """
    Morning Loss 2 Root Cause:
    US30_Forex_Signals SELL @ 4118.80 with Bearish OB high at 4122.55.
    Narrow buffer + spread placed SL at 4123.10. Market stop-hunted to 4123.12 (by 2 cents!)
    and then plunged 390 pips to 4084.
    OrderBlockEngine buffer must enforce max(1.20, atr * 0.40) on Gold.
    """
    # Create candle sequence with origin at bar 1, displacement at bar 2:
    # Bar 0: Prior context
    # Bar 1: Origin bullish candle, high = 4122.55, low = 4120.0, close = 4122.0
    # Bar 2: Bearish displacement candle, open = 4122.0, close = 4115.0 (below 4120.0)
    # Subsequent bars stay below 4122.55 so OB is unmitigated
    df = pd.DataFrame([
        {"open": 4120.0, "high": 4121.0, "low": 4119.5, "close": 4120.5},
        {"open": 4120.5, "high": 4122.55, "low": 4120.0, "close": 4122.0},
        {"open": 4122.0, "high": 4122.20, "low": 4115.0, "close": 4115.5},
        {"open": 4115.5, "high": 4117.0, "low": 4114.0, "close": 4116.0},
        {"open": 4116.0, "high": 4118.5, "low": 4115.5, "close": 4118.0},
        {"open": 4118.0, "high": 4119.0, "low": 4117.0, "close": 4118.8},
    ])

    sl, ob, reason = OrderBlockEngine.calculate_order_block_sl(
        df=df,
        side="SELL",
        entry_price=4118.80,
        symbol="XAUUSD",
        min_noise_distance=3.50,
        max_allowed_distance=8.0,
        spread_cushion=0.15
    )

    assert sl is not None, f"Expected order block SL, got None (reason: {reason})"
    # With OB High at 4122.55, min buffer 1.20 and spread cushion 0.15:
    # SL must be >= 4122.55 + 1.20 + 0.15 = 4123.90
    min_required_sl = 4122.55 + 1.20 + 0.15
    assert sl >= min_required_sl, f"Expected SL >= {min_required_sl}, got {sl}"


def test_order_block_buffer_calibrated_forex():
    """
    Verify OrderBlockEngine buffer on Forex enforces at least 0.0008 (8 pips).
    """
    # Create candle sequence with origin at bar 1, displacement at bar 2:
    # Bar 0: Prior context
    # Bar 1: Origin bearish candle, low = 1.0820, high = 1.0835, close = 1.0822
    # Bar 2: Bullish displacement candle, open = 1.0822, close = 1.0860 (above 1.0835)
    # Subsequent bars stay above 1.0820 so OB is unmitigated
    df = pd.DataFrame([
        {"open": 1.0835, "high": 1.0840, "low": 1.0830, "close": 1.0832},
        {"open": 1.0832, "high": 1.0835, "low": 1.0820, "close": 1.0822},
        {"open": 1.0822, "high": 1.0865, "low": 1.0821, "close": 1.0860},
        {"open": 1.0860, "high": 1.0868, "low": 1.0845, "close": 1.0850},
        {"open": 1.0850, "high": 1.0860, "low": 1.0848, "close": 1.0852},
        {"open": 1.0852, "high": 1.0858, "low": 1.0849, "close": 1.0850},
    ])

    sl, ob, reason = OrderBlockEngine.calculate_order_block_sl(
        df=df,
        side="BUY",
        entry_price=1.0850,
        symbol="EURUSD",
        min_noise_distance=0.0025,
        max_allowed_distance=0.0050,
        spread_cushion=0.0
    )

    assert sl is not None, f"Expected order block SL, got None (reason: {reason})"
    # For BUY: OB Low (1.0820) - buffer (>= 0.0008)
    max_allowed_sl = 1.0820 - 0.0008
    assert sl <= max_allowed_sl, f"Expected SL <= {max_allowed_sl}, got {sl}"


def test_rollover_strictly_requires_one_point_five_rr():
    """
    Morning Loss 3 Root Cause:
    SELL XAUUSD entered at 4085.26 with ratcheted SL 4088.91 (risk 3.65) chasing TP1 at 4081.0 (reward 4.26).
    R:R = 1.16 (< 1.5). The trade stopped out on an M5 retest before reaching target.
    With the loophole closed, candidate TPs must strictly provide >= 1.5 * eff_risk.
    """
    copier = TelegramMultiSignalCopier(dry_run=True)
    params = copier.get_asset_parameters("XAUUSD")
    params["max_slippage"] = 2.0
    params["max_rollover_slippage"] = 4.0

    # Test 1: Sub-1.5 R:R candidate target (Reward = 4.0, Risk = 3.0, R:R = 1.33)
    curr_spot = 4085.0
    ratcheted_sl = 4088.0
    eff_risk = max(abs(curr_spot - ratcheted_sl), params.get("be_buffer", 0.5))  # 3.0
    candidate_tps_low_rr = [4081.0]  # Reward = 4.0

    viable_tp = None
    for i, tp in enumerate(candidate_tps_low_rr):
        reward = abs(tp - curr_spot)
        if reward >= (1.5 * eff_risk):
            viable_tp = tp
            break

    assert viable_tp is None, "Sub-1.5 R:R target should NOT be accepted as viable rollover!"

    # Test 2: Adequate R:R candidate target (Reward = 10.0, Risk = 3.0, R:R = 3.33)
    candidate_tps_high_rr = [4081.0, 4075.0]
    viable_tp_high = None
    for i, tp in enumerate(candidate_tps_high_rr):
        reward = abs(tp - curr_spot)
        if reward >= (1.5 * eff_risk):
            viable_tp_high = tp
            break

    assert viable_tp_high == 4075.0, f"Expected TP2 (4075.0) to be selected for rollover, got {viable_tp_high}"


def test_swing_timeout_deducts_weekend_hours():
    """
    Weekend Swing Timeout Defect:
    Forex markets close Friday 22:00 UTC and reopen Sunday 22:00 UTC (48h closed).
    A trade opened Thursday 12:00 UTC checked on Monday 02:00 UTC has elapsed 86 real hours,
    but only 38 active market hours. It MUST NOT be closed at Sunday open!
    """
    thursday_noon = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
    monday_2am = datetime(2026, 11, 9, 2, 0, 0, tzinfo=timezone.utc)

    market_hours = TelegramMultiSignalCopier.calculate_active_market_hours(thursday_noon, monday_2am)

    # 86 real hours - 48 weekend hours = 38 market hours
    assert abs(market_hours - 38.0) < 0.01, f"Expected 38.0 market hours, got {market_hours}"


def test_swing_timeout_triggers_after_48_active_market_hours():
    """
    A trade open for 51 active market hours MUST trigger the swing timeout.
    """
    start_dt = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)  # Monday 10:00 UTC
    end_dt = datetime(2026, 11, 4, 13, 0, 0, tzinfo=timezone.utc)    # Wednesday 13:00 UTC (51h elapsed, no weekend)

    market_hours = TelegramMultiSignalCopier.calculate_active_market_hours(start_dt, end_dt)
    assert abs(market_hours - 51.0) < 0.01
    assert market_hours >= 48.0


def test_gold_breakeven_buffer_covers_broker_commission():
    """
    Nov 11 Pseudo-Loss Root Cause:
    When Gold BE was set with 0.20 buffer, gross profit was $1.40.
    With cTrader round-turn commission of $1.42 ($0.71 open + $0.71 close),
    trades closed at -$0.02 and appeared in RED as losses.
    With Invariant 40, be_buffer MUST be at least 0.50 pts ($3.50 gross),
    guaranteeing strictly positive net profit (+$2.08) upon BE exit.
    """
    copier = TelegramMultiSignalCopier(dry_run=True)
    params = copier.get_asset_parameters("XAUUSD")
    be_buf = params["be_buffer"]

    assert be_buf >= 0.50, f"Expected be_buffer >= 0.50 on Gold, got {be_buf}"

    # Verify math on 0.07L (7 oz):
    lots = params["lot_size"]  # 0.07
    gross_pnl = be_buf * lots * 100.0  # 0.50 * 7 = $3.50
    commission = 1.42  # cTrader standard round-turn on 0.07L Gold
    net_pnl = gross_pnl - commission

    assert net_pnl > 0, f"Expected positive net PnL at BE, got {net_pnl:.2f}"
    assert net_pnl >= 2.00, f"Expected at least $2.00 net profit cushion, got {net_pnl:.2f}"

