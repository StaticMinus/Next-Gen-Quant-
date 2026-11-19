"""Tests for the Invo -> cTrader copier (sizing, gating, exit mirroring)."""

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.integrations import invo_ctrader_copier as mod
from src.integrations.risk_guardian import guardian


class FakeCTrader:
    def __init__(self, balance=6000.0, equity=6000.0, bar_range=200.0):
        self.balance = balance
        self.equity = equity
        self.bar_range = bar_range
        self.orders = []
        self.closed = []
        self.deals = []
        self.stop = None
        self.suppress_sl = False
        self.sl_amend_fails = False
        self.fail_close = 0
        self._stops = {}

    def get_balance(self):
        return {"balance": self.balance, "equity": self.equity, "freeMargin": 5000.0}

    def get_spot_price(self, symbol):
        return {"bid": 62000.0, "ask": 62010.0}

    def get_trendbars_dataframe(self, symbol, period="M_15", count=30):
        base = 62000.0
        rows = []
        for i in range(count):
            rows.append({
                "timestamp": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=15 * i),
                "open": base,
                "high": base + self.bar_range / 2,
                "low": base - self.bar_range / 2,
                "close": base,
                "volume": 1,
            })
        return pd.DataFrame(rows).set_index("timestamp")

    def get_symbol_digits(self, symbol):
        return 3

    def get_symbols(self):
        return [{"symbolName": "BTCUSD"}, {"symbolName": "ETHUSD"}]

    def place_market_order(self, **kwargs):
        self.orders.append(kwargs)
        position_id = 4242 + len(self.orders) - 1  # real broker allocates a new id per fill
        self.stop = None if self.suppress_sl else kwargs.get("stop_loss_price")
        self._stops[position_id] = self.stop
        return {"positionId": position_id}

    def get_positions_strict(self):
        return [
            {
                "positionId": position_id,
                "symbolId": 22395 if order.get("symbol") == "BTCUSD" else 22397,
                "symbolName": order.get("symbol"),
                "tradeSide": order.get("side", "BUY"),
                "volume": int(round(order.get("volume_lots", 0) * 100)),
                "entryPrice": 62010.0,
                # A position placed through this fake tracks its live stop; one seeded
                # directly reports the stop it was seeded with.
                "stopLoss": (self._stops[position_id] if position_id in self._stops
                             else order.get("stop_loss_price")) or 0.0,
                "comment": order.get("comment", ""),
            }
            for offset, order in enumerate(self.orders)
            for position_id in [4242 + offset]
            if position_id not in self.closed
        ]

    def amend_position(self, position_id, stop_loss=None, take_profit=None, symbol=None):
        if self.sl_amend_fails:
            return None
        self._stops[position_id] = stop_loss
        self.stop = stop_loss
        return {"positionId": position_id, "stopLoss": stop_loss}

    def amend_position_sl(self, position_id, stop_loss, symbol=None):
        return self.amend_position(position_id, stop_loss=stop_loss, symbol=symbol)

    def get_closed_deals(self, days=7):
        return self.deals

    def close_position(self, position_id, volume=None):
        if self.fail_close:
            self.fail_close -= 1
            return None
        self.closed.append(position_id)
        return {"status": "closed", "positionId": position_id}


def make_signal(coin="BTC", side="long", shot="shot-1", post_id="post-1",
                trader="mastertrader"):
    return {
        "postId": post_id,
        "action": "open",
        "owner": {"id": f"u-{trader}", "username": trader},
        "trade": {"coin": coin, "side": side, "leverage": 10, "entryPrice": 62000.0,
                  "closingPrice": None, "entrySize": 1.0},
        "mimicMeta": {"portfolioId": "p1", "baseShortId": shot},
    }


@pytest.fixture(autouse=True)
def _silence_telegram(monkeypatch):
    # Alerts are real HTTP calls to the operator's phone; a test run must never send one.
    monkeypatch.setattr(mod, "send_telegram_alert", lambda *_a, **_k: True)


@pytest.fixture(autouse=True)
def _reset_guardian(monkeypatch):
    # RiskGuardian is a process-global that persists to cache/risk_guardian_state.json.
    # Tests must never write through it, or they corrupt live prop-firm breaker state.
    monkeypatch.setattr(guardian, "save_state", lambda: None)
    guardian.state["trading_halted"] = False
    guardian.state["halt_reason"] = None
    guardian.state["daily_losses_count"] = 0
    guardian.state["daily_loss_total"] = 0.0
    yield


@pytest.fixture
def copier(tmp_path):
    # allowed_traders is pinned empty so a real INVO_ALLOWED_TRADERS in .env cannot
    # change what these tests assert.
    return mod.InvoCtaderCopier(
        dry_run=False,
        ctrader=FakeCTrader(),
        state_file=tmp_path / "state.json",
        allowed_traders=set(),
    )


def test_symbol_map_has_only_broker_listed_crypto():
    mapping = mod.symbol_map()
    assert mapping["BTC"] == "BTCUSD"
    assert mapping["ETH"] == "ETHUSD"
    assert "SOL" not in mapping


def test_synthetic_stop_is_clamped_to_bounds():
    assert mod.synthetic_stop_distance(100000.0, None) == pytest.approx(750.0)
    assert mod.synthetic_stop_distance(100000.0, 1.0) == pytest.approx(250.0)   # floor 0.25%
    assert mod.synthetic_stop_distance(100000.0, 5000.0) == pytest.approx(2000.0)  # ceiling 2%


def test_compute_units_respects_risk_budget():
    # 0.5% of 6000 = $30 risk over a $300 stop -> 0.1 units
    assert mod.compute_units(6000.0, 62000.0, 300.0, 0.5) == pytest.approx(0.1)


def test_compute_units_capped_by_notional():
    # Tiny stop would imply huge size; notional cap (2x equity) must bind
    units = mod.compute_units(6000.0, 62000.0, 1.0, 0.5)
    assert units * 62000.0 <= 6000.0 * mod.MAX_NOTIONAL_MULT + 1


def test_parse_min_volume_reads_broker_error():
    payload = {"isError": True, "content": "minimum allowed volume = 0.1"}
    assert mod.parse_min_volume(payload) == pytest.approx(0.1)
    assert mod.parse_min_volume({"ok": True}) is None


def test_open_places_order_with_synthetic_stop(copier):
    record = copier.handle_open(make_signal())

    assert len(copier.ctrader.orders) == 1
    order = copier.ctrader.orders[0]
    assert order["symbol"] == "BTCUSD"
    assert order["side"] == "BUY"
    assert order["volume_lots"] == pytest.approx(0.1, abs=0.02)
    assert order["stop_loss_price"] < 62010.0
    assert record["positionId"] == 4242
    assert copier.state["copies"]["shot-1"]["closed"] is False


def test_open_is_idempotent_per_base_short_id(copier):
    copier.handle_open(make_signal())
    copier.handle_open(make_signal())
    assert len(copier.ctrader.orders) == 1


def test_unsupported_coin_is_skipped(copier):
    assert copier.handle_open(make_signal(coin="SOL")) is None
    assert copier.ctrader.orders == []


def test_halted_guardian_blocks_entry(copier):
    guardian.state["trading_halted"] = True
    guardian.state["halt_reason"] = "Daily 2-Strike"
    assert copier.handle_open(make_signal()) is None
    assert copier.ctrader.orders == []


def test_close_mirrors_trader_exit(copier):
    copier.handle_open(make_signal())
    copier.handle_close(make_signal())

    assert copier.ctrader.closed == [4242]
    assert copier.state["copies"]["shot-1"]["closed"] is True


def test_close_ignores_untracked_signal(copier):
    copier.handle_close(make_signal(shot="never-copied"))
    assert copier.ctrader.closed == []


def test_handle_post_requires_verified_trade(copier):
    post = {
        "id": "p9",
        "update": {"ticker": "BTC", "isOpen": True, "verifiedTrade": False,
                   "baseShortId": "shot-9", "directionLong": True, "portfolio": {"id": "p1"},
                   "owner": {"id": "u1", "username": "x"}, "changes": {"isAdded": True}},
    }
    assert copier.handle_post(post) is None
    assert copier.ctrader.orders == []


def test_handle_post_open_then_close(copier):
    open_post = {
        "id": "p10",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "update": {"ticker": "BTC", "isOpen": True, "verifiedTrade": True,
                   "baseShortId": "shot-10", "directionLong": True, "leverage": 5,
                   "entryPrice": 62000.0, "closingPrice": None,
                   "portfolio": {"id": "p1"}, "owner": {"id": "u1", "username": "x"},
                   "changes": {"isOpen": True, "reasonClosed": None}},
    }
    close_post = {
        "id": "p11",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "update": {"ticker": "BTC", "isOpen": False, "verifiedTrade": True,
                   "baseShortId": "shot-10", "directionLong": True, "leverage": 5,
                   "entryPrice": 62000.0, "closingPrice": 63100.0,
                   "portfolio": {"id": "p1"}, "owner": {"id": "u1", "username": "x"},
                   "changes": {"isAdded": False}},
    }

    assert copier.handle_post(open_post) == "open"
    assert copier.handle_post(close_post) == "close"
    assert copier.ctrader.closed == [4242]


def test_first_poll_still_processes_exit_for_held_position(copier, monkeypatch):
    copier.handle_open(make_signal())

    close_post = {
        "id": "p-restart",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "update": {"ticker": "BTC", "isOpen": False, "verifiedTrade": True,
                   "baseShortId": "shot-1", "directionLong": True,
                   "closingPrice": 63100.0, "portfolio": {"id": "p1"},
                   "owner": {"id": "u1", "username": "mastertrader"},
                   "changes": {"isAdded": False}},
    }
    monkeypatch.setattr(mod.InvoClient, "get_feed", lambda self, *a, **k: [close_post])

    copier.poll_once()  # restart: first poll must not swallow the exit

    assert copier.ctrader.closed == [4242]


def test_restored_cycle_is_not_a_cold_start(tmp_path):
    # No history at all -> index the feed rather than replay it.
    cold = mod.InvoCtaderCopier(dry_run=True, state_file=tmp_path / "fresh.json",
                               ctrader=FakeCTrader(), allowed_traders=set())
    assert cold._first_poll is True


def test_cold_start_adopts_a_live_entry(tmp_path, monkeypatch):
    """A fresh deploy must not sit idle until the next master happens to post.

    Only undatable posts are treated as history; a dated entry inside the window that
    the master has not exited is a live trade and is worth joining.
    """
    cold = mod.InvoCtaderCopier(dry_run=True, state_file=tmp_path / "cold.json",
                               ctrader=FakeCTrader(), allowed_traders=set())
    entry = qualified_post(post_id="p-live", shot="shot-live", minutes_old=90)
    monkeypatch.setattr(mod.InvoClient, "get_feed", lambda self, *a, **k: [entry])

    assert cold.poll_once() == 1
    assert len(cold._dry_planned) == 1


def test_cold_start_indexes_posts_it_cannot_date(tmp_path, monkeypatch):
    cold = mod.InvoCtaderCopier(dry_run=True, state_file=tmp_path / "cold2.json",
                               ctrader=FakeCTrader(), allowed_traders=set())
    undated = qualified_post(post_id="p-undated", shot="shot-undated")
    undated.pop("createdAt")
    monkeypatch.setattr(mod.InvoClient, "get_feed", lambda self, *a, **k: [undated])

    assert cold.poll_once() == 0
    assert cold._dry_planned == set()


def test_restored_cycle_copies_an_entry_posted_between_cycles(tmp_path, monkeypatch):
    # The chained runner restarts every ~10 minutes. Entries a master posts during that
    # gap used to be indexed as if they were ancient history, so they were never copied.
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"copies": {}, "seen_posts": ["seen-old"],
                                 "pending_closes": []}))
    restored = mod.InvoCtaderCopier(dry_run=True, state_file=state,
                                    ctrader=FakeCTrader(), allowed_traders=set())
    monkeypatch.setattr(mod.InvoClient, "get_feed",
                        lambda self, *a, **k: [qualified_post(post_id="p-gap",
                                                              shot="shot-gap")])

    restored.poll_once()

    assert restored._first_poll is False
    assert len(restored._dry_planned) == 1


def test_first_poll_ignores_historical_entries(copier, monkeypatch):
    stale = {
        "id": "p-old",
        "update": {"ticker": "BTC", "isOpen": True, "verifiedTrade": True,
                   "baseShortId": "shot-old", "directionLong": True,
                   "portfolio": {"id": "p1"}, "owner": {"id": "u1", "username": "x"},
                   "changes": {"isAdded": True}},
    }
    monkeypatch.setattr(mod.InvoClient, "get_feed", lambda self, *a, **k: [stale])

    copier.poll_once()

    assert copier.ctrader.orders == []
    assert copier.state["copies"] == {}


def test_unprotected_position_is_flattened(copier, monkeypatch):
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    copier.ctrader.suppress_sl = True
    copier.ctrader.sl_amend_fails = True

    assert copier.handle_open(make_signal()) is None
    assert copier.ctrader.closed == [4242]
    assert copier.state["copies"] == {}


def test_missing_stop_is_repaired_when_amend_succeeds(copier, monkeypatch):
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    copier.ctrader.suppress_sl = True

    record = copier.handle_open(make_signal())

    assert record is not None
    assert copier.ctrader.stop == record["stop"]
    assert copier.ctrader.closed == []


def test_reconcile_attributes_pnl_to_guardian(copier):
    copier.handle_open(make_signal())
    copier.ctrader.deals = [{"position_id": 4242, "net_pnl": -27.5}]

    assert copier.reconcile_closed_trades() == 1
    copy = copier.state["copies"]["shot-1"]
    assert copy["reconciled"] is True and copy["closed"] is True
    assert copy["realizedPnl"] == pytest.approx(-27.5)
    assert guardian.state["daily_losses_count"] == 1


def test_reconcile_is_idempotent(copier):
    copier.handle_open(make_signal())
    copier.ctrader.deals = [{"position_id": 4242, "net_pnl": -27.5}]

    copier.reconcile_closed_trades()
    assert copier.reconcile_closed_trades() == 0
    assert guardian.state["daily_losses_count"] == 1


def test_reconcile_ignores_foreign_positions(copier):
    copier.handle_open(make_signal())
    copier.ctrader.deals = [{"position_id": 999, "net_pnl": -500.0}]

    assert copier.reconcile_closed_trades() == 0
    assert guardian.state["daily_losses_count"] == 0


def test_rejected_close_is_queued_then_retried(copier):
    copier.handle_open(make_signal())
    copier.ctrader.fail_close = 1  # broker refuses once (e.g. market closed)

    copier.handle_close(make_signal())

    copy = copier.state["copies"]["shot-1"]
    assert copy["closed"] is False
    assert copier.state["pending_closes"] == ["shot-1"]

    assert copier.retry_pending_closes() == 1
    assert copy["closed"] is True
    assert copier.state["pending_closes"] == []
    assert copier.ctrader.closed == [4242]


def test_retry_drops_queue_entries_for_vanished_copies(copier):
    copier.state["pending_closes"] = ["ghost"]
    assert copier.retry_pending_closes() == 0
    assert copier.state["pending_closes"] == []


def test_close_without_base_short_id_falls_back_to_symbol(copier):
    copier.handle_open(make_signal())
    anonymous_close = make_signal(shot="")

    copier.handle_close(anonymous_close)

    assert copier.ctrader.closed == [4242]
    assert copier.state["copies"]["shot-1"]["closed"] is True


def test_engine_budget_blocks_second_copy(copier):
    copier.max_positions = 1

    first = copier.handle_open(make_signal(coin="BTC", shot="shot-btc"))
    second = copier.handle_open(make_signal(coin="ETH", shot="shot-eth"))

    assert first is not None
    assert second is None
    assert len(copier.ctrader.orders) == 1


def test_closed_copy_frees_budget_slot(copier):
    copier.max_positions = 1
    copier.handle_open(make_signal(coin="BTC", shot="shot-btc"))
    copier.handle_close(make_signal(coin="BTC", shot="shot-btc"))

    second = copier.handle_open(make_signal(coin="ETH", shot="shot-eth"))

    assert second is not None
    assert len(copier.ctrader.orders) == 2


def test_adopt_marks_copy_closed_when_broker_position_vanished(copier):
    copier.handle_open(make_signal())
    copier.ctrader.closed.append(4242)  # flattened at the broker, outside this process

    assert copier.adopt_broker_positions() == 1
    assert copier.state["copies"]["shot-1"]["closed"] is True
    assert "gone from broker" in copier.state["copies"]["shot-1"]["closeReason"]


def test_adopt_takes_over_untracked_broker_position(copier):
    # A position the state file knows nothing about must still be managed, otherwise
    # a lost state file would re-open the symbol and double the exposure.
    copier.ctrader.orders.append({"symbol": "ETHUSD", "side": "BUY",
                                  "volume_lots": 0.05, "stop_loss_price": 61000.0})

    assert copier.adopt_broker_positions() == 1
    adopted = copier.state["copies"]["adopted-4242"]
    assert adopted["symbol"] == "ETHUSD"
    assert adopted["adopted"] is True

    assert copier.handle_open(make_signal(coin="ETH", shot="shot-eth")) is None
    assert len(copier.ctrader.orders) == 1


def test_adoption_records_the_fill_so_the_copy_can_be_managed(copier):
    # An adopted record without an entry price is invisible to break-even.
    copier.ctrader.orders.append({"symbol": "ETHUSD", "side": "BUY",
                                  "volume_lots": 0.05, "stop_loss_price": 61000.0})

    copier.adopt_broker_positions()

    assert copier.state["copies"]["adopted-4242"]["entry"] == 62010.0
    assert copier.state["copies"]["adopted-4242"]["stop"] == 61000.0


def test_legacy_adopted_record_gets_its_entry_backfilled_then_locks_breakeven(copier):
    # Records written by the previous version have a stop but no entry.
    copier.ctrader.orders.append({"symbol": "BTCUSD", "side": "BUY",
                                  "volume_lots": 0.07, "stop_loss_price": 61000.0})
    copier.state["copies"]["legacy"] = {
        "symbol": "BTCUSD", "side": "BUY", "positionId": 4242,
        "stop": 61000.0, "closed": False, "trader": "adopted", "adopted": True,
    }
    copier.adopt_broker_positions()
    assert copier.state["copies"]["legacy"]["entry"] == 62010.0

    copier.ctrader.get_spot_price = lambda _s: {"bid": 63400.0, "ask": 63410.0}
    assert copier.lock_in_breakeven() == 1
    assert copier.state["copies"]["legacy"]["stop"] == 62010.0


def test_adopted_position_is_closed_when_its_slot_is_exited(copier):
    # The broker echoes the slot we stamped on the order, so an adopted copy is still
    # tied to exactly one master's trade instead of to the symbol.
    copier.ctrader.orders.append({"symbol": "ETHUSD", "side": "BUY",
                                  "volume_lots": 0.05, "stop_loss_price": 61000.0,
                                  "comment": "InvoCopy:ETH:shot-eth"})
    copier.adopt_broker_positions()

    assert "shot-eth" in copier.state["copies"]
    copier.handle_close(make_signal(coin="ETH", shot="shot-eth"))

    assert copier.ctrader.closed == [4242]


def test_untraceable_adopted_position_is_left_to_its_stop(copier):
    # No comment means no owner and no slot. Flattening on an unrelated exit would
    # hand a stranger's decision our position, so the stop stays in charge instead.
    copier.ctrader.orders.append({"symbol": "ETHUSD", "side": "BUY",
                                  "volume_lots": 0.05, "stop_loss_price": 61000.0})
    copier.adopt_broker_positions()

    copier.handle_close(make_signal(coin="ETH", shot="unknown-shot"))

    assert copier.ctrader.closed == []
    assert copier.state["copies"]["adopted-4242"]["closed"] is False


def test_allowlisted_master_exit_does_not_flatten_another_masters_copy(copier):
    # Both masters are vetted and both trade BTC - only the owner's exit may close us.
    copier.handle_open(make_signal(coin="BTC", shot="shot-apx", trader="apx"))
    assert len(copier.ctrader.orders) == 1

    copier.handle_close(make_signal(coin="BTC", shot=None, trader="peterr"))

    assert copier.ctrader.closed == []
    assert copier.state["copies"]["shot-apx"]["closed"] is False


def test_same_master_exiting_a_different_btc_slot_leaves_the_copy_open(copier):
    # A master can run several BTC slots at once, so a named slot we do not hold is
    # another trade - only a close post that omits the slot may fall back to symbol.
    copier.handle_open(make_signal(coin="BTC", shot="slot-a", trader="apx"))

    copier.handle_close(make_signal(coin="BTC", shot="slot-b", trader="apx"))

    assert copier.ctrader.closed == []
    assert copier.state["copies"]["slot-a"]["closed"] is False


def test_winner_moves_its_stop_to_entry_at_one_r(copier):
    # A copy that earned back its risk must stop being able to lose.
    copier.handle_open(make_signal())
    copy = copier.state["copies"]["shot-1"]
    risk = copy["entry"] - copy["stop"]
    copier.ctrader.get_spot_price = lambda _s: {"bid": copy["entry"] + risk,
                                                "ask": copy["entry"] + risk + 1.0}

    assert copier.lock_in_breakeven() == 1
    assert copier.state["copies"]["shot-1"]["stop"] == round(copy["entry"], 3)
    assert copier.ctrader._stops[4242] == round(copy["entry"], 3)
    assert copier.state["copies"]["shot-1"]["breakevenAt"]


def test_breakeven_waits_for_a_full_risk_unit(copier):
    copier.handle_open(make_signal())
    copy = copier.state["copies"]["shot-1"]
    risk = copy["entry"] - copy["stop"]
    original_stop = copy["stop"]
    copier.ctrader.get_spot_price = lambda _s: {"bid": copy["entry"] + risk * 0.9,
                                                "ask": copy["entry"] + risk}

    assert copier.lock_in_breakeven() == 0
    assert copier.state["copies"]["shot-1"]["stop"] == original_stop
    assert "breakevenAt" not in copier.state["copies"]["shot-1"]


def test_failed_breakeven_amendment_is_retried_rather_than_recorded(copier):
    # Recording a lock the broker refused would leave the trade unprotected forever.
    copier.handle_open(make_signal())
    copy = copier.state["copies"]["shot-1"]
    risk = copy["entry"] - copy["stop"]
    copier.ctrader.get_spot_price = lambda _s: {"bid": copy["entry"] + risk,
                                                "ask": copy["entry"] + risk + 1.0}
    copier.ctrader.sl_amend_fails = True

    assert copier.lock_in_breakeven() == 0
    assert "breakevenAt" not in copier.state["copies"]["shot-1"]

    copier.ctrader.sl_amend_fails = False
    assert copier.lock_in_breakeven() == 1


def test_breakeven_is_applied_once_not_repeatedly(copier):
    copier.handle_open(make_signal())
    copy = copier.state["copies"]["shot-1"]
    risk = copy["entry"] - copy["stop"]
    copier.ctrader.get_spot_price = lambda _s: {"bid": copy["entry"] + risk,
                                                "ask": copy["entry"] + risk + 1.0}

    assert copier.lock_in_breakeven() == 1
    assert copier.lock_in_breakeven() == 0


def test_closed_copy_is_left_alone_by_breakeven(copier):
    copier.handle_open(make_signal())
    copy = copier.state["copies"]["shot-1"]
    risk = copy["entry"] - copy["stop"]
    copier.ctrader.get_spot_price = lambda _s: {"bid": copy["entry"] + risk,
                                                "ask": copy["entry"] + risk + 1.0}
    copier.handle_close(make_signal())

    assert copier.lock_in_breakeven() == 0
    assert copier.ctrader._stops[4242] == copy["stop"]


def test_breakeven_uses_the_broker_fill_not_the_planned_quote(copier):
    # Breaking even on the quote leaves the difference to the real fill unhedged.
    copier.handle_open(make_signal())
    copy = copier.state["copies"]["shot-1"]
    risk = copy["entry"] - copy["stop"]
    copier.ctrader.get_spot_price = lambda _s: {"bid": copy["entry"] + risk,
                                                "ask": copy["entry"] + risk + 1.0}
    real = copier.ctrader.get_positions_strict
    copier.ctrader.get_positions_strict = lambda: [
        {**pos, "entryPrice": 62100.0} for pos in real()
    ]

    assert copier.lock_in_breakeven() == 1
    assert copier.state["copies"]["shot-1"]["stop"] == 62100.0


def test_breakeven_never_widens_a_stop_already_tighter_than_entry(copier):
    # A trailed or hand-tightened stop is better than break-even; this code must not
    # push it back out to entry just because the trade is in profit.
    copier.handle_open(make_signal())
    copy = copier.state["copies"]["shot-1"]
    copy["stop"] = copy["entry"] + 50.0
    copier.ctrader._stops[4242] = copy["stop"]
    copier.ctrader.get_spot_price = lambda _s: {"bid": copy["entry"] + 500.0,
                                                "ask": copy["entry"] + 510.0}

    assert copier.lock_in_breakeven() == 0
    assert copier.state["copies"]["shot-1"]["stop"] == copy["entry"] + 50.0
    assert copier.ctrader._stops[4242] == copy["entry"] + 50.0


def test_record_already_at_breakeven_is_marked_and_left_alone(copier):
    copier.handle_open(make_signal())
    copy = copier.state["copies"]["shot-1"]
    copy["stop"] = copy["entry"]
    copier.ctrader.get_spot_price = lambda _s: {"bid": copy["entry"] + 500.0,
                                                "ask": copy["entry"] + 510.0}

    assert copier.lock_in_breakeven() == 0
    assert copier.state["copies"]["shot-1"]["breakevenAt"]


def test_notification_failure_never_blocks_a_copy(copier, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(mod, "send_telegram_alert", boom)

    assert copier.handle_open(make_signal()) is not None
    assert len(copier.ctrader.orders) == 1


def test_rehearsal_pnl_does_not_charge_the_daily_breaker(copier):
    # A smoke test is not a master signal; charging it would burn a real strike.
    copier.handle_open({
        "postId": "r1", "action": "open",
        "owner": {"id": "self", "username": "rehearsal"},
        "trade": {"coin": "BTC", "side": "long", "leverage": 1},
        "mimicMeta": {"portfolioId": "rehearsal", "baseShortId": "REHEARSAL-1"},
    })
    copier.ctrader.closed.append(4242)
    copier.ctrader.deals.append({"position_id": 4242, "net_pnl": -12.0,
                                 "symbol_name": "BTCUSD"})

    assert copier.reconcile_closed_trades() == 1

    assert guardian.state["daily_losses_count"] == 0
    assert copier.state["copies"]["REHEARSAL-1"]["realizedPnl"] == pytest.approx(-12.0)


def test_dry_run_never_touches_broker(tmp_path):
    client = FakeCTrader()
    dry = mod.InvoCtaderCopier(dry_run=True, ctrader=client, state_file=tmp_path / "s.json",
                               allowed_traders=set())

    plan = dry.handle_open(make_signal())

    assert plan["symbol"] == "BTCUSD"
    assert client.orders == []
    assert "shot-1" not in dry.state["copies"]


def test_dry_run_dedupes_and_counts_budget_in_memory(tmp_path):
    dry = mod.InvoCtaderCopier(dry_run=True, ctrader=FakeCTrader(),
                               state_file=tmp_path / "s.json", max_positions=1,
                               allowed_traders=set())

    first = dry.handle_open(make_signal(coin="BTC", shot="shot-btc"))
    repeated = dry.handle_open(make_signal(coin="BTC", shot="shot-btc"))
    second = dry.handle_open(make_signal(coin="ETH", shot="shot-eth"))

    assert first is not None
    assert repeated is None      # same shot is not re-planned
    assert second is None        # budget consumed by the in-memory plan
    assert dry.state["copies"] == {}   # nothing persisted


def test_trader_rows_normalises_nested_payload():
    rows = mod.trader_rows([
        {"portfolio": {"id": "pf-1", "title": "Alpha", "ownerId": "u-1",
                       "winRate": 0.81, "pnl": 12.5},
         "owner": {"username": "alice"}},
        {"portfolio": {"title": "Beta"}, "owner": {"id": "u-2", "username": "bob"},
         "winRate": 63, "totalPnl": "44.0%"},
    ])

    assert [r["trader"] for r in rows] == ["bob", "alice"]      # ranked by pnl
    assert rows[0]["user_id"] == "u-2"
    assert rows[1]["user_id"] == "u-1"
    assert rows[1]["win_rate"] == pytest.approx(0.81)
    assert rows[0]["pnl"] == pytest.approx(44.0)


def test_format_traders_renders_win_rate_and_id():
    table = mod.format_traders(mod.trader_rows([
        {"portfolio": {"title": "Alpha", "ownerId": "u-1", "winRate": 0.81, "pnl": 12.5},
         "owner": {"username": "alice"}},
    ]))

    assert "@alice" in table
    assert "81.0%" in table
    assert "u-1" in table
    assert "user id" in table


def test_trader_rows_survives_unknown_payload():
    rows = mod.trader_rows([{"mystery": {"deep": 1}}, "not-a-dict"])

    assert len(rows) == 1
    assert rows[0]["user_id"] is None
    assert "?" in mod.format_traders(rows)


def test_trader_rows_drops_liquidated_accounts():
    payload = [
        {"title": "Blown", "owner": {"id": "u-bad", "username": "bad"},
         "winRate": 82.0, "percentChange": -100, "liquidated": True},
        {"title": "Alive", "owner": {"id": "u-ok", "username": "ok"},
         "winRate": 60.0, "percentChange": 12},
    ]

    assert [r["trader"] for r in mod.trader_rows(payload)] == ["ok"]
    assert len(mod.trader_rows(payload, include_liquidated=True)) == 2


def test_trader_rows_ranks_copyable_traders_first():
    payload = [
        # Bigger record, but only holds DOGE - nothing the broker can mirror.
        {"title": "Doges", "owner": {"id": "u-sol", "username": "doge"},
         "winRate": 99.0, "percentChange": 900,
         "openTrades": {"count": 1, "assets": ["DOGE"]}},
        {"title": "Btc", "owner": {"id": "u-btc", "username": "btc"},
         "winRate": 70.0, "percentChange": 40,
         "openTrades": {"count": 2, "assets": ["BTC", "SOL"]}},
    ]

    rows = mod.trader_rows(payload)

    assert [r["trader"] for r in rows] == ["btc", "doge"]
    assert rows[0]["copyable"] == ["BTC"]
    assert rows[1]["copyable"] == []


def test_empty_following_feed_warns_operator(copier, monkeypatch, caplog):
    monkeypatch.setattr(copier.invo, "get_feed", lambda *a, **k: [])

    with caplog.at_level("WARNING"):
        copier.poll_once()

    assert any("--discover" in record.message for record in caplog.records)


def test_multiple_feeds_are_merged_and_deduped(copier, monkeypatch):
    post = {
        "id": "p-shared",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "update": {"ticker": "BTC", "isOpen": True, "verifiedTrade": True,
                   "baseShortId": "shot-shared", "directionLong": True,
                   "entryPrice": 62000.0, "closingPrice": None,
                   "portfolio": QUALIFIED_PORTFOLIO,
                   "owner": {"id": "u1", "username": "x"},
                   "changes": {"isOpen": True, "reasonClosed": None}},
    }
    calls = []

    def fake(self, name, limit=20, last_post_id=None):
        if last_post_id is not None:
            return []           # this fixture only holds one page of history
        calls.append(name)
        return [post]

    monkeypatch.setattr(mod.InvoClient, "get_feed", fake)
    copier.feeds = ["following", "trending"]
    copier._first_poll = False

    assert copier.poll_once() == 1
    assert calls == ["following", "trending"]
    assert len(copier.ctrader.orders) == 1     # the shared post id is handled once


# A copy of the portfolio block Invo attaches to every post: 85% win over 400 closed
# trades and positive P&L, i.e. a record that clears the quality gate.
QUALIFIED_PORTFOLIO = {"id": "p1", "closedPositionsCount": 400,
                       "wonPositionsCount": 340, "lostPositionsCount": 60,
                       "winRate": 85.0, "plSnapshot": 1200.0}


def make_open_post(post_id="p-allow", owner_id="u-allow", shot="shot-allow",
                   is_open_snapshot=True, minutes_old=0):
    """A post shaped like the live feed's real entry events.

    The `changes` diff carries the event (what the master did). `isOpen` is only the
    position's current snapshot, which reads False once the trade has since closed.
    """
    return {
        "id": post_id,
        "createdAt": (datetime.now(timezone.utc) - timedelta(minutes=minutes_old))
                     .isoformat().replace("+00:00", "Z"),
        "update": {"ticker": "BTC", "isOpen": is_open_snapshot, "verifiedTrade": True,
                   "baseShortId": shot, "directionLong": True,
                   "entryPrice": 62000.0, "closingPrice": None,
                   "portfolio": {"id": "p1"},
                   "owner": {"id": owner_id, "username": "master"},
                   "changes": {"isOpen": True, "reasonClosed": None}},
    }


def make_close_post(post_id="p-close", owner_id="u-allow", shot="shot-allow",
                    closing_price=63100.0, minutes_old=0):
    """A real exit: Invo marks it as removed, and often omits the closing price."""
    return {
        "id": post_id,
        "createdAt": (datetime.now(timezone.utc) - timedelta(minutes=minutes_old))
                     .isoformat().replace("+00:00", "Z"),
        "update": {"ticker": "BTC", "isOpen": False, "verifiedTrade": True,
                   "baseShortId": shot, "directionLong": True,
                   "entryPrice": 62000.0, "closingPrice": closing_price,
                   "portfolio": {"id": "p1"},
                   "owner": {"id": owner_id, "username": "master"},
                   "changes": {"isAdded": False}},
    }


def test_allowlist_accepts_owner_carried_at_post_level(copier):
    # Trending posts put the owner on the post, not inside the update.
    post = make_open_post(post_id="p-trend", owner_id="u-master", shot="shot-trend")
    post["update"].pop("owner", None)
    post["owner"] = {"id": "u-master", "username": "master"}
    copier.allowed = {"u-master"}

    assert copier._allowed_post(post) is True


def test_feed_pagination_reaches_entries_beyond_the_first_page(copier, monkeypatch):
    # A burst between cycles pushes a real entry onto page 2; fetching one page only
    # would lose that trade entirely.
    noise = qualified_post(post_id="p-noise", shot="shot-noise")
    noise["update"]["ticker"] = "SOL"      # uncopyable filler occupying page 1
    entry = qualified_post(post_id="p-entry", shot="shot-entry")

    def fake(self, name, limit=20, last_post_id=None):
        if last_post_id is None:
            return [noise]
        if last_post_id == "p-noise":
            return [entry]
        return []

    monkeypatch.setattr(mod.InvoClient, "get_feed", fake)
    copier.feeds = ["following"]
    copier._first_poll = False

    assert copier.poll_once() == 2
    assert copier.state["copies"]["shot-entry"]["closed"] is False


def test_feed_pagination_stops_once_a_page_is_known_history(copier, monkeypatch):
    post = make_open_post(post_id="p-known", shot="shot-known")
    seen = []

    def fake(self, name, limit=20, last_post_id=None):
        seen.append(last_post_id)
        return [post]

    monkeypatch.setattr(mod.InvoClient, "get_feed", fake)
    copier.seen_posts.add("p-known")

    copier._feed_pages("following")

    assert seen == [None]      # one page, then stop - no needless API calls


def test_allowlist_ignores_masters_we_did_not_choose(copier, monkeypatch):
    monkeypatch.setattr(mod.InvoClient, "get_feed",
                        lambda self, *a, **k: [make_open_post(owner_id="u-stranger")])
    copier.allowed = {"u-chosen"}
    copier._first_poll = False

    assert copier.poll_once() == 0
    assert copier.ctrader.orders == []


def test_allowlist_copies_chosen_master(copier, monkeypatch):
    monkeypatch.setattr(mod.InvoClient, "get_feed",
                        lambda self, *a, **k: [make_open_post(owner_id="u-chosen")])
    copier.allowed = {"u-chosen"}
    copier._first_poll = False

    assert copier.poll_once() == 1
    assert len(copier.ctrader.orders) == 1


# -- signal quality gate ---------------------------------------------------- #
# A static allowlist cannot track who is actually posting copyable trades, so each
# signal is also judged on the portfolio record Invo attaches to the post.


def qualified_post(**kwargs):
    post = make_open_post(**kwargs)
    post["update"]["portfolio"] = dict(QUALIFIED_PORTFOLIO)
    return post


def test_unlisted_master_with_a_proven_record_is_copied(copier, monkeypatch):
    copier.allowed = set()
    copier._first_poll = False
    post = qualified_post(post_id="p-qual", owner_id="u-stranger", shot="shot-qual")
    monkeypatch.setattr(mod.InvoClient, "get_feed", lambda self, *a, **k: [post])

    copier.poll_once()

    assert len(copier.ctrader.orders) == 1


def test_unlisted_master_with_a_poor_record_is_refused(copier):
    post = qualified_post(post_id="p-poor", owner_id="u-bad", shot="shot-poor")
    post["update"]["portfolio"]["winRate"] = 52.0

    assert copier._allowed_post(post) is False


def test_thin_track_record_is_refused(copier):
    post = qualified_post(post_id="p-thin", owner_id="u-thin", shot="shot-thin")
    post["update"]["portfolio"]["closedPositionsCount"] = 5

    assert copier._allowed_post(post) is False


def test_losing_portfolio_is_refused(copier):
    post = qualified_post(post_id="p-neg", owner_id="u-neg", shot="shot-neg")
    post["update"]["portfolio"]["plSnapshot"] = -42.0

    assert copier._allowed_post(post) is False


def test_missing_win_rate_falls_back_to_won_over_closed(copier):
    post = qualified_post(post_id="p-wr", owner_id="u-wr", shot="shot-wr")
    post["update"]["portfolio"].pop("winRate")

    assert copier._allowed_post(post) is True     # 340/400 = 85%


def test_operator_allowlist_overrides_the_quality_bar(copier):
    # An explicitly chosen master is trusted even with an unrated record.
    post = make_open_post(post_id="p-trust", owner_id="u-trusted", shot="shot-trust")
    copier.allowed = {"u-trusted"}

    assert copier._allowed_post(post) is True


def test_quality_gate_can_be_switched_off(copier, monkeypatch):
    monkeypatch.setattr(mod, "QUALITY_VET", False)
    post = qualified_post(post_id="p-off", owner_id="u-off", shot="shot-off")
    copier.allowed = set()

    assert copier._allowed_post(post) is False    # nothing is copied unvetted


def test_held_position_exit_is_mirrored_whatever_the_record(copier):
    copier.handle_open(make_signal(shot="shot-held-q"))
    copier.allowed = set()
    post = make_close_post(post_id="p-held-q", owner_id="u-gone", shot="shot-held-q")
    post["update"]["portfolio"] = {"id": "p1"}

    assert copier._allowed_post(post) is True


def test_allowlist_still_mirrors_exit_for_held_copy(copier, monkeypatch):
    copier.handle_open(make_signal(shot="shot-held"))
    assert len(copier.ctrader.orders) == 1
    copier.allowed = {"u-somebody-else"}      # the master was dropped from the allowlist
    exit_post = make_close_post(post_id="p-exit", owner_id="u-dropped", shot="shot-held")
    monkeypatch.setattr(mod.InvoClient, "get_feed", lambda self, *a, **k: [exit_post])
    copier._first_poll = False

    copier.poll_once()

    assert copier.ctrader.closed == [4242]     # the exit is never swallowed


def test_broken_feed_does_not_stop_the_others(copier, monkeypatch):
    post = {
        "id": "p-good",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "update": {"ticker": "BTC", "isOpen": True, "verifiedTrade": True,
                   "baseShortId": "shot-good", "directionLong": True,
                   "entryPrice": 62000.0, "closingPrice": None,
                   "portfolio": QUALIFIED_PORTFOLIO,
                   "owner": {"id": "u1", "username": "x"},
                   "changes": {"isOpen": True, "reasonClosed": None}},
    }

    def fake(self, name, limit=20, last_post_id=None):
        if name == "trending":
            raise RuntimeError("Invo /v1_0/posts/get_feed 500: Invalid filter")
        if last_post_id is not None:
            return []
        return [post]

    monkeypatch.setattr(mod.InvoClient, "get_feed", fake)
    copier.feeds = ["trending", "following"]
    copier._first_poll = False

    assert copier.poll_once() == 1
    assert len(copier.ctrader.orders) == 1


def test_stale_daily_halt_is_released_on_a_new_day(copier, monkeypatch):
    monkeypatch.setattr(copier.invo, "get_feed", lambda *a, **k: [])
    guardian.state.update({"trading_halted": True,
                           "halt_reason": "Daily 2-Strike Stop-Loss Limit Hit (2 losses today)",
                           "halt_time": "2026-01-01 15:00 UTC"})

    copier.poll_once()

    assert guardian.state["trading_halted"] is False
    assert guardian.state["halt_reason"] is None


def test_manual_kill_switch_is_never_auto_released(copier, monkeypatch):
    monkeypatch.setattr(copier.invo, "get_feed", lambda *a, **k: [])
    guardian.state.update({"trading_halted": True,
                           "halt_reason": "Manual User Trigger via Telegram",
                           "halt_time": "2026-01-01 15:00 UTC"})

    copier.poll_once()

    assert guardian.state["trading_halted"] is True
    assert guardian.state["halt_reason"] == "Manual User Trigger via Telegram"


def test_same_day_daily_halt_stays_engaged(copier, monkeypatch):
    monkeypatch.setattr(copier.invo, "get_feed", lambda *a, **k: [])
    now = mod.datetime.now(mod.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    guardian.state.update({"trading_halted": True,
                           "halt_reason": "Daily 2-Strike Stop-Loss Limit Hit (2 losses today)",
                           "halt_time": now})

    copier.poll_once()

    assert guardian.state["trading_halted"] is True


# -- post classification ---------------------------------------------------- #
# Invo's `update.isOpen` / `closingPrice` are the position's live snapshot, not the
# event the post reported. Reading them as the event inverted every entry into an
# exit, so the copier silently took no trades at all.


def test_historical_entry_is_read_as_an_entry_not_an_exit(copier):
    # Live shape: a post that opened a trade, whose position has since closed.
    post = make_open_post(post_id="p-hist", shot="shot-hist", is_open_snapshot=False)

    assert copier.handle_post(post) == "open"
    assert len(copier.ctrader.orders) == 1
    assert copier.ctrader.closed == []


def test_exit_is_detected_even_without_a_closing_price(copier):
    copier.handle_open(make_signal(shot="shot-np"))
    post = make_close_post(post_id="p-np", shot="shot-np", closing_price=None)

    assert copier.handle_post(post) == "close"
    assert copier.ctrader.closed == [4242]


def test_real_close_marked_only_as_removed_is_an_exit(copier):
    # akira's exits carry nothing but {"isAdded": False}.
    copier.handle_open(make_signal(shot="shot-rm"))
    post = make_close_post(post_id="p-rm", shot="shot-rm")
    post["update"]["changes"] = {"isAdded": False}
    post["update"].pop("closingPrice")

    assert copier.handle_post(post) == "close"
    assert copier.ctrader.closed == [4242]


def test_averaging_in_is_not_copied_as_a_new_entry(copier):
    post = make_open_post(post_id="p-add", shot="shot-add")
    post["update"]["changes"] = {"simIncrease": True, "entryPrice": 61000.0}

    assert copier.handle_post(post) == "increase"
    assert copier.ctrader.orders == []


def test_entry_older_than_the_signal_window_is_skipped(copier):
    post = make_open_post(post_id="p-late", shot="shot-late",
                          minutes_old=mod.MAX_SIGNAL_AGE_MIN + 5)

    assert copier.handle_post(post) == "stale"
    assert copier.ctrader.orders == []


def test_fresh_entry_is_copied_even_when_the_snapshot_says_closed(copier):
    # Seen live: isOpen reads False and closedAt predates the post on fresh entries.
    post = make_open_post(post_id="p-fresh", shot="shot-fresh", is_open_snapshot=False)
    post["update"]["closedAt"] = "2020-01-01T00:00:00.000Z"

    assert copier.handle_post(post) == "open"
    assert len(copier.ctrader.orders) == 1


def test_post_without_a_recognisable_diff_is_ignored(copier):
    post = make_open_post(post_id="p-null", shot="shot-null", is_open_snapshot=None)
    post["update"]["changes"] = {}

    assert copier.handle_post(post) is None
    assert copier.ctrader.orders == []


# -- telegram heartbeat ------------------------------------------------------ #
# The cloud chains a new process every ~10 minutes, so alerting on every startup
# would send ~144 messages a day and make real alerts indistinguishable from noise.

ACCT = {"balance": 6000.0, "equity": 6000.0, "free_margin": 5000.0}


def test_repeated_cycles_do_not_re_announce(copier, monkeypatch):
    sent = []
    monkeypatch.setattr(mod, "notify", lambda msg: sent.append(msg))

    copier._heartbeat(ACCT)
    copier._heartbeat(ACCT)

    assert len([m for m in sent if "online" in m]) == 1


def test_restart_after_an_outage_announces_again(copier, monkeypatch):
    sent = []
    monkeypatch.setattr(mod, "notify", lambda msg: sent.append(msg))
    now = datetime.now(timezone.utc)
    copier.state["last_heartbeat"] = (
        now - timedelta(minutes=mod.HEARTBEAT_QUIET_MIN + 5)).isoformat()
    copier.state["last_digest_date"] = now.strftime("%Y-%m-%d")

    copier._heartbeat(ACCT)

    assert len([m for m in sent if "online" in m]) == 1


def test_daily_digest_is_sent_once_and_names_open_copies(copier, monkeypatch):
    sent = []
    monkeypatch.setattr(mod, "notify", lambda msg: sent.append(msg))
    copier.handle_open(make_signal(shot="shot-digest"))

    copier._heartbeat(ACCT)
    copier._heartbeat(ACCT)

    digests = [m for m in sent if "Daily copy report" in m]
    assert len(digests) == 1
    assert "BTCUSD" in digests[0]


# --------------------------------------------------------------------------- #
# baseShortId is a reusable slot, not a trade id. A master closes a slot and
# later opens a new position in it, so "the slot has a close post" says nothing
# about the *current* trade - only a close written AFTER the entry does.
# --------------------------------------------------------------------------- #


def test_entry_the_master_already_exited_is_not_copied(copier):
    """A close posted after the entry means the master is out - do not fill it."""
    copier.allowed = {"u-allow"}
    entry = make_open_post(minutes_old=30)
    later_exit = make_close_post(post_id="p-out", minutes_old=5)

    assert copier.handle_post(entry, context=[entry, later_exit]) == "exited"
    assert copier.ctrader.orders == []


def test_close_written_before_the_entry_belongs_to_the_previous_trade(copier):
    """The dominant live pattern: slot closed days ago, reopened now. Copy it."""
    copier.allowed = {"u-allow"}
    entry = make_open_post(minutes_old=10)
    old_exit = make_close_post(post_id="p-old", minutes_old=600)

    assert copier.handle_post(entry, context=[entry, old_exit]) == "open"
    assert len(copier.ctrader.orders) == 1


def test_swing_hold_means_a_multi_hour_entry_is_still_copyable(copier):
    """Masters hold for days, so a four-hour-old entry still has its trade ahead."""
    copier.allowed = {"u-allow"}
    entry = make_open_post(minutes_old=200)

    assert entry["update"]["changes"] == {"isOpen": True, "reasonClosed": None}
    assert copier.handle_post(entry, context=[entry]) == "open"
    assert len(copier.ctrader.orders) == 1


def test_master_reentering_a_reused_slot_is_copied(copier):
    """After our copy closes, the same slot opening again is a new trade."""
    copier.allowed = {"u-allow"}
    first = make_open_post(post_id="p-a", shot="slot-1", minutes_old=120)
    assert copier.handle_post(first, context=[first]) == "open"

    copier.state["copies"]["slot-1"]["closed"] = True
    second = make_open_post(post_id="p-b", shot="slot-1", minutes_old=0)
    assert copier.handle_post(second, context=[second]) == "open"

    assert len(copier.ctrader.orders) == 2
    # The finished trade keeps its own record so its P&L can still be reconciled.
    archived = [k for k in copier.state["copies"] if k.startswith("slot-1@")]
    assert len(archived) == 1


def test_stale_close_does_not_flatten_a_newer_copy(copier):
    """A slot's old exit must not close the position we opened after it."""
    copier.allowed = {"u-allow"}
    entry = make_open_post(minutes_old=60)
    copier.handle_post(entry, context=[entry])

    stale = make_close_post(post_id="p-old", minutes_old=240)
    copier.handle_post(stale, context=[stale])

    assert copier.ctrader.closed == []
    assert copier.state["copies"]["shot-allow"]["closed"] is False


def test_feeds_are_merged_so_a_close_on_one_feed_ends_a_trade_from_the_other(copier, monkeypatch):
    """An entry seen on 'following' can be exited on 'trending'."""
    copier.allowed = {"u-allow"}
    copier.feeds = ["following", "trending"]
    entry = make_open_post(post_id="p-feed-a", shot="slot-feed")
    exit_post = make_close_post(post_id="p-feed-b", shot="slot-feed")

    def fake_pages(feed_name):
        return [entry] if feed_name == "following" else [exit_post]

    monkeypatch.setattr(copier, "_feed_pages", fake_pages)
    copier._first_poll = False

    assert copier.poll_once() == 2
    # The entry opened a copy and the cross-feed exit then flattened it.
    assert len(copier.ctrader.orders) == 1
    assert copier.ctrader.closed == [4242]

