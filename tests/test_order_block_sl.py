"""
Unit Tests for Institutional Order Block & Price Action Stop-Loss (OB-PASL) Engine
===================================================================================
"""

import pandas as pd
import pytest
from src.strategies.order_block_engine import OrderBlockEngine, OrderBlock
from src.strategies.price_action_sl_engine import PriceActionSLEngine


def create_ohlc_bars(opens, highs, lows, closes):
    n = len(opens)
    timestamps = pd.date_range("2026-10-26 08:00", periods=n, freq="5min")
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1000] * n
    }).set_index("timestamp")


def test_detect_bullish_order_block():
    """
    Bullish Order Block:
    Bar 1: Bearish candle (open 4015, close 4012, high 4015.5, low 4011.0)
    Bar 2: Strong bullish displacement (open 4012, close 4018, high 4018.5, low 4011.8) breaking Bar 1 high.
    Bar 3: Follow-through (open 4018, close 4020, high 4020.5, low 4017.5)
    """
    opens =  [4016.0, 4015.0, 4012.0, 4018.0, 4020.0, 4021.0]
    highs =  [4017.0, 4015.5, 4018.5, 4020.5, 4021.5, 4022.0]
    lows =   [4014.0, 4011.0, 4011.8, 4017.5, 4019.5, 4020.5]
    closes = [4015.0, 4012.0, 4018.0, 4020.0, 4021.0, 4022.0]
    df = create_ohlc_bars(opens, highs, lows, closes)

    obs = OrderBlockEngine.detect_order_blocks(df, side="BUY", lookback_bars=5)
    assert len(obs) >= 1
    bull_ob = obs[0]
    assert bull_ob.side == "BULLISH"
    assert bull_ob.low == 4011.0
    assert bull_ob.high == 4015.5
    assert bull_ob.displacement_size >= 5.0
    assert not bull_ob.mitigated


def test_detect_bearish_order_block():
    """
    Bearish Order Block:
    Bar 1: Bullish candle (open 4020, close 4024, high 4024.5, low 4019.5)
    Bar 2: Strong bearish displacement (open 4024, close 4017, high 4024.2, low 4016.5) breaking Bar 1 low.
    Bar 3: Follow-through (open 4017, close 4015, high 4017.5, low 4014.5)
    """
    opens =  [4018.0, 4020.0, 4024.0, 4017.0, 4015.0, 4014.0]
    highs =  [4020.0, 4024.5, 4024.2, 4017.5, 4015.5, 4014.5]
    lows =   [4017.5, 4019.5, 4016.5, 4014.5, 4013.5, 4013.0]
    closes = [4020.0, 4024.0, 4017.0, 4015.0, 4014.0, 4013.5]
    df = create_ohlc_bars(opens, highs, lows, closes)

    obs = OrderBlockEngine.detect_order_blocks(df, side="SELL", lookback_bars=5)
    assert len(obs) >= 1
    bear_ob = obs[0]
    assert bear_ob.side == "BEARISH"
    assert bear_ob.high == 4024.5
    assert bear_ob.low == 4019.5
    assert bear_ob.displacement_size >= 6.0
    assert not bear_ob.mitigated


def test_order_block_sl_calculation_buy():
    """
    Entry @ 4018.0. Bullish Order Block low @ 4013.50.
    With buffer (min 0.40), invalidation SL should sit below 4013.50 (~4013.00),
    providing safe breathing room outside the 3.50 pt noise floor (4018.0 - 4013.0 = 5.0 pts).
    """
    opens =  [4016.0, 4015.0, 4013.5, 4017.5, 4017.8, 4018.0]
    highs =  [4017.0, 4015.5, 4018.0, 4018.5, 4018.5, 4018.8]
    lows =   [4014.0, 4013.5, 4013.5, 4017.0, 4017.2, 4017.5]
    closes = [4015.0, 4013.5, 4017.5, 4018.0, 4018.0, 4018.0]
    df = create_ohlc_bars(opens, highs, lows, closes)

    sl, ob, reason = OrderBlockEngine.calculate_order_block_sl(
        df=df,
        side="BUY",
        entry_price=4018.0,
        symbol="XAUUSD",
        min_noise_distance=3.50,
        max_allowed_distance=5.00
    )

    assert sl is not None
    assert ob is not None
    assert sl < 4013.50
    assert round(4018.0 - sl, 2) >= 3.50  # Respects Invariant 33
    assert round(4018.0 - sl, 2) <= 5.00  # Within max prop firm risk


def test_order_block_sl_calculation_sell_with_spread():
    """
    Entry @ 4020.0. Bearish Order Block high @ 4023.50.
    Spread cushion is 0.35. Buffer is ~0.40.
    SL must sit above 4023.50 + 0.40 + 0.35 = 4024.25.
    """
    opens =  [4018.0, 4020.0, 4023.5, 4019.0, 4020.0, 4020.0]
    highs =  [4020.0, 4023.5, 4023.8, 4020.5, 4020.5, 4020.2]
    lows =   [4017.5, 4019.5, 4018.5, 4018.0, 4019.0, 4019.2]
    closes = [4020.0, 4023.5, 4019.0, 4019.8, 4020.0, 4020.0]
    df = create_ohlc_bars(opens, highs, lows, closes)

    sl, ob, reason = OrderBlockEngine.calculate_order_block_sl(
        df=df,
        side="SELL",
        entry_price=4020.0,
        symbol="XAUUSD",
        min_noise_distance=3.50,
        max_allowed_distance=5.00,
        spread_cushion=0.35
    )

    assert sl is not None
    assert ob is not None
    # Must be cushioned by spread to protect short position from ask spikes
    assert sl >= 4023.50 + 0.35
    assert round(sl - 4020.0, 2) >= 3.50
    assert round(sl - 4020.0, 2) <= 5.00


def test_order_block_noise_floor_stepping():
    """
    Invariant 33 Anti-Suffocation Test:
    There is a micro Bullish OB close to entry (dist = 1.50 pts, inside noise floor).
    There is a parent macro Bullish OB further back (dist = 4.00 pts, outside noise floor).
    The engine MUST step back to the parent OB to prevent suffocation!
    """
    # Parent OB at bar 1 (low: 4015.5) -> displaced to 4019
    # Micro OB at bar 4 (low: 4018.5) -> displaced to 4020
    # Entry at 4020.0
    opens =  [4017.0, 4016.0, 4015.5, 4019.0, 4018.5, 4020.0, 4020.0]
    highs =  [4018.0, 4016.5, 4019.5, 4019.8, 4020.5, 4020.5, 4020.5]
    lows =   [4015.5, 4015.0, 4015.5, 4018.0, 4018.5, 4019.5, 4019.8]
    closes = [4016.0, 4015.5, 4019.0, 4018.5, 4020.0, 4020.0, 4020.0]
    df = create_ohlc_bars(opens, highs, lows, closes)

    sl, ob, reason = OrderBlockEngine.calculate_order_block_sl(
        df=df,
        side="BUY",
        entry_price=4020.0,
        symbol="XAUUSD",
        min_noise_distance=3.50,
        max_allowed_distance=5.00
    )

    assert sl is not None
    assert ob is not None
    # Must have chosen the parent OB with low ~4015.5, NOT the suffocating micro OB @ 4018.5!
    assert ob.low <= 4016.0
    assert round(4020.0 - sl, 2) >= 3.50


def test_price_action_engine_adopts_order_block_when_sl_missing():
    """
    When signal provider omits SL, PriceActionSLEngine adopts the confirmed Order Block SL.
    """
    opens =  [4016.0, 4015.0, 4013.5, 4017.5, 4017.8, 4018.0]
    highs =  [4017.0, 4015.5, 4018.0, 4018.5, 4018.5, 4018.8]
    lows =   [4014.0, 4013.5, 4013.5, 4017.0, 4017.2, 4017.5]
    closes = [4015.0, 4013.5, 4017.5, 4018.0, 4018.0, 4018.0]
    df = create_ohlc_bars(opens, highs, lows, closes)

    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=None,
        df_bars=df,
        side="BUY",
        entry_price=4018.0,
        symbol="XAUUSD",
        max_allowed_distance=5.0
    )

    assert "ORDER_BLOCK" in reason
    assert sl < 4013.50
    assert round(4018.0 - sl, 2) >= 3.50


def test_price_action_engine_tightens_wide_provider_sl_to_order_block():
    """
    When provider gives an overly wide SL (e.g. 4010.0, $8 away),
    PriceActionSLEngine tightens to the Order Block invalidation level (~4013.0).
    """
    opens =  [4016.0, 4015.0, 4013.5, 4017.5, 4017.8, 4018.0]
    highs =  [4017.0, 4015.5, 4018.0, 4018.5, 4018.5, 4018.8]
    lows =   [4014.0, 4013.5, 4013.5, 4017.0, 4017.2, 4017.5]
    closes = [4015.0, 4013.5, 4017.5, 4018.0, 4018.0, 4018.0]
    df = create_ohlc_bars(opens, highs, lows, closes)

    sl, reason = PriceActionSLEngine.reconcile_structural_sl(
        provider_sl=4010.0,  # 8 pts wide
        df_bars=df,
        side="BUY",
        entry_price=4018.0,
        symbol="XAUUSD",
        max_allowed_distance=5.0
    )

    assert "ORDER_BLOCK_TIGHTENED" in reason
    assert sl > 4010.0  # Successfully tightened
    assert sl < 4013.50
    assert round(4018.0 - sl, 2) >= 3.50
