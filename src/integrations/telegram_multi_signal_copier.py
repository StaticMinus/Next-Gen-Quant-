"""
Universal Multi-Channel Signal Copier for cTrader
=================================================
Monitors multiple high-signal public Telegram channels (ssfgold, forexgdpfree,
learn2tradenews, XAUUSD_GOLD_TRADING_FOREX), parses real-time Gold and Forex calls,
filters out promotional/spam messages, enforces anti-chase price limits, prevents
inter-channel directional conflicts, and executes risk-managed positions on cTrader
with automated Breakeven protection.

Supported Assets:
- Commodities: XAUUSD (Gold)
- Forex Majors: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD
- Forex Crosses: EURJPY, GBPJPY, AUDNZD, GBPCHF, USDNOK
"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

from src.integrations.ctrader_mcp_client import CTraderMCPClient, RiskViolationError
from src.integrations.guard_sentinel import RestrictedActionsGuard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [MultiCopier] %(message)s"
)
logger = logging.getLogger("telegram_multi_signal_copier")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PRIMARY_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8428715579")
STATE_FILE = ROOT_DIR / "cache" / "multi_signal_copier_state.json"

CHANNELS_CONFIG = [
    {"id": "ssfgold", "name": "SureShotFX Gold", "enabled": True, "assets": ["XAUUSD"]},
    {"id": "forexgdpfree", "name": "ForexGDP Free", "enabled": True, "assets": ["ALL"]},
    {"id": "learn2tradenews", "name": "Learn 2 Trade", "enabled": True, "assets": ["ALL"]},
    {"id": "anabelsignals", "name": "Anabel Signals", "enabled": True, "assets": ["ALL"]},
    {"id": "XAUUSD_GOLD_TRADING_FOREX", "name": "Gold Scalper", "enabled": True, "assets": ["XAUUSD"]},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}


class MultiChannelSignalParser:
    """Universal signal signature extractor across all target Telegram channels."""

    @classmethod
    def clean_text(cls, raw: str) -> str:
        t = raw.replace("&#33;", "!").replace("&#036;", "$").replace("&amp;", "&").replace("&#39;", "'").replace("&#092;", "/")
        return t

    @classmethod
    def parse_message(cls, text: str, channel: str) -> Optional[Dict[str, Any]]:
        text_clean = cls.clean_text(text)
        text_lower = text_clean.lower()

        # Hard filters: locked teasers, tournament spam, recaps
        if any(w in text_lower for w in ["locked", "tournament", "weekend market brief", "week ahead", "bonus"]):
            return None
        if "to get full trade management" in text_lower and not ("sl:" in text_lower or "tp:" in text_lower):
            return None

        # 1. SSFGOLD FORMAT: "XAUUSD BUY 4179.76  SL:  4169.76 TP:  4199.76" or "XAUUSD BUY STOP 4177.4 SL: 4167.4 TP: 4197.4"
        m_ssf = re.search(r"\b(XAUUSD|GOLD)\s+(BUY|SELL)(?:\s+(?:STOP|LIMIT|NOW))?\s+([\d\.]+)\s+SL:\s*([\d\.]+)\s+TP:\s*([\d\.]+)", text_clean, re.IGNORECASE)
        if m_ssf:
            side = m_ssf.group(2).upper()
            entry = float(m_ssf.group(3))
            sl = float(m_ssf.group(4))
            tp = float(m_ssf.group(5))
            return {
                "channel": channel,
                "symbol": "XAUUSD",
                "side": side,
                "entry_min": entry,
                "entry_max": entry,
                "entry_mid": entry,
                "sl": sl,
                "tps": [tp],
                "type": "DIRECT_EXECUTION"
            }

        # 2. FOREXGDP FORMAT: "Sell AUDNZD at any price between 1.2348 till 1.2375 ... Target 1: 1.2300 ... Stop loss: 1.2436"
        m_fgdp = re.search(
            r"(?:(?:Forex|Gold)?\s*Signal[\s\S]*?)?(BUY|SELL)\s+([A-Z]{6}|XAUUSD)[\s\S]*?between\s+([\d\.]+)\s+till\s+([\d\.]+)",
            text_clean, re.IGNORECASE
        )
        if m_fgdp:
            side = m_fgdp.group(1).upper()
            sym = m_fgdp.group(2).upper()
            e1 = float(m_fgdp.group(3))
            e2 = float(m_fgdp.group(4))
            entry_min, entry_max = min(e1, e2), max(e1, e2)
            entry_mid = (e1 + e2) / 2.0
            targets = [float(x) for x in re.findall(r"Target\s*\d?\s*:\s*([\d\.]+)", text_clean, re.IGNORECASE)]
            m_sl = re.search(r"Stop\s*loss\s*:\s*([\d\.]+)", text_clean, re.IGNORECASE)
            sl = float(m_sl.group(1)) if m_sl else None
            if sl:
                return {
                    "channel": channel,
                    "symbol": sym,
                    "side": side,
                    "entry_min": entry_min,
                    "entry_max": entry_max,
                    "entry_mid": entry_mid,
                    "sl": sl,
                    "tps": targets,
                    "type": "ZONE_EXECUTION"
                }

        # 3. LEARN2TRADE FORMAT: "SIGNAL — GOLD (XAU/USD) SHORT ... Entry: $4,210 – $4,230 ... TP1: $4,130 SL: $4,265"
        m_l2t_sym = re.search(r"\b([A-Z]{3}/[A-Z]{3}|XAU/USD|GOLD)\b[\s\S]*?\b(BUY|SELL|LONG|SHORT)\b", text_clean, re.IGNORECASE)
        m_l2t_entry = re.search(r"Entry(?:\s*Zone)?:\s*[\$]?([\d\.,]+)\s*[–\-]\s*[\$]?([\d\.,]+)", text_clean, re.IGNORECASE)
        m_l2t_sl = re.search(r"(?:SL|Stop\s*Loss):\s*[\$]?([\d\.,]+)", text_clean, re.IGNORECASE)

        if m_l2t_sym and m_l2t_entry and m_l2t_sl:
            raw_sym = m_l2t_sym.group(1).upper().replace("/", "")
            if "GOLD" in raw_sym: raw_sym = "XAUUSD"
            raw_side = m_l2t_sym.group(2).upper()
            side = "BUY" if raw_side in ["BUY", "LONG"] else "SELL"
            e1 = float(m_l2t_entry.group(1).replace(",", ""))
            e2 = float(m_l2t_entry.group(2).replace(",", ""))
            entry_min, entry_max = min(e1, e2), max(e1, e2)
            entry_mid = (e1 + e2) / 2.0
            sl = float(m_l2t_sl.group(1).replace(",", ""))
            tps = [float(x.replace(",", "")) for x in re.findall(r"TP\d?:\s*[\$]?([\d\.,]+)", text_clean, re.IGNORECASE)]
            return {
                "channel": channel,
                "symbol": raw_sym,
                "side": side,
                "entry_min": entry_min,
                "entry_max": entry_max,
                "entry_mid": entry_mid,
                "sl": sl,
                "tps": tps,
                "type": "ZONE_EXECUTION"
            }

        # 4. ANABELSIGNALS FORMAT:
        # Supports both (signal) with explicit SL, and (forecast) with entry level + target/goal
        m_ana_header = re.search(r"✍️([A-Z0-9]+)\s+.*?\s+(BUY|SELL)", text_clean, re.IGNORECASE)
        m_ana_sl = re.search(r"(?:Stop\s*Loss|My\s*Stop\s*Loss|Recommended\s*Stop\s*Loss|Safe\s*Stop\s*Loss)\s*-\s*(\d+(?:\.\d+)?)", text_clean, re.IGNORECASE)
        m_ana_target = re.search(r"(?:Target|Goal)\s*-\s*(\d+(?:\.\d+)?)", text_clean, re.IGNORECASE)
        m_ana_level = re.search(r"(?:tests|level|trading on|around).*?(\d+(?:\.\d+)?)", text_clean, re.IGNORECASE)

        if m_ana_header and (m_ana_sl or (m_ana_level and m_ana_target)):
            raw_sym = m_ana_header.group(1).upper()
            if "GOLD" in raw_sym: raw_sym = "XAUUSD"
            side = m_ana_header.group(2).upper()
            entry = float(m_ana_level.group(1)) if m_ana_level else None
            tp = float(m_ana_target.group(1)) if m_ana_target else None

            if m_ana_sl:
                sl = float(m_ana_sl.group(1))
                if not entry:
                    entry = sl + 10.0 if side == "SELL" else sl - 10.0
            else:
                # Forecast without written SL: attach safe clamped Stop Loss
                if entry and tp:
                    dist = abs(tp - entry)
                    sl = (entry - dist) if side == "BUY" else (entry + dist)
                else:
                    sl = (entry - 10.0) if side == "BUY" else (entry + 10.0)

            tps = [tp] if tp else []
            return {
                "channel": channel,
                "symbol": raw_sym,
                "side": side,
                "entry_min": entry,
                "entry_max": entry,
                "entry_mid": entry,
                "sl": round(sl, 5),
                "tps": tps,
                "type": "ANABEL_DIRECT"
            }

        # 5. LEGACY DIRECT FORMAT: "BUY GOLD 4280 SL 4270 TP 4288"
        m_legacy = re.search(r"(BUY|SELL)(?:\s+(?:NOW|MORE|GOLD|XAUUSD|AT|@))*[\s:\-@]*(\d{4}(?:\.\d+)?)", text_clean, re.IGNORECASE)
        if m_legacy:
            side = m_legacy.group(1).upper()
            entry = float(m_legacy.group(2))
            m_sl = re.search(r"(?:STOP\s*LOSS|SL)[\s:\-@]*(\d{4}(?:\.\d+)?)", text_clean, re.IGNORECASE)
            sl = float(m_sl.group(1)) if m_sl else (entry - 10 if side == "BUY" else entry + 10)
            tp_matches = re.findall(r"(?:TAKE\s*PROFIT|TP)\s*(?:[123¹²³]|\d)?[\s:\-@]*(\d{4}(?:\.\d+)?)", text_clean, re.IGNORECASE)
            tps = [float(x) for x in tp_matches][:3]
            return {
                "channel": channel,
                "symbol": "XAUUSD",
                "side": side,
                "entry_min": entry,
                "entry_max": entry,
                "entry_mid": entry,
                "sl": sl,
                "tps": tps,
                "type": "LEGACY_DIRECT"
            }

        return None


class TelegramMultiSignalCopier:
    def __init__(self, dry_run: bool = False, ctrader_client: Optional[CTraderMCPClient] = None):
        self.dry_run = dry_run
        self.ctrader = ctrader_client if ctrader_client is not None else CTraderMCPClient()
        self.state = self.load_state()
        self.guard = RestrictedActionsGuard(max_volume=0.20, max_sl_points=10.0, floor_equity=5650.0)

        # Cold-start watermark initialization per channel
        watermarks = self.state.setdefault("watermarks", {})
        for ch in CHANNELS_CONFIG:
            ch_id = ch["id"]
            if not watermarks.get(ch_id):
                try:
                    msgs = self.fetch_channel_posts(ch_id)
                    if msgs:
                        watermarks[ch_id] = msgs[-1]["post_id"]
                        logger.info(f"🛡️ Cold-start [{ch_id}]: Watermark set to {watermarks[ch_id]}")
                except Exception as e:
                    logger.warning(f"Could not set watermark for {ch_id}: {e}")
        self.save_state()

    def load_state(self) -> dict:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load state, creating fresh: {e}")
        return {
            "watermarks": {},
            "executed_signal_keys": [],
            "active_positions": []
        }

    def save_state(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def send_telegram_alert(self, message: str):
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

    def fetch_channel_posts(self, channel_id: str) -> List[Dict[str, Any]]:
        url = f"https://t.me/s/{channel_id}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=12)
            if resp.status_code != 200:
                return []
            pattern = r'data-post="([^"]+)"[\s\S]*?<div class="tgme_widget_message_text[^>]*>([\s\S]*?)</div>'
            matches = re.findall(pattern, resp.text)
            messages = []
            for pid, raw_html in matches:
                clean_text = re.sub(r'<br\s*/?>', '\n', raw_html)
                clean_text = re.sub(r'<[^>]+>', '', clean_text).strip()
                if clean_text:
                    messages.append({"post_id": pid, "text": clean_text})
            return messages
        except Exception as e:
            logger.error(f"Error fetching channel {channel_id}: {e}")
            return []

    def get_asset_parameters(self, symbol: str) -> Dict[str, Any]:
        sym = symbol.upper()
        if "XAU" in sym or "GOLD" in sym:
            return {
                "lot_size": float(os.getenv("GOLD_COPIER_LOT_SIZE", "0.07")),
                "max_sl_distance": 10.0,
                "max_slippage": 2.50,
                "be_buffer": 0.30,
                "trailing_distance": 3.00,       # 30 pips / 3.0 pts Gold
                "trailing_activation": 4.00,     # Activate trailing once +4.0 pts in profit
                "pip_multiplier": 1.0
            }
        elif "JPY" in sym:
            return {
                "lot_size": float(os.getenv("FOREX_COPIER_LOT_SIZE", "0.07")),
                "max_sl_distance": 0.60,
                "max_slippage": 0.15,
                "be_buffer": 0.02,
                "trailing_distance": 0.30,       # 30 pips
                "trailing_activation": 0.40,     # Activate trailing once +40 pips in profit
                "pip_multiplier": 100.0
            }
        else:
            return {
                "lot_size": float(os.getenv("FOREX_COPIER_LOT_SIZE", "0.07")),
                "max_sl_distance": 0.0050,  # 50 pips
                "max_slippage": 0.0012,     # 12 pips
                "be_buffer": 0.0002,        # 2 pips
                "trailing_distance": 0.0030,     # 30 pips
                "trailing_activation": 0.0040,   # Activate trailing once +40 pips in profit
                "pip_multiplier": 10000.0
            }

    def execute_signal(self, sig: Dict[str, Any], spot_price: float) -> Optional[List[dict]]:
        symbol = sig["symbol"]
        side = sig["side"]
        channel = sig["channel"]
        params = self.get_asset_parameters(symbol)

        raw_sl = sig["sl"]
        entry = spot_price  # Fill at live market spot
        max_dist = params["max_sl_distance"]

        # Clamp Stop Loss to safety maximum
        if side == "BUY":
            safe_sl = max(raw_sl, entry - max_dist)
            if safe_sl >= entry:
                logger.warning(f"Invalid BUY for {symbol}: SL {safe_sl} >= Entry {entry}")
                return None
        else:
            safe_sl = min(raw_sl, entry + max_dist)
            if safe_sl <= entry:
                logger.warning(f"Invalid SELL for {symbol}: SL {safe_sl} <= Entry {entry}")
                return None

        tps = sig["tps"]
        if not tps:
            # Fallback 1.5:1 R:R target
            dist = abs(entry - safe_sl)
            tps = [round(entry + (dist * 1.5) if side == "BUY" else entry - (dist * 1.5), 5)]

        lot_size = params["lot_size"]  # 0.07 lots per ticket
        executed_orders = []

        # 2-Ticket Split Architecture ("Banker + Trailing Runner"):
        # Ticket 1 (0.07 lots) targets TP1 to bank immediate profit into balance.
        # Ticket 2 (0.07 lots) targets the deepest target (tps[-1]) to capture massive swing runs with trailing protection.
        has_multi_targets = len(tps) > 1
        t1_vol = lot_size
        t2_vol = lot_size if has_multi_targets else 0.0

        tickets_plan = [{"ticket": 1, "vol": max(0.01, t1_vol), "tp": tps[0]}]
        if has_multi_targets and t2_vol >= 0.01:
            tickets_plan.append({"ticket": 2, "vol": t2_vol, "tp": tps[-1]})

        total_vol = round(sum(t["vol"] for t in tickets_plan), 2)
        logger.info(f"🚀 Executing {side} {symbol} ({len(tickets_plan)} tickets • {total_vol} total lots) | Entry ~{entry} | SL: {safe_sl} | TP1: {tps[0]} | Runner TP: {tps[-1]} | Channel: {channel}")

        for t_plan in tickets_plan:
            t_num = t_plan["ticket"]
            t_vol = t_plan["vol"]
            t_tp = t_plan["tp"]

            if self.dry_run:
                simulated_pos = {
                    "positionId": int(time.time()) + t_num,
                    "ticket": t_num,
                    "symbol": symbol,
                    "side": side,
                    "volume": t_vol,
                    "entry": entry,
                    "sl": safe_sl,
                    "tp": t_tp,
                    "channel": channel,
                    "be_locked": False,
                    "time": datetime.now(timezone.utc).isoformat()
                }
                executed_orders.append(simulated_pos)
            else:
                try:
                    comment = f"Sig_{channel[:6]}_{symbol}_T{t_num}"
                    order_res = self.ctrader.place_market_order(
                        symbol=symbol,
                        side=side,
                        volume_lots=t_vol,
                        stop_loss_price=safe_sl,
                        take_profit_price=t_tp,
                        comment=comment,
                        bypass_concurrency_check=(t_num > 1)  # Allow twin ticket from same signal
                    )
                    if order_res and "result" in order_res:
                        pos_id = order_res.get("result", {}).get("positionId")
                        executed_orders.append({
                            "positionId": pos_id,
                            "ticket": t_num,
                            "symbol": symbol,
                            "side": side,
                            "volume": t_vol,
                            "entry": entry,
                            "sl": safe_sl,
                            "tp": t_tp,
                            "channel": channel,
                            "be_locked": False,
                            "time": datetime.now(timezone.utc).isoformat()
                        })
                except RiskViolationError as rve:
                    logger.warning(f"🛡️ Risk Choke Point blocked order Ticket #{t_num}: {rve}")
                    break
                except Exception as e:
                    logger.error(f"Failed to place live order on cTrader (Ticket #{t_num}): {e}")
                    break

        if executed_orders:
            self.state.setdefault("active_positions", []).extend(executed_orders)
            sig_key = f"{symbol}_{side}_{round(sig['entry_mid'], 2)}_{channel}"
            self.state.setdefault("executed_signal_keys", []).append(sig_key)
            self.save_state()

            # Telegram broadcast to David (LIVE ONLY - never broadcast simulated dry-run orders)
            if not self.dry_run:
                tps_str = f"TP1: {tps[0]}" + (f" | Runner TP: {tps[-1]} ({len(tps)} targets)" if len(tps) > 1 else "")
                alert_msg = (
                    f"⚡ <b>NEW SIGNAL EXECUTED</b>\n"
                    f"📡 <b>Source:</b> {channel}\n"
                    f"📈 <b>Action:</b> {side} {symbol}\n"
                    f"📍 <b>Fill Price:</b> {entry}\n"
                    f"🛡️ <b>Stop Loss:</b> {safe_sl}\n"
                    f"🎯 <b>Targets:</b> {tps_str}\n"
                    f"📦 <b>Tickets:</b> {len(executed_orders)} tickets ({total_vol} lots total)"
                )
                self.send_telegram_alert(alert_msg)
            else:
                logger.info(f"🧪 [SIMULATION] Dry-run signal executed for {symbol} {side} ({total_vol} lots) - skipping live Telegram broadcast.")

        return executed_orders

    def check_conflicts(self, symbol: str, side: str) -> bool:
        """Returns True if there is an opposing active position on the same symbol."""
        active = self.state.get("active_positions", [])
        for pos in active:
            if pos.get("symbol") == symbol and pos.get("side") != side:
                logger.warning(f"⚠️ CONFLICT DETECTED: Opposing position #{pos.get('positionId')} ({pos.get('side')} {symbol}) is already active. Skipping {side}.")
                return True
        return False

    def check_market_hours(self) -> bool:
        """Weekend check: Forex and Gold markets are closed from Friday 22:00 UTC to Sunday 22:00 UTC."""
        now_utc = datetime.now(timezone.utc)
        weekday = now_utc.weekday()
        hour = now_utc.hour
        if weekday == 5 or (weekday == 4 and hour >= 22) or (weekday == 6 and hour < 22):
            return False
        return True

    def manage_active_breakeven(self):
        """Monitors active positions, triggers Breakeven locks, and enforces 48-Hour swing timeouts."""
        active = self.state.get("active_positions", [])
        if not active or self.dry_run:
            return

        try:
            live_positions = self.ctrader.get_positions() or []
            live_pos_ids = {p.get("positionId") for p in live_positions}
            now_utc = datetime.now(timezone.utc)

            # 1. 48-Hour Swing Timeout (Time-Decay Exit)
            for pos in list(active):
                pos_id = pos.get("positionId")
                if not pos_id or pos_id not in live_pos_ids:
                    continue
                pos_time_str = pos.get("time")
                if pos_time_str:
                    try:
                        pos_dt = datetime.fromisoformat(pos_time_str)
                        age_hours = (now_utc - pos_dt).total_seconds() / 3600.0
                        if age_hours >= 48.0:
                            logger.info(f"⏳ [SWING TIMEOUT] Position #{pos_id} ({pos.get('symbol')}) open for {age_hours:.1f}h (>= 48h). Closing at market.")
                            self.ctrader.close_position(pos_id)
                            self.send_telegram_alert(
                                f"⏳ <b>48-Hour Swing Timeout Exit</b>\n"
                                f"Position #{pos_id} ({pos.get('symbol')}) closed after {age_hours:.1f}h to liberate margin and avoid swap decay."
                            )
                            active.remove(pos)
                            continue
                    except Exception as te:
                        logger.debug(f"Could not calculate age for #{pos_id}: {te}")

            # 2. Check if Ticket 1 has hit TP1 to advance Ticket 2 to Breakeven
            t1_items = [p for p in active if p.get("ticket") == 1]
            remaining_tickets = [p for p in active if p.get("ticket") == 2]

            for t1 in t1_items:
                t1_id = t1.get("positionId")
                if t1_id and t1_id not in live_pos_ids:
                    # Ticket 1 closed! Move companion Ticket 2 to Breakeven
                    entry_p = t1.get("entry")
                    side = t1.get("side", "BUY")
                    sym = t1.get("symbol")
                    params = self.get_asset_parameters(sym)
                    be_price = round(entry_p + params["be_buffer"] if side == "BUY" else entry_p - params["be_buffer"], 5)

                    for rem in remaining_tickets:
                        rem_id = rem.get("positionId")
                        if rem_id and rem_id in live_pos_ids and not rem.get("be_locked") and rem.get("symbol") == sym:
                            try:
                                self.ctrader.amend_position(rem_id, stop_loss=be_price)
                                rem["be_locked"] = True
                                rem["sl"] = be_price
                                logger.info(f"🛡️ Ticket #1 filled! Ticket #2 (#{rem_id}) SL moved to Breakeven {be_price}")
                                self.send_telegram_alert(
                                    f"🎯 <b>Target 1 Banked!</b>\n"
                                    f"Symbol: {sym} | Ticket #2 (#{rem_id})\n"
                                    f"SL moved to Breakeven @ <code>{be_price}</code> (Free-Ride Mode activated!)"
                                )
                            except Exception as ae:
                                logger.error(f"Failed to amend Ticket #{rem_id} to Breakeven: {ae}")

            # 3. Dynamic Breakeven for individual running tickets past 50% TP distance
            for pos in active:
                pos_id = pos.get("positionId")
                if not pos_id or pos_id not in live_pos_ids or pos.get("be_locked"):
                    continue

                symbol = pos.get("symbol")
                side = pos.get("side")
                entry = pos.get("entry")
                params = self.get_asset_parameters(symbol)
                spot = self.ctrader.get_spot_price(symbol)

                if not spot:
                    continue

                curr_price = float(spot["bid"] if side == "BUY" else spot["ask"])
                gain = (curr_price - entry) if side == "BUY" else (entry - curr_price)
                half_tp_distance = abs(pos.get("tp", entry) - entry) * 0.50

                if gain >= half_tp_distance:
                    be_price = round(entry + params["be_buffer"] if side == "BUY" else entry - params["be_buffer"], 5)
                    try:
                        self.ctrader.amend_position(pos_id, stop_loss=be_price)
                        pos["be_locked"] = True
                        pos["sl"] = be_price
                        logger.info(f"🛡️ Position #{pos_id} ({symbol}) moved to Breakeven @ {be_price}")
                        self.send_telegram_alert(
                            f"🛡️ <b>Breakeven Locked!</b>\n"
                            f"Symbol: {symbol} | Position #{pos_id}\n"
                            f"SL moved to entry buffer: <code>{be_price}</code>"
                        )
                    except Exception as ae:
                        logger.error(f"Failed to amend #{pos_id} to Breakeven: {ae}")

            # 4. Dynamic Ratcheting Trailing Stop for Ticket 2 Runners
            for pos in active:
                pos_id = pos.get("positionId")
                if not pos_id or pos_id not in live_pos_ids:
                    continue

                # Trailing stop actively protects Ticket 2 runners or any position with BE already secured
                if pos.get("ticket") != 2 and not pos.get("be_locked"):
                    continue

                symbol = pos.get("symbol")
                side = pos.get("side")
                entry = pos.get("entry")
                current_sl = pos.get("sl", entry)
                params = self.get_asset_parameters(symbol)
                spot = self.ctrader.get_spot_price(symbol)

                if not spot:
                    continue

                curr_price = float(spot["bid"] if side == "BUY" else spot["ask"])
                gain = (curr_price - entry) if side == "BUY" else (entry - curr_price)
                trail_act = params.get("trailing_activation", 0.0040)
                trail_dist = params.get("trailing_distance", 0.0030)

                if gain >= trail_act:
                    if side == "BUY":
                        new_sl = round(curr_price - trail_dist, 5)
                        # Ratchet constraint: only ratchet SL upwards
                        if new_sl > current_sl + (params["be_buffer"] * 0.5):
                            try:
                                self.ctrader.amend_position(pos_id, stop_loss=new_sl)
                                pos["sl"] = new_sl
                                pos["be_locked"] = True
                                logger.info(f"🏃 [TRAILING STOP] Ticket #2 (#{pos_id} {symbol}) SL trailed up to {new_sl} (gain: +{gain:.4f})")
                                self.send_telegram_alert(
                                    f"🏃 <b>Trailing Stop Advanced</b>\n"
                                    f"Symbol: {symbol} | Ticket #{pos.get('ticket')} (#{pos_id})\n"
                                    f"Floating Gain: +{gain:.4f}\n"
                                    f"New Protected SL: <code>{new_sl}</code>"
                                )
                            except Exception as ae:
                                logger.error(f"Failed to trail SL for #{pos_id}: {ae}")
                    else:  # SELL
                        new_sl = round(curr_price + trail_dist, 5)
                        # Ratchet constraint: only ratchet SL downwards
                        if new_sl < current_sl - (params["be_buffer"] * 0.5):
                            try:
                                self.ctrader.amend_position(pos_id, stop_loss=new_sl)
                                pos["sl"] = new_sl
                                pos["be_locked"] = True
                                logger.info(f"🏃 [TRAILING STOP] Ticket #2 (#{pos_id} {symbol}) SL trailed down to {new_sl} (gain: +{gain:.4f})")
                                self.send_telegram_alert(
                                    f"🏃 <b>Trailing Stop Advanced</b>\n"
                                    f"Symbol: {symbol} | Ticket #{pos.get('ticket')} (#{pos_id})\n"
                                    f"Floating Gain: +{gain:.4f}\n"
                                    f"New Protected SL: <code>{new_sl}</code>"
                                )
                            except Exception as ae:
                                logger.error(f"Failed to trail SL for #{pos_id}: {ae}")

            # Keep only open positions in state
            self.state["active_positions"] = [p for p in active if p.get("positionId") in live_pos_ids]
            self.save_state()
        except Exception as e:
            logger.error(f"Error in Breakeven manager: {e}")

    def poll_cycle(self):
        """Executes a single polling and evaluation cycle across all configured channels."""
        if not self.check_market_hours():
            logger.info("⏸️ [WEEKEND FILTER] Markets are closed. Copier sleeping.")
            return

        # Check account equity circuit breaker
        try:
            bal = self.ctrader.get_balance()
            if bal and bal.get("equity", 6000.0) <= 5650.0:
                logger.warning(f"🛑 [DRAWDOWN CIRCUIT BREAKER] Equity ${bal.get('equity')} <= $5650. Trading locked.")
                return
        except Exception as e:
            logger.warning(f"Could not verify equity: {e}")

        watermarks = self.state.setdefault("watermarks", {})

        for ch in CHANNELS_CONFIG:
            if not ch.get("enabled"):
                continue

            ch_id = ch["id"]
            posts = self.fetch_channel_posts(ch_id)
            if not posts:
                continue

            last_id = watermarks.get(ch_id)
            new_posts = []

            if not last_id:
                # First time running, set watermark to latest post
                watermarks[ch_id] = posts[-1]["post_id"]
                self.save_state()
                continue

            found_last = False
            for p in posts:
                if found_last:
                    new_posts.append(p)
                elif p["post_id"] == last_id:
                    found_last = True

            # If watermark was scrolled past, take the latest 3 posts
            if not found_last and posts:
                new_posts = posts[-3:]

            for p in new_posts:
                pid = p["post_id"]
                watermarks[ch_id] = pid
                self.save_state()

                sig = MultiChannelSignalParser.parse_message(p["text"], ch_id)
                if not sig:
                    continue

                symbol = sig["symbol"]
                side = sig["side"]
                sig_key = f"{symbol}_{side}_{round(sig['entry_mid'], 2)}_{ch_id}"

                if sig_key in self.state.get("executed_signal_keys", []):
                    logger.debug(f"Skipping already executed signal {sig_key}")
                    continue

                if self.check_conflicts(symbol, side):
                    continue

                # Verify live spot price and anti-chase
                spot = self.ctrader.get_spot_price(symbol)
                if not spot:
                    logger.warning(f"Could not fetch spot price for {symbol}. Skipping.")
                    continue

                curr_spot = float(spot["ask"] if side == "BUY" else spot["bid"])
                params = self.get_asset_parameters(symbol)

                # Check if price is within acceptable distance from entry range
                e_min = sig["entry_min"]
                e_max = sig["entry_max"]
                dist_from_zone = 0.0
                if curr_spot < e_min:
                    dist_from_zone = e_min - curr_spot
                elif curr_spot > e_max:
                    dist_from_zone = curr_spot - e_max

                if dist_from_zone > params["max_slippage"]:
                    logger.info(f"⏭️ Anti-Chase Filter: {symbol} spot {curr_spot} is {dist_from_zone} from entry zone (max {params['max_slippage']}). Skipping.")
                    continue

                # Execute order
                self.execute_signal(sig, curr_spot)

        # Manage active trades (Breakeven locks)
        self.manage_active_breakeven()


def start_multi_copier_daemon(interval_sec: int = 15, dry_run: bool = False):
    """Entrypoint for running multi-channel copier daemon inside a background thread."""
    copier = TelegramMultiSignalCopier(dry_run=dry_run)
    logger.info(f"Multi-Channel Signal Copier daemon thread active ({interval_sec}s poll).")
    while True:
        try:
            copier.poll_cycle()
        except Exception as e:
            logger.error(f"Error in multi-channel copier poll cycle: {e}")
        time.sleep(interval_sec)


def run_continuous():
    start_multi_copier_daemon(interval_sec=15, dry_run=False)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Multi-Channel Telegram Signal Copier")
    parser.add_argument("--dry-run", action="store_true", help="Run without sending live broker orders")
    parser.add_argument("--once", action="store_true", help="Run a single poll cycle and exit")
    args = parser.parse_args()

    copier = TelegramMultiSignalCopier(dry_run=args.dry_run)
    if args.once:
        logger.info("Executing single poll cycle test...")
        copier.poll_cycle()
        logger.info("Single poll cycle test completed.")
    else:
        run_continuous()
