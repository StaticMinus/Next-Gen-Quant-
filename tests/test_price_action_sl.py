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
        closes = [(l + h) / 2.0 for l, h in zip(lows, highs)]
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
    If a provider sets a tight SL (e.g. 4115.0) right inside the noise pocket,
    the Structural Shield adopts the swing low SL (4111.0) so the trade isn't wicked out.
    """
    lows = [4116.0, 4114.0, 4112.0, 4112.0, 4115.0, 4118.0, 4119.0, 4120.0, 4121.0]
    highs = [4120.0, 4118.0, 4116.0, 4117.0, 4119.0, 4122.0, 4123.0, 4124.0, 4125.0]
    df = create_sample_bars(lows, highs)

    # Provider gave 4116.0 (which sits above the swing low 4112.0)
    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=4116.0,
        df_bars=df,
        side="BUY",
        entry_price=4122.0,
        symbol="XAUUSD",
        max_allowed_distance=12.0
    )

    assert reason == "STRUCTURAL_SHIELD_ADOPTED"
    assert sl < 4112.0  # Safe behind the swing low


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
    Verifies TelegramMultiSignalCopier uses PriceActionSLEngine during execute_signal.
    """
    mock_ctrader = MagicMock()
    lows = [4115.0, 4113.0, 4111.0, 4114.0, 4116.0, 4118.0]
    highs = [4120.0, 4118.0, 4116.0, 4118.0, 4120.0, 4122.0]
    df = create_sample_bars(lows, highs)
    mock_ctrader.get_trendbars_dataframe.return_value = df

    copier = TelegramMultiSignalCopier(dry_run=True, ctrader_client=mock_ctrader)
    sig = {
        "channel": "ssfgold",
        "symbol": "XAUUSD",
        "side": "BUY",
        "entry_min": 4120.0,
        "entry_max": 4120.0,
        "entry_mid": 4120.0,
        "sl": 4116.0,  # Provider tight SL (inside noise)
        "tps": [4125.0],
        "type": "DIRECT_EXECUTION"
    }

    orders = copier.execute_signal(sig, spot_price=4120.0)
    assert len(orders) == 2
    # Verify the SL adopted was shielded behind the swing low (4111.0)
    assert orders[0]["sl"] < 4111.0
    assert orders[1]["sl"] < 4111.0
