"""Unit Tests for RestrictedActionsGuard, MicroMomentumFilter, and SlippageEngine."""

import time
from src.integrations.guard_sentinel import RestrictedActionsGuard, MicroMomentumFilter
from src.integrations.slippage_engine import SlippageEngine


def test_restricted_actions_guard_approves_valid_trade():
    guard = RestrictedActionsGuard(max_volume=0.14, max_sl_points=10.0, floor_equity=5650.0)
    ok, reason = guard.validate_action(
        symbol="XAUUSD",
        side="BUY",
        volume_lots=0.07,
        entry_price=4165.0,
        sl_price=4157.0,  # 8 pts distance (< 10)
        current_equity=5999.83
    )
    assert ok is True
    assert reason == "APPROVED"


def test_restricted_actions_guard_rejects_oversized_volume():
    guard = RestrictedActionsGuard(max_volume=0.14)
    ok, reason = guard.validate_action(
        symbol="XAUUSD",
        side="BUY",
        volume_lots=0.20,  # Exceeds 0.14
        entry_price=4165.0,
        sl_price=4157.0,
        current_equity=5999.83
    )
    assert ok is False
    assert "exceeds max allowed" in reason


def test_restricted_actions_guard_rejects_wide_sl():
    guard = RestrictedActionsGuard(max_sl_points=10.0)
    ok, reason = guard.validate_action(
        symbol="XAUUSD",
        side="BUY",
        volume_lots=0.07,
        entry_price=4165.0,
        sl_price=4140.0,  # 25 pts distance (> 10)
        current_equity=5999.83
    )
    assert ok is False
    assert "SL distance" in reason


def test_restricted_actions_guard_rejects_circuit_breaker():
    guard = RestrictedActionsGuard(floor_equity=5650.0)
    ok, reason = guard.validate_action(
        symbol="XAUUSD",
        side="BUY",
        volume_lots=0.07,
        entry_price=4165.0,
        sl_price=4158.0,
        current_equity=5640.0  # Below floor
    )
    assert ok is False
    assert "below floor" in reason


def test_micro_momentum_filter_confirms_healthy_trend():
    filter_engine = MicroMomentumFilter()
    # Steady upward progression (healthy buy)
    prices = [4160.0, 4160.5, 4161.0, 4162.0, 4162.5, 4163.0, 4164.0]
    ok, score, reason = filter_engine.evaluate_confluence("BUY", prices)
    assert ok is True
    assert reason == "CONFLUENCE_CONFIRMED"


def test_micro_momentum_filter_rejects_counter_trend_dump():
    filter_engine = MicroMomentumFilter()
    # Severe cascade down (counter-trend buy trap)
    prices = [4175.0, 4172.0, 4168.0, 4165.0, 4160.0, 4155.0]
    ok, score, reason = filter_engine.evaluate_confluence("BUY", prices)
    assert ok is False
    assert "COUNTER_TREND_DROP" in reason


def test_slippage_engine_calculates_latency_and_score():
    record = SlippageEngine._process_and_save(
        signal_key="TEST_KEY",
        side="BUY",
        expected_entry=4165.00,
        executed_fill=4165.10,  # +0.10 slippage
        signal_timestamp=time.time() - 0.150,  # 150ms ago
        fill_timestamp=time.time(),
        ticket_id=123456,
        volume=0.07,
        spread_at_entry=0.35
    )
    assert record["slippage_pts"] == 0.10
    assert record["latency_ms"] >= 100.0
    assert record["execution_score"] > 80.0
