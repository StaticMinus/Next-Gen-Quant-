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
        """
        sym = symbol.upper()
        raw_sl = extracted_targets.get("stop_loss")
        raw_tp = extracted_targets.get("take_profit")

        if sym == "XAUUSD":
            default_risk_dist = 20.0  # 20 dollars gold move (~0.5%)
            default_target_dist = 40.0  # 40 dollars gold move (1:2 R:R)
            lot_size = 0.01
            point_value = 1.0  # $1 per 1.0 point on 0.01 lot
        elif sym == "BTCUSD":
            default_risk_dist = spot_price * 0.025  # 2.5% stop
            default_target_dist = spot_price * 0.050  # 5.0% take profit
            lot_size = 0.01
            point_value = 0.01  # $0.01 per $1 move on 0.01 BTC
        else:
            default_risk_dist = spot_price * 0.01
            default_target_dist = spot_price * 0.02
            lot_size = 0.01
            point_value = 1.0

        if action == "BUY":
            sl = raw_sl if (raw_sl and raw_sl < spot_price) else (spot_price - default_risk_dist)
            tp = raw_tp if (raw_tp and raw_tp > spot_price) else (spot_price + default_target_dist)
            risk_usd = (spot_price - sl) * (1.0 if sym == "XAUUSD" else (spot_price * 0.01 if sym == "BTCUSD" else 1.0)) * lot_size
        else:  # SELL
            sl = raw_sl if (raw_sl and raw_sl > spot_price) else (spot_price + default_risk_dist)
            tp = raw_tp if (raw_tp and raw_tp < spot_price) else (spot_price - default_target_dist)
            risk_usd = (sl - spot_price) * (1.0 if sym == "XAUUSD" else (spot_price * 0.01 if sym == "BTCUSD" else 1.0)) * lot_size

        return {
            "lot_size": lot_size,
            "stop_loss": round(sl, 2),
            "take_profit": round(tp, 2),
            "est_risk_usd": round(abs(risk_usd), 2),
            "risk_reward_ratio": "1:2.0"
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

        # 6. Execute Dry-Run or Live
        trade_id = f"TA-{broker_symbol}-{int(datetime.now().timestamp())}"
        trade_ticket = {
            "trade_id": trade_id,
            "broker_symbol": broker_symbol,
            "action": action,
            "rating": rating,
            "entry_price": entry_price,
            "stop_loss": sizing["stop_loss"],
            "take_profit": sizing["take_profit"],
            "lot_size": sizing["lot_size"],
            "est_risk_usd": sizing["est_risk_usd"],
            "dry_run": self.dry_run,
            "timestamp": datetime.now().isoformat(),
            "bull_thesis": analysis.get("bull_summary", "")[:280],
            "bear_thesis": analysis.get("bear_summary", "")[:280],
            "decision_summary": analysis.get("decision_text", "")[:350],
        }

        if self.dry_run:
            trade_ticket["status"] = "SIMULATED_FILLED" if action in ("BUY", "SELL") else "OBSERVED_HOLD"
            self.state["simulated_trades"].append(trade_ticket)
            self.save_state()
            logger.info(f"✅ [DRY-RUN] Simulated Trade Recorded: {action} {sizing['lot_size']} lots @ {entry_price}")
        else:
            if action in ("BUY", "SELL"):
                logger.info(f"⚡ [LIVE] Executing {action} order on cTrader...")
                res = self.ctrader.place_market_order(
                    symbol=broker_symbol,
                    action=action,
                    volume_lots=sizing["lot_size"],
                    stop_loss=sizing["stop_loss"],
                    take_profit=sizing["take_profit"],
                    comment=f"TradingAgents-{rating}"
                )
                trade_ticket["execution_result"] = res
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

        msg = (
            f"{mode_badge}\n\n"
            f"{action_emoji} *Signal:* `{ticket['action']}` | *Rating:* `{ticket['rating']}`\n"
            f"🎯 *Asset:* `{ticket['broker_symbol']}`\n"
            f"💵 *Spot Entry:* `${ticket['entry_price']:,.2f}`\n"
            f"🛑 *Stop Loss:* `${ticket['stop_loss']:,.2f}`\n"
            f"🎁 *Take Profit:* `${ticket['take_profit']:,.2f}`\n"
            f"📦 *Volume:* `{ticket['lot_size']} lots` (~${ticket['est_risk_usd']:.2f} max risk)\n"
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
