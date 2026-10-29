"""
Forensic Regression Suite: Oct 23 - Oct 29 Signal Audit (AC-1 through AC-5)
===========================================================================
Verifies all 9 root-cause fixes identified from the Telegram & GitHub Actions
cloud copier audit (Friday Oct 23 -> Thursday Oct 29):

1. AC-1a: `anabelsignals` inverted SL-based entry synthesis & Bias reconciliation
   (e.g. `EURJPY SELL Stop Loss: 185.62` -> entry < 185.62, and `Bias - Bullish` overrides prose `'short'`).
2. AC-1b: Price plausibility & single-digit timeframe/count rejection (`"BUY 4H"` -> 4.0, `"SELL 3M"` -> 3.0,
   cross-asset `1.11941` on `XAUUSD` rejected).
3. AC-1c: Shorthand 2-digit Gold SL/TP expansion (`Entry 4039.88` with `SL 54.66` -> `4054.66`).
4. AC-1d: Missing TP auto-synthesis (`[tp1, tp2]` synthesized when provider omits explicit TP tags) &
   `@handle` stripping (`@xauusd_signals` does not force `EURUSD` signal to `XAUUSD`).
5. AC-2a: Invariant 29 Rollover + Invariant 36 Anti-Suffocation Harmonization
   (`XAUUSD` rollover with 2.91 pt gap anchors `safe_sl` to `3.50` noise floor or original provider SL instead of aborting).
6. AC-2b: Invariant 37 Target Exhaustion & Smart Target Promotion
   (does not falsely abort at 40% target span when remaining reward >= `min_viable_reward`, and promotes `TP2`/`TP3` when `TP1` is exhausted).
7. AC-2c: Dedicated `ETHUSD` & `US30`/`NAS100` asset parameter profiles
   (never fall into `0.0050` Forex max_sl_distance branch).
8. AC-3a: Adopted broker position symbol resolution (`_resolve_broker_position_symbol` resolves via `symbolName` / `symbolId` / comment regex, never corrupting `XAUUSD` into `"EURAUD"`).
9. AC-3b & AC-4: Risk-free Breakeven runner exemption in `CTraderMCPClient.place_market_order` and `TelegramMultiSignalCopier`, plus cold-start fresh post execution (`<= 180s`) and `get_spot_price` retry/trendbar fallback.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from src.integrations.telegram_multi_signal_copier import (
    MultiChannelSignalParser,
    TelegramMultiSignalCopier,
)
from src.integrations.ctrader_mcp_client import CTraderMCPClient, RiskViolationError


def test_ac1a_anabelsignals_entry_synthesis_and_bias_reconciliation():
    """
    AC-1a:
    - Anabel `EURJPY SELL` with `Stop Loss: 185.62` and no explicit level synthesizes entry BELOW SL (185.42),
      not above SL (185.82), passing directional coherence.
    - Anabel `XAUUSD` forecast with prose 'short-term pullback' but explicit `Bias - Bullish`,
      `trading near 3982`, `Target - 3995`, `Safe Stop Loss - 3970` resolves as valid BUY.
    """
    text_eurjpy = (
        "✍️ #EURJPY SELL\n"
        "Sellers are dominating below supply zone.\n"
        "Recommended Stop Loss: 185.62"
    )
    sig_ej = MultiChannelSignalParser.parse_message(text_eurjpy, "anabelsignals")
    assert sig_ej is not None
    assert sig_ej["symbol"] == "EURJPY"
    assert sig_ej["side"] == "SELL"
    assert sig_ej["sl"] == 185.62
    assert sig_ej["entry_mid"] < 185.62
    assert sig_ej["is_valid"] is True, f"Expected valid SELL signal, got error: {sig_ej.get('validation_error')}"
    assert len(sig_ej["tps"]) >= 1 and sig_ej["tps"][0] < sig_ej["entry_mid"]

    text_gold_bias = (
        "✍️ #XAUUSD Outlook\n"
        "After a short pullback, price is trading near 3982.\n"
        "Bias - Bullish\n"
        "Target - 3995\n"
        "Safe Stop Loss - 3970"
    )
    sig_gold = MultiChannelSignalParser.parse_message(text_gold_bias, "anabelsignals")
    assert sig_gold is not None
    assert sig_gold["symbol"] == "XAUUSD"
    assert sig_gold["side"] == "BUY"
    assert sig_gold["entry_mid"] == 3982.0
    assert sig_gold["sl"] == 3970.0
    assert sig_gold["tps"] == [3995.0]
    assert sig_gold["is_valid"] is True


def test_ac1b_price_plausibility_rejects_timeframe_digits_and_cross_asset_mismatch():
    """
    AC-1b:
    - Single-digit timeframe/count numbers ('BUY 4H', 'SELL 3M', 'SELL 5M') are never parsed as 4.0/3.0/5.0 entries.
    - Cross-asset price mismatches (e.g. 1.11941 or 53.84921 or 172.38 on XAUUSD) fail plausibility.
    """
    assert MultiChannelSignalParser.is_plausible_asset_price("XAUUSD", 4.0, "4") is False
    assert MultiChannelSignalParser.is_plausible_asset_price("XAUUSD", 1.11941, "1.11941") is False
    assert MultiChannelSignalParser.is_plausible_asset_price("XAUUSD", 53.84921, "53.84921") is False
    assert MultiChannelSignalParser.is_plausible_asset_price("XAUUSD", 172.38, "172.38") is False
    assert MultiChannelSignalParser.is_plausible_asset_price("EURUSD", 4.0, "4") is False
    assert MultiChannelSignalParser.is_plausible_asset_price("EURUSD", 3.0, "3") is False
    assert MultiChannelSignalParser.is_plausible_asset_price("EURUSD", 1.0845, "1.0845") is True
    assert MultiChannelSignalParser.is_plausible_asset_price("XAUUSD", 3985.50, "3985.50") is True

    # Ensure a message with "BUY 4H" before actual entry 3985 parses 3985, not 4.0
    text_tf = "XAUUSD BUY 4H Structure Breakout\nBUY 3985\nSL: 3975\nTP: 4005"
    sig = MultiChannelSignalParser.parse_message(text_tf, "GoldSignals_io")
    assert sig is not None
    assert sig["entry_mid"] == 3985.0
    assert sig["is_valid"] is True


def test_ac1c_shorthand_2digit_gold_sl_tp_expansion():
    """
    AC-1c:
    - Shorthand 2-digit Gold SL/TP values (e.g. SELL 4039.88 with SL 54.66 -> 4054.66)
      are expanded using the century prefix of the entry price.
    """
    text_short = "GOLD SELL @ 4039.88\nSL: 54.66\nTP1: 35.00\nTP2: 28.00"
    sig = MultiChannelSignalParser.parse_message(text_short, "VasilyTrader")
    assert sig is not None
    assert sig["symbol"] == "XAUUSD"
    assert sig["side"] == "SELL"
    assert sig["entry_mid"] == 4039.88
    assert sig["sl"] == 4054.66
    assert sig["tps"] == [4035.0, 4028.0]
    assert sig["is_valid"] is True


def test_ac1d_missing_tp_synthesis_and_handle_stripping():
    """
    AC-1d:
    - Signals with valid symbol, side, entry, and SL but missing explicit TP tags synthesize default [tp1, tp2].
    - @handles like @xauusd_signals do not pollute symbol detection when the signal is actually EURUSD.
    """
    text_no_tp = "Shared by @xauusd_signals\nEURUSD SELL\nEntry: 1.0850\nSL: 1.0885"
    sig = MultiChannelSignalParser.parse_message(text_no_tp, "ProSignalsFx")
    assert sig is not None
    assert sig["symbol"] == "EURUSD"
    assert sig["side"] == "SELL"
    assert sig["entry_mid"] == 1.0850
    assert sig["sl"] == 1.0885
    assert sig.get("tps_synthesized") is True
    assert len(sig["tps"]) == 2
    assert sig["tps"][0] < 1.0850
    assert sig["is_valid"] is True


def test_ac2a_rollover_and_anti_suffocation_harmonization():
    """
    AC-2a:
    - When Invariant 29 triggers a Target Rollover on XAUUSD with a 2.91 pt gap (e.g. Entry 3972.00,
      Spot 3969.09 on SELL, TP 3955.00), `execute_signal()` does NOT abort on Invariant 36
      Anti-Suffocation (`2.91 < 3.50` noise floor). Instead, it anchors `safe_sl` to preserve
      at least the `3.50` pt noise floor (3969.09 + 3.50 = 3972.59) and places the order!
    """
    mock_ctrader = MagicMock()
    mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
    mock_ctrader.get_spot_price.return_value = {"bid": 3969.09, "ask": 3969.29}
    mock_ctrader.get_positions_strict.return_value = []
    mock_ctrader.place_market_order.return_value = {"orderId": 9001, "positionId": 9001}

    copier = TelegramMultiSignalCopier(ctrader_client=mock_ctrader, dry_run=False)
    copier.send_telegram_alert = MagicMock()
    copier.check_market_hours = MagicMock(return_value=True)
    copier.check_conflicts = MagicMock(return_value=False)
    copier.fetch_channel_posts = MagicMock(return_value=[{
        "post_id": "XAUUSD_GOLD_TRADING_FOREX/8801",
        "post_url": "https://t.me/XAUUSD_GOLD_TRADING_FOREX/8801",
        "text": "XAUUSD SELL 3972.00\nSL: 3982.00\nTP1: 3964.00\nTP2: 3955.00",
        "published_ts": datetime.now(timezone.utc).timestamp(),
    }])
    copier.state["watermarks"] = {"XAUUSD_GOLD_TRADING_FOREX": "XAUUSD_GOLD_TRADING_FOREX/8800"}
    copier.state["executed_signal_keys"] = []

    copier.poll_cycle()

    assert mock_ctrader.place_market_order.called, "Expected rollover trade to execute without Anti-Suffocation abort"
    call_kwargs = mock_ctrader.place_market_order.call_args[1]
    assert call_kwargs["symbol"] == "XAUUSD"
    assert call_kwargs["side"] == "SELL"
    # SL must be at least 3.50 pts above 3969.09 (>= 3972.59) so Invariant 36 never aborts
    assert call_kwargs["stop_loss_price"] >= 3972.59


def test_ac2b_invariant_37_target_exhaustion_and_smart_target_promotion():
    """
    AC-2b:
    - Signal is NOT aborted when 50% of TP1 span is consumed if remaining reward >= min_viable_reward (1.50 pts on Gold).
    - When TP1 IS exhausted (e.g. remaining reward < 1.50 pts), TP2/TP3 are automatically promoted instead of aborting.
    """
    mock_ctrader = MagicMock()
    mock_ctrader.get_balance.return_value = {"balance": 6000.0, "equity": 6000.0}
    # Entry 3980, TP1 3984, TP2 3990. Spot is 3982.0 (50% of TP1 consumed, 2.0 pts remaining >= 1.50 min_viable_reward, within 2.50 max_slippage)
    mock_ctrader.get_spot_price.return_value = {"bid": 3981.80, "ask": 3982.00}

    copier = TelegramMultiSignalCopier(ctrader_client=mock_ctrader, dry_run=True)
    copier.check_market_hours = MagicMock(return_value=True)
    copier.check_conflicts = MagicMock(return_value=False)
    copier.execute_signal = MagicMock()
    copier.fetch_channel_posts = MagicMock(return_value=[{
        "post_id": "XAUUSD_GOLD_TRADING_FOREX/8810",
        "post_url": "https://t.me/XAUUSD_GOLD_TRADING_FOREX/8810",
        "text": "XAUUSD BUY 3980.00\nSL: 3970.00\nTP1: 3984.00\nTP2: 3992.00",
    }])
    copier.state["watermarks"] = {"XAUUSD_GOLD_TRADING_FOREX": "XAUUSD_GOLD_TRADING_FOREX/8809"}
    copier.state["executed_signal_keys"] = []

    copier.poll_cycle()
    assert copier.execute_signal.called, "50% consumed span with 2.0 pts remaining reward must NOT be aborted"
    sig_executed, _ = copier.execute_signal.call_args[0]
    assert sig_executed["tps"] == [3984.0, 3992.0]

    # Case 2: TP1 (3983.0) has only 1.0 pt remaining at spot 3982.0 (< 1.50 min_viable_reward), so TP2 (3992.0) is promoted!
    copier.execute_signal.reset_mock()
    copier.state["executed_signal_keys"] = []
    copier.fetch_channel_posts = MagicMock(return_value=[{
        "post_id": "XAUUSD_GOLD_TRADING_FOREX/8811",
        "post_url": "https://t.me/XAUUSD_GOLD_TRADING_FOREX/8811",
        "text": "XAUUSD BUY 3980.00\nSL: 3970.00\nTP1: 3983.00\nTP2: 3992.00",
    }])
    copier.poll_cycle()
    assert copier.execute_signal.called, "Exhausted TP1 with viable TP2 must promote TP2 and execute"
    sig_promoted, _ = copier.execute_signal.call_args[0]
    assert sig_promoted["tps"] == [3992.0]


def test_ac2c_eth_and_index_asset_parameters():
    """
    AC-2c:
    - ETHUSD and US30/NAS100 have dedicated risk profiles and never fall into the 0.0050 Forex branch.
    """
    copier = TelegramMultiSignalCopier(dry_run=True)
    p_eth = copier.get_asset_parameters("ETHUSD")
    assert p_eth["max_sl_distance"] == 100.0
    assert p_eth["max_slippage"] == 15.0
    assert p_eth["max_rollover_slippage"] == 30.0

    p_us30 = copier.get_asset_parameters("US30")
    assert p_us30["max_sl_distance"] == 100.0
    assert p_us30["max_slippage"] == 25.0
    assert p_us30["max_rollover_slippage"] == 45.0


def test_ac3a_adopted_broker_position_symbol_resolution_never_corrupts_to_euraud():
    """
    AC-3a:
    - `_resolve_broker_position_symbol` resolves symbol via `symbolName`, `symbolId`, or `Sig_<ch>_<SYM>_T1`
      comment regex, and never defaults an adopted XAUUSD position to 'EURAUD'.
    """
    mock_ctrader = MagicMock()
    mock_ctrader.get_symbol_map.return_value = {"XAUUSD": 41, "EURUSD": 1}
    copier = TelegramMultiSignalCopier(ctrader_client=mock_ctrader, dry_run=True)

    # 1. Resolved by symbolId when symbolName is omitted by cTrader raw position payload
    pos_by_id = {"positionId": 555, "symbolId": 41, "tradeSide": "SELL", "entryPrice": 3980.0}
    assert copier._resolve_broker_position_symbol(pos_by_id, []) == "XAUUSD"

    # 2. Resolved by comment regex when both symbolName and symbolId map are unavailable
    mock_ctrader.get_symbol_map.return_value = {}
    pos_by_comment = {
        "positionId": 556,
        "symbolId": 999,
        "comment": "Sig_ssfgold_XAUUSD_T1",
        "tradeSide": "SELL",
        "entryPrice": 3980.0,
    }
    assert copier._resolve_broker_position_symbol(pos_by_comment, []) == "XAUUSD"

    # 3. Unknown position without symbolName/symbolId/comment returns None (skipped cleanly, never 'EURAUD')
    pos_unknown = {"positionId": 557, "symbolId": 999, "tradeSide": "SELL", "entryPrice": 3980.0}
    assert copier._resolve_broker_position_symbol(pos_unknown, []) is None


def test_ac3b_and_ac4_be_runner_exemption_cold_start_freshness_and_spot_fallback():
    """
    AC-3b & AC-4:
    - Risk-free BE-locked runner positions on cTrader do not trigger DUPLICATE ASSET or CONCURRENCY violations,
      whereas at-risk positions still enforce the lock.
    - Cold-start channel initialization executes signals published within the last 180 seconds.
    - `CTraderMCPClient.get_spot_price` falls back to M1 trendbar close if `get_spot_prices` returns empty.
    """
    client = CTraderMCPClient()
    client.get_symbol_map = MagicMock(return_value={"XAUUSD": 41, "EURUSD": 1})

    # A position whose stopLoss (3980.50) is >= entryPrice (3980.00) on a BUY is risk-free BE
    client.get_positions_strict = MagicMock(return_value=[
        {
            "positionId": 101,
            "symbolId": 41,
            "symbolName": "XAUUSD",
            "tradeSide": "BUY",
            "entryPrice": 3980.00,
            "stopLoss": 3980.50,
        }
    ])
    client.get_spot_price = MagicMock(return_value={"bid": 3990.0, "ask": 3990.2})
    client.call_tool = MagicMock(return_value={
        "result": {"content": [{"type": "text", "text": '{"orderId": 202, "positionId": 202}'}]}
    })

    # Should NOT raise RiskViolationError because position #101 is locked at BE+
    res = client.place_market_order("XAUUSD", side="BUY", volume_lots=0.01, stop_loss_price=3982.0, take_profit_price=4000.0)
    assert res is not None and res.get("orderId") == 202

    # Conversely, if stopLoss (3970.00) < entryPrice (3980.00) on BUY, it IS at-risk and MUST block duplicate asset
    client.get_positions_strict = MagicMock(return_value=[
        {
            "positionId": 101,
            "symbolId": 41,
            "symbolName": "XAUUSD",
            "tradeSide": "BUY",
            "entryPrice": 3980.00,
            "stopLoss": 3970.00,
        }
    ])
    with pytest.raises(RiskViolationError, match="DUPLICATE ASSET VIOLATION"):
        client.place_market_order("XAUUSD", side="BUY", volume_lots=0.01, stop_loss_price=3982.0, take_profit_price=4000.0)

    # Cold-start freshness check: post published 45s ago is executed on cold start; post 600s ago is watermarked only
    now_ts = datetime.now(timezone.utc).timestamp()
    assert TelegramMultiSignalCopier._is_fresh_cold_start_post({"published_ts": now_ts - 45.0}) is True
    assert TelegramMultiSignalCopier._is_fresh_cold_start_post({"published_ts": now_ts - 600.0}) is False

    # Spot price trendbar fallback when get_spot_prices returns empty
    client2 = CTraderMCPClient()
    client2.get_symbol_map = MagicMock(return_value={"XAUUSD": 41})
    client2.call_tool = MagicMock(return_value={"result": {"content": [{"type": "text", "text": '{"prices": []}'}]}})
    client2.get_trendbars_dataframe = MagicMock(return_value=pd.DataFrame([
        {"open": 3984.0, "high": 3986.0, "low": 3983.5, "close": 3985.25, "volume": 100}
    ]))
    with patch("src.integrations.ctrader_streamer.get_streamed_spot_price", return_value=None):
        spot_fb = client2.get_spot_price("XAUUSD")
    assert spot_fb is not None
    assert spot_fb["bid"] == 3985.25
    assert spot_fb["ask"] == 3985.25
    assert spot_fb.get("source") == "trendbar_fallback"


def test_ac3c_forex_breakeven_amend_position_preserves_5_digits_and_tp_from_orders():
    """
    Verifies the root cause of the EURUSD (#299651557), GBPCAD (#299755539), GBPAUD (#299829567),
    and CADCHF (#300074628) losses:
    - When `amend_position(pos_id, stop_loss=1.89748)` is called (even without `symbol`),
      `CTraderMCPClient.amend_position` resolves `symbolId: 16` (`GBPAUD`) and `limitPrice: 1.89928`
      from `data_det["orders"]` (`STOP_LOSS_TAKE_PROFIT`), sending 5-digit `stopLoss: 1.89748`
      and `takeProfit: 1.89928` instead of rounding to 2 decimals (`1.90`).
    """
    import json
    client = CTraderMCPClient()
    client.get_symbol_map = MagicMock(return_value={"GBPAUD": 16, "XAUUSD": 41})

    calls = []
    def mock_call_tool(name, args=None):
        calls.append((name, args))
        if name == "get_position_details":
            payload = {
                "position": {"positionId": 299829567, "symbolId": 16, "tradeSide": "BUY", "volume": 700000},
                "orders": [{
                    "orderId": 325274156,
                    "symbolId": 16,
                    "orderType": "STOP_LOSS_TAKE_PROFIT",
                    "limitPrice": 1.89928,
                    "stopPrice": 1.8935,
                }]
            }
            return {"result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}
        return {"result": {"content": [{"type": "text", "text": '{"status": "OK"}'}]}}

    client.call_tool = mock_call_tool
    client.amend_position(299829567, stop_loss=1.89748)

    amend_calls = [args for name, args in calls if name == "amend_position"]
    assert len(amend_calls) == 1
    assert amend_calls[0]["stopLoss"] == 1.89748
    assert amend_calls[0]["takeProfit"] == 1.89928

