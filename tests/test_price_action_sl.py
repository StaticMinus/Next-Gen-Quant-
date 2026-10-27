"""
Unit Tests for Price Action Stop-Loss (PASL) Engine & Structural Shield
======================================================================
"""

import pandas as pd
import pytest
from unittest.mock import MagicMock
from src.strategies.price_action_sl_engine import PriceActionSLEngine
from src.integrations.telegram_multi_signal_copier import TelegramMultiSignalCopier


def create_sample_bars(lows, highs, closes=None, opens=None):
    n = len(lows)
    if closes is None:
        closes = [(low_val + high_val) / 2.0 for low_val, high_val in zip(lows, highs)]
    if opens is None:
        opens = closes.copy()
    timestamps = pd.date_range("2026-10-21 00:00", periods=n, freq="5min")
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [100] * n
    }).set_index("timestamp")


def test_calculate_atr():
    # 5 bars with constant range of 2.0
    lows = [4100.0, 4102.0, 4101.0, 4103.0, 4102.0]
    highs = [4102.0, 4104.0, 4103.0, 4105.0, 4104.0]
    df = create_sample_bars(lows, highs)
    atr = PriceActionSLEngine.calculate_atr(df, period=5)
    assert 1.5 <= atr <= 3.0


def test_calculate_swing_sl_buy():
    # 10 bars where bar #4 dipped to 4112.0 (the swing low)
    lows = [4118.0, 4117.0, 4115.0, 4112.0, 4114.0, 4116.0, 4118.0, 4119.0, 4120.0, 4120.5]
    highs = [4122.0, 4121.0, 4119.0, 4117.0, 4118.0, 4120.0, 4122.0, 4123.0, 4124.0, 4124.5]
    df = create_sample_bars(lows, highs)

    pasl, dist = PriceActionSLEngine.calculate_swing_sl(
        df=df,
        side="BUY",
        entry_price=4121.0,
        symbol="XAUUSD",
        lookback_bars=8
    )

    # Swing low is 4112.0. PASL must sit below 4112.0 with buffer
    assert pasl < 4112.0
    assert pasl > 4105.0  # reasonable buffer
    assert dist == round(4121.0 - pasl, 2)


def test_calculate_swing_sl_sell():
    # 10 bars where bar #5 spiked to 4135.0 (the swing high)
    lows = [4120.0, 4122.0, 4124.0, 4126.0, 4128.0, 4125.0, 4123.0, 4121.0, 4119.0, 4118.0]
    highs = [4124.0, 4126.0, 4128.0, 4131.0, 4135.0, 4130.0, 4128.0, 4125.0, 4122.0, 4121.0]
    df = create_sample_bars(lows, highs)

    pasl, dist = PriceActionSLEngine.calculate_swing_sl(
        df=df,
        side="SELL",
        entry_price=4118.0,
        symbol="XAUUSD",
        lookback_bars=8
    )

    # Swing high is 4135.0. PASL must sit above 4135.0 with buffer
    assert pasl > 4135.0
    assert pasl < 4142.0
    assert dist == round(pasl - 4118.0, 2)


def test_structural_shield_adoption_buy():
    """
    INVARIANT: Provider tight SL is NEVER widened.
    Overly wide provider SL is tightened to market structure.
    """
    lows = [4116.0, 4114.0, 4112.0, 4112.0, 4115.0, 4118.0, 4119.0, 4120.0, 4121.0]
    highs = [4120.0, 4118.0, 4116.0, 4117.0, 4119.0, 4122.0, 4123.0, 4124.0, 4125.0]
    df = create_sample_bars(lows, highs)

    # 1. Provider gave tight 4116.0 (closer to entry 4122.0 than swing low 4111.0)
    # Must NOT widen to 4111.0!
    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=4116.0,
        df_bars=df,
        side="BUY",
        entry_price=4122.0,
        symbol="XAUUSD",
        max_allowed_distance=12.0
    )
    assert reason == "PROVIDER_EXACT"
    assert sl == 4116.0

    # 2. Provider gave wide 4105.0 (further from entry than swing low ~4111.0)
    # Must tighten to swing structure!
    sl_tight, reason_tight = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=4105.0,
        df_bars=df,
        side="BUY",
        entry_price=4122.0,
        symbol="XAUUSD",
        max_allowed_distance=12.0
    )
    assert reason_tight == "STRUCTURAL_SHIELD_TIGHTENED"
    assert sl_tight < 4112.0
    assert sl_tight > 4105.0


def test_max_risk_clamp():
    """
    If swing low is 20 points away, it must be clamped to max_allowed_distance ($10.00).
    """
    lows = [4100.0, 4101.0, 4102.0, 4103.0]
    highs = [4105.0, 4106.0, 4107.0, 4108.0]
    df = create_sample_bars(lows, highs)

    # Entry is 4130.0, swing low is 4100.0 (dist = 30 pts)
    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=None,
        df_bars=df,
        side="BUY",
        entry_price=4130.0,
        symbol="XAUUSD",
        max_allowed_distance=10.0
    )

    assert "CLAMPED_MAX_RISK" in reason
    assert sl == 4120.0  # Exactly 4130.0 - 10.0


def test_copier_integration_with_pasl():
    """
    Verifies TelegramMultiSignalCopier uses PriceActionSLEngine during execute_signal:
    - Tight provider SL is preserved.
    - Missing SL is synthesized by PASL.
    """
    mock_ctrader = MagicMock()
    lows = [4115.0, 4113.0, 4111.0, 4114.0, 4116.0, 4118.0]
    highs = [4120.0, 4118.0, 4116.0, 4118.0, 4120.0, 4122.0]
    df = create_sample_bars(lows, highs)
    mock_ctrader.get_trendbars_dataframe.return_value = df

    copier = TelegramMultiSignalCopier(dry_run=True, ctrader_client=mock_ctrader)
    sig_tight = {
        "channel": "ssfgold",
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_min": 4120.0,
        "entry_max": 4120.0,
        "entry_mid": 4120.0,
        "sl": 4116.0,  # Provider tight SL (4 pts risk)
        "tps": [4125.0],
        "type": "DIRECT_EXECUTION"
    }

    orders = copier.execute_signal(sig_tight, spot_price=4120.0)
    assert len(orders) == 2
    # Verify tight SL was preserved exactly
    assert orders[0]["sl"] == 4116.0
    assert orders[1]["sl"] == 4116.0

    # Missing SL synthesized by PASL behind swing low 4111.0
    sig_none = {
        "channel": "ssfgold",
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_min": 4120.0,
        "entry_max": 4120.0,
        "entry_mid": 4120.0,
        "sl": None,
        "tps": [4125.0],
        "type": "DIRECT_EXECUTION"
    }
    orders_syn = copier.execute_signal(sig_none, spot_price=4120.0)
    # Clamped to new 5.0 pt max risk ceiling (4120.0 - 5.0 = 4115.0)
    assert orders_syn[0]["sl"] == 4115.0


def test_calculate_swing_sl_sell_with_spread_cushion():
    """
    Verifies that for SELL trades, spread_cushion is added to the PASL to prevent
    Ask-price spread spikes from prematurely triggering stop-loss.
    """
    lows = [4120.0, 4122.0, 4124.0, 4126.0, 4128.0, 4125.0, 4123.0, 4121.0, 4119.0, 4118.0]
    highs = [4124.0, 4126.0, 4128.0, 4131.0, 4135.0, 4130.0, 4128.0, 4125.0, 4122.0, 4121.0]
    df = create_sample_bars(lows, highs)

    # Without spread cushion
    pasl_no_spread, _ = PriceActionSLEngine.calculate_swing_sl(
        df=df,
        side="SELL",
        entry_price=4118.0,
        symbol="XAUUSD",
        lookback_bars=8,
        spread_cushion=0.0
    )

    # With 0.35 pt live spread cushion
    pasl_with_spread, dist = PriceActionSLEngine.calculate_swing_sl(
        df=df,
        side="SELL",
        entry_price=4118.0,
        symbol="XAUUSD",
        lookback_bars=8,
        spread_cushion=0.35
    )

    # The cushioned SL must sit exactly 0.35 higher than the uncushioned SL
    assert round(pasl_with_spread - pasl_no_spread, 2) == 0.35
    assert pasl_with_spread > 4135.0 + 0.35


def test_calculate_m5_trailing_sl_buy():
    """
    Verifies institutional M5 market structure trailing for BUY positions.
    When a trade moves into profit and confirms a higher swing low base,
    the SL ratchets behind that swing low (protecting banked gains).
    """
    # 8 M5 bars showing an uptrend with a pull-back base at 4124.50
    lows = [4120.0, 4121.0, 4124.5, 4125.0, 4126.0, 4127.0, 4128.0, 4129.0]
    highs = [4123.0, 4124.0, 4127.0, 4128.0, 4129.0, 4130.0, 4131.0, 4132.0]
    df = create_sample_bars(lows, highs)

    # Entry was 4120.00, current SL is BE @ 4120.30, price reached 4130.00
    new_sl = PriceActionSLEngine.calculate_m5_trailing_sl(
        df=df,
        side="BUY",
        entry_price=4120.00,
        current_sl=4120.30,
        current_price=4130.00,
        symbol="XAUUSD",
        lookback_bars=5
    )

    assert new_sl is not None
    # Swing low is 4124.50. SL should be below 4124.50, but way above current BE 4120.30!
    assert new_sl < 4124.50
    assert new_sl > 4123.00
    assert new_sl > 4120.30


def test_calculate_m5_trailing_sl_sell():
    """
    Verifies institutional M5 market structure trailing for SELL positions.
    Ratchet must trail behind lower swing highs with spread cushion.
    """
    # 8 M5 bars showing a downtrend with a lower high bounce at 4115.00
    lows = [4118.0, 4116.0, 4114.0, 4112.0, 4110.0, 4109.0, 4108.0, 4107.0]
    highs = [4122.0, 4120.0, 4118.0, 4115.0, 4113.0, 4112.0, 4111.0, 4110.0]
    df = create_sample_bars(lows, highs)

    # Entry was 4122.00, current SL is BE @ 4121.70, price is down to 4108.00
    new_sl = PriceActionSLEngine.calculate_m5_trailing_sl(
        df=df,
        side="SELL",
        entry_price=4122.00,
        current_sl=4121.70,
        current_price=4108.00,
        symbol="XAUUSD",
        lookback_bars=5,
        spread_cushion=0.25
    )

    assert new_sl is not None
    # Swing high in lookback is 4115.00. SL must sit above 4115.00 + buffer + spread
    assert new_sl > 4115.00
    assert new_sl < 4121.70  # strictly ratcheted lower than BE


def test_copier_m5_structure_trailing_integration():
    """
    Verifies copier uses M5 structure trailing in manage_active_breakeven
    when trendbars are provided by broker.
    """
    mock_ctrader = MagicMock()
    lows = [4120.0, 4121.0, 4122.0, 4125.0, 4126.0, 4127.0]
    highs = [4123.0, 4124.0, 4125.0, 4128.0, 4129.0, 4130.0]
    df = create_sample_bars(lows, highs)
    mock_ctrader.get_trendbars_dataframe.return_value = df
    mock_ctrader.get_positions.return_value = [{"positionId": 777}]
    mock_ctrader.get_spot_price.return_value = {"bid": 4129.50, "ask": 4129.70}

    copier = TelegramMultiSignalCopier(dry_run=False, ctrader_client=mock_ctrader)
    copier.state["active_positions"] = [{
        "positionId": 777,
        "ticket": 2,
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry": 4120.00,
        "sl": 4120.30,  # BE
        "tp": 4140.00,
        "be_locked": True
    }]

    copier.manage_active_breakeven()

    # Position 777 should have been amended using M5 structural level (> 4123.0)
    mock_ctrader.amend_position.assert_called_once()
    called_sl = mock_ctrader.amend_position.call_args[1]["stop_loss"]
    assert called_sl > 4123.0
    assert called_sl < 4129.50


def test_get_min_noise_floor_distance():
    assert PriceActionSLEngine.get_min_noise_floor_distance("XAUUSD") == 3.50
    assert PriceActionSLEngine.get_min_noise_floor_distance("GOLD") == 3.50
    assert PriceActionSLEngine.get_min_noise_floor_distance("EURUSD") == 0.00250  # 25 pips Majors
    assert PriceActionSLEngine.get_min_noise_floor_distance("GBPUSD") == 0.00250  # 25 pips Majors
    assert PriceActionSLEngine.get_min_noise_floor_distance("GBPCAD") == 0.00350  # 35 pips Crosses
    assert PriceActionSLEngine.get_min_noise_floor_distance("CADCHF") == 0.00350  # 35 pips Crosses
    assert PriceActionSLEngine.get_min_noise_floor_distance("USDJPY") == 0.15
    assert PriceActionSLEngine.get_min_noise_floor_distance("US30") == 25.0
    assert PriceActionSLEngine.get_min_noise_floor_distance("BTCUSD") == 50.0


def test_structural_shield_rejects_sub_noise_tightening():
    """
    Forex incident test: Provider gave 1.11920 (7 pips from entry 1.11990).
    A micro-consolidation wick gave PASL of 1.11959 (3.1 pips from entry).
    Because 3.1 pips is inside the noise floor (< 25 pips), PASL tightening
    must be DISCARDED and provider SL 1.11920 preserved.
    """
    lows = [1.11980, 1.11975, 1.11965, 1.11970, 1.11980, 1.11985]
    highs = [1.12010, 1.12005, 1.11995, 1.12000, 1.12015, 1.12020]
    df = create_sample_bars(lows, highs)

    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=1.11920,
        df_bars=df,
        side="BUY",
        entry_price=1.11990,
        symbol="EURUSD",
        max_allowed_distance=0.0050
    )
    assert reason == "PROVIDER_EXACT"
    assert sl == 1.11920


def test_structural_shield_allows_valid_macro_tightening():
    """
    When provider gives an overly wide SL (55 pips away) and a valid swing structure
    exists outside the 25 pip noise floor (e.g. 28 pips away), it can be tightened for scalpers.
    """
    lows = [1.11700, 1.11680, 1.11660, 1.11700, 1.11750, 1.11800]
    highs = [1.11750, 1.11720, 1.11710, 1.11750, 1.11800, 1.11850]
    df = create_sample_bars(lows, highs)

    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=1.11440,  # 55 pips away
        df_bars=df,
        side="BUY",
        entry_price=1.11990,
        symbol="EURUSD",
        max_allowed_distance=0.0050
    )
    assert reason == "STRUCTURAL_SHIELD_TIGHTENED"
    assert sl > 1.11440
    assert sl < 1.11990
    assert round(1.11990 - sl, 5) >= 0.00250  # Outside 25 pip noise floor


def test_gold_pasl_rejects_sub_3_5pt_tightening():
    """
    Invariant 33 Verification:
    Provider posted SELL Gold with SL 4029.10 (entry 4020.96).
    A micro-consolidation high at 4021.50 gives raw PASL 4022.54 ($1.58 away).
    Because $1.58 is inside the Gold 3.50 pt noise floor, PASL tightening
    MUST BE DISCARDED to prevent suffocation, preserving the provider SL 4029.10.
    """
    lows = [4019.0, 4019.5, 4020.0, 4019.8, 4020.2, 4020.5]
    highs = [4021.0, 4021.3, 4021.5, 4021.2, 4021.4, 4021.5]
    df = create_sample_bars(lows, highs)

    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=4029.10,
        df_bars=df,
        side="SELL",
        entry_price=4020.96,
        symbol="XAUUSD",
        max_allowed_distance=10.0,
        spread_cushion=0.35
    )
    assert reason == "PROVIDER_EXACT"
    assert sl == 4029.10


def test_invariant_38_gbpcad_swing_channel_preserves_macro_sl():
    """
    Invariant 38 Verification:
    Wallstreet Pips posted GBPCAD BUY with macro SL 1.86481 (55.7 pips away from 1.87038).
    An M5 local consolidation has a swing low at 1.86779 (26 pips away).
    Because wallstreet_pips is an authorized swing channel (is_swing_channel=True),
    M5 down-tightening is BYPASSED and provider macro SL 1.86481 is preserved.
    """
    lows = [1.86800, 1.86790, 1.86779, 1.86810, 1.86830, 1.86850]
    highs = [1.87000, 1.87020, 1.87040, 1.87030, 1.87050, 1.87060]
    df = create_sample_bars(lows, highs)

    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=1.86481,
        df_bars=df,
        side="BUY",
        entry_price=1.87038,
        symbol="GBPCAD",
        max_allowed_distance=0.0070,
        is_swing_channel=True
    )
    assert reason == "PROVIDER_EXACT"
    assert sl == 1.86481


def test_invariant_39_conversational_review_without_sl_rejected():
    """
    Invariant 39 Verification:
    Signalsproviderfx post: 'CADCHF Will Go Lower From Resistance! Sell! ... technical review ... crucial zone of supply 0.589'
    Lacks explicit author Stop Loss. Must be rejected by MultiChannelSignalParser.
    """
    from src.integrations.telegram_multi_signal_copier import MultiChannelSignalParser
    text = (
        "CADCHF Will Go Lower From Resistance! Sell! "
        "Here is our detailed technical review for CADCHF. "
        "The market is on a crucial zone of supply 0.589."
    )
    parsed = MultiChannelSignalParser.parse_message(text, "signalsproviderfx")
    assert parsed is None



