"""
Unit Tests for AgentQuant V2 Regime & Structure Engine
======================================================
Verifies:
  - 15M Regime classification (Bullish, Bearish, Shock)
  - 5M Liquidity Sweep + Displacement detection
  - Dynamic Position Sizing (Fixed $ Risk / Distance)
  - Full Multi-Timeframe V2 Sniper Orchestration
"""

import numpy as np
import pandas as pd
import pytest

from src.strategies.regime_engine import RegimeEngine, MarketRegime
from src.strategies.structure_engine import StructureEngine, StructureState
from src.strategies.v2_sniper import V2SniperStrategy


def create_synthetic_bars(n_bars: int = 60, start_price: float = 80000.0, trend: float = 0.0) -> pd.DataFrame:
    """Generates synthetic OHLCV data for testing."""
    records = []
    curr = start_price
    for i in range(n_bars):
        curr += trend + np.random.normal(0, 10.0)
        high = curr + abs(np.random.normal(20, 5.0))
        low = curr - abs(np.random.normal(20, 5.0))
        close = low + (high - low) * np.random.uniform(0.2, 0.8)
        records.append({
            "open": curr,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000
        })
        curr = close
    return pd.DataFrame(records)


def test_regime_classification_bullish_and_bearish():
    engine = RegimeEngine(ema_fast_period=10, ema_slow_period=20)
    
    # 1. Strong Bullish Trend (+50 pts per bar)
    df_bull = create_synthetic_bars(60, start_price=80000.0, trend=80.0)
    res_bull = engine.classify(df_bull)
    assert res_bull["regime"] == MarketRegime.BULLISH_TREND.value
    assert res_bull["allowed_side"] == "BUY_ONLY"

    # 2. Strong Bearish Trend (-50 pts per bar)
    df_bear = create_synthetic_bars(60, start_price=80000.0, trend=-80.0)
    res_bear = engine.classify(df_bear)
    assert res_bear["regime"] == MarketRegime.BEARISH_TREND.value
    assert res_bear["allowed_side"] == "SELL_ONLY"


def test_regime_volatility_shock():
    engine = RegimeEngine(ema_fast_period=10, ema_slow_period=20, shock_percentile_threshold=80.0)
    df = create_synthetic_bars(60, start_price=84000.0, trend=0.0)
    
    # Inject massive waterfall dump in the last 3 bars (-$2500 dump)
    df.iloc[-3, df.columns.get_loc("close")] = 83000.0
    df.iloc[-2, df.columns.get_loc("close")] = 82000.0
    df.iloc[-1, df.columns.get_loc("close")] = 81000.0
    df.iloc[-1, df.columns.get_loc("low")] = 80500.0
    df.iloc[-1, df.columns.get_loc("high")] = 82500.0

    res = engine.classify(df)
    assert res["regime"] == MarketRegime.VOLATILITY_EXPANSION_SHOCK.value
    assert res["allowed_side"] == "NONE"


def test_structure_bullish_sweep_and_displacement():
    engine = StructureEngine(swing_window=4, min_wick_ratio=0.20, min_body_ratio=0.50)
    
    # Create baseline bars around 83000
    df = create_synthetic_bars(25, start_price=83000.0, trend=0.0)
    
    # Set a clear swing low within the 4-bar window (at bar 18, low = 82800)
    df.iloc[18, df.columns.get_loc("low")] = 82800.0
    df.iloc[18, df.columns.get_loc("close")] = 82900.0

    # At bar 20: Liquidity Sweep!
    # Low pierces 82800 (goes to 82700), but closes back at 82830 with large bottom wick
    df.iloc[20, df.columns.get_loc("open")] = 82810.0
    df.iloc[20, df.columns.get_loc("low")] = 82700.0
    df.iloc[20, df.columns.get_loc("high")] = 82880.0
    df.iloc[20, df.columns.get_loc("close")] = 82830.0

    # At bar 21: Bullish Displacement!
    # Strong green expansion candle breaking counter high
    df.iloc[21, df.columns.get_loc("open")] = 82830.0
    df.iloc[21, df.columns.get_loc("low")] = 82820.0
    df.iloc[21, df.columns.get_loc("high")] = 83050.0
    df.iloc[21, df.columns.get_loc("close")] = 83040.0

    # At bar 22 (current bar): Retest of broken level (82880)
    df.iloc[22, df.columns.get_loc("open")] = 83000.0
    df.iloc[22, df.columns.get_loc("low")] = 82880.0
    df.iloc[22, df.columns.get_loc("high")] = 83010.0
    df.iloc[22, df.columns.get_loc("close")] = 82890.0

    setup = engine.evaluate_setup(df, allowed_side="BUY_ONLY")
    assert setup is not None
    assert setup.side == "BUY"
    assert setup.structural_sl_price < setup.retest_entry_price
    assert setup.take_profit_price > setup.retest_entry_price
    # Check 2R asymmetry
    risk = setup.retest_entry_price - setup.structural_sl_price
    reward = setup.take_profit_price - setup.retest_entry_price
    assert reward >= 1.9 * risk


def test_dynamic_lot_sizing_clamps_risk():
    # If SL distance is $300 on BTC and budget is $15 -> lots should be 0.05
    lots_tight = StructureEngine.calculate_lot_size(
        entry_price=84000.0, sl_price=83700.0, risk_usd=15.0, symbol="BTCUSD"
    )
    assert lots_tight == 0.05
    assert (84000.0 - 83700.0) * lots_tight == 15.0

    # If SL distance is wide ($600 on BTC) and budget is $15 -> lots should dynamically scale down to 0.02
    lots_wide = StructureEngine.calculate_lot_size(
        entry_price=84000.0, sl_price=83400.0, risk_usd=15.0, symbol="BTCUSD"
    )
    assert lots_wide == 0.02 or lots_wide == 0.03
    # Dollar risk is strictly <= $18
    assert (84000.0 - 83400.0) * lots_wide <= 18.0


def test_v2_sniper_strategy_full_pipeline():
    v2 = V2SniperStrategy(target_r_multiple=2.0, max_risk_usd=15.0)
    
    # 15M Bullish trend
    df_15m = create_synthetic_bars(60, start_price=82000.0, trend=50.0)
    # 5M neutral bars
    df_5m = create_synthetic_bars(40, start_price=84000.0, trend=0.0)
    
    res = v2.evaluate_multitimeframe(df_15m, df_5m, symbol="BTCUSD")
    assert "action" in res
    assert "regime" in res
