"""
TradingAgents Execution & Dry-Run Engine
========================================
Combines TradingAgents multi-agent signals with cTrader live quotes
and FundedNext Risk Guardian safety controls.

Supports:
- 100% Dry-Run / Paper validation mode with live ticks
- Automated risk-based lot sizing (0.01 lot strict micro risk)
- Broker stop-loss and take-profit calculations
- Telegram dispatch with full multi-agent debate summary
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

from src.integrations.ctrader_mcp_client import CTraderMCPClient
from src.integrations.risk_guardian import guardian
from src.integrations.tradingagents_bridge import TradingAgentsBridge

logger = logging.getLogger("tradingagents_dry_runner")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [TradingAgentsRunner] %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

load_dotenv()

STATE_FILE = Path("cache/tradingagents_execution_state.json")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PRIMARY_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8428715579")


class TradingAgentsRunner:
    def __init__(
        self,
        bridge: Optional[TradingAgentsBridge] = None,
        ctrader_client: Optional[CTraderMCPClient] = None,
        dry_run: bool = True
    ):
        self.bridge = bridge or TradingAgentsBridge()
        self.account_id = os.getenv("CTRADER_TRADINGAGENTS_ACCOUNT_ID", "5947478")
        ta_token = os.getenv("CTRADER_TRADINGAGENTS_ACCESS_TOKEN") or os.getenv("CTRADER_ACCESS_TOKEN")
        self.ctrader = ctrader_client or CTraderMCPClient(token=ta_token)
        self.dry_run = dry_run
        self.state = self.load_state()

    def load_state(self) -> Dict[str, Any]:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load state: {e}")
        return {"simulated_trades": [], "active_positions": {}, "last_run": None}

    def save_state(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    def calculate_lot_and_stops(
        self,
        symbol: str,
        action: str,
        spot_price: float,
        extracted_targets: Dict[str, Optional[float]]
    ) -> Dict[str, Any]:
        """
        Calculates conservative stop-loss, take-profit, and lot size.
        For FundedNext $6K account:
        - Gold (XAUUSD): 0.01 lot (100 oz cents / $1 per $1 move).
          Max risk capped at $30 (30 pts / $30.00).
        - Bitcoin (BTCUSD): 0.01 lot.
          Max risk capped at $40 (4000 pts / $40.00).
        - Forex Majors (EURUSD, GBPUSD, AUDUSD, etc.): 0.01 lot (1,000 units, $0.10/pip).
          Default 30-pip risk ($3.00), 60-pip target (1:2 R:R). 5-decimal precision.
        - Forex JPY Pairs (USDJPY, EURJPY, GBPJPY): 0.01 lot.
          Default 35-pip risk ($2.30), 70-pip target (1:2 R:R). 3-decimal precision.
        """
        sym = symbol.upper()
        raw_sl = extracted_targets.get("stop_loss")
        raw_tp = extracted_targets.get("take_profit")

        is_jpy = "JPY" in sym
        is_forex = sym in (
            "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY"
        )

        # Dual-Ticket sizing: Ticket 1 @ 0.05 lots (banker), Ticket 2 @ 0.07 lots (runner)
        lot_t1 = float(os.getenv("TRADINGAGENTS_TICKET1_LOT_SIZE", "0.05"))
        lot_t2 = float(os.getenv("TRADINGAGENTS_TICKET2_LOT_SIZE", "0.07"))

        if sym == "XAUUSD":
            default_risk_dist = 2.50   # 2.50 pts Gold (~$12.50 risk on 0.05 lot, ~$17.50 on 0.07 lot)
            default_tp1_dist = 4.00    # 4.00 pts Gold TP1 (~1:1.6 R:R)
            default_tp2_dist = 7.50    # 7.50 pts Gold TP2 runner (~1:3.0 R:R)
            risk_per_unit = 100.0      # 100 oz per 1.0 lot -> $1.00/pt on 0.01 lot
            decimals = 2
        elif sym == "BTCUSD":
            default_risk_dist = spot_price * 0.015   # 1.5% stop
            default_tp1_dist = spot_price * 0.030    # 3.0% TP1
            default_tp2_dist = spot_price * 0.050    # 5.0% TP2 runner
            risk_per_unit = 1.0
            decimals = 2
        elif is_forex:
            if is_jpy:
                default_risk_dist = 0.30             # 30 pips
                default_tp1_dist = 0.50              # 50 pips TP1
                default_tp2_dist = 0.90              # 90 pips TP2
                risk_per_unit = (100000.0 / spot_price) if spot_price > 0 else 650.0
                decimals = 3
            else:
                default_risk_dist = 0.0025           # 25 pips ($12.50 on 0.05, $17.50 on 0.07)
                default_tp1_dist = 0.0040            # 40 pips TP1
                default_tp2_dist = 0.0075            # 75 pips TP2 runner
                risk_per_unit = 100000.0             # 1.0 lot = 100k units ($10/pip)
                decimals = 5
        else:
            default_risk_dist = spot_price * 0.01
            default_tp1_dist = spot_price * 0.02
            default_tp2_dist = spot_price * 0.035
            risk_per_unit = 1.0
            decimals = 2

        # Enforce mathematical dollar risk ceiling ($35 max across both tickets)
        max_dollar_risk = 35.0
        total_vol = lot_t1 + lot_t2
        max_allowed_dist = max_dollar_risk / (risk_per_unit * total_vol) if (risk_per_unit * total_vol) > 0 else default_risk_dist

        if action == "BUY":
            raw_dist = (spot_price - raw_sl) if (raw_sl and raw_sl < spot_price) else default_risk_dist
            dist = min(raw_dist, max_allowed_dist)
            sl = spot_price - dist
            tp1 = raw_tp if (raw_tp and raw_tp > spot_price) else (spot_price + default_tp1_dist)
            tp2 = (spot_price + default_tp2_dist) if (not raw_tp or raw_tp <= spot_price) else (raw_tp * 1.005)
            risk_usd_t1 = dist * risk_per_unit * lot_t1
            risk_usd_t2 = dist * risk_per_unit * lot_t2
        else:  # SELL
            raw_dist = (raw_sl - spot_price) if (raw_sl and raw_sl > spot_price) else default_risk_dist
            dist = min(raw_dist, max_allowed_dist)
            sl = spot_price + dist
            tp1 = raw_tp if (raw_tp and raw_tp < spot_price) else (spot_price - default_tp1_dist)
            tp2 = (spot_price - default_tp2_dist) if (not raw_tp or raw_tp >= spot_price) else (raw_tp * 0.995)
            risk_usd_t1 = dist * risk_per_unit * lot_t1
            risk_usd_t2 = dist * risk_per_unit * lot_t2

        return {
            "lot_size": lot_t1,
            "stop_loss": round(sl, decimals),
            "take_profit": round(tp1, decimals),
            "est_risk_usd": round(abs(risk_usd_t1 + risk_usd_t2), 2),
            "ticket1": {
                "lot_size": lot_t1,
                "stop_loss": round(sl, decimals),
                "take_profit": round(tp1, decimals),
                "est_risk_usd": round(abs(risk_usd_t1), 2),
            },
            "ticket2": {
                "lot_size": lot_t2,
                "stop_loss": round(sl, decimals),
                "take_profit": round(tp2, decimals),
                "est_risk_usd": round(abs(risk_usd_t2), 2),
            },
            "risk_reward_ratio": "1:1.6 / 1:3.0"
        }

    def run_cycle_for_symbol(self, broker_symbol: str) -> Dict[str, Any]:
        """Runs complete multi-agent analysis and simulates or executes the trade."""
        logger.info(f"=== Starting TradingAgents Cycle for {broker_symbol} (Dry-Run: {self.dry_run}) ===")

        # 1. Initialize cTrader and check telemetry
        c_init = self.ctrader.initialize()
        if not c_init:
            logger.warning("cTrader MCP failed to initialize. Running with fallback telemetry.")
            balance_info = {"balance": 6079.57, "equity": 6079.57}
            spot_quote = None
        else:
            balance_info = self.ctrader.get_balance() or {"balance": 6079.57, "equity": 6079.57}
            spot_quote = self.ctrader.get_spot_price(broker_symbol)

        # 2. Verify FundedNext Risk Guardian
        equity = balance_info.get("equity", 6000.0)
        daily_dd = balance_info.get("balance", 6000.0) - equity
        open_positions = self.ctrader.get_positions() if c_init else []

        if len(open_positions) >= 2:
            msg = f"Trade Rejected: Max concurrent positions ceiling reached ({len(open_positions)}/2)."
            logger.warning(msg)
            return {"success": False, "reason": msg}

        if daily_dd > 150.0:  # Within $30 of $180 limit
            msg = f"Trade Rejected: Daily drawdown warning (${daily_dd:.2f} close to $180 limit)."
            logger.warning(msg)
            return {"success": False, "reason": msg}

        # 3. Multi-Agent Analysis via TradingAgentsBridge
        analysis = self.bridge.analyze_symbol(broker_symbol)
        if not analysis.get("success"):
            return {"success": False, "reason": "TradingAgents analysis failed", "error": analysis.get("error")}

        rating = analysis["rating"]
        action = analysis["action"]

        # 4. Resolve fresh spot price at execution time
        fresh_quote = self.ctrader.get_spot_price(broker_symbol)
        if fresh_quote and fresh_quote.get("bid"):
            spot_quote = fresh_quote

        if spot_quote and spot_quote.get("bid"):
            entry_price = spot_quote["ask"] if action == "BUY" else spot_quote["bid"]
        else:
            # Fallback for offline/mock
            entry_price = 80720.0 if "BTC" in broker_symbol else 4016.50

        # 5. Calculate Sizing & Risk
        sizing = self.calculate_lot_and_stops(broker_symbol, action, entry_price, analysis["extracted_targets"])
        t1 = sizing["ticket1"]
        t2 = sizing["ticket2"]

        # 6. Execute Dry-Run or Live
        trade_id = f"TA-{broker_symbol}-{int(datetime.now().timestamp())}"
        trade_ticket = {
            "trade_id": trade_id,
            "broker_symbol": broker_symbol,
            "action": action,
            "rating": rating,
            "entry_price": entry_price,
            "stop_loss": t1["stop_loss"],
            "take_profit": t1["take_profit"],
            "lot_size": t1["lot_size"],
            "ticket1": t1,
            "ticket2": t2,
            "est_risk_usd": sizing["est_risk_usd"],
            "dry_run": self.dry_run,
            "timestamp": datetime.now().isoformat(),
            "bull_thesis": analysis.get("bull_summary", "")[:280],
            "bear_thesis": analysis.get("bear_summary", "")[:280],
            "decision_summary": analysis.get("decision_text", "")[:350],
        }

        if self.dry_run:
            trade_ticket["status"] = "SIMULATED_FILLED" if action in ("BUY", "SELL") else "OBSERVED_HOLD"
            trade_ticket["tickets"] = [
                {"ticket": 1, "lot_size": t1["lot_size"], "sl": t1["stop_loss"], "tp": t1["take_profit"]},
                {"ticket": 2, "lot_size": t2["lot_size"], "sl": t2["stop_loss"], "tp": t2["take_profit"]}
            ]
            self.state["simulated_trades"].append(trade_ticket)
            self.save_state()
            logger.info(f"✅ [DRY-RUN] Dual-Ticket Simulated: {action} T1={t1['lot_size']} lots, T2={t2['lot_size']} lots @ {entry_price}")
        else:
            if action in ("BUY", "SELL"):
                logger.info(f"⚡ [LIVE] Executing Dual-Ticket {action} on cTrader (T1={t1['lot_size']}, T2={t2['lot_size']})...")
                # Place Ticket 1 (0.05 lots)
                res1 = self.ctrader.place_market_order(
                    symbol=broker_symbol,
                    side=action,
                    volume_lots=t1["lot_size"],
                    stop_loss_price=t1["stop_loss"],
                    take_profit_price=t1["take_profit"],
                    comment=f"TradingAgents-{rating}-T1"
                )
                trade_ticket["execution_result_t1"] = res1

                # Place Ticket 2 (0.07 lots) if capacity permits
                active_pos = self.ctrader.get_positions() or []
                if len(active_pos) < 2:
                    res2 = self.ctrader.place_market_order(
                        symbol=broker_symbol,
                        side=action,
                        volume_lots=t2["lot_size"],
                        stop_loss_price=t2["stop_loss"],
                        take_profit_price=t2["take_profit"],
                        comment=f"TradingAgents-{rating}-T2"
                    )
                    trade_ticket["execution_result_t2"] = res2
                else:
                    logger.warning("Max 2 positions reached after Ticket 1. Ticket 2 skipped for safety.")

                trade_ticket["status"] = "LIVE_SUBMITTED"
            else:
                trade_ticket["status"] = "HOLD_NO_ORDER"

        # 7. Dispatch Telegram Alert
        self.send_telegram_ticket(trade_ticket, equity)

        return {
            "success": True,
            "ticket": trade_ticket,
            "analysis": analysis
        }

    def send_telegram_ticket(self, ticket: Dict[str, Any], equity: float):
        """Sends rich formatted trade ticket to Telegram."""
        if not TELEGRAM_BOT_TOKEN or not PRIMARY_CHAT_ID:
            logger.info("Telegram credentials not configured. Skipping alert.")
            return

        mode_badge = "🧪 *DRY-RUN / PAPER TICKET*" if ticket["dry_run"] else "⚡ *LIVE CTRADER EXECUTION*"
        action_emoji = "🟢" if ticket["action"] == "BUY" else ("🔴" if ticket["action"] == "SELL" else "🟡")

        t1 = ticket.get("ticket1", {})
        t2 = ticket.get("ticket2", {})
        t1_str = f"T1: `{t1.get('lot_size', 0.05)} lots` (TP: ${t1.get('take_profit', ticket['take_profit']):,.2f})" if t1 else f"`{ticket['lot_size']} lots`"
        t2_str = f"\nT2: `{t2.get('lot_size', 0.07)} lots` (TP: ${t2.get('take_profit', ticket['take_profit']):,.2f} Runner)" if t2 else ""

        msg = (
            f"{mode_badge}\n\n"
            f"{action_emoji} *Signal:* `{ticket['action']}` | *Rating:* `{ticket['rating']}`\n"
            f"🎯 *Asset:* `{ticket['broker_symbol']}`\n"
            f"💵 *Spot Entry:* `${ticket['entry_price']:,.2f}`\n"
            f"🛑 *Stop Loss:* `${ticket['stop_loss']:,.2f}`\n"
            f"🎁 *Dual Targets:*\n   • {t1_str}{t2_str}\n"
            f"📦 *Total Sizing:* `{t1.get('lot_size', 0.05) + t2.get('lot_size', 0.07):.2f} lots` (~${ticket['est_risk_usd']:.2f} total risk)\n"
            f"🛡️ *FundedNext Account:* `#{self.account_id}` (${equity:,.2f})\n\n"
            f"🧠 *Multi-Agent Consensus:*\n"
            f"• *Bull Case:* {ticket['bull_thesis']}...\n"
            f"• *Bear Case:* {ticket['bear_thesis']}...\n\n"
            f"📋 *Executive Rationale:*\n_{ticket['decision_summary']}..._\n\n"
            f"⏰ _{datetime.now().strftime('%Y-%m-%d %H:%M:%S WAT')}_"
        )

        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": PRIMARY_CHAT_ID,
                "text": msg,
                "parse_mode": "Markdown"
            }
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info("Telegram ticket sent successfully.")
            else:
                logger.warning(f"Telegram returned status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.warning(f"Failed to send Telegram notification: {e}")
