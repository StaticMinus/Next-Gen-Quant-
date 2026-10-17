"""
Telegram Gold (XAUUSD) Signal Copier for cTrader
================================================
Monitors public Telegram channel (t.me/XAUUSD_GOLD_TRADING_FOREX), parses real-time
Gold trading calls, filters out spam/promotional messages, checks anti-chase price limits,
and executes 3 split-target trades (0.05 lot each) on cTrader with automatic Breakeven locks.

Rules & FundedNext Protection:
- Symbol: XAUUSD (symbolId: 41)
- 3 split tickets (0.05 lot each = 0.15 lot total)
  * Ticket 1: TP1 (+8 pts) -> Locks in +$40 USD
  * Ticket 2: TP2 (+10 pts) -> Locks in +$50 USD
  * Ticket 3: TP3 (+20 pts) -> Locks in +$100 USD
- Protective Stop Loss: Clamps wide channel SLs to max 10.0 points ($50 risk per ticket / $150 total risk max).
- Auto Breakeven Lock: Once Ticket 1 fills at TP1, SL on Tickets 2 & 3 is moved to Entry.
- Anti-Chase Guard: Rejects signals if market price has already slipped > 2.50 points from entry.
- Duplicate Filter: Prevents duplicate execution if signal is re-posted or quoted.
"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

from src.integrations.ctrader_mcp_client import CTraderMCPClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [GoldCopier] %(messageサービス)s" if hasattr(logging, "messageサービス") else "%(asctime)s [%(levelname)s] [GoldCopier] %(message)s"
)
logger = logging.getLogger("telegram_gold_copier")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PRIMARY_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8428715579")
CHANNEL_URL = "https://t.me/s/XAUUSD_GOLD_TRADING_FOREX"
STATE_FILE = ROOT_DIR / "cache" / "gold_copier_state.json"

DEFAULT_LOT_SIZE = 0.05
MAX_SL_DISTANCE_POINTS = 10.0  # Max $10.00 price distance ($50 risk per 0.05 lot ticket)
MAX_SLIPPAGE_TOLERANCE = 2.50   # Max $2.50 price deviation to prevent chasing late entries


class TelegramGoldCopier:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.ctrader = CTraderMCPClient()
        self.state = self.load_state()

        # Cold-start watermark: on boot, record current latest post ID so past messages are NEVER executed
        if not self.state.get("last_processed_post_id"):
            try:
                initial_msgs = self.fetch_channel_messages()
                if initial_msgs:
                    self.state["last_processed_post_id"] = initial_msgs[-1]["post_id"]
                    self.save_state()
                    logger.info(f"🛡️ Cold-start initialized: Watermark set to {self.state['last_processed_post_id']}. Past messages ignored.")
            except Exception as e:
                logger.warning(f"Could not fetch initial watermark: {e}")

    def load_state(self) -> dict:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load state, creating fresh: {e}")
        return {
            "last_processed_post_id": None,
            "executed_signal_keys": [],
            "active_positions": []  # List of {ticket: 1/2/3, pos_id: 123, entry: 4280.0, tp: 4272.0}
        }

    def save_state(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def send_telegram_alert(self, message: str):
        """Sends rich formatted alert to David's Telegram."""
        if not TELEGRAM_BOT_TOKEN:
            logger.warning("TELEGRAM_BOT_TOKEN not configured.")
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": PRIMARY_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to dispatch Telegram alert: {e}")

    def fetch_channel_messages(self) -> List[Dict[str, Any]]:
        """Scrapes recent public posts from Telegram channel preview."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            resp = requests.get(CHANNEL_URL, headers=headers, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"Telegram channel fetch returned HTTP {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            wraps = soup.find_all("div", class_="tgme_widget_message_wrap")
            messages = []
            for w in wraps:
                msg_div = w.find("div", class_="tgme_widget_message")
                if not msg_div:
                    continue
                post_id = msg_div.get("data-post")
                txt_div = w.find("div", class_="tgme_widget_message_text")
                text = txt_div.get_text(separator=" ").strip() if txt_div else ""
                time_tag = w.find("time")
                datetime_str = time_tag.get("datetime") if time_tag else ""

                if post_id and text:
                    messages.append({
                        "post_id": post_id,
                        "text": text,
                        "datetime": datetime_str
                    })
            return messages
        except Exception as e:
            logger.error(f"Error fetching Telegram channel: {e}")
            return []

    def parse_and_validate_signal(self, text: str, current_spot: Optional[float] = None) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Parses text for Gold signal signature, filters out promo/spam/celebration messages,
        and enforces anti-chase price tolerance. Prioritizes signal syntax over footer promo links.
        """
        # 1. Normalize broken space digits inside numbers (e.g. '4 355' -> '4355', '40 62' -> '4062')
        text_normalized = re.sub(r"(\d{1,2})\s+(\d{2,3})\b", r"\1\2", text)
        # Normalize range digits e.g. '4348-44' -> '4348'
        text_normalized = re.sub(r"(\d{4})-\d{2,4}", r"\1", text_normalized)

        # 2. Clean text for regex
        text_clean = re.sub(r"[^\w\s\./#:\-@]", " ", text_normalized)

        # 3. Match Action (BUY/SELL) and 4-digit Entry Price
        m_side = re.search(r"(BUY|SELL)(?:\s+(?:NOW|MORE|GOLD|XAUUSD|AT|@))*[\s:\-@]*(\d{4}(?:\.\d+)?)", text_clean, re.IGNORECASE)
        if not m_side:
            # Also check if format is 'GOLD/XAUUSD (BUY|SELL) 4xxx'
            m_side = re.search(r"(?:GOLD|XAUUSD)[\s:\-@]+(BUY|SELL)[\s:\-@]*(\d{4}(?:\.\d+)?)", text_clean, re.IGNORECASE)

        # If no valid trading signal signature is present, apply spam/celebration filters
        if not m_side:
            text_lower = text.lower()
            spam_keywords = ["shering", "profit share", "daily return", "vip", "dubbel", "investment", "double", "account management", "tournament"]
            for kw in spam_keywords:
                if kw in text_lower:
                    return None, f"Promo/Spam filtered ({kw})"
            if any(k in text_lower for k in ["hit", "running", "zero loss", "boom", "congratulations"]):
                return None, "Celebration update filtered"
            return None, "No Action and 4-digit Entry found"

        # Signal signature found! Extract parameters
        side = m_side.group(1).upper()
        entry = float(m_side.group(2))

        # Match Stop Loss (or fallback to default safe 10.0 pts if minimal format)
        m_sl = re.search(r"(?:STOP\s*LOSS|SL)[\s:\-@]*(\d{4}(?:\.\d+)?)", text_clean, re.IGNORECASE)
        if m_sl:
            raw_sl = float(m_sl.group(1))
        else:
            raw_sl = (entry - MAX_SL_DISTANCE_POINTS) if side == "BUY" else (entry + MAX_SL_DISTANCE_POINTS)

        # Match Take Profits (or fallback to standard targets if minimal format)
        tp_matches = re.findall(r"(?:TAKE\s*PROFIT|TP)\s*(?:[123¹²³]|\d)?[\s:\-@]*(\d{4}(?:\.\d+)?)", text_clean, re.IGNORECASE)
        if not tp_matches:
            potential_tps = re.findall(r"\b4\d{3}(?:\.\d+)?\b", text_clean)
            tp_matches = [p for p in potential_tps if float(p) != entry and float(p) != raw_sl]

        tps = [float(x) for x in tp_matches][:3]
        if not tps:
            if side == "BUY":
                tps = [entry + 8.0, entry + 10.0, entry + 20.0]
            else:
                tps = [entry - 8.0, entry - 10.0, entry - 20.0]

        # Validate logic direction
        if side == "BUY":
            tps = sorted(tps)
            if raw_sl >= entry:
                return None, "Invalid BUY: SL is above entry"
            # Safe Clamped Stop Loss (max 10 points risk)
            safe_sl = max(raw_sl, entry - MAX_SL_DISTANCE_POINTS)
        else:
            tps = sorted(tps, reverse=True)
            if raw_sl <= entry:
                return None, "Invalid SELL: SL is below entry"
            # Safe Clamped Stop Loss (max 10 points risk)
            safe_sl = min(raw_sl, entry + MAX_SL_DISTANCE_POINTS)

        # Anti-Chase / Price Slippage Guard (only if live current_spot is provided)
        if current_spot is not None:
            slippage = abs(current_spot - entry)
            if slippage > MAX_SLIPPAGE_TOLERANCE:
                return None, f"Anti-Chase: Spot {current_spot:.2f} is {slippage:.2f} pts from Entry {entry:.2f} (max {MAX_SLIPPAGE_TOLERANCE})"

        signal_key = f"XAUUSD_{side}_{entry:.1f}_{raw_sl:.1f}"

        return {
            "symbol": "XAUUSD",
            "side": side,
            "entry": entry,
            "raw_sl": raw_sl,
            "safe_sl": safe_sl,
            "tps": tps,
            "signal_key": signal_key
        }, "OK"

    def execute_copier_signal(self, sig: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Executes split tickets on cTrader based on GOLD_COPIER_TICKET_MODE (TWO_TICKETS or THREE_TICKETS)."""
        side = sig["side"]
        entry = sig["entry"]
        safe_sl = sig["safe_sl"]

        ticket_mode = os.getenv("GOLD_COPIER_TICKET_MODE", "TWO_TICKETS").upper()
        max_targets = 3 if ticket_mode == "THREE_TICKETS" else 2
        tps = sig["tps"][:max_targets]

        executed = []
        logger.info(f"🚀 Executing {len(tps)}-ticket Gold Copier orders ({ticket_mode}): {side} {sig['symbol']} @ {entry} | Safe SL: {safe_sl} | TPs: {tps}")

        for i, tp in enumerate(tps, start=1):
            comment = f"GoldCopier TP{i} #{sig['signal_key']}"
            if self.dry_run:
                logger.info(f"  [DRY-RUN] Ticket #{i}: {DEFAULT_LOT_SIZE} lots {side} XAUUSD | SL: {safe_sl} | TP{i}: {tp}")
                executed.append({
                    "ticket": i,
                    "positionId": 999000 + i,
                    "volume": DEFAULT_LOT_SIZE,
                    "side": side,
                    "entry": entry,
                    "tp": tp,
                    "sl": safe_sl
                })
            else:
                try:
                    res = self.ctrader.place_market_order(
                        symbol="XAUUSD",
                        side=side,
                        volume_lots=DEFAULT_LOT_SIZE,
                        stop_loss_price=safe_sl,
                        take_profit_price=tp,
                        comment=comment,
                        bypass_concurrency_check=True
                    )
                    pos_id = (
                        res.get("positionId")
                        or (res.get("position", {}).get("positionId") if isinstance(res.get("position"), dict) else None)
                        or res.get("orderId")
                    )
                    logger.info(f"  ✅ [LIVE] Ticket #{i} placed successfully: Position #{pos_id} | TP: {tp}")
                    executed.append({
                        "ticket": i,
                        "positionId": pos_id,
                        "volume": DEFAULT_LOT_SIZE,
                        "side": side,
                        "entry": entry,
                        "tp": tp,
                        "sl": safe_sl
                    })
                except Exception as e:
                    logger.error(f"  ❌ Failed to place Ticket #{i}: {e}")

        # Record in active positions state for Breakeven tracking
        self.state.setdefault("active_positions", []).extend(executed)
        self.state.setdefault("executed_signal_keys", []).append(sig["signal_key"])
        self.save_state()

        # Send Minimalist 1-Line Telegram Alert
        tps_str = f"TP1: {tps[0]:.2f}" + (f" | TP2: {tps[1]:.2f}" if len(tps) > 1 else "")
        alert_msg = f"🟢 <b>{side} Gold @ {entry:.2f}</b> | {tps_str} | SL: {safe_sl:.2f}"
        self.send_telegram_alert(alert_msg)
        return executed

    def manage_active_positions_breakeven(self):
        """Monitors active copier positions and moves SL to Breakeven (+0.30 pt buffer) when TP1 hits."""
        active = self.state.get("active_positions", [])
        if not active:
            return

        if self.dry_run:
            return

        try:
            live_positions = self.ctrader.get_positions() or []
            live_pos_ids = {p.get("positionId") for p in live_positions}

            # Check if Ticket 1 has closed (hit TP1)
            t1_items = [p for p in active if p.get("ticket") == 1]
            remaining_tickets = [p for p in active if p.get("ticket") in (2, 3)]

            for t1 in t1_items:
                t1_id = t1.get("positionId")
                # If t1 is no longer in live positions, it closed (likely hit TP1)
                if t1_id and t1_id not in live_pos_ids:
                    entry_price = t1.get("entry")
                    side = t1.get("side", "BUY")
                    # Commission buffer (+0.30 pts on BUY, -0.30 pts on SELL) to cover broker fee
                    be_price = round(entry_price + 0.30 if side == "BUY" else entry_price - 0.30, 2)
                    logger.info(f"🎯 Ticket #1 (#{t1_id}) closed! Moving remaining tickets to Breakeven @ {be_price}...")

                    for rem in remaining_tickets:
                        rem_id = rem.get("positionId")
                        if rem_id and rem_id in live_pos_ids and not rem.get("be_locked"):
                            try:
                                self.ctrader.amend_position(rem_id, stop_loss=be_price)
                                rem["be_locked"] = True
                                logger.info(f"  🛡️ Ticket #{rem.get('ticket')} (#{rem_id}) SL moved to Breakeven {be_price}")
                                self.send_telegram_alert(
                                    f"🛡️ <b>TP1 Banked!</b> Ticket #{rem.get('ticket')} SL moved to Breakeven @ <code>{be_price:.2f}</code> (+Commission Buffer)"
                                )
                            except Exception as ae:
                                logger.error(f"Failed to amend Ticket #{rem_id} to Breakeven: {ae}")

            # Clean up closed positions from state
            self.state["active_positions"] = [p for p in active if p.get("positionId") in live_pos_ids]
            self.save_state()
        except Exception as e:
            logger.error(f"Error managing active Breakeven positions: {e}")

    def process_raw_message(self, text: str, post_id: Optional[str] = None, msg_datetime: Optional[str] = None) -> bool:
        """Processes a single raw text message from MTProto push or web poll."""
        if not text:
            return False

        # 1. Weekend check: Gold market closed from Friday 22:00 UTC to Sunday 22:00 UTC
        from datetime import timezone
        now_utc = datetime.now(timezone.utc)
        weekday = now_utc.weekday()  # 4=Friday, 5=Saturday, 6=Sunday
        hour = now_utc.hour
        if weekday == 5 or (weekday == 4 and hour >= 22) or (weekday == 6 and hour < 22):
            logger.info(f"⏸️ [WEEKEND FILTER] Market is closed (UTC {now_utc.strftime('%A %H:%M')}). Ignoring signal.")
            return False

        # 2. Freshness check: reject messages older than 5 minutes
        if msg_datetime:
            try:
                dt = datetime.fromisoformat(msg_datetime.replace("Z", "+00:00"))
                age_seconds = (now_utc - dt).total_seconds()
                if age_seconds > 300:
                    logger.debug(f"⏭️ Skipping stale message ({post_id}): posted {age_seconds:.0f}s ago (> 300s max allowed)")
                    return False
            except Exception as e:
                logger.debug(f"Could not parse msg_datetime '{msg_datetime}': {e}")

        # 3. Concurrency check: Max 1 active signal setup (2 tickets = 0.10 lots).
        # Only allow a second signal entry if the active trade has already reached Breakeven!
        active = self.state.get("active_positions", [])
        if active:
            unlocked = [p for p in active if not p.get("be_locked")]
            if unlocked:
                logger.info("⏸️ [CONCURRENCY GUARD] An active Gold trade is currently open and has not yet hit Breakeven. Skipping new signal.")
                return False

        # 4. Strict Daily Loss Circuit Breaker: Enforce configurable daily loss limit
        bal_data = self.ctrader.get_balance()
        if bal_data:
            current_bal = bal_data.get("equity") or bal_data.get("balance") or 5840.0
            daily_floor = float(os.getenv("DAILY_DRAWDOWN_FLOOR", "5650.0"))
            if current_bal <= daily_floor:
                logger.warning(f"🛑 [DAILY DRAWDOWN CIRCUIT BREAKER] Current equity ${current_bal:.2f} is at safety floor (${daily_floor:.2f}). All execution locked until reset.")
                return False

        # 5. Fetch live spot price and spread on cTrader
        spot_data = self.ctrader.get_spot_price("XAUUSD")
        if not spot_data or not spot_data.get("bid"):
            if not self.ctrader.initialize():
                logger.warning("cTrader offline. Retrying...")
                return False
            spot_data = self.ctrader.get_spot_price("XAUUSD") or {}

        current_spot = float(spot_data.get("bid", 0.0))
        ask_spot = float(spot_data.get("ask", 0.0))
        if current_spot <= 0:
            logger.warning("Could not obtain live XAUUSD spot price.")
            return False

        # 6. Spread check: broker spread must be <= 1.50 points
        if ask_spot > 0:
            spread_pts = abs(ask_spot - current_spot)
            if spread_pts > 1.50:
                logger.warning(f"⚠️ [SPREAD FILTER] Gold spread is {spread_pts:.2f} pts (> 1.50 max allowed). Skipping trade to prevent slippage.")
                return False

        # 7. Validate signal syntax & anti-chase tolerance
        sig, reason = self.parse_and_validate_signal(text, current_spot=current_spot)
        if not sig:
            return False

        # 8. Deduplication check: verify signal key has not already been executed
        if sig["signal_key"] in self.state.get("executed_signal_keys", []):
            return False

        # 9. Execute orders
        logger.info(f"✨ [0-LATENCY SIGNAL DETECTED] ({post_id or 'PUSH'}): {sig['side']} {sig['symbol']} @ {sig['entry']}")
        self.execute_copier_signal(sig)
        if post_id:
            self.state["last_processed_post_id"] = post_id
        self.save_state()
        return True

    def run_poll_cycle(self):
        """Single poll cycle: checks channel, extracts new signal, verifies price, and executes."""
        messages = self.fetch_channel_messages()
        if not messages:
            return

        # Check latest messages
        for msg in messages[-3:]:
            post_id = msg["post_id"]
            text = msg["text"]
            dt = msg.get("datetime")
            if self.process_raw_message(text, post_id=post_id, msg_datetime=dt):
                break

        # Check existing trades for Breakeven management
        self.manage_active_positions_breakeven()


def start_telethon_listener(copier: TelegramGoldCopier):
    """Starts the Telethon 0-Latency MTProto push client."""
    api_id_val = os.getenv("TELEGRAM_API_ID", "39413180")
    api_hash_val = os.getenv("TELEGRAM_API_HASH", "bdc5dff1961bdf031366120670658e58")
    bot_token_val = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_target = os.getenv("TELEGRAM_CHANNEL_HANDLE", "XAUUSD_GOLD_TRADING_FOREX")

    if not api_id_val or not api_hash_val or not bot_token_val:
        logger.warning("[Telethon] Missing API credentials, running in Web-Poller mode only.")
        return

    try:
        from telethon import TelegramClient, events
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        session_path = str(ROOT_DIR / "cache" / "gold_copier_bot.session")
        client = TelegramClient(session_path, int(api_id_val), api_hash_val, loop=loop)

        @client.on(events.NewMessage(chats=channel_target))
        async def on_new_channel_message(event):
            raw_text = event.raw_text or ""
            logger.info(f"⚡ [Telethon MTProto Event] New push from {channel_target}: {raw_text[:60]}...")
            copier.process_raw_message(raw_text, post_id=str(event.id))

        async def main_async():
            await client.start(bot_token=bot_token_val)
            logger.info(f"🚀 [Telethon MTProto] 0-Latency listener connected to @{channel_target} successfully!")
            await client.run_until_disconnected()

        loop.run_until_complete(main_async())
    except Exception as e:
        logger.warning(f"[Telethon] MTProto client startup note: {e} (Falling back to 2s high-speed poller)")


def start_copier_daemon(interval_sec: int = 2, dry_run: bool = False):
    """Starts the continuous 24/7 Telegram Gold signal listener (Dual MTProto + Poller Engine)."""
    import threading

    copier = TelegramGoldCopier(dry_run=dry_run)
    mode_str = "DRY-RUN (Simulated)" if dry_run else "LIVE EXECUTION (cTrader)"
    logger.info(f"🚀 Telegram Gold Copier started in {mode_str} mode. Polling every {interval_sec}s + MTProto Push active...")

    # 1. Start Telethon MTProto Push in background thread
    t_proto = threading.Thread(target=start_telethon_listener, args=(copier,), daemon=True, name="TelethonPushWorker")
    t_proto.start()

    # 2. Main loop: 2s Web Poller + Breakeven Position Manager
    while True:
        try:
            copier.run_poll_cycle()
            time.sleep(interval_sec)
        except KeyboardInterrupt:
            logger.info("Gold Copier stopped by user.")
            break
        except Exception as e:
            logger.error(f"Unexpected error in Gold Copier loop: {e}")
            time.sleep(5)


def parse_gold_signal(text: str, current_spot: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Convenience helper to parse and validate a raw Telegram signal string."""
    copier = TelegramGoldCopier(dry_run=True)
    sig, _ = copier.parse_and_validate_signal(text, current_spot=current_spot)
    return sig


if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv or "-d" in sys.argv
    start_copier_daemon(interval_sec=2, dry_run=is_dry)
