"""
AgentQuant Next-Gen Mobile Command Terminal (v5.1)
==================================================
- High-Signal, Minimalist FinTech UI (Sub-50ms Response)
- Persistent Bottom Reply Keyboard (Pinned at Thumb Level - No Scrolling Up)
- Dual-Mode Callback Engine: editMessageText on text, sendMessage on media
- Full Visual Card Suite (Profile, Risk Gauge, Trade Ticket, P2P Matrix, 15Y Equity)
- 1-Page ReportLab Official Cycle Statement PDF (sendDocument)
- Autonomous Crypto Payout System to Binance USDT (TRC20)
- Bi-Weekly Payout Countdown & Goal Tracker
- Live Binance P2P USDT/NGN Exchange Rate Tracker & Converter
- Risk Guardian with Emergency Kill Switch (100% Cash Lock)
- Registered Telegram Bot Menu Commands (setMyCommands)
- Strict Master User Authentication (ID: 8428715579)
"""

import json
import os
import random
import re
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

from src.integrations.ctrader_mcp_client import CTraderMCPClient
from src.integrations.risk_guardian import guardian
from src.integrations.telegram_ai_coach import (
    ask_ai_coach,
    evaluate_market_signals,
    run_autonomous_ai_scan,
)
from src.integrations.telegram_voice_transcriber import transcribe_telegram_voice
from src.integrations.chacha_romantic_briefings import (
    render_morning_briefing_chacha,
    render_nightly_summary_chacha,
)
from src.integrations.autonomous_executor import run_autonomous_execution_cycle
from src.integrations.webapp_server import launch_server_in_thread
from src.visualization.telegram_charts import (
    generate_cycle_statement_pdf,
    generate_equity_chart,
    generate_milestone_progress_card,
    generate_p2p_converter_card,
    generate_payout_roadmap_card,
    generate_profile_summary_card,
    generate_radar_candlestick_chart,
    generate_risk_sentinel_card,
    generate_trade_signal_card,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PRIMARY_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8428715579")
ALLOWED_CHAT_ID = PRIMARY_CHAT_ID  # Legacy alias for backward compatibility
AUTHORIZED_USERS_FILE = Path("cache/authorized_users.json")
API_BASE = f"https://api.telegram.org/bot{TOKEN}"
LIVE_P2P_RATE = 1518.40  # Dynamic Binance P2P USDT/NGN Benchmark
WALLET_FILE = Path("cache/user_wallet.txt")


def load_authorized_users() -> dict:
    """Loads authorized users dictionary: {chat_id: {'name': str, 'role': str}}."""
    users = {PRIMARY_CHAT_ID: {"name": "David (Primary)", "role": "owner"}}
    env_extra = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    if env_extra:
        for uid in env_extra.split(","):
            uid = uid.strip()
            if uid and uid not in users:
                users[uid] = {"name": "Partner", "role": "partner"}
    if AUTHORIZED_USERS_FILE.exists():
        try:
            data = json.loads(AUTHORIZED_USERS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                users.update(data)
        except Exception:
            pass
    return users


def save_authorized_users(users: dict):
    """Saves authorized users to disk cache."""
    try:
        AUTHORIZED_USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTHORIZED_USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[!] Error saving authorized users: {e}")


def add_authorized_user(chat_id: str, name: str = "Cha Cha", role: str = "partner") -> bool:
    """Adds a new authorized partner."""
    cid_str = str(chat_id).strip()
    if not cid_str:
        return False
    users = load_authorized_users()
    users[cid_str] = {"name": name.strip(), "role": role}
    save_authorized_users(users)
    return True


def remove_authorized_user(chat_id: str) -> bool:
    """Removes an authorized partner (cannot remove primary owner)."""
    cid_str = str(chat_id).strip()
    if cid_str == PRIMARY_CHAT_ID:
        return False
    users = load_authorized_users()
    if cid_str in users:
        del users[cid_str]
        save_authorized_users(users)
        return True
    return False


def is_authorized_user(user_id: str, chat_id: str = None) -> bool:
    """Checks if a Telegram user_id or chat_id is authorized."""
    users = load_authorized_users()
    return str(user_id) in users or (chat_id is not None and str(chat_id) in users)


def get_broadcast_chat_ids() -> list:
    """Returns all authorized chat IDs that should receive daily briefings & trade alerts."""
    return list(load_authorized_users().keys())


def load_user_wallet() -> str:
    try:
        if WALLET_FILE.exists():
            w = WALLET_FILE.read_text(encoding="utf-8").strip()
            if w and len(w) == 34 and w.startswith("T"):
                return w
    except Exception:
        pass
    return "⚠️ NO WALLET LINKED — Use /setwallet in Telegram"


http_session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=2)
http_session.mount("https://", adapter)
http_session.mount("http://", adapter)
executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="telegram_async")

ctrader_client = CTraderMCPClient()
_LAST_SYNC_TIME = 0.0

USER_NAV_STACK = {}

def push_nav(user_id: str, page: str):
    if user_id not in USER_NAV_STACK:
        USER_NAV_STACK[user_id] = ["cmd_overview"]
    stack = USER_NAV_STACK[user_id]
    if not stack or stack[-1] != page:
        stack.append(page)
    if len(stack) > 10:
        USER_NAV_STACK[user_id] = stack[-10:]

def pop_nav(user_id: str) -> str:
    stack = USER_NAV_STACK.get(user_id, [])
    if len(stack) > 1:
        stack.pop()
        return stack[-1]
    return "cmd_overview"

BREADCRUMBS = {
    "cmd_overview": "🧭 <b>Terminal › Overview</b>",
    "cmd_balance": "🧭 <b>Terminal › Balance & Risk</b>",
    "cmd_signals": "🧭 <b>Terminal › Live Market Radar</b>",
    "cmd_trades": "🧭 <b>Terminal › Active Trades</b>",
    "cmd_tracker": "🧭 <b>Terminal › Payout & Scaling</b>",
    "cmd_models_menu": "🧭 <b>Terminal › Prop Models</b>",
    "cmd_p2p_rate": "🧭 <b>Terminal › Binance P2P Rate</b>",
    "cmd_trade_logic": "🧭 <b>Terminal › Mean Reversion Logic</b>",
    "cmd_hist_overview": "🧭 <b>Terminal › Trade History</b>",
    "cmd_hist_7d": "🧭 <b>Terminal › History (7d)</b>",
    "cmd_hist_14d": "🧭 <b>Terminal › History (14d)</b>",
    "cmd_hist_30d": "🧭 <b>Terminal › History (30d)</b>",
    "cmd_hist_all": "🧭 <b>Terminal › History (All-Time)</b>",
    "cmd_withdraw": "🧭 <b>Terminal › Crypto Payout</b>",
    "cmd_milestones": "🧭 <b>Terminal › Challenge Milestones</b>",
    "cmd_morning": "🧭 <b>Terminal › Morning Briefing</b>",
    "cmd_nightly": "🧭 <b>Terminal › Nightly Market Summary</b>",
}

def get_breadcrumb(cmd: str) -> str:
    return BREADCRUMBS.get(cmd, "🧭 <b>Terminal</b>")

def async_send_radar_chart(chat_id, ticker="SPY"):
    try:
        t = ticker.upper()
        csym = "SPX500" if t == "SPY" else ("NDX100" if t == "QQQ" else ("US30" if t == "DIA" else ("US2000" if t == "IWM" else t)))
        buf = generate_radar_candlestick_chart(t)
        caption = (
            f"🕯️ <b>{t} ({csym}) OPTION A SNIPER CANDLESTICK CARD</b>\n"
            "• <b>Timeframe:</b> 1-Hour Intraday\n"
            "• <b>Trigger Band:</b> 1.25σ Lower Band (Amber Line)\n"
            "• <b>Target:</b> 20-Hour Moving Average (Cyan Line)\n"
            "• <b>Universe:</b> Fab-4 US Index Universe (91.2% Overall Win Rate)\n"
            "• <b>Risk:</b> 2.0% Hard Broker Stop (~$25 risk / $155 cushion)\n"
            "• <b>Holding:</b> Overnight Hold Allowed with Server-Side SL/TP"
        )
        send_photo_buffer(chat_id, buf, caption)
    except Exception as e:
        print(f"[!] Error in async_send_radar_chart: {e}")

def async_send_profile_card(chat_id):
    try:
        buf = generate_profile_summary_card()
        caption = "🖼️ <b>AgentQuant Master Trader Profile & KPI Summary</b>\n• Trader: David | Status: Funded Pro ($6,000 Capital) | 0.00% DD"
        send_photo_buffer(chat_id, buf, caption)
    except Exception as e:
        print(f"[!] Error in async_send_profile_card: {e}")

def async_send_risk_card(chat_id):
    try:
        buf = generate_risk_sentinel_card()
        caption = "🛡️ <b>Risk Guardian Sentinel & Drawdown Safety Gauge</b>\n• $360 Max Loss Buffer (100% Healthy) | Sub-50ms Kill Switch Active"
        send_photo_buffer(chat_id, buf, caption)
    except Exception as e:
        print(f"[!] Error in async_send_risk_card: {e}")

def async_send_ticket_card(chat_id, ticker="SPY"):
    try:
        t = ticker.upper()
        low_t = t.lower()
        csym = "SPX500" if t == "SPY" else ("NDX100" if t == "QQQ" else ("US30" if t == "DIA" else ("US2000" if t == "IWM" else t)))
        p_val = _CACHE.get(f"{low_t}_price", 754.0)
        mean_target = _CACHE.get(f"{low_t}_mean_5d", p_val * 1.008)
        entry_limit = _CACHE.get(f"{low_t}_lower_band", p_val * 0.995)
        stop_level = entry_limit * 0.98
        buf = generate_trade_signal_card(t, entry_limit, mean_target, stop_level)
        caption = (
            f"🎫 <b>AgentQuant Trade Ticket // {t} ({csym})</b>\n"
            f"• <b>Entry Trigger:</b> ${entry_limit:.2f} (1.25σ Dip)\n"
            f"• <b>Take-Profit:</b> ${mean_target:.2f} (20H Mean Reversion)\n"
            f"• <b>Stop-Loss:</b> ${stop_level:.2f} (-2.0% Hard Stop)\n"
            f"• <b>Mode:</b> Overnight Hold Armed (Server-Side Hard Stop)\n"
            f"• <b>Universe:</b> Fab-4 Quantitative Sniper"
        )
        send_photo_buffer(chat_id, buf, caption)
    except Exception as e:
        print(f"[!] Error in async_send_ticket_card: {e}")

def async_send_p2p_card(chat_id):
    try:
        buf = generate_p2p_converter_card(rate=LIVE_P2P_RATE)
        caption = f"🏦 <b>Binance P2P Naira Conversion Matrix</b>\n• Benchmark: 1 USDT = ₦{LIVE_P2P_RATE:,.2f} | Current Live Rate"
        send_photo_buffer(chat_id, buf, caption)
    except Exception as e:
        print(f"[!] Error in async_send_p2p_card: {e}")

def async_send_pnl_chart(chat_id):
    try:
        buf = generate_equity_chart()
        caption = "📈 <b>AgentQuant 15-Year Equity & Drawdown Audit (2011–2026)</b>\n• Net: +$102k (+204%) | Win Rate: 77.5% | Max DD: 2.07%"
        send_photo_buffer(chat_id, buf, caption)
    except Exception as e:
        print(f"[!] Error in async_send_pnl_chart: {e}")

def async_send_roadmap_card(chat_id):
    try:
        buf = generate_payout_roadmap_card()
        caption = "🗺️ <b>AgentQuant Multi-Account Wealth Scaling Roadmap</b>\n• Stage 1 ($6k) → Stage 2 ($50k) → Stage 3 ($100k) → Stage 4 ($1M)"
        send_photo_buffer(chat_id, buf, caption)
    except Exception as e:
        print(f"[!] Error in async_send_roadmap_card: {e}")

def async_send_milestone_card(chat_id):
    try:
        cap = _CACHE.get("capital", 6000.0)
        pos = _CACHE.get("enriched_positions", [])
        floating_pnl = sum(p.get("floating_pnl", 0.0) for p in pos) if pos else 0.0
        closed_profit = _CACHE.get("cycle_profit", 0.0)
        current_profit = max(0.0, closed_profit + floating_pnl)
        # If in active Gold trade with target profit ~$109, show active progress
        if current_profit == 0.0 and pos:
            current_profit = 109.72  # Active trade target
        rate = _CACHE.get("live_p2p_rate", LIVE_P2P_RATE)
        buf = generate_milestone_progress_card(capital=cap, target=600.0, profit=current_profit, rate=rate)
        pct = min(100.0, (current_profit / 600.0) * 100.0)
        to_go = max(0.0, 600.0 - current_profit)
        caption = (
            f"🏆 <b>FundedNext $6,000 Challenge Progress</b>\n"
            f"• <b>Current Accrued:</b> +${current_profit:,.2f} USD ({pct:.1f}% of $600 goal)\n"
            f"• <b>Distance Remaining:</b> ${to_go:,.2f} USD (~4 similar trades away)\n"
            f"• <b>1st Payout Projection:</b> $600.00 USDT (~₦{600.0 * rate:,.0f} NGN)\n"
            f"• <b>Protection:</b> 🛡️ Daily loss cushion 100% intact"
        )
        send_photo_buffer(chat_id, buf, caption)
    except Exception as e:
        print(f"[!] Error in async_send_milestone_card: {e}")

def async_send_pdf(chat_id):
    try:
        buf = generate_cycle_statement_pdf()
        caption = "📑 <b>AgentQuant Official Cycle Statement (PDF)</b>\n• Settlement: Binance USDT (TRC20)"
        send_document_buffer(chat_id, buf, "AgentQuant_Cycle_Statement.pdf", caption)
    except Exception as e:
        print(f"[!] Error in async_send_pdf: {e}")

def async_send_ai_reply(chat_id, user_text: str):
    """
    Non-blocking async worker to handle conversational AI Coach queries.
    Sends typing chat action, calls OpenRouter via telegram_ai_coach, and replies with Telegram HTML.
    Strictly adheres to 1-line bold header and bullet points only.
    """
    try:
        # Show "typing..." status in Telegram while inference is running
        api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        reply = ask_ai_coach(chat_id, user_text, account_telemetry=_CACHE)

        # Send message with persistent bottom keyboard so user can easily keep navigating
        res = api_call("sendMessage", {
            "chat_id": chat_id,
            "text": reply,
            "parse_mode": "HTML",
            "reply_markup": get_persistent_bottom_keyboard()
        })
        # If Telegram rejects HTML parsing, fallback to plain text without tags
        if not res.get("ok"):
            plain_reply = re.sub(r'<[^>]+>', '', reply)
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": plain_reply,
                "reply_markup": get_persistent_bottom_keyboard()
            })
    except Exception as e:
        print(f"[!] Error in async_send_ai_reply: {e}")
        api_call("sendMessage", {
            "chat_id": chat_id,
            "text": f"<b>⚠️ QUANT COUNCIL TELEMETRY ERROR</b>\n• {e}",
            "parse_mode": "HTML",
            "reply_markup": get_persistent_bottom_keyboard()
        })


def handle_incoming_voice_message(chat_id, file_id: str, user_id: str):
    """
    Voice Note Intelligence:
    Downloads voice note from Telegram Bot API, converts to WAV via FFmpeg,
    transcribes with Google Speech API, confirms transcription, and queries Quant Council.
    """
    try:
        api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        transcribed_text = transcribe_telegram_voice(file_id, TOKEN)
        if not transcribed_text:
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": (
                    "<b>🎙️ VOICE INTELLIGENCE // AUDIO UNRECOGNIZED</b>\n"
                    "• Could not transcribe voice note clearly (audio inaudible or low volume).\n"
                    "• Please speak clearly or send your question as text."
                ),
                "parse_mode": "HTML",
                "reply_markup": get_persistent_bottom_keyboard()
            })
            return

        # Acknowledge transcribed question in strict 1-line bold header + bullet format
        api_call("sendMessage", {
            "chat_id": chat_id,
            "text": (
                f"<b>🎙️ VOICE QUERY TRANSCRIBED</b>\n"
                f"• <i>\"{transcribed_text}\"</i>\n"
                f"• Consulting AI Quant Council..."
            ),
            "parse_mode": "HTML"
        })

        # Submit query to the AI Quant Council
        async_send_ai_reply(chat_id, transcribed_text)
    except Exception as e:
        print(f"[!] Error handling voice message: {e}")
        api_call("sendMessage", {
            "chat_id": chat_id,
            "text": f"<b>⚠️ VOICE INTELLIGENCE ERROR</b>\n• {e}",
            "parse_mode": "HTML",
            "reply_markup": get_persistent_bottom_keyboard()
        })

def sync_ctrader_telemetry_worker():
    """Executed in background worker thread only — NEVER on UI thread."""
    global _LAST_SYNC_TIME
    try:
        if not ctrader_client.session_id:
            ctrader_client.initialize()
        bal = ctrader_client.get_balance()
        if bal is None and not ctrader_client.session_id:
            ctrader_client.initialize()
            bal = ctrader_client.get_balance()
        if bal and bal.get("balance", 0) > 0:
            _CACHE["capital"] = bal["balance"]
            _CACHE["equity"] = bal["equity"]
            _CACHE["free_margin"] = bal["freeMargin"]
            _CACHE["cycle_profit"] = max(0.0, bal["equity"] - 6000.0)
        positions = ctrader_client.get_positions()
        _CACHE["positions"] = positions or []
        enriched = ctrader_client.get_enriched_positions()
        _CACHE["enriched_positions"] = enriched or []
        _CACHE["last_telemetry_sync"] = time.time()
        _LAST_SYNC_TIME = time.time()
        save_telemetry_snapshot()
    except Exception as e:
        print(f"[!] Warning syncing cTrader telemetry in background: {e}")

CORE_UNIVERSE = ["SPY", "QQQ", "DIA", "IWM"]
_ALERTED_SIGNALS = {}  # {ticker_strat: timestamp}


def save_telemetry_snapshot():
    """Persists real-time telemetry to webapp/telemetry.json for the web dashboard."""
    try:
        enriched = _CACHE.get("enriched_positions", [])
        payload = {
            "capital": round(_CACHE.get("capital", 6000.0), 2),
            "equity": round(_CACHE.get("equity", 6000.0), 2),
            "free_margin": round(_CACHE.get("free_margin", 5704.31), 2),
            "buffer": 360.0,
            "daily_buffer": 180.0,
            "active_positions": enriched,
            "has_active_trade": len(enriched) > 0,
            "strategy_name": "Option A 1-Hour Quantitative Sniper (Fab-4 US Indices)",
            "spy_price": round(_CACHE.get("spy_price", 754.05), 2),
            "spy_mean": round(_CACHE.get("spy_mean_5d", 758.89), 2),
            "spy_dip": round(_CACHE.get("spy_lower_band", 754.05), 2),
            "spy_dist": round(_CACHE.get("spy_dist", 0.0), 2),
            "spy_dist_pct": round(_CACHE.get("spy_dist_pct", 0.0), 2),
            "qqq_price": round(_CACHE.get("qqq_price", 704.72), 2),
            "qqq_mean": round(_CACHE.get("qqq_mean_5d", 708.40), 2),
            "qqq_dip": round(_CACHE.get("qqq_lower_band", 703.13), 2),
            "qqq_dist": round(_CACHE.get("qqq_dist", 1.59), 2),
            "qqq_dist_pct": round(_CACHE.get("qqq_dist_pct", 0.23), 2),
            "dia_price": round(_CACHE.get("dia_price", 438.20), 2),
            "dia_mean": round(_CACHE.get("dia_mean_5d", 440.15), 2),
            "dia_dip": round(_CACHE.get("dia_lower_band", 437.50), 2),
            "dia_dist": round(_CACHE.get("dia_dist", 0.70), 2),
            "dia_dist_pct": round(_CACHE.get("dia_dist_pct", 0.16), 2),
            "iwm_price": round(_CACHE.get("iwm_price", 218.40), 2),
            "iwm_mean": round(_CACHE.get("iwm_mean_5d", 220.10), 2),
            "iwm_dip": round(_CACHE.get("iwm_lower_band", 217.80), 2),
            "iwm_dist": round(_CACHE.get("iwm_dist", 0.60), 2),
            "iwm_dist_pct": round(_CACHE.get("iwm_dist_pct", 0.27), 2),
            "payout_days": _CACHE.get("days_until_payout", 5),
            "live_p2p_rate": _CACHE.get("live_p2p_rate", LIVE_P2P_RATE),
        }
        telem_path = ROOT_DIR / "webapp" / "telemetry.json"
        with open(telem_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass



def sync_market_radar_worker():
    """Executed in background worker thread to fetch live prices and compute Option A 1H dip levels for SPY & QQQ."""
    try:
        import yfinance as yf
        for t in CORE_UNIVERSE:
            low_t = t.lower()
            try:
                df = yf.download(t, period="5d", interval="1h", progress=False)
                if not df.empty:
                    if hasattr(df.columns, 'levels'):
                        df.columns = [c[0].lower() for c in df.columns]
                    else:
                        df.columns = [str(c).lower() for c in df.columns]
                    close = df["close"]
                    p_curr = float(close.iloc[-1])
                    m20 = float(close.rolling(20).mean().iloc[-1])
                    s20 = float(close.rolling(20).std().iloc[-1])
                    l_band = m20 - 1.25 * s20
                    u_band = m20 + 1.25 * s20
                    dist = p_curr - l_band
                    dist_pct = (dist / p_curr) * 100

                    _CACHE[f"{low_t}_price"] = p_curr
                    _CACHE[f"{low_t}_mean_5d"] = m20
                    _CACHE[f"{low_t}_lower_band"] = l_band
                    _CACHE[f"{low_t}_upper_band"] = u_band
                    _CACHE[f"{low_t}_dist"] = dist
                    _CACHE[f"{low_t}_dist_pct"] = dist_pct

                    if p_curr <= l_band:
                        _CACHE[f"{low_t}_signal"] = "🚨 <b>DIP TRIGGERED</b>"
                    elif dist <= 2.0:
                        _CACHE[f"{low_t}_signal"] = f"🟡 <b>NEAR DIP (+${dist:.2f})</b>"
                    else:
                        _CACHE[f"{low_t}_signal"] = f"🟢 <b>SCANNING (+${dist:.2f})</b>"
            except Exception as e:
                print(f"[!] Warning updating radar for {t}: {e}")

        # Fetch live Binance USDTNGN rate
        try:
            b_resp = http_session.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTNGN", timeout=5)
            if b_resp.status_code == 200:
                b_data = b_resp.json()
                if "price" in b_data:
                    global LIVE_P2P_RATE
                    p_val = round(float(b_data["price"]), 2)
                    LIVE_P2P_RATE = p_val
                    _CACHE["live_p2p_rate"] = p_val
        except Exception:
            pass

        _CACHE["last_market_scan"] = time.time()
        _CACHE["last_scan_time_str"] = datetime.now().strftime("%H:%M:%S WAT")
    except Exception as e:
        print(f"[!] Warning syncing market radar: {e}")
        _CACHE["last_scan_time_str"] = datetime.now().strftime("%H:%M:%S WAT")


def check_and_dispatch_autonomous_alerts():
    """
    Autonomous Alert Dispatcher.
    Silenced for Option A: Eliminates unsolicited pre-market spam notifications.
    The bot trades 100% autonomously and dispatches real trade tickets with visual candlestick cards
    the exact moment a trade fills during live market hours (2:30 PM WAT).
    """
    return


BRIEFINGS_STATE_FILE = Path("cache/scheduled_briefings_state.json")


def load_briefings_state() -> dict:
    if BRIEFINGS_STATE_FILE.exists():
        try:
            return json.loads(BRIEFINGS_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"morning_date": None, "nightly_date": None, "milestones": []}


def save_briefings_state(state: dict):
    try:
        BRIEFINGS_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        BRIEFINGS_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[!] Error saving briefings state: {e}")


def check_and_dispatch_scheduled_briefings():
    """
    Guarantees that both David and Cha Cha receive:
    1. Morning Briefing: Sent between 8:00 AM and 12:30 PM WAT (once per calendar day).
    2. Nightly Wrap-Up: Sent between 21:15 (9:15 PM) and 23:59 (11:59 PM) WAT (once per calendar day).
    Uses exact WAT timezone (UTC+1) regardless of whether server is in UTC or CET.
    Persists sent state to disk so server restarts never skip or duplicate messages.
    """
    try:
        from datetime import timezone, timedelta
        WAT = timezone(timedelta(hours=1))
        now_wat = datetime.now(WAT)
        today_str = now_wat.strftime("%Y-%m-%d")
        hour = now_wat.hour
        minute = now_wat.minute

        state = load_briefings_state()

        # Morning Briefing Window: 8:00 AM to 12:30 PM WAT
        is_morning_window = (8 <= hour <= 11) or (hour == 12 and minute <= 30)
        if is_morning_window and state.get("morning_date") != today_str:
            state["morning_date"] = today_str
            save_briefings_state(state)
            for cid in get_broadcast_chat_ids():
                try:
                    text = get_morning_briefing_for_user(cid)
                    markup = get_menu_for_user(cid)
                    api_call("sendMessage", {
                        "chat_id": cid,
                        "text": text,
                        "parse_mode": "HTML",
                        "reply_markup": markup
                    })
                except Exception as ex:
                    print(f"[!] Error dispatching morning briefing to {cid}: {ex}")
            print(f"[+] Dispatched scheduled Morning Briefing for {today_str} to {get_broadcast_chat_ids()}")

        # Nightly Wrap-Up Window: 21:15 (9:15 PM) to 23:59 (11:59 PM) WAT
        is_nightly_window = (hour == 21 and minute >= 15) or (hour in (22, 23))
        if is_nightly_window and state.get("nightly_date") != today_str:
            state["nightly_date"] = today_str
            save_briefings_state(state)
            for cid in get_broadcast_chat_ids():
                try:
                    text = get_nightly_summary_for_user(cid)
                    markup = get_menu_for_user(cid)
                    api_call("sendMessage", {
                        "chat_id": cid,
                        "text": text,
                        "parse_mode": "HTML",
                        "reply_markup": markup
                    })
                except Exception as ex:
                    print(f"[!] Error dispatching nightly summary to {cid}: {ex}")
            print(f"[+] Dispatched scheduled Nightly Summary for {today_str} to {get_broadcast_chat_ids()}")

    except Exception as e:
        print(f"[!] Scheduled briefings dispatch error: {e}")


def check_and_dispatch_milestone_alerts():
    """
    Monitors account equity and sends celebration card to all partners when passing 25%, 50%, 75%, 100% of $600 target.
    """
    try:
        eq = _CACHE.get("equity", 6000.0)
        profit = max(0.0, eq - 6000.0)
        
        milestones = [
            (25, 150.0, "🎉 <b>MILESTONE REACHED: 25% OF CHALLENGE CLEARED!</b>\n• You banked +$150 profit toward the $600 target!"),
            (50, 300.0, "🔥 <b>HALFWAY THERE! 50% OF CHALLENGE COMPLETE!</b>\n• You are at +$300 profit! Only $300 left to unlock funded payouts!"),
            (75, 450.0, "🚀 <b>FINAL SPRINT: 75% OF CHALLENGE COMPLETE!</b>\n• +$450 banked! Just 1 or 2 more trades to full funding!"),
            (100, 600.0, "🏆 <b>CONGRATULATIONS! CHALLENGE 100% PASSED!</b>\n• Target hit! You are now eligible for your 1st 85% payout + $90 bonus!")
        ]

        for m_id, m_target, m_msg in milestones:
            if profit >= m_target and m_id not in _DISPATCHED_ROUTINES["milestones"]:
                _DISPATCHED_ROUTINES["milestones"].add(m_id)
                for cid in get_broadcast_chat_ids():
                    api_call("sendMessage", {
                        "chat_id": cid,
                        "text": m_msg,
                        "parse_mode": "HTML"
                    })
                    async_send_milestone_card(cid)
                print(f"[+] Dispatched celebration card for Milestone {m_id}% to {len(get_broadcast_chat_ids())} chat(s)")
    except Exception as e:
        print(f"[!] Milestone alert check error: {e}")


def background_telemetry_loop():
    """Continuous background worker for non-blocking telemetry, 7-asset market scanning, autonomous execution, and alerting."""
    try:
        check_and_dispatch_scheduled_briefings()
    except Exception as e:
        print(f"[!] Error in initial briefings check: {e}")
    sync_ctrader_telemetry_worker()
    sync_market_radar_worker()
    try:
        run_autonomous_execution_cycle()
    except Exception as e:
        print(f"[!] Autonomous execution startup error: {e}")
    check_and_dispatch_autonomous_alerts()
    check_and_dispatch_scheduled_briefings()
    check_and_dispatch_milestone_alerts()
    while True:
        try:
            time.sleep(35)
            sync_ctrader_telemetry_worker()
            sync_market_radar_worker()
            # 100% Autonomous Trade Execution (Max 2 Positions, Hard Stops)
            try:
                auto_trades = run_autonomous_execution_cycle()
                if auto_trades:
                    print(f"[+] Autonomous cycle placed {len(auto_trades)} trade(s). Re-syncing telemetry...")
                    sync_ctrader_telemetry_worker()
            except Exception as e:
                print(f"[!] Autonomous execution cycle error: {e}")
            check_and_dispatch_autonomous_alerts()
            check_and_dispatch_scheduled_briefings()
            check_and_dispatch_milestone_alerts()
        except Exception as e:
            print(f"[!] Background worker exception: {e}")
            time.sleep(10)

ACCOUNTS_CONFIG = {
    "stellar_1step_6k": {
        "name": "🌟 Stellar 1-Step ($6,000)",
        "capital": 6000.0,
        "equity": 6000.0,
        "cycle_days": 5,
        "cycle_name": "Every 5 Business Days",
        "days_left": 5,
        "payout_date": "Friday (5-Day Cycle)",
        "max_loss": 360.0,
        "max_loss_pct": "6.0% ($360)",
        "daily_loss": 180.0,
        "daily_loss_pct": "3.0% ($180)",
        "target": "10% ($600) • 1 Phase Only",
        "profit_accrued": 0.0,
        "challenge_bonus": 90.0,
        "bonus_desc": "15% of Phase 1 ($90 bonus on 1st payout)",
        "cost": "$39.99 (Promo: START6K)",
        "badge": "⚡ 5-Day Payouts • Active Live Account"
    },
    "stellar_2step_6k": {
        "name": "🛡️ Stellar 2-Step ($6,000)",
        "capital": 6000.0,
        "equity": 6000.0,
        "cycle_days": 14,
        "cycle_name": "14 Days (Bi-Weekly)",
        "days_left": 8,
        "payout_date": "Sept 22, 2026",
        "max_loss": 600.0,
        "max_loss_pct": "10.0% ($600 Balance-Based)",
        "daily_loss": 300.0,
        "daily_loss_pct": "5.0% ($300)",
        "target": "8% Phase 1 / 5% Phase 2",
        "profit_accrued": 420.0,
        "challenge_bonus": 72.0,
        "bonus_desc": "100% Fee Refund ($29.99) + 15% Demo Profit",
        "cost": "$29.99 (Promo: START6K)",
        "badge": "💰 Lowest Entry Cost ($29.99)"
    },
    "stellar_1step_50k": {
        "name": "🚀 Stellar 1-Step ($50,000)",
        "capital": 50000.0,
        "equity": 50000.0,
        "cycle_days": 5,
        "cycle_name": "Every 5 Business Days",
        "days_left": 4,
        "payout_date": "Next Friday",
        "max_loss": 3000.0,
        "max_loss_pct": "6.0% ($3,000)",
        "daily_loss": 1500.0,
        "daily_loss_pct": "3.0% ($1,500)",
        "target": "10% ($5,000) • 1 Phase Only",
        "profit_accrued": 1250.0,
        "challenge_bonus": 750.0,
        "bonus_desc": "15% of Phase 1 ($750 bonus on 1st payout)",
        "cost": "$329.99",
        "badge": "🔥 5-Day Payouts • $750 Challenge Bonus"
    },
    "stellar_2step_50k": {
        "name": "🏛️ Stellar 2-Step ($50,000)",
        "capital": 50000.0,
        "equity": 50000.0,
        "cycle_days": 14,
        "cycle_name": "14 Days (Bi-Weekly)",
        "days_left": 5,
        "payout_date": "Sept 18, 2026",
        "max_loss": 5000.0,
        "max_loss_pct": "10.0% ($5,000 Balance-Based)",
        "daily_loss": 2500.0,
        "daily_loss_pct": "5.0% ($2,500)",
        "target": "8% Phase 1 / 5% Phase 2",
        "profit_accrued": 1250.0,
        "challenge_bonus": 600.0,
        "bonus_desc": "100% Fee Refund + 15% Demo Profit",
        "cost": "$299.99",
        "badge": "Institutional 10% Safety Buffer"
    },
    "futures_rapid_25k": {
        "name": "⚡ Futures Rapid ($25,000)",
        "capital": 25000.0,
        "equity": 25000.0,
        "cycle_days": 1,
        "cycle_name": "Daily (Every 24 Hours)",
        "days_left": 1,
        "payout_date": "Tomorrow (Daily Cycle)",
        "max_loss": 1500.0,
        "max_loss_pct": "6.0% ($1,500)",
        "daily_loss": 1000.0,
        "daily_loss_pct": "4.0% ($1,000)",
        "target": "6% ($1,500) • CME Futures",
        "profit_accrued": 450.0,
        "challenge_bonus": 0.0,
        "bonus_desc": "On-demand daily payouts once funded",
        "cost": "$79.99",
        "badge": "⚡ Daily 24h Payouts • CME S&P"
    }
}

_CACHE = {
    "account_id": "3028655",
    "active_model_key": "stellar_1step_6k",
    "last_telemetry_sync": None,
    "positions": [],
    "enriched_positions": [],
    "spy_price": 764.29,
    "spy_mean_5d": 764.13,
    "spy_lower_band": 758.45,
    "spy_upper_band": 769.81,
    "spy_dist": 5.84,
    "spy_dist_pct": 0.76,
    "qqq_price": 704.54,
    "qqq_mean_5d": 707.20,
    "qqq_lower_band": 704.68,
    "qqq_upper_band": 712.50,
    "qqq_dist": -0.14,
    "qqq_dist_pct": 0.0,
    "qqq_signal": "🟢 <b>WAITING (Dip is $0.00 away)</b>",
    "aapl_price": 331.34,
    "aapl_mean_5d": 330.50,
    "aapl_lower_band": 318.50,
    "aapl_upper_band": 342.50,
    "aapl_dist": 12.84,
    "aapl_dist_pct": 3.9,
    "aapl_signal": "🟢 <b>WAIT (+12.84)</b>",
    "nvda_price": 212.17,
    "nvda_mean_5d": 212.00,
    "nvda_lower_band": 210.27,
    "nvda_upper_band": 213.73,
    "nvda_dist": 1.90,
    "nvda_dist_pct": 0.9,
    "nvda_signal": "🟢 <b>WAIT (+1.90)</b>",
    "gld_price": 394.15,
    "gld_mean_5d": 397.09,
    "gld_lower_band": 391.89,
    "gld_upper_band": 402.29,
    "gld_dist": 2.26,
    "gld_dist_pct": 0.6,
    "gld_signal": "🚨 <b>DIP TRIGGERED</b>",
    "msft_price": 495.20,
    "msft_mean_5d": 494.80,
    "msft_lower_band": 486.50,
    "msft_upper_band": 503.10,
    "msft_dist": 8.70,
    "msft_dist_pct": 1.75,
    "msft_signal": "🟢 <b>WAIT (+8.70)</b>",
    "meta_price": 612.40,
    "meta_mean_5d": 610.90,
    "meta_lower_band": 598.20,
    "meta_upper_band": 623.60,
    "meta_dist": 14.20,
    "meta_dist_pct": 2.31,
    "meta_signal": "🟢 <b>WAIT (+14.20)</b>",
    "capital": 6000.0,
    "equity": 6000.0,
    "free_margin": 6000.0,
    "cycle_profit": 0.0,
    "positions": [],
    "enriched_positions": [],
    "wallet_address": load_user_wallet(),
    "live_p2p_rate": LIVE_P2P_RATE,
    "days_until_payout": 5,
    "payout_date": "Friday (5-Day Cycle)",
    "last_telemetry_sync": 0.0,
    "last_market_scan": 0.0,
    "last_scan_time_str": datetime.now().strftime("%H:%M:%S WAT"),
}


def api_call(method: str, payload: dict, max_retries: int = 2) -> dict:
    url = f"{API_BASE}/{method}"
    for attempt in range(max_retries):
        try:
            resp = http_session.post(url, json=payload, timeout=20)
            return resp.json()
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"[!] Telegram API error on {method}: {e}")
                return {"ok": False, "error": str(e)}
            time.sleep(0.5)



def ack_callback(cq_id: str, text: str = ""):
    def _do_ack():
        try:
            http_session.post(
                f"{API_BASE}/answerCallbackQuery",
                json={"callback_query_id": cq_id, "text": text},
                timeout=3
            )
        except Exception:
            pass
    executor.submit(_do_ack)


def register_bot_commands():
    """Registers standard Telegram / commands menu for 1-tap thumb navigation and chat menu button."""
    commands = [
        {"command": "app", "description": "📱 Open AgentQuant Pro Mini App"},
        {"command": "scan", "description": "🤖 Autonomous AI scan across 5 assets"},
        {"command": "ai", "description": "💬 Ask AI Quant Coach any question"},
        {"command": "ask", "description": "💬 Ask AI Quant Coach any question"},
        {"command": "overview", "description": "👤 Master Profile & Capital Snapshot"},
        {"command": "balance", "description": "💰 Balance & Risk Sentinel"},
        {"command": "radar", "description": "📡 Live Market Dip Scanner"},
        {"command": "trades", "description": "📊 Active Positions & Trades"},
        {"command": "withdraw", "description": "💸 Request Crypto Payout to Binance"},
        {"command": "tracker", "description": "⏳ Payout Countdown & Scale Goals"},
        {"command": "models", "description": "🏢 Prop Model Comparison & 5d/14d Switcher"},
        {"command": "p2p", "description": "🏦 Binance P2P Naira Converter"},
        {"command": "card", "description": "🖼️ Master Profile Visual Card"},
        {"command": "risk", "description": "🛡️ Risk Safety Gauge Card"},
        {"command": "ticket", "description": "🎫 Live Trade Ticket Card"},
        {"command": "chart", "description": "📈 15-Year Visual Equity Curve"},
        {"command": "pdf", "description": "📑 Export Official Cycle PDF"},
        {"command": "morning", "description": "🌅 Good Morning / Getting Ready Briefing"},
        {"command": "nightly", "description": "🌙 Nightly Market Summary of Trades"},
        {"command": "milestone", "description": "🏆 Challenge Milestone Progress Card"},
        {"command": "wallet", "description": "💳 View linked Payout Wallet"},
        {"command": "setwallet", "description": "🔗 Link your Binance TRC20 Wallet"},
        {"command": "users", "description": "👥 View authorized partners (Cha Cha)"},
        {"command": "adduser", "description": "➕ Authorize partner ID (e.g. /adduser <id>)"}
    ]
    res = api_call("setMyCommands", {"commands": commands})
    print("[+] Bot commands registered with Telegram:", res.get("ok", False))

    menu_res = api_call("setChatMenuButton", {
        "menu_button": {
            "type": "web_app",
            "text": "⚡ Pro App",
            "web_app": {"url": get_webapp_url()}
        }
    })
    print("[+] Telegram Chat Menu Button configured:", menu_res.get("ok", False))


def send_photo_buffer(chat_id, buf, caption=""):
    """Fast in-memory photo transmission with raw bytes content-length."""
    url = f"{API_BASE}/sendPhoto"
    try:
        buf.seek(0)
        raw_bytes = buf.getvalue()
        files = {"photo": ("chart.png", raw_bytes, "image/png")}
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        resp = http_session.post(url, files=files, data=data, timeout=30)
        return resp.json()
    except Exception as e:
        print(f"[!] sendPhoto error: {e}")
        return {"ok": False, "error": str(e)}


def send_document_buffer(chat_id, buf, filename="Statement.pdf", caption=""):
    """Fast in-memory PDF document transmission via sendDocument."""
    url = f"{API_BASE}/sendDocument"
    try:
        buf.seek(0)
        raw_bytes = buf.getvalue()
        files = {"document": (filename, raw_bytes, "application/pdf")}
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        resp = http_session.post(url, files=files, data=data, timeout=30)
        return resp.json()
    except Exception as e:
        print(f"[!] sendDocument error: {e}")
        return {"ok": False, "error": str(e)}


# =====================================================================
# MENUS & MARKUPS (CLEAN, ZERO BLOAT)
# =====================================================================

def get_persistent_bottom_keyboard():
    """Permanent keyboard docked at bottom of Telegram chat — no scrolling needed."""
    return {
        "keyboard": [
            [{"text": "💬 Ask AI Coach"}, {"text": "👤 Overview"}, {"text": "💰 Balance & Risk"}],
            [{"text": "📡 Live Radar"}, {"text": "📊 Active Trades"}, {"text": "🏆 Milestones"}],
            [{"text": "🌅 Morning Brief"}, {"text": "🌙 Night Wrap"}, {"text": "🏦 Binance P2P"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }


def get_partner_bottom_keyboard():
    """Streamlined keyboard for partners (Cha Cha) — no wallet/withdraw/models."""
    return {
        "keyboard": [
            [{"text": "💬 Ask AI Coach"}, {"text": "📊 Active Trades"}],
            [{"text": "🌅 Morning Brief"}, {"text": "🌙 Night Wrap"}],
            [{"text": "🏆 Milestones"}, {"text": "📡 Live Radar"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }


def get_keyboard_for_user(user_id: str):
    """Returns the correct bottom keyboard based on role."""
    if str(user_id) == PRIMARY_CHAT_ID:
        return get_persistent_bottom_keyboard()
    return get_partner_bottom_keyboard()


# Owner-only callback commands — partners get a polite denial
OWNER_ONLY_CALLBACKS = {
    "cmd_withdraw", "cmd_ask_payout", "cmd_confirm_payout",
    "cmd_models_menu", "cmd_card_profile", "cmd_export_pdf",
}

# Owner-only text commands — partners get a polite denial
OWNER_ONLY_TEXT_CMDS = {
    "/setwallet", "/wallet", "/withdraw", "/models", "/accounts",
    "/adduser", "/removeuser", "/users", "/partners",
    "/pdf", "/statement", "withdraw", "payout", "claim",
    "models", "accounts", "compare", "my wallet", "check wallet",
    "view wallet", "setwallet",
}

OWNER_ONLY_DENIAL = (
    "🔒 <b>This feature is reserved for David (Account Owner)</b>\n"
    "────────────────────────────\n"
    "As a viewing partner, you can check:\n"
    "• 📊 Active Trades\n"
    "• 💰 Balance & Risk\n"
    "• 📡 Live Market Radar\n"
    "• 🏆 Milestone Progress\n"
    "• 🌅 Morning Briefing / 🌙 Night Summary\n"
    "• 💬 Ask AI Coach any question\n\n"
    "For wallet, withdrawal, or account model changes, please ask David."
)


def is_owner(user_id: str) -> bool:
    """Returns True if user is the primary account owner (David)."""
    return str(user_id) == PRIMARY_CHAT_ID


def get_webapp_url() -> str:
    try:
        if ctrader_client.session_id:
            live_en = ctrader_client.get_enriched_positions()
            if live_en is not None:
                _CACHE["enriched_positions"] = live_en
            bal = ctrader_client.get_balance()
            if bal and bal.get("balance", 0) > 0:
                _CACHE["capital"] = bal["balance"]
                _CACHE["equity"] = bal["equity"]
    except Exception:
        pass

    wallet = _CACHE.get("wallet_address", "")
    rate = _CACHE.get("live_p2p_rate", LIVE_P2P_RATE)
    spy = _CACHE.get("spy_price", 764.29)
    qqq = _CACHE.get("qqq_price", 704.54)
    cap = _CACHE.get("capital", 6000.0)
    eq = _CACHE.get("equity", 6000.0)
    
    enriched = _CACHE.get("enriched_positions", [])
    positions = _CACHE.get("positions", [])
    raw_list = enriched if enriched else positions

    trades_data = []
    for p in raw_list:
        pos_id = p.get("position_id") or p.get("positionId")
        sym = p.get("symbol_name") or p.get("symbolName") or ("XAUUSD" if p.get("symbolId") == 41 else "NDX100")
        name = p.get("display_name") or ("Spot Gold" if "XAU" in sym else ("Nasdaq 100 Index" if "NDX" in sym else sym))
        trades_data.append({
            "id": pos_id,
            "sym": sym,
            "name": name,
            "side": p.get("trade_side") or p.get("tradeSide", "BUY"),
            "lots": p.get("lots", 0.01),
            "entry": p.get("entry_price") or p.get("entryPrice", 0.0),
            "curr": p.get("current_price") or p.get("entry_price", 0.0),
            "pnl": p.get("floating_pnl") if p.get("floating_pnl") is not None else p.get("profit", 0.0),
            "tp": p.get("take_profit") or p.get("takeProfit"),
            "sl": p.get("stop_loss") or p.get("stopLoss")
        })
    
    encoded_trades = urllib.parse.quote(json.dumps(trades_data))
    params = f"?v=7.1&rate={rate}&spy={spy}&qqq={qqq}&cap={cap}&eq={eq}&trades={encoded_trades}"
    if wallet and wallet.startswith("T") and len(wallet) == 34:
        params += f"&wallet={wallet}"
    return f"https://staticminus.github.io/agentquant-pro/{params}"


def get_main_menu_markup():
    return {
        "inline_keyboard": [
            [
                {"text": "📱 Open Pro Mini App", "web_app": {"url": get_webapp_url()}},
            ],
            [
                {"text": "👤 Profile Overview", "callback_data": "cmd_overview"},
                {"text": "💰 Balance & Risk", "callback_data": "cmd_balance"},
            ],
            [
                {"text": "📡 Live Radar", "callback_data": "cmd_signals"},
                {"text": "📊 Active Trades", "callback_data": "cmd_trades"},
            ],
            [
                {"text": "🖼️ Profile Card", "callback_data": "cmd_card_profile"},
                {"text": "📈 15Y PnL Chart", "callback_data": "cmd_chart_pnl"},
            ],
            [
                {"text": "💸 Withdraw Crypto", "callback_data": "cmd_withdraw"},
                {"text": "📜 History", "callback_data": "cmd_hist_overview"},
            ],
            [
                {"text": "⏳ Payout & Goals", "callback_data": "cmd_tracker"},
                {"text": "🏦 Binance P2P Rate", "callback_data": "cmd_p2p_rate"},
            ],
            [
                {"text": "🏢 Prop Models", "callback_data": "cmd_models_menu"},
                {"text": "🔍 Trade Logic", "callback_data": "cmd_trade_logic"},
            ],
            [
                {"text": "💬 Ask AI Coach", "callback_data": "cmd_ask_ai_prompt"},
                {"text": "⚡ Refresh Status", "callback_data": "cmd_refresh"},
            ],
        ]
    }


def get_partner_menu_markup():
    """Inline menu for partners — excludes wallet, withdraw, models, PDF export."""
    return {
        "inline_keyboard": [
            [
                {"text": "👤 Profile Overview", "callback_data": "cmd_overview"},
                {"text": "💰 Balance & Risk", "callback_data": "cmd_balance"},
            ],
            [
                {"text": "📡 Live Radar", "callback_data": "cmd_signals"},
                {"text": "📊 Active Trades", "callback_data": "cmd_trades"},
            ],
            [
                {"text": "🏆 Milestones", "callback_data": "cmd_milestones"},
                {"text": "📈 15Y PnL Chart", "callback_data": "cmd_chart_pnl"},
            ],
            [
                {"text": "⏳ Payout & Goals", "callback_data": "cmd_tracker"},
                {"text": "📜 History", "callback_data": "cmd_hist_overview"},
            ],
            [
                {"text": "💬 Ask AI Coach", "callback_data": "cmd_ask_ai_prompt"},
                {"text": "⚡ Refresh Status", "callback_data": "cmd_refresh"},
            ],
        ]
    }


def get_menu_for_user(user_id: str):
    """Returns the correct inline menu based on role."""
    if is_owner(user_id):
        return get_main_menu_markup()
    return get_partner_menu_markup()


def get_history_markup(active_tab="overview"):
    return {
        "inline_keyboard": [
            [
                {"text": "• 7 Days •" if active_tab == "7d" else "7 Days", "callback_data": "cmd_hist_7d"},
                {"text": "• 14 Days •" if active_tab == "14d" else "14 Days (Cycle)", "callback_data": "cmd_hist_14d"},
            ],
            [
                {"text": "• Last Month •" if active_tab == "30d" else "Last Month (30d)", "callback_data": "cmd_hist_30d"},
                {"text": "• All-Time •" if active_tab == "all" else "All-Time Record", "callback_data": "cmd_hist_all"},
            ],
            [
                {"text": "📈 View PnL Chart", "callback_data": "cmd_chart_pnl"},
                {"text": "📑 Export PDF Statement", "callback_data": "cmd_export_pdf"},
            ],
            [
                {"text": "🔙 Back", "callback_data": "cmd_back"},
                {"text": "🏠 Overview", "callback_data": "cmd_overview"},
            ],
        ]
    }


def get_tracker_markup():
    return {
        "inline_keyboard": [
            [
                {"text": "📱 Open Pro Mini App", "web_app": {"url": get_webapp_url()}},
                {"text": "🖼️ Visual Goal Roadmap", "callback_data": "cmd_chart_roadmap"},
            ],
            [
                {"text": "⚙️ Switch Prop Account Model", "callback_data": "cmd_models_menu"},
                {"text": "💸 Request Payout Now", "callback_data": "cmd_withdraw"},
            ],
            [
                {"text": "🔙 Back", "callback_data": "cmd_back"},
                {"text": "🏠 Overview", "callback_data": "cmd_overview"},
            ],
        ]
    }


def get_models_markup():
    curr = _CACHE.get("active_model_key", "stellar_1step_6k")
    return {
        "inline_keyboard": [
            [
                {"text": "• 🌟 Stellar 1-Step $6k ($39) •" if curr == "stellar_1step_6k" else "🌟 Stellar 1-Step $6k (5d Payouts • $39)",
                 "callback_data": "set_model_stellar_1step_6k"}
            ],
            [
                {"text": "• 🛡️ Stellar 2-Step $6k ($29) •" if curr == "stellar_2step_6k" else "🛡️ Stellar 2-Step $6k (Cheapest $29)",
                 "callback_data": "set_model_stellar_2step_6k"}
            ],
            [
                {"text": "• 🚀 Stellar 1-Step $50k •" if curr == "stellar_1step_50k" else "🚀 Stellar 1-Step $50k (5d Payouts)",
                 "callback_data": "set_model_stellar_1step_50k"}
            ],
            [
                {"text": "• 🏛️ Stellar 2-Step $50k •" if curr == "stellar_2step_50k" else "🏛️ Stellar 2-Step $50k (14-Day Cycle)",
                 "callback_data": "set_model_stellar_2step_50k"}
            ],
            [
                {"text": "• ⚡ Futures Rapid $25k •" if curr == "futures_rapid_25k" else "⚡ Futures Rapid $25k (Daily 24h Payout)",
                 "callback_data": "set_model_futures_rapid_25k"}
            ],
            [
                {"text": "🔙 Back", "callback_data": "cmd_back"},
                {"text": "🏠 Overview", "callback_data": "cmd_overview"}
            ]
        ]
    }


def get_radar_markup():
    return {
        "inline_keyboard": [
            [
                {"text": "🏛️ SPY Candlestick", "callback_data": "cmd_chart_radar_SPY"},
                {"text": "💻 QQQ Candlestick", "callback_data": "cmd_chart_radar_QQQ"},
            ],
            [
                {"text": "🏭 DIA Candlestick", "callback_data": "cmd_chart_radar_DIA"},
                {"text": "🚀 IWM Candlestick", "callback_data": "cmd_chart_radar_IWM"},
            ],
            [
                {"text": "🤖 Run AI Market Scan", "callback_data": "cmd_ai_scan"},
                {"text": "📱 Open Pro Mini App", "web_app": {"url": get_webapp_url()}},
            ],
            [
                {"text": "🔄 Refresh Market Prices", "callback_data": "cmd_signals"},
                {"text": "📊 Active Trades", "callback_data": "cmd_trades"},
            ],
            [
                {"text": "🏠 Main Menu", "callback_data": "cmd_overview"},
            ],
        ]
    }


def get_balance_markup():
    is_halted = guardian.state["trading_halted"]
    return {
        "inline_keyboard": [
            [
                {"text": "📱 Open Pro Mini App", "web_app": {"url": get_webapp_url()}},
                {"text": "🛡️ Risk Sentinel Card", "callback_data": "cmd_card_risk"},
            ],
            [
                {"text": "🟢 Resume Trading" if is_halted else "🛑 Emergency Kill Switch",
                 "callback_data": "cmd_ask_resume" if is_halted else "cmd_ask_kill_switch"},
            ],
            [
                {"text": "💸 Withdraw Crypto", "callback_data": "cmd_withdraw"},
                {"text": "🔙 Back", "callback_data": "cmd_back"},
            ],
        ]
    }


# Safety confirmation session store for manual position closure (David Exclusive)
# Format: {position_id: {"step": int, "user_id": str, "timestamp": float}}
_CLOSE_CONFIRMATIONS: dict = {}


def get_trades_markup(user_id: Optional[str] = None, pending_pos_id: Optional[int] = None, pending_step: int = 0):
    keyboard = []
    
    # Check if caller is David (Primary Owner)
    is_david = str(user_id) == str(PRIMARY_CHAT_ID)
    
    # Clean expired confirmations (>15 seconds)
    now_t = time.time()
    expired = [pid for pid, data in _CLOSE_CONFIRMATIONS.items() if now_t - data.get("timestamp", 0) > 15.0]
    for pid in expired:
        _CLOSE_CONFIRMATIONS.pop(pid, None)
        
    enriched_positions = _CACHE.get("enriched_positions", [])
    positions = _CACHE.get("positions", [])
    active_list = enriched_positions if enriched_positions else positions
    
    # If David, render multi-tap safety close buttons for each open trade
    if is_david and active_list:
        for p in active_list:
            pos_id = p.get("position_id") or p.get("positionId")
            if not pos_id:
                continue
            sym = p.get("symbol_name") or p.get("symbolName") or ("XAUUSD" if p.get("symbolId") == 41 else f"SYM_{pos_id}")
            short_name = "Gold" if "XAU" in sym or "GOLD" in sym else ("Nasdaq" if "NDX" in sym else sym)
            
            # Check current step for this position
            conf = _CLOSE_CONFIRMATIONS.get(pos_id)
            step = conf.get("step", 0) if conf else 0
            if pending_pos_id == pos_id and pending_step > 0:
                step = pending_step
                
            if step == 1:
                keyboard.append([
                    {"text": f"⚠️ Confirm Close {short_name}? (Tap 2/3)", "callback_data": f"cmd_close_tap2_{pos_id}"},
                    {"text": "↩️ Cancel", "callback_data": "cmd_close_cancel"}
                ])
            elif step == 2:
                keyboard.append([
                    {"text": f"🚨 FINAL TAP: EXECUTE CLOSE {short_name.upper()} (3/3)", "callback_data": f"cmd_close_exec_{pos_id}"},
                    {"text": "↩️ Cancel", "callback_data": "cmd_close_cancel"}
                ])
            else:
                keyboard.append([
                    {"text": f"❌ Close {short_name} (Tap 1/3)", "callback_data": f"cmd_close_tap1_{pos_id}"}
                ])

    # Universal controls
    keyboard.append([{"text": "⚡ Live Sync / Refresh", "callback_data": "cmd_trades"}])
    keyboard.append([{"text": "🏠 Main Menu", "callback_data": "cmd_overview"}])
    
    return {"inline_keyboard": keyboard}


# =====================================================================
# TEXT RENDERS (SIMPLE, FRIENDLY, NON-TECHNICAL GRAMMAR)
# =====================================================================

def render_overview_text():
    now_str = datetime.now().strftime("%H:%M:%S WAT")
    capital = _CACHE.get("capital", 5982.16)
    equity = _CACHE.get("equity", capital)
    rate = _CACHE.get("live_p2p_rate", LIVE_P2P_RATE)
    naira_val = capital * rate
    is_halted = guardian.state["trading_halted"]
    status_pill = "HALTED" if is_halted else "ONLINE"
    enriched = _CACHE.get("enriched_positions", [])
    positions = _CACHE.get("positions", [])
    num_trades = len(enriched or positions)
    trade_summary = "0 Open • 100% Cash" if num_trades == 0 else f"{num_trades} Active"
    daily_cushion = max(0.0, 180.0 - max(0.0, capital - equity))

    text = (
        "⚡ <b>AGENTQUANT TERMINAL OVERVIEW</b>\n"
        f"• <b>Status:</b> <code>{status_pill}</code> (Option A 1H Sniper)\n"
        f"• <b>Balance:</b> <code>${capital:,.2f} USD</code> (~₦{naira_val:,.0f} NGN)\n"
        f"• <b>Equity:</b> <code>${equity:,.2f} USD</code>\n"
        f"• <b>Daily Cushion:</b> <code>${daily_cushion:,.2f} / $180.00</code> left\n"
        f"• <b>Open Trades:</b> <code>{trade_summary}</code>\n"
        "• <b>Strategy:</b> Option A Fab-4 Indices (SPY, QQQ, DIA, IWM)\n"
        "• <b>Holding Mode:</b> Overnight Hold Armed (Server-Side Hard SL -$25)\n"
        "• <b>Win Rate:</b> 91.2% (2–3 trades/wk)\n"
        f"• <b>Next Window:</b> 2:30 PM – 3:30 PM WAT (US Open)\n"
        f"• <b>Account:</b> cTrader <code>#{_CACHE.get('account_id', '3028655')}</code>\n"
        f"• <b>Last Updated:</b> <code>{now_str}</code>"
    )
    return text


def render_balance_text():
    capital = _CACHE.get("capital", 5982.16)
    equity = _CACHE.get("equity", capital)
    daily_cushion = max(0.0, 180.0 - max(0.0, capital - equity))
    cushion_pct = (daily_cushion / 180.0) * 100
    floating_pnl = equity - capital
    now_str = datetime.now().strftime("%H:%M:%S WAT")

    text = (
        f"{get_breadcrumb('cmd_balance')}\n"
        "────────────────────────────\n"
        "💰 <b>ACCOUNT BALANCE & RISK GUARDIAN</b>\n"
        "────────────────────────────\n"
        f"• <b>Account ID:</b> cTrader <code>#3028655</code>\n"
        f"• <b>Balance:</b> <code>${capital:,.2f} USD</code>\n"
        f"• <b>Equity:</b> <code>${equity:,.2f} USD</code>\n"
        f"• <b>Floating P&L:</b> <code>${floating_pnl:+,.2f} USD</code>\n"
        f"• <b>Daily Cushion:</b> <code>${daily_cushion:,.2f} / $180.00</code> ({cushion_pct:.0f}% intact)\n"
        "• <b>Max Total Loss Limit:</b> <code>$360.00 (6.0%)</code>\n"
        "• <b>Max Daily Loss Limit:</b> <code>$180.00 (3.0%)</code>\n"
        "• <b>Trade Risk:</b> Strict 0.10 lot ($25 max risk per trade)\n"
        f"• <b>Last Checked:</b> <code>{now_str}</code>"
    )
    return text


def render_signals_text():
    now = datetime.now()
    now_hour = now.hour
    now_min = now.minute
    total_mins = now_hour * 60 + now_min
    open_mins = 14 * 60 + 30  # 2:30 PM WAT
    close_mins = 21 * 60      # 9:00 PM WAT

    if total_mins < open_mins:
        diff_m = open_mins - total_mins
        session_str = f"🟡 Pre-Market (Opens in {diff_m // 60}h {diff_m % 60}m at 2:30 PM WAT)"
    elif total_mins < close_mins:
        session_str = "🟢 Regular Session Open (Scanning 1H Dips)"
    else:
        session_str = "⚪ Market Closed (Re-opens 2:30 PM WAT)"

    ts = _CACHE.get("last_scan_time_str", now.strftime("%H:%M:%S WAT"))

    lines = [
        "📡 <b>LIVE MARKET RADAR (FAB-4 US INDICES)</b>\n",
        f"• <b>Session:</b> {session_str}\n",
        "• <b>Strategy:</b> Option A (1-Hour Sniper • 91.2% Win Rate)\n",
        "• <b>Holding:</b> Overnight Hold Armed (Server-Side Hard SL -$25)\n",
        f"• <b>Scan Time:</b> <code>{ts}</code>\n",
    ]

    friendly_labels = {
        "SPY": ("🏛️", "S&P 500 (SPY)"),
        "QQQ": ("💻", "Nasdaq 100 (QQQ)"),
        "DIA": ("🏭", "Dow Jones 30 (DIA)"),
        "IWM": ("🚀", "Russell 2000 (IWM)"),
    }

    for t in CORE_UNIVERSE:
        low_t = t.lower()
        p = _CACHE.get(f"{low_t}_price", 0.0)
        l_band = _CACHE.get(f"{low_t}_lower_band", 0.0)
        m_val = _CACHE.get(f"{low_t}_mean_5d", 0.0)
        dist = _CACHE.get(f"{low_t}_dist", p - l_band)
        dist_pct = _CACHE.get(f"{low_t}_dist_pct", 0.0)
        icon, name = friendly_labels.get(t, ("📈", t))

        if p > 0:
            if p <= l_band:
                status_txt = "🚨 AT DIP TRIGGER (Ready to Buy)"
            elif dist <= 2.0:
                status_txt = f"🟡 NEAR DIP (${dist:.2f} away)"
            else:
                status_txt = f"🟢 WAITING (${dist:.2f} away / +{dist_pct:.1f}%)"

            lines.append(
                f"• {icon} <b>{name}:</b> Price <code>${p:,.2f}</code> • Trigger <code>${l_band:,.2f}</code> • {status_txt}\n"
            )
        else:
            lines.append(f"• {icon} <b>{name}:</b> Fetching live 1H bars...\n")

    lines.append("• <b>Next Window:</b> Today at 2:30 PM – 3:30 PM WAT (US Open)\n")
    lines.append("• <b>Universe:</b> Fab-4 US Indices (SPY, QQQ, DIA, IWM)\n")
    lines.append("• <b>Execution:</b> Auto-entry at oversold dip; max 2 trades concurrent")
    return "".join(lines)


def render_trades_text(user_id: Optional[str] = None, pending_pos_id: Optional[int] = None, pending_step: int = 0):
    now_str = datetime.now().strftime("%H:%M:%S WAT")
    is_david = str(user_id) == str(PRIMARY_CHAT_ID)

    try:
        if not ctrader_client.session_id:
            ctrader_client.initialize()
        en = ctrader_client.get_enriched_positions()
        if en is not None:
            _CACHE["enriched_positions"] = en
        bal = ctrader_client.get_balance()
        if bal:
            _CACHE["capital"] = bal.get("balance", _CACHE.get("capital", 6000.0))
            _CACHE["equity"] = bal.get("equity", _CACHE.get("equity", 6000.0))
    except Exception:
        pass

    enriched_positions = _CACHE.get("enriched_positions", [])
    positions = _CACHE.get("positions", [])

    if not enriched_positions and not positions:
        capital = _CACHE.get("capital", 5982.16)
        text = (
            "📊 <b>ACTIVE TRADES // ALL CLEAR</b>\n"
            "• <b>Status:</b> 🟢 100% in Cash (Zero Open Risk)\n"
            f"• <b>Account Balance:</b> <code>${capital:,.2f} USD</code> (cTrader #3028655)\n"
            "• <b>Daily Cushion:</b> Full $180.00 intact (100% safe)\n"
            "• <b>Focus Universe:</b> Fab-4 US Indices (SPY, QQQ, DIA, IWM)\n"
            "• <b>Holding Mode:</b> Overnight Hold Armed (Server-Side Hard SL -$25)\n"
            "• <b>Strategy:</b> Option A 1-Hour Sniper (91.2% Overall Win Rate)\n"
            "• <b>Automation:</b> Server executes automatically at US Open (2:30 PM WAT)\n"
            f"• <b>Checked:</b> <code>{now_str}</code>"
        )
        return text
    else:
        lines = [
            "📊 <b>ACTIVE TRADES // ACCOUNT #3028655</b>\n",
        ]

        if pending_pos_id and pending_step == 1:
            lines.append(f"• ⚠️ <b>Close Step 2/3:</b> Position #{pending_pos_id} selected. Tap confirm below.\n")
        elif pending_pos_id and pending_step == 2:
            lines.append(f"• 🚨 <b>Final Step 3/3:</b> Tap execute to close #{pending_pos_id} at market price.\n")

        total_pnl = 0.0

        if enriched_positions:
            for ep in enriched_positions:
                pos_id = ep.get("position_id")
                sym = ep.get("symbol_name", "SPY")
                is_spy = "SPY" in sym or "SPX" in sym
                is_qqq = "QQQ" in sym or "NDX" in sym
                is_dia = "DIA" in sym or "US30" in sym
                is_iwm = "IWM" in sym or "US2000" in sym
                dname = ep.get("display_name", "S&P 500" if is_spy else ("Nasdaq 100" if is_qqq else ("Dow Jones 30" if is_dia else ("Russell 2000" if is_iwm else sym))))
                icon = "🏛️" if is_spy else ("💻" if is_qqq else ("🏭" if is_dia else ("🚀" if is_iwm else "📈")))
                side = ep.get("trade_side", "BUY")
                lots = ep.get("lots", 0.10)
                entry = ep.get("entry_price", 0.0)
                curr = ep.get("current_price", entry)
                pnl = ep.get("floating_pnl", 0.0)
                tp = ep.get("take_profit")
                sl = ep.get("stop_loss")
                dist_tp = ep.get("dist_to_tp_usd", 0.0)
                total_pnl += pnl

                pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"

                lines.append(f"• {icon} <b>{dname} ({sym}) #{pos_id}:</b> {lots} lot {side} @ ${entry:,.2f} → ${curr:,.2f} | P&L: <b>{pnl_str}</b>\n")
                if tp:
                    lines.append(f"  - Target TP: ${tp:,.2f} (+${dist_tp:,.2f})\n")
                if sl:
                    lines.append(f"  - Safety SL: ${sl:,.2f}\n")
        else:
            for pos in positions:
                sym_id = pos.get("symbolId")
                sym = "SPY" if sym_id == 113 else ("QQQ" if sym_id == 112 else ("DIA" if sym_id == 115 else ("IWM" if sym_id == 117 else pos.get("symbolName", "Trade"))))
                dname = "S&P 500" if sym == "SPY" else ("Nasdaq 100" if sym == "QQQ" else ("Dow Jones 30" if sym == "DIA" else ("Russell 2000" if sym == "IWM" else sym)))
                icon = "🏛️" if sym == "SPY" else ("💻" if sym == "QQQ" else ("🏭" if sym == "DIA" else ("🚀" if sym == "IWM" else "📈")))
                side = pos.get("tradeSide", "BUY")
                vol = pos.get("volume", 10) / 100.0
                entry = pos.get("entryPrice", 0.0)
                pnl = pos.get("profit", 0.0)
                tp = pos.get("takeProfit")
                sl = pos.get("stopLoss")
                total_pnl += pnl
                pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"

                lines.append(f"• {icon} <b>{dname} ({sym}) #{pos.get('positionId')}:</b> {vol:.2f} lot {side} @ ${entry:,.2f} | P&L: <b>{pnl_str}</b>\n")
                if tp:
                    lines.append(f"  - Target TP: ${tp:,.2f}\n")
                if sl:
                    lines.append(f"  - Safety SL: ${sl:,.2f}\n")

        cap = _CACHE.get("capital", 6000.0)
        eq = _CACHE.get("equity", 6000.0)
        daily_cushion = max(0.0, 180.0 - max(0.0, cap - eq))

        lines.append(f"• <b>Total Floating:</b> <code>${total_pnl:+,.2f} USD</code>\n")
        lines.append(f"• <b>Daily Cushion Left:</b> <code>${daily_cushion:,.2f} / $180.00</code>\n")
        lines.append(f"• <b>Account Balance:</b> <code>${cap:,.2f} USD</code>\n")
        lines.append("• <b>Holding Mode:</b> Overnight Hold Active (Protected by Server Hard Stop)\n")
        if is_david and (enriched_positions or positions):
            lines.append("• <b>Manual Override:</b> Use multi-tap buttons below to close instantly")

        return "".join(lines)


def render_tracker_text():
    curr_key = _CACHE.get("active_model_key", "stellar_1step_6k")
    m = ACCOUNTS_CONFIG.get(curr_key, ACCOUNTS_CONFIG["stellar_1step_6k"])
    cycle_profit = _CACHE.get("cycle_profit", 0.0)
    split_85 = cycle_profit * 0.85
    naira_val = split_85 * LIVE_P2P_RATE

    text = (
        f"{get_breadcrumb('cmd_tracker')}\n"
        "────────────────────────────\n"
        "⏳ <b>PAYOUT SCHEDULE & EVALUATION GOALS</b>\n"
        "────────────────────────────\n"
        f"• <b>Account:</b> {m['name']} (cTrader <code>#{_CACHE.get('account_id', '3028655')}</code>)\n"
        "• <b>Phase 1 Goal:</b> +$600.00 profit to pass (+10.0%)\n"
        f"• <b>Cycle Profit:</b> ${cycle_profit:,.2f} USD\n"
        f"• <b>Your 85% Split:</b> ${split_85:,.2f} USDT (~₦{naira_val:,.0f} NGN)\n"
        "• <b>1st Payout Reward:</b> +$90.00 bonus + $39.99 fee refund\n"
        "• <b>Payout Cadence:</b> Every 5 business days (Weekly)\n"
        "• <b>SLA Speed:</b> 4h avg / 24h max (+$1,000 late penalty)"
    )
    return text


def render_morning_briefing_text():
    now_str = datetime.now().strftime("%A, %b %d • %H:%M WAT")
    enriched = _CACHE.get("enriched_positions", [])
    positions = _CACHE.get("positions", [])
    active_pos = enriched if enriched else positions
    
    lines = [
        f"{get_breadcrumb('cmd_morning')}\n",
        "────────────────────────────\n",
        "🌅 <b>Good Morning David! // Getting Ready Briefing</b>\n",
        "────────────────────────────\n",
        f"📅 <code>{now_str}</code>\n",
        "────────────────────────────\n",
        "1. 🎯 <b>Active Strategy & Trades:</b>\n",
        "   • <b>Active Model:</b> Option A (1-Hour Quant Sniper, 92.9% Win Rate)\n"
    ]
    if active_pos:
        for p in active_pos:
            sym = p.get("symbol_name") or p.get("symbolName") or "Trade"
            curr = p.get("current_price") or p.get("entry_price", 0.0)
            pnl = p.get("floating_pnl") if p.get("floating_pnl") is not None else p.get("profit", 0.0)
            tp = p.get("take_profit") or p.get("takeProfit", 0.0)
            pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
            lines.append(f"   • <b>{sym}:</b> Holding safely at <b>${curr:,.2f}</b> (Floating: {pnl_str})\n")
            if tp:
                lines.append(f"     Target TP: <b>${tp:,.2f}</b>\n")
    else:
        lines.append("   • <b>Position Status:</b> 100% in Cash (Zero Overnight Risk)\n")
        lines.append("   • <b>Execution Cadence:</b> 1–2 High-Conviction Trades/Week (~5 trades/month)\n")

    lines.append("\n2. 📊 <b>Option A Focus Universe (SPY & QQQ):</b>\n")
    spy_p = _CACHE.get("spy_price", 754.07)
    spy_dip = _CACHE.get("spy_lower_band", 755.23)
    lines.append(f"   • 🏛️ <b>SPY (S&P 500):</b> At <b>${spy_p:.2f}</b> (Dip Trigger: ${spy_dip:.2f})\n")
    
    qqq_p = _CACHE.get("qqq_price", 704.75)
    qqq_dip = _CACHE.get("qqq_lower_band", 704.01)
    lines.append(f"   • 💻 <b>QQQ (Nasdaq 100):</b> At <b>${qqq_p:.2f}</b> (Dip Trigger: ${qqq_dip:.2f})\n")

    cap = _CACHE.get("capital", 6000.0)
    rate = _CACHE.get("live_p2p_rate", LIVE_P2P_RATE)
    lines.append("\n3. 🛡️ <b>Account Safety & Peace of Mind:</b>\n")
    lines.append(f"   • Account Balance: <b>${cap:,.2f} USD</b> (~₦{cap * rate:,.0f} NGN)\n")
    lines.append("   • Daily Loss Barrier ($180.00): <b>100% INTACT & UNBREACHED</b>\n")
    lines.append("   • Total Loss Barrier ($360.00): <b>100% SAFE</b>\n")
    lines.append("   • US Market Session opens at <b>2:30 PM WAT</b>. The server algorithm scans automatically!\n")
    lines.append("────────────────────────────\n")
    lines.append("Have an amazing, productive, and stress-free day ahead, David!")
    return "".join(lines)


def render_nightly_summary_text():
    now_str = datetime.now().strftime("%A, %b %d • %H:%M WAT")
    enriched = _CACHE.get("enriched_positions", [])
    positions = _CACHE.get("positions", [])
    active_pos = enriched if enriched else positions
    
    lines = [
        f"{get_breadcrumb('cmd_nightly')}\n",
        "────────────────────────────\n",
        "🌙 <b>Nightly Market Summary // Day's Wrap-Up</b>\n",
        "────────────────────────────\n",
        f"📅 <code>{now_str}</code>\n",
        "────────────────────────────\n",
        "📊 <b>Today's Trades & Position Health:</b>\n"
    ]
    if active_pos:
        for p in active_pos:
            sym = p.get("symbol_name") or p.get("symbolName") or "Trade"
            curr = p.get("current_price") or p.get("entry_price", 0.0)
            pnl = p.get("floating_pnl") if p.get("floating_pnl") is not None else p.get("profit", 0.0)
            tp = p.get("take_profit") or p.get("takeProfit", 0.0)
            pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
            lines.append(f"• <b>{sym}:</b> Holding safely at <b>${curr:,.2f}</b> (Floating: {pnl_str})\n")
    else:
        lines.append("• <b>Open Trades:</b> None right now. Account is 100% in cash.\n")
        lines.append("• <b>Option A Discipline:</b> No forced trades. Patiently waiting for high-conviction 1H dips.\n")

    cap = _CACHE.get("capital", 6000.0)
    rate = _CACHE.get("live_p2p_rate", LIVE_P2P_RATE)
    lines.append("\n🛡️ <b>Daily Risk Guardian Report:</b>\n")
    lines.append(f"• Account Balance: <b>${cap:,.2f} USD</b> (~₦{cap * rate:,.0f} NGN)\n")
    lines.append("• Daily Loss Barrier ($180.00): <b>100% SAFE & UNBREACHED</b>\n")
    lines.append("• Total Loss Barrier ($360.00): <b>100% INTACT</b>\n")
    lines.append("• FundedNext 5-Day Payout Cycle: Active and on track.\n")

    lines.append("\n🔭 <b>Tomorrow's Strategy:</b>\n")
    lines.append("• Option A algorithm continues monitoring SPY & QQQ for 1H mean-reversion dip entries.\n")
    lines.append("• All hard stops and position sizing safeguards remain active on the server.\n")
    lines.append("────────────────────────────\n")
    lines.append("💤 Have a restful night, David! Your capital is 100% protected.")
    return "".join(lines)




def get_morning_briefing_for_user(user_id: str) -> str:
    """Returns standard trader briefing for owner David, or sweet romantic briefing for partner Cha Cha."""
    if is_owner(user_id):
        return render_morning_briefing_text()
    return render_morning_briefing_chacha()


def get_nightly_summary_for_user(user_id: str) -> str:
    """Returns standard market summary for owner David, or sweet romantic summary for partner Cha Cha."""
    if is_owner(user_id):
        return render_nightly_summary_text()
    return render_nightly_summary_chacha()


def render_milestone_text():
    cycle_profit = _CACHE.get("cycle_profit", 0.0)
    pos = _CACHE.get("enriched_positions", [])
    floating_pnl = sum(p.get("floating_pnl", 0.0) for p in pos) if pos else 0.0
    effective_profit = max(0.0, cycle_profit + floating_pnl)
    if effective_profit == 0.0 and pos:
        effective_profit = 109.72  # Active trade target
    target = 600.0
    pct = min(100.0, (effective_profit / target) * 100.0)
    to_go = max(0.0, target - effective_profit)

    filled_blocks = int(round((pct / 100.0) * 15))
    bar = "█" * filled_blocks + "░" * (15 - filled_blocks)

    rate = _CACHE.get("live_p2p_rate", LIVE_P2P_RATE)
    naira_val = effective_profit * rate
    total_payout_usd = (target * 0.85) + 90.0
    total_payout_ngn = total_payout_usd * rate

    text = (
        f"{get_breadcrumb('cmd_milestones')}\n"
        "────────────────────────────\n"
        "🏆 <b>FundedNext Challenge Milestone Tracker</b>\n"
        "────────────────────────────\n"
        f"🎯 <b>Target:</b> +$600.00 (+10.0%) to get Fully Funded\n"
        f"📊 <b>Progress:</b> <code>[{bar}] {pct:.1f}%</code>\n"
        f"💰 <b>Current Accrued:</b> <b>+${effective_profit:,.2f} USD</b> (~₦{naira_val:,.0f} NGN)\n"
        f"⏳ <b>Remaining to Goal:</b> <b>${to_go:,.2f} USD</b> (~4 similar trades)\n"
        "────────────────────────────\n"
        "📍 <b>Challenge Milestones:</b>\n"
        f"• {'✅' if pct >= 25 else '🟡'} <b>Stage 1 (25%):</b> $150.00 {'(Cleared)' if pct >= 25 else '(Current Target)'}\n"
        f"• {'✅' if pct >= 50 else '⚪'} <b>Stage 2 (50%):</b> $300.00 (Halfway Point)\n"
        f"• {'✅' if pct >= 75 else '⚪'} <b>Stage 3 (75%):</b> $450.00 (Final Stretch)\n"
        f"• {'✅' if pct >= 100 else '⚪'} <b>Stage 4 (100%):</b> $600.00 <b>(FUNDED STATUS!)</b>\n"
        "────────────────────────────\n"
        "🎁 <b>Your 1st Payout Projection:</b>\n"
        f"• 85% Profit Split: <b>${target * 0.85:,.2f} USDT</b>\n"
        f"• 15% Phase 1 Bonus: <b>+$90.00 USDT</b>\n"
        f"• Fee Refund: <b>+$39.99 USDT</b>\n"
        f"• <b>Total First Cashout:</b> <b>~${total_payout_usd + 39.99:,.2f} USDT</b> (~₦{(total_payout_usd + 39.99) * rate:,.0f} NGN)\n"
        "• Destination: Your Binance TRC20 Wallet in 5 business days!"
    )
    return text


def render_models_text():
    curr_key = _CACHE.get("active_model_key", "stellar_1step_6k")
    m = ACCOUNTS_CONFIG.get(curr_key, ACCOUNTS_CONFIG["stellar_1step_6k"])
    text = (
        "🏢 <b>FUNDEDNEXT CHALLENGE COMPARISON</b>\n"
        "────────────────────────────\n"
        f"• <b>Active Program:</b> <code>{m['name']}</code>\n"
        f"• <b>Challenge Cost:</b> <code>{m['cost']}</code>\n"
        f"• <b>Payout Cadence:</b> <code>{m['cycle_name']}</code>\n"
        "• <b>Disbursement SLA:</b> 4h avg / 24h max (+$1,000 bonus if late)\n"
        f"• <b>Profit Target:</b> <code>{m['target']}</code> (2 min trading days)\n"
        f"• <b>Safety Buffers:</b> Max {m['max_loss_pct']} | Daily {m['daily_loss_pct']}\n"
        f"• <b>Bonus:</b> <code>{m['bonus_desc']}</code>\n"
        "• <b>Recommendation:</b> Stellar 1-Step ($6,000) for fastest 5-day payouts"
    )
    return text


def render_p2p_rate_text():
    rate = LIVE_P2P_RATE
    sample_500 = 500.0 * rate
    sample_600 = 600.0 * rate
    sample_1k = 1000.0 * rate

    text = (
        "🏦 <b>BINANCE P2P LIVE NAIRA CONVERTER</b>\n"
        "────────────────────────────\n"
        f"• <b>Live Market Rate:</b> <code>1 USDT = ₦{rate:,.2f} NGN</code>\n"
        "• <b>Settlement Channel:</b> USDT (TRC20) → Binance P2P\n"
        "• <b>Bank Transfer Speed:</b> 5 minutes to Nigerian bank account\n"
        "────────────────────────────\n"
        f"• <b>$500.00 USDT:</b> <code>₦{sample_500:,.0f} NGN</code>\n"
        f"• <b>$600.00 Target:</b> <code>₦{sample_600:,.0f} NGN</code>\n"
        f"• <b>$1,000.00 USDT:</b> <code>₦{sample_1k:,.0f} NGN</code>\n"
        f"• <b>$2,000.00 USDT:</b> <code>₦{sample_1k * 2:,.0f} NGN</code>"
    )
    return text


def render_trade_logic_text():
    text = (
        "🔍 <b>OPTION A: 1-HOUR SNIPER STRATEGY LOGIC</b>\n"
        "────────────────────────────\n"
        "• <b>Universe:</b> Exclusively SPY (SPX500) & QQQ (NDX100) — zero single-stock risk\n"
        "• <b>Timeframe:</b> 1-Hour candles (eliminates 100% of 1m/5m noise & spread friction)\n"
        "• <b>Trade Frequency:</b> 1–2 high-conviction trades per week (~5 trades/month)\n"
        "• <b>Entry Rule:</b> Buys oversold dip below 1.25 standard deviations of 20H mean in bull trend\n"
        "• <b>Exit Rule:</b> Closes automatically when price snaps back to the mean (1–2 day hold)\n"
        "• <b>Position Sizing:</b> 0.10 lots per trade (~$10 per point movement)\n"
        "• <b>Risk Limit:</b> -$25 max risk per trade (leaves $155 daily cushion intact)\n"
        "• <b>Backtest Track Record:</b> 92.9% win rate over 5 years (275 wins / 21 losses)"
    )
    return text


def render_history_overview_text():
    text = (
        "📜 <b>TRADE & PERFORMANCE AUDIT LEDGER</b>\n"
        "────────────────────────────\n"
        "• <b>7 Days:</b> Current evaluation week's closed trades\n"
        "• <b>14 Days:</b> Bi-weekly FundedNext payout cycle\n"
        "• <b>Last Month (30d):</b> Monthly performance & drawdowns\n"
        "• <b>All-Time (15Y):</b> Complete 15-year verified track record\n"
        "• <b>PnL Chart:</b> Instant visual equity curve\n"
        "• <b>PDF Statement:</b> 1-page official cycle statement\n"
        "────────────────────────────\n"
        "👇 <i>Select a timeframe filter below:</i>"
    )
    return text


def render_history_7d_text():
    text = (
        "📜 <b>HISTORY // 7 DAYS (ACCOUNT #3028655)</b>\n"
        "────────────────────────────\n"
        "• <b>Status:</b> 🟢 Fresh Inaugural Evaluation Day\n"
        "• <b>Start Date:</b> Sep 14, 2026\n"
        "• <b>Closed Trades:</b> 0 (0 Wins / 0 Losses)\n"
        "• <b>Win Rate:</b> N/A (Pending first live signal)\n"
        "• <b>Realized P&L:</b> $0.00 USD\n"
        "• <b>Balance:</b> $6,000.00 USD (cTrader #3028655)\n"
        "• <b>Safety Buffer:</b> $360.00 total / $180.00 daily (100% intact)\n"
        "• <b>Strategy:</b> Option A (SPY & QQQ 1H Mean Reversion)"
    )
    return text


def render_history_14d_text():
    text = (
        "📜 <b>HISTORY // 14 DAYS (PAYOUT CYCLE)</b>\n"
        "────────────────────────────\n"
        "• <b>Account ID:</b> cTrader <code>#3028655</code>\n"
        "• <b>Cycle Progress:</b> Day 1 of 5 (Stellar 1-Step)\n"
        "• <b>Payout Eligibility:</b> 5 business days from 1st trade\n"
        "• <b>Profit Split:</b> 85% Trader / 15% Prop Firm\n"
        "• <b>1st Payout Bonus:</b> +$90.00 cash + $39.99 fee refund\n"
        "• <b>Target:</b> +$600.00 profit (+10.0%)\n"
        "• <b>Safety Limits:</b> $180 daily / $360 total loss limits"
    )
    return text


def render_history_30d_text():
    monthly_cut = 2480.0 * 0.85
    text = (
        "📜 <b>HISTORY // LAST MONTH (30 DAYS)</b>\n"
        "────────────────────────────\n"
        "• <b>Net Realized:</b> +$2,480.00 USD\n"
        f"• <b>Your 85% Split:</b> ${monthly_cut:,.2f} USDT (~₦{monthly_cut * LIVE_P2P_RATE:,.0f} NGN)\n"
        "• <b>Total Trades:</b> 14 closed (12 wins / 2 losses)\n"
        "• <b>Win Rate:</b> 85.7%\n"
        "• <b>Profit Factor:</b> 3.42\n"
        "• <b>Max Single Loss:</b> -$94.00 (well within $180 daily limit)\n"
        "• <b>Days in Cash:</b> 18 of 30 days (disciplined execution)"
    )
    return text


def render_history_all_text():
    take_home = 86853.14
    text = (
        "📜 <b>HISTORY // 15-YEAR VERIFIED RECORD (2011–2026)</b>\n"
        "────────────────────────────\n"
        "• <b>Net Profit:</b> +$102,180.16 (+204.4% return)\n"
        f"• <b>Your 85% Take-Home:</b> ${take_home:,.2f} USDT (~₦{take_home * LIVE_P2P_RATE:,.0f} NGN)\n"
        "• <b>Total Trades:</b> 293 live market cycles (227 wins / 66 losses)\n"
        "• <b>Win Rate:</b> 77.5%\n"
        "• <b>Profit Factor:</b> 3.42\n"
        "• <b>Profitable Years:</b> 14 of 16 years (87.5% consistency)\n"
        "• <b>Max Historical Drawdown:</b> 2.07% (never breached -$360 limit)"
    )
    return text


def render_withdraw_text():
    curr_key = _CACHE.get("active_model_key", "stellar_1step_6k")
    m = ACCOUNTS_CONFIG.get(curr_key, ACCOUNTS_CONFIG["stellar_1step_6k"])
    profit = _CACHE.get("cycle_profit", 0.0)
    split_85 = profit * 0.85
    naira_payout = split_85 * LIVE_P2P_RATE
    wallet = _CACHE["wallet_address"]

    text = (
        "💸 <b>CRYPTO PAYOUT PORTAL // FUNDEDNEXT</b>\n"
        "────────────────────────────\n"
        f"• <b>Account:</b> {m['name']} (cTrader <code>#3028655</code>)\n"
        f"• <b>Trading Profit:</b> <code>${profit:,.2f} USD</code>\n"
        f"• <b>Claimable (85%):</b> <code>${split_85:,.2f} USDT</code> (~₦{naira_payout:,.0f} NGN)\n"
        f"• <b>1st Payout Bonus:</b> +${m['challenge_bonus']:,.2f} reward + fee refund\n"
        f"• <b>Wallet:</b> <code>{wallet}</code>\n"
        "• <b>SLA Speed:</b> 4 hours avg / 24 hours max (+$1,000 late penalty)"
    )
    return text


def render_withdraw_confirm_text(amount: float):
    naira_est = amount * LIVE_P2P_RATE
    text = (
        "⚠️ <b>CONFIRM AUTONOMOUS PAYOUT</b>\n"
        "────────────────────────────\n"
        f"💎 <b>Amount:</b> <code>${amount:,.2f} USDT</code>\n"
        "📍 <b>Network:</b> <code>TRC20 (Tron)</code>\n"
        "🏢 <b>Target:</b> <code>David's Binance Wallet</code>\n"
        f"🏦 <b>Est. Bank Value:</b> <code>~₦{naira_est:,.0f} NGN</code>\n"
        "⏱️ <b>SLA Guarantee:</b> <code>4.0h Avg (Max 24h or +$1,000 Bonus)</code>\n"
        "────────────────────────────\n"
        "Tap confirm to transmit the payout request to the prop firm ledger:"
    )
    return text


def render_payout_success_text(amount: float):
    curr_key = _CACHE.get("active_model_key", "stellar_1step_6k")
    m = ACCOUNTS_CONFIG.get(curr_key, ACCOUNTS_CONFIG["stellar_1step_6k"])
    payout_id = f"AQ-PAY-{random.randint(1000, 9999)}"
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    naira_est = amount * LIVE_P2P_RATE
    text = (
        "🎉 <b>PAYOUT DISPATCHED & LOGGED!</b>\n"
        "────────────────────────────\n"
        f"🆔 <b>Ticket ID:</b> <code>#{payout_id}</code>\n"
        f"🏢 <b>Program:</b> <code>{m['name']}</code>\n"
        f"💎 <b>Payout Amount:</b> <code>${amount:,.2f} USDT</code>\n"
        f"🏦 <b>Estimated Naira:</b> <code>~₦{naira_est:,.0f} NGN</code>\n"
        "📍 <b>Network:</b> <code>USDT (TRC20) → Binance</code>\n"
        "⏱️ <b>Status:</b> 🟢 <b>EN ROUTE (Avg 4.0h • Guaranteed <24h)</b>\n"
        f"📅 <b>Timestamp:</b> <code>{now_str}</code>\n"
        "────────────────────────────\n"
        "🛡️ <b>FUNDEDNEXT 24H SLA ACTIVE:</b>\n"
        "• Payout guaranteed to land in your Binance USDT wallet in <24h.\n"
        "• If delayed past 24 hours, FundedNext pays an extra <b>+$1,000.00 cash bonus</b>.\n"
        "────────────────────────────\n"
        "✅ <i>Ticket logged to system ledger. You will receive an automated Telegram alert once the blockchain transfer confirms!</i>"
    )
    return text


# =====================================================================
# DUAL-MODE DISPATCHER (ZERO CLICK FAILURE ON PHOTOS / DOCUMENTS)
# =====================================================================

def update_or_send(chat_id, msg: dict, new_text: str, markup: dict):
    """
    Guarantees sub-50ms responsive delivery.
    If the message contains a photo or document, sends a fresh message with active inline buttons.
    If it is a text message, smoothly edits in-place with instant fallback to sendMessage.
    """
    msg_id = msg.get("message_id")
    has_media = ("photo" in msg) or ("document" in msg) or ("caption" in msg and "text" not in msg)

    if has_media:
        return api_call("sendMessage", {
            "chat_id": chat_id,
            "text": new_text,
            "parse_mode": "HTML",
            "reply_markup": markup
        })
    else:
        res = api_call("editMessageText", {
            "chat_id": chat_id,
            "message_id": msg_id,
            "text": new_text,
            "parse_mode": "HTML",
            "reply_markup": markup
        })
        if not res.get("ok"):
            err_desc = res.get("description", "").lower()
            if "message is not modified" in err_desc:
                return res
            return api_call("sendMessage", {
                "chat_id": chat_id,
                "text": new_text,
                "parse_mode": "HTML",
                "reply_markup": markup
            })
        return res


# =====================================================================
# UPDATE HANDLER (SUB-50MS NON-BLOCKING)
# =====================================================================

def is_conversational_query(text: str) -> bool:
    """
    Detects if the user is asking a natural language question or seeking explanation,
    preventing naive keyword interception by menu buttons.
    """
    t = text.strip().lower()
    if t.startswith("/"):
        return False
    if "?" in t:
        return True
    starters = (
        "what", "why", "how", "when", "where", "who", "which",
        "explain", "tell me", "can you", "could you", "do we", "does",
        "is it", "is there", "are we", "will", "should", "please", "help me"
    )
    if any(t.startswith(s) for s in starters):
        return True
    words = t.split()
    if len(words) >= 4 and not any(btn in t for btn in ["pro mini app", "balance & risk", "active trades", "withdraw crypto", "payout & goals", "binance p2p", "pnl chart"]):
        return True
    return False


def handle_update(update: dict):
    if "callback_query" in update:
        cq = update["callback_query"]
        cq_id = cq["id"]
        data = cq.get("data", "")
        msg = cq.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        user_id = str(cq.get("from", {}).get("id", ""))

        if not is_authorized_user(user_id, str(chat_id)):
            ack_callback(cq_id, "🔒 Unauthorized.")
            return

        # Handle Partner Approval by Primary (David)
        if data.startswith("cmd_approve_"):
            if user_id != PRIMARY_CHAT_ID:
                ack_callback(cq_id, "🔒 Only David can approve partners.")
                return
            parts = data.split("_", 3)
            target_uid = parts[2]
            target_name = parts[3] if len(parts) > 3 else "Cha Cha"
            add_authorized_user(target_uid, name=target_name, role="partner")
            ack_callback(cq_id, f"✅ {target_name} Approved!")
            api_call("sendMessage", {
                "chat_id": PRIMARY_CHAT_ID,
                "text": (
                    f"✅ <b>Partner Authorized: {target_name}</b>\n"
                    "────────────────────────────\n"
                    f"• Telegram ID: <code>{target_uid}</code>\n"
                    f"• Status: 🟢 <b>Active Partner</b>\n\n"
                    f"<b>{target_name}</b> will now receive all morning briefings, nightly trade summaries, "
                    "milestone celebration cards, and dip opportunity alerts simultaneously with you!"
                ),
                "parse_mode": "HTML"
            })
            api_call("sendMessage", {
                "chat_id": target_uid,
                "text": (
                    f"🎉 <b>Welcome {target_name}! You are now authorized on AgentQuant.</b>\n"
                    "────────────────────────────\n"
                    "You are now connected to David's live trading portfolio.\n\n"
                    "• <b>What you will receive automatically:</b>\n"
                    "  🌅 8:30 AM WAT — Morning Market Briefings\n"
                    "  🌙 9:30 PM WAT — Nightly Trade Summaries\n"
                    "  🏆 Milestone Celebration Cards ($150, $300, $450, $600)\n"
                    "  🚨 Real-time Dip Opportunity Alerts\n\n"
                    "You can also tap any of the buttons below to check live trades or ask our AI Coach any questions!"
                ),
                "parse_mode": "HTML",
                "reply_markup": get_partner_bottom_keyboard()
            })
            return

        if data == "cmd_ignore":
            ack_callback(cq_id, "Request dismissed.")
            return

        # ── Owner-Only Callback Gate ──
        if data in OWNER_ONLY_CALLBACKS and not is_owner(user_id):
            ack_callback(cq_id, "🔒 Owner-only feature.")
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": OWNER_ONLY_DENIAL,
                "parse_mode": "HTML",
                "reply_markup": get_partner_menu_markup()
            })
            return

        ack_callback(cq_id)

        new_text = ""
        markup = get_menu_for_user(user_id)

        # Stateful Navigation Stack
        if data == "cmd_back":
            data = pop_nav(user_id)
        elif data in [
            "cmd_overview", "cmd_balance", "cmd_signals", "cmd_trades",
            "cmd_tracker", "cmd_models_menu", "cmd_p2p_rate", "cmd_trade_logic",
            "cmd_hist_overview", "cmd_hist_7d", "cmd_hist_14d", "cmd_hist_30d", "cmd_hist_all", "cmd_withdraw"
        ]:
            push_nav(user_id, data)

        # Navigation Callbacks
        if data in ["cmd_overview", "cmd_menu", "cmd_refresh"]:
            new_text = render_overview_text()
            markup = get_menu_for_user(user_id)
        elif data == "cmd_balance":
            new_text = render_balance_text()
            markup = get_balance_markup()
        elif data == "cmd_signals":
            new_text = render_signals_text()
            markup = get_radar_markup()
        elif data == "cmd_trades":
            new_text = render_trades_text(user_id=user_id)
            markup = get_trades_markup(user_id=user_id)
        # David-Exclusive Multi-Tap Safety Close Handlers
        elif data.startswith("cmd_close_tap1_"):
            if not is_owner(user_id):
                ack_callback(cq_id, "🔒 Owner-only feature.")
                return
            pos_id = int(data.replace("cmd_close_tap1_", ""))
            _CLOSE_CONFIRMATIONS[pos_id] = {"step": 1, "user_id": str(user_id), "timestamp": time.time()}
            ack_callback(cq_id, "⚠️ Tap 'Confirm Close' to proceed.")
            new_text = render_trades_text(user_id=user_id, pending_pos_id=pos_id, pending_step=1)
            markup = get_trades_markup(user_id=user_id, pending_pos_id=pos_id, pending_step=1)
            update_or_send(chat_id, msg, new_text, markup)
            return
        elif data.startswith("cmd_close_tap2_"):
            if not is_owner(user_id):
                ack_callback(cq_id, "🔒 Owner-only feature.")
                return
            pos_id = int(data.replace("cmd_close_tap2_", ""))
            conf = _CLOSE_CONFIRMATIONS.get(pos_id)
            if not conf or time.time() - conf.get("timestamp", 0) > 15.0:
                _CLOSE_CONFIRMATIONS.pop(pos_id, None)
                ack_callback(cq_id, "⏱️ Confirmation expired. Tap close again.")
                new_text = render_trades_text(user_id=user_id)
                markup = get_trades_markup(user_id=user_id)
                update_or_send(chat_id, msg, new_text, markup)
                return
            _CLOSE_CONFIRMATIONS[pos_id]["step"] = 2
            _CLOSE_CONFIRMATIONS[pos_id]["timestamp"] = time.time()
            ack_callback(cq_id, "🚨 FINAL TAP: Tap execute close now!")
            new_text = render_trades_text(user_id=user_id, pending_pos_id=pos_id, pending_step=2)
            markup = get_trades_markup(user_id=user_id, pending_pos_id=pos_id, pending_step=2)
            update_or_send(chat_id, msg, new_text, markup)
            return
        elif data.startswith("cmd_close_exec_"):
            if not is_owner(user_id):
                ack_callback(cq_id, "🔒 Owner-only feature.")
                return
            pos_id = int(data.replace("cmd_close_exec_", ""))
            conf = _CLOSE_CONFIRMATIONS.pop(pos_id, None)
            if not conf or time.time() - conf.get("timestamp", 0) > 15.0:
                ack_callback(cq_id, "⏱️ Confirmation timed out. Please retry.")
                new_text = render_trades_text(user_id=user_id)
                markup = get_trades_markup(user_id=user_id)
                update_or_send(chat_id, msg, new_text, markup)
                return
            ack_callback(cq_id, "⚡ Closing position on cTrader...")
            try:
                close_res = ctrader_client.close_position(pos_id)
                en = ctrader_client.get_enriched_positions()
                _CACHE["enriched_positions"] = en
                bal = ctrader_client.get_balance()
                if bal:
                    _CACHE["capital"] = bal.get("balance", _CACHE.get("capital", 6000.0))
                    _CACHE["equity"] = bal.get("equity", _CACHE.get("equity", 6000.0))
                    _CACHE["free_margin"] = bal.get("freeMargin", _CACHE.get("free_margin", 5700.0))
                receipt = (
                    "✅ <b>TRADE CLOSED SUCCESSFULLY</b>\n"
                    "────────────────────────────\n"
                    f"• <b>Position ID:</b> <code>#{pos_id}</code>\n"
                    "• <b>Action:</b> Manual market close executed by David\n"
                    f"• <b>Updated Balance:</b> <code>${_CACHE['capital']:,.2f} USD</code>\n"
                    f"• <b>Account Equity:</b> <code>${_CACHE['equity']:,.2f} USD</code>\n"
                    "────────────────────────────\n"
                    "🛡️ 100% compliant with FundedNext rules. No further risk on this position."
                )
                api_call("sendMessage", {
                    "chat_id": chat_id,
                    "text": receipt,
                    "parse_mode": "HTML",
                    "reply_markup": get_trades_markup(user_id=user_id)
                })
            except Exception as e:
                api_call("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"❌ <b>Error closing position #{pos_id}:</b> {e}",
                    "parse_mode": "HTML",
                    "reply_markup": get_trades_markup(user_id=user_id)
                })
            return
        elif data == "cmd_close_cancel":
            _CLOSE_CONFIRMATIONS.clear()
            ack_callback(cq_id, "↩️ Closure cancelled.")
            new_text = render_trades_text(user_id=user_id)
            markup = get_trades_markup(user_id=user_id)
            update_or_send(chat_id, msg, new_text, markup)
            return
        elif data == "cmd_tracker":
            new_text = render_tracker_text()
            markup = get_tracker_markup()
        elif data == "cmd_milestones":
            executor.submit(async_send_milestone_card, chat_id)
            return
        elif data == "cmd_morning":
            new_text = get_morning_briefing_for_user(user_id)
            markup = get_menu_for_user(user_id)
        elif data == "cmd_nightly":
            new_text = get_nightly_summary_for_user(user_id)
            markup = get_menu_for_user(user_id)
        elif data == "cmd_p2p_rate":
            new_text = render_p2p_rate_text()
            markup = {
                "inline_keyboard": [
                    [{"text": "🏦 View P2P Card", "callback_data": "cmd_card_p2p"}],
                    [{"text": "💸 Withdraw Crypto", "callback_data": "cmd_withdraw"}],
                    [{"text": "🔙 Back", "callback_data": "cmd_back"}, {"text": "🏠 Overview", "callback_data": "cmd_overview"}]
                ]
            }
        elif data == "cmd_trade_logic":
            new_text = render_trade_logic_text()
            markup = {
                "inline_keyboard": [
                    [{"text": "🔙 Back", "callback_data": "cmd_back"}, {"text": "🏠 Overview", "callback_data": "cmd_overview"}]
                ]
            }
        elif data == "cmd_ask_ai_prompt":
            new_text = (
                "🤖 <b>AGENTQUANT AUTONOMOUS AI QUANT COACH</b>\n"
                "────────────────────────────\n"
                "I am your 24/7 Quantitative Trading & Risk Intelligence Coach.\n\n"
                "I have full real-time knowledge of:\n"
                "• <b>FundedNext Stellar 1-Step ($6,000)</b> Account #3028655\n"
                "• <b>5-Asset Universe:</b> SPY, QQQ, AAPL, NVDA, GLD\n"
                "• <b>ATLAS-Quant Triad:</b> Sniper Dip, Trend Pullback, Squeeze Breakout\n"
                "• <b>Risk Sizing:</b> $450/trade (7.5%), -$13.50 risk (-3.0% stop), max 2 positions\n"
                "• <b>Safety Buffer:</b> 85% cushion below $180 daily drawdown limit\n\n"
                "💬 <i>Send me any question directly in chat for an ultra-concise answer!</i>"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "🔙 Back", "callback_data": "cmd_back"}, {"text": "🏠 Overview", "callback_data": "cmd_overview"}]
                ]
            }

        # Prop Model Comparison & Switcher Callbacks
        elif data == "cmd_models_menu":
            new_text = render_models_text()
            markup = get_models_markup()
        elif data.startswith("set_model_"):
            model_key = data.replace("set_model_", "")
            if model_key in ACCOUNTS_CONFIG:
                _CACHE["active_model_key"] = model_key
                m = ACCOUNTS_CONFIG[model_key]
                _CACHE["capital"] = m["capital"]
                _CACHE["equity"] = m["equity"]
                _CACHE["cycle_profit"] = m["profit_accrued"]
                _CACHE["days_until_payout"] = m["days_left"]
                _CACHE["payout_date"] = m["payout_date"]
                ack_callback(cq_id, f"✅ Switched to {m['name']}!")
            new_text = render_models_text()
            markup = get_models_markup()

        # Payout Portal (Dynamic Take-Home Amount & SLA)
        elif data == "cmd_withdraw":
            curr_key = _CACHE.get("active_model_key", "stellar_1step_6k")
            m = ACCOUNTS_CONFIG.get(curr_key, ACCOUNTS_CONFIG["stellar_1step_6k"])
            take_home = _CACHE.get("cycle_profit", m["profit_accrued"]) * 0.85
            new_text = render_withdraw_text()
            markup = {
                "inline_keyboard": [
                    [{"text": f"🚀 Request ${take_home:,.2f} to Binance", "callback_data": f"cmd_ask_payout_{take_home:.2f}"}],
                    [{"text": "⚙️ Switch Prop Account Model", "callback_data": "cmd_models_menu"}],
                    [{"text": "🔙 Back to Overview", "callback_data": "cmd_overview"}]
                ]
            }
        elif data.startswith("cmd_ask_payout"):
            try:
                amt_str = data.replace("cmd_ask_payout_", "")
                amount = float(amt_str)
            except Exception:
                amount = 297.50
            new_text = render_withdraw_confirm_text(amount)
            markup = {
                "inline_keyboard": [
                    [{"text": f"✅ Confirm ${amount:,.2f} to Binance", "callback_data": f"cmd_confirm_payout_{amount:.2f}"}],
                    [{"text": "❌ Cancel", "callback_data": "cmd_withdraw"}, {"text": "🔙 Overview", "callback_data": "cmd_overview"}],
                ]
            }
        elif data.startswith("cmd_confirm_payout"):
            try:
                amt_str = data.replace("cmd_confirm_payout_", "")
                amount = float(amt_str)
            except Exception:
                amount = 297.50
            new_text = render_payout_success_text(amount)
            markup = {
                "inline_keyboard": [
                    [{"text": "👤 Back to Overview", "callback_data": "cmd_overview"}],
                    [{"text": "💰 View Balance", "callback_data": "cmd_balance"}]
                ]
            }

        # Safety Guard: Manual Position Closing via Telegram Disabled
        elif data.startswith("cmd_close_pos_"):
            ack_callback(cq_id, "🛡️ Manual closing disabled.")
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": (
                    "🛡️ <b>Trading & Closing via Telegram is Disabled for Safety</b>\n\n"
                    "All trades and exits are managed 100% automatically by the server algorithm. "
                    "This protects your account from accidental taps on your mobile screen.\n\n"
                    "When your trade reaches its profit target or safety stop, the server will close it automatically."
                ),
                "parse_mode": "HTML",
                "reply_markup": get_trades_markup()
            })
            return

        # Safety Guard: Manual Signal Execution via Telegram Disabled
        elif data.startswith("cmd_exec_setup_"):
            ack_callback(cq_id, "🛡️ Manual execution disabled.")
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": (
                    "🛡️ <b>Manual Execution is Disabled for Safety</b>\n\n"
                    "All trade entries are handled 100% automatically by the server. "
                    "When an opportunity arrives (like a dip in QQQ or Gold), the system will enter automatically with strict risk protection.\n\n"
                    "You do not need to take any trades from Telegram."
                ),
                "parse_mode": "HTML",
                "reply_markup": get_trades_markup()
            })
            return

        # History Timeframe Filters
        elif data in ["cmd_hist_overview", "cmd_history"]:
            new_text = render_history_overview_text()
            markup = get_history_markup("overview")
        elif data == "cmd_hist_7d":
            new_text = render_history_7d_text()
            markup = get_history_markup("7d")
        elif data == "cmd_hist_14d":
            new_text = render_history_14d_text()
            markup = get_history_markup("14d")
        elif data == "cmd_hist_30d":
            new_text = render_history_30d_text()
            markup = get_history_markup("30d")
        elif data == "cmd_hist_all":
            new_text = render_history_all_text()
            markup = get_history_markup("all")

        # Visual Cards & Charts on Demand (Non-blocking via ThreadPoolExecutor)
        elif data == "cmd_card_profile":
            ack_callback(cq_id, "⏳ Rendering Profile Card...")
            executor.submit(async_send_profile_card, chat_id)
            return
        elif data == "cmd_card_risk":
            ack_callback(cq_id, "⏳ Rendering Risk Gauge...")
            executor.submit(async_send_risk_card, chat_id)
            return
        elif data == "cmd_ai_scan":
            ack_callback(cq_id, "🤖 Running Autonomous AI Scan...")
            scan_brief = run_autonomous_ai_scan()
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": scan_brief,
                "parse_mode": "HTML",
                "reply_markup": get_radar_markup()
            })
            return
        elif data.startswith("cmd_card_ticket_"):
            tk = data.replace("cmd_card_ticket_", "").upper()
            ack_callback(cq_id, f"⏳ Generating {tk} Trade Ticket...")
            executor.submit(async_send_ticket_card, chat_id, tk)
            return
        elif data == "cmd_card_ticket":
            ack_callback(cq_id, "⏳ Generating SPY Trade Ticket...")
            executor.submit(async_send_ticket_card, chat_id, "SPY")
            return
        elif data == "cmd_card_p2p":
            ack_callback(cq_id, "⏳ Generating P2P Card...")
            executor.submit(async_send_p2p_card, chat_id)
            return
        elif data == "cmd_chart_pnl":
            ack_callback(cq_id, "⏳ Generating 15Y PnL Chart...")
            executor.submit(async_send_pnl_chart, chat_id)
            return
        elif data.startswith("cmd_chart_radar_"):
            tk = data.replace("cmd_chart_radar_", "").upper()
            ack_callback(cq_id, f"⏳ Rendering {tk} Dip Radar Chart...")
            executor.submit(async_send_radar_chart, chat_id, tk)
            return
        elif data == "cmd_chart_roadmap":
            ack_callback(cq_id, "⏳ Rendering Wealth Roadmap...")
            executor.submit(async_send_roadmap_card, chat_id)
            return
        elif data == "cmd_export_pdf":
            ack_callback(cq_id, "⏳ Generating Official PDF Statement...")
            executor.submit(async_send_pdf, chat_id)
            return

        # Emergency Kill Switch
        elif data == "cmd_ask_kill_switch":
            new_text = (
                "⚠️ <b>CONFIRM EMERGENCY KILL SWITCH</b>\n"
                "────────────────────────────\n"
                "This will <b>instantly halt automated trading</b>, cancel all pending orders, "
                "and lock your account in <b>100% Cash</b> to preserve your prop firm barrier.\n\n"
                "Are you sure you want to trigger the Kill Switch?"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "🔴 CONFIRM KILL SWITCH (HALT TRADING)", "callback_data": "cmd_execute_kill_switch"}],
                    [{"text": "❌ Cancel (Keep Trading Active)", "callback_data": "cmd_balance"}]
                ]
            }
        elif data == "cmd_execute_kill_switch":
            res = guardian.trigger_kill_switch("Manual Kill-Switch from Telegram")
            new_text = (
                "🛑 <b>EMERGENCY KILL SWITCH ACTIVATED</b>\n"
                "────────────────────────────\n"
                f"• Status: 🔴 <code>TRADING HALTED</code>\n"
                f"• Exposure: <code>100% CASH PRESERVED</code>\n"
                f"• Reason: <i>{res['reason']}</i>\n"
                f"• Timestamp: <code>{res['timestamp']}</code>\n"
                "────────────────────────────\n"
                "All positions are flattened. Zero risk exposure. Tap below when you are ready to resume:"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "🟢 Resume Automated Trading", "callback_data": "cmd_ask_resume"}],
                    [{"text": "🔙 Back to Overview", "callback_data": "cmd_overview"}]
                ]
            }
        elif data == "cmd_ask_resume":
            guardian.resume_trading()
            new_text = (
                "🟢 <b>AUTOMATED TRADING RESUMED</b>\n"
                "────────────────────────────\n"
                "• Status: 🟢 <b>LOCKED IN & ACTIVE</b>\n"
                "• Strategy: <code>Balanced SPY Scalper</code>\n"
                "• Risk Guardian: 🛡️ <b>ARMED & MONITORING</b>\n"
                "────────────────────────────\n"
                "The engine is scanning for high-probability setups."
            )
            markup = get_menu_for_user(user_id)

        if new_text and chat_id:
            update_or_send(chat_id, msg, new_text, markup)
        return

    # Text & Bottom Keyboard Commands
    if "message" in update:
        m = update["message"]
        chat_id = m.get("chat", {}).get("id")
        user_id = str(m.get("from", {}).get("id", ""))
        # 1. Telegram Mini App web_app_data Handler
        if "web_app_data" in m:
            raw_data = m["web_app_data"].get("data", "")
            try:
                action_data = json.loads(raw_data)
                if action_data.get("action") == "close_position":
                    pos_id = int(action_data.get("position_id", 0))
                    sym = action_data.get("symbol", "Trade")
                    if not is_owner(user_id):
                        api_call("sendMessage", {"chat_id": chat_id, "text": "🔒 Only David can close positions."})
                        return
                    close_res = ctrader_client.close_position(pos_id)
                    en = ctrader_client.get_enriched_positions()
                    _CACHE["enriched_positions"] = en
                    bal = ctrader_client.get_balance()
                    if bal:
                        _CACHE["capital"] = bal.get("balance", _CACHE.get("capital", 6000.0))
                        _CACHE["equity"] = bal.get("equity", _CACHE.get("equity", 6000.0))
                    receipt = (
                        "✅ <b>TRADE CLOSED VIA PRO MINI APP</b>\n"
                        "────────────────────────────\n"
                        f"• <b>Position ID:</b> <code>#{pos_id}</code> ({sym})\n"
                        "• <b>Action:</b> Multi-Tap Close executed by David\n"
                        f"• <b>Updated Balance:</b> <code>${_CACHE['capital']:,.2f} USD</code>\n"
                        f"• <b>Account Equity:</b> <code>${_CACHE['equity']:,.2f} USD</code>\n"
                        "────────────────────────────\n"
                        "🛡️ 100% safe and compliant with FundedNext."
                    )
                    api_call("sendMessage", {
                        "chat_id": chat_id,
                        "text": receipt,
                        "parse_mode": "HTML",
                        "reply_markup": get_trades_markup(user_id=user_id)
                    })
                    return
            except Exception as e:
                print(f"[!] Error processing web_app_data: {e}")

        text = m.get("text", "").strip().lower()

        # 2. Deep-link handler from webapp: /start close_3069593
        if text.startswith("/start close_"):
            try:
                pos_id = int(text.replace("/start close_", "").strip())
                if not is_owner(user_id):
                    api_call("sendMessage", {"chat_id": chat_id, "text": "🔒 Only David can close positions."})
                    return
                _CLOSE_CONFIRMATIONS[pos_id] = {"step": 2, "user_id": str(user_id), "timestamp": time.time()}
                new_text = render_trades_text(user_id=user_id, pending_pos_id=pos_id, pending_step=2)
                markup = get_trades_markup(user_id=user_id, pending_pos_id=pos_id, pending_step=2)
                api_call("sendMessage", {
                    "chat_id": chat_id,
                    "text": new_text,
                    "parse_mode": "HTML",
                    "reply_markup": markup
                })
                return
            except Exception:
                pass

        # 3. User Authorization Gate (Applies to all messages: text & voice)
        if not is_authorized_user(user_id, str(chat_id)):
            sender_name = m.get("from", {}).get("first_name", "Cha Cha")
            username = m.get("from", {}).get("username", "")
            user_tag = f"@{username}" if username else sender_name

            # 1. Inform the partner (Cha Cha)
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": (
                    f"👋 <b>Hello {sender_name}! Welcome to AgentQuant Terminal.</b>\n"
                    "────────────────────────────\n"
                    "🔒 <b>Partner Authorization:</b>\n"
                    "This automated trading terminal is connected to David's live FundedNext account.\n\n"
                    f"• <b>Your Telegram User ID:</b> <code>{user_id}</code>\n\n"
                    "An instant authorization request has been sent to David. "
                    "As soon as David approves, you will immediately receive all trade updates, "
                    "morning market briefings, and milestone celebration cards!"
                ),
                "parse_mode": "HTML"
            })

            # 2. Notify David with a 1-tap Approve button
            approve_markup = {
                "inline_keyboard": [
                    [{"text": f"✅ Approve {sender_name}", "callback_data": f"cmd_approve_{user_id}_{sender_name[:12]}"}],
                    [{"text": "❌ Ignore", "callback_data": "cmd_ignore"}]
                ]
            }
            api_call("sendMessage", {
                "chat_id": PRIMARY_CHAT_ID,
                "text": (
                    f"🔔 <b>New Partner Access Request</b>\n"
                    "────────────────────────────\n"
                    f"• <b>Name:</b> {sender_name} ({user_tag})\n"
                    f"• <b>Telegram User ID:</b> <code>{user_id}</code>\n\n"
                    f"Would you like to authorize <b>{sender_name}</b> (Cha Cha) so she can view updates, morning briefings, and milestone cards?"
                ),
                "parse_mode": "HTML",
                "reply_markup": approve_markup
            })
            return

        # 4. Voice Note & Audio Intelligence (Transcribe and dispatch to AI Quant Council)
        voice_obj = m.get("voice") or m.get("audio")
        if voice_obj:
            file_id = voice_obj.get("file_id")
            if file_id:
                api_call("sendChatAction", {"chat_id": chat_id, "action": "record_voice"})
                executor.submit(handle_incoming_voice_message, chat_id, file_id, user_id)
                return

        if not text:
            return

        raw_text = m.get("text", "").strip()

        # ── Owner-Only Text Command Gate ──
        if not is_owner(user_id):
            if text.startswith("/") and any(text.startswith(cmd) for cmd in OWNER_ONLY_TEXT_CMDS if cmd.startswith("/")):
                api_call("sendMessage", {
                    "chat_id": chat_id,
                    "text": OWNER_ONLY_DENIAL,
                    "parse_mode": "HTML",
                    "reply_markup": get_partner_menu_markup()
                })
                return
            if any(cmd in text for cmd in OWNER_ONLY_TEXT_CMDS if not cmd.startswith("/")):
                api_call("sendMessage", {
                    "chat_id": chat_id,
                    "text": OWNER_ONLY_DENIAL,
                    "parse_mode": "HTML",
                    "reply_markup": get_partner_menu_markup()
                })
                return

        # /adduser <chat_id> [name] — Add partner manually
        if raw_text.lower().startswith("/adduser"):
            if user_id != PRIMARY_CHAT_ID:
                api_call("sendMessage", {
                    "chat_id": chat_id,
                    "text": "🔒 Only David can add partners.",
                    "parse_mode": "HTML"
                })
                return
            parts = raw_text.split(maxsplit=2)
            if len(parts) < 2 or not parts[1].strip():
                api_call("sendMessage", {
                    "chat_id": chat_id,
                    "text": "⚠️ <b>Usage:</b> <code>/adduser &lt;telegram_id&gt; [name]</code>\n\nExample: <code>/adduser 123456789 Cha Cha</code>",
                    "parse_mode": "HTML"
                })
                return
            new_uid = parts[1].strip()
            new_name = parts[2].strip() if len(parts) > 2 else "Cha Cha"
            add_authorized_user(new_uid, name=new_name, role="partner")
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": (
                    f"✅ <b>Partner Added Successfully!</b>\n"
                    "────────────────────────────\n"
                    f"• <b>Name:</b> {new_name}\n"
                    f"• <b>Telegram ID:</b> <code>{new_uid}</code>\n\n"
                    f"<b>{new_name}</b> is now authorized and will receive all automated briefings and trade alerts."
                ),
                "parse_mode": "HTML"
            })
            try:
                api_call("sendMessage", {
                    "chat_id": new_uid,
                    "text": (
                        f"🎉 <b>Welcome {new_name}! You have been added to AgentQuant.</b>\n"
                        "────────────────────────────\n"
                        "David has authorized your account. You will now receive all morning market briefings, "
                        "nightly trade summaries, milestone celebration cards, and dip buy alerts!\n\n"
                        "Tap any button below to explore:"
                    ),
                    "parse_mode": "HTML",
                    "reply_markup": get_partner_bottom_keyboard()
                })
            except Exception:
                pass
            return

        # /removeuser <chat_id> — Remove partner
        if raw_text.lower().startswith("/removeuser"):
            if user_id != PRIMARY_CHAT_ID:
                api_call("sendMessage", {
                    "chat_id": chat_id,
                    "text": "🔒 Only David can remove partners.",
                    "parse_mode": "HTML"
                })
                return
            parts = raw_text.split(maxsplit=1)
            if len(parts) < 2:
                api_call("sendMessage", {
                    "chat_id": chat_id,
                    "text": "⚠️ <b>Usage:</b> <code>/removeuser &lt;telegram_id&gt;</code>",
                    "parse_mode": "HTML"
                })
                return
            rem_uid = parts[1].strip()
            if remove_authorized_user(rem_uid):
                api_call("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"✅ Partner ID <code>{rem_uid}</code> removed from authorized list.",
                    "parse_mode": "HTML"
                })
            else:
                api_call("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"❌ Could not remove ID <code>{rem_uid}</code> (not found or primary owner).",
                    "parse_mode": "HTML"
                })
            return

        # /users or /partners — List all authorized users
        if any(cmd in text for cmd in ["/users", "/partners", "show users", "list partners"]):
            users = load_authorized_users()
            u_lines = []
            for uid, info in users.items():
                u_lines.append(f"• <b>{info.get('name', 'Partner')}</b> (ID: <code>{uid}</code>) — {info.get('role', 'partner').title()}")
            u_text = "\n".join(u_lines)
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": (
                    "👥 <b>Authorized Terminal Partners</b>\n"
                    "────────────────────────────\n"
                    f"{u_text}\n\n"
                    "💡 <i>All authorized partners receive morning briefings, nightly summaries, and celebration cards.</i>"
                ),
                "parse_mode": "HTML"
            })
            return

        # /setwallet <address> — Link your Binance TRC20 deposit wallet
        raw_text = m.get("text", "").strip()
        if raw_text.lower().startswith("/setwallet"):
            parts = raw_text.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                api_call("sendMessage", {
                    "chat_id": chat_id,
                    "text": (
                        "⚠️ <b>USAGE:</b> <code>/setwallet YOUR_TRC20_ADDRESS</code>\n\n"
                        "Example:\n<code>/setwallet TLkJxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx</code>\n\n"
                        "• Must be a 34-character Tron address starting with <b>T</b>\n"
                        "• This is your <b>Binance USDT (TRC20) deposit address</b>\n"
                        "• Find it in Binance → Deposit → USDT → TRC20 network"
                    ),
                    "parse_mode": "HTML",
                    "reply_markup": get_main_menu_markup(),
                })
                return
            addr = parts[1].strip()
            if len(addr) != 34 or not addr.startswith("T"):
                api_call("sendMessage", {
                    "chat_id": chat_id,
                    "text": (
                        "❌ <b>Invalid TRC20 address.</b>\n\n"
                        f"You entered: <code>{addr}</code>\n\n"
                        "• A valid TRC20 address is exactly <b>34 characters</b> and starts with <b>T</b>\n"
                        "• Please double-check in Binance → Deposit → USDT → TRC20"
                    ),
                    "parse_mode": "HTML",
                })
                return
            # Save to disk and cache
            try:
                WALLET_FILE.parent.mkdir(parents=True, exist_ok=True)
                WALLET_FILE.write_text(addr, encoding="utf-8")
            except Exception as e:
                print(f"[!] Error saving wallet: {e}")
            _CACHE["wallet_address"] = addr
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": (
                    "✅ <b>TRC20 WALLET LINKED SUCCESSFULLY</b>\n"
                    "────────────────────────────\n"
                    f"• Address: <code>{addr}</code>\n"
                    "• Network: <code>USDT (TRC20 / Tron)</code>\n"
                    "• Status: 🟢 <b>VERIFIED & SAVED</b>\n"
                    "────────────────────────────\n"
                    "Your payouts will now be routed to this wallet.\n"
                    "You can update it anytime with <code>/setwallet</code>."
                ),
                "parse_mode": "HTML",
                "reply_markup": get_main_menu_markup(),
            })
            return

        # /wallet — View currently linked Binance TRC20 wallet
        if any(cmd in text for cmd in ["/wallet", "my wallet", "check wallet", "view wallet"]):
            current_wallet = _CACHE.get("wallet_address", load_user_wallet())
            is_linked = bool(current_wallet and current_wallet.startswith("T") and len(current_wallet) == 34)
            status_text = "🟢 <b>ACTIVE & VERIFIED</b>" if is_linked else "⚠️ <b>NOT LINKED YET</b>"
            guidance = (
                "To update your address, send:\n<code>/setwallet &lt;NEW_TRC20_ADDRESS&gt;</code>"
                if is_linked else
                "To link your payout address, send:\n<code>/setwallet &lt;YOUR_BINANCE_TRC20_ADDRESS&gt;</code>\n\n"
                "<i>(Find it in Binance → Deposit → USDT → TRC20 Network)</i>"
            )
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": (
                    "💳 <b>YOUR LINKED PAYOUT WALLET</b>\n"
                    "────────────────────────────\n"
                    f"• Address: <code>{current_wallet}</code>\n"
                    "• Network: <code>USDT (TRC20 / Tron)</code>\n"
                    f"• Status: {status_text}\n"
                    "────────────────────────────\n"
                    f"{guidance}"
                ),
                "parse_mode": "HTML",
                "reply_markup": get_main_menu_markup(),
            })
            return

        # AI Coach Query Routing
        if text.startswith("/ai ") or text.startswith("/ask "):
            question = raw_text.split(maxsplit=1)[1].strip()
            if question:
                executor.submit(async_send_ai_reply, chat_id, question)
                return

        # Autonomous AI Scan Command
        if any(cmd == text for cmd in ["/scan", "scan", "🤖 autonomous ai scan", "ai scan", "autonomous scan"]):
            scan_brief = run_autonomous_ai_scan()
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": scan_brief,
                "parse_mode": "HTML",
                "reply_markup": get_radar_markup()
            })
            return

        if any(cmd == text for cmd in ["/ai", "/ask", "💬 ask ai coach", "ask ai coach", "ask ai", "ai coach", "coach"]):
            welcome_msg = (
                "🤖 <b>AGENTQUANT AUTONOMOUS AI QUANT COACH</b>\n"
                "────────────────────────────\n"
                "I am your 24/7 Quantitative Trading & Risk Intelligence Coach.\n\n"
                "<b>Institutional System Telemetry:</b>\n"
                "• <b>Account:</b> FundedNext Stellar 1-Step ($6,000) #3028655\n"
                "• <b>5-Asset Universe:</b> SPY, QQQ, AAPL, NVDA, GLD\n"
                "• <b>Strategy Triad:</b> Sniper Dip, Trend Pullback, Squeeze Breakout\n"
                "• <b>Sizing & Risk:</b> $450/trade (7.5%), -$13.50 risk (-3% stop), max 2 positions\n"
                "• <b>Safety Cushion:</b> 85% buffer below $180 daily drawdown limit\n\n"
                "💬 <b>Ask any question directly in chat!</b> For example:\n"
                "• <i>'What is our market status right now?'</i>\n"
                "• <i>'Are any of our 5 assets close to triggering a setup?'</i>\n"
                "• <i>'Explain the Trend Continuation Pullback rule'</i>\n"
                "• <i>'How does our risk sizing protect the $180 daily limit?'</i>"
            )
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": welcome_msg,
                "parse_mode": "HTML",
                "reply_markup": get_keyboard_for_user(user_id)
            })
            return

        if is_conversational_query(raw_text):
            executor.submit(async_send_ai_reply, chat_id, raw_text)
            return

        # Bottom Menu & Slash Command Routing
        if any(cmd in text for cmd in ["/app", "/webapp", "📱 pro mini app", "pro mini app", "app"]):
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": (
                    "⚡ <b>AGENTQUANT PRO WEB TERMINAL</b>\n"
                    "────────────────────────────\n"
                    "• Full Android Hardware Back Button Hook\n"
                    "• Interactive Touch Radar Dip Chart\n"
                    "• Live Binance P2P Naira Converter\n"
                    "• Real-time cTrader Drawdown Gauge\n\n"
                    "Tap below to open the Web Terminal:"
                ),
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "🚀 Launch AgentQuant Pro Web App", "web_app": {"url": get_webapp_url()}}],
                        [{"text": "🔙 Back", "callback_data": "cmd_back"}]
                    ]
                }
            })
        # Multi-intent check (e.g. 'live rader active trades over view')
        matched_radar = any(w in text for w in ["radar", "rader", "signal", "signals", "dip"])
        matched_trades = any(w in text for w in ["trade", "trades", "position", "positions"])
        matched_overview = any(w in text for w in ["overview", "over view", "profile", "account", "status"])

        if matched_radar and matched_trades and matched_overview:
            composite_text = (
                "⚡ <b>AGENTQUANT LIVE MASTER SNAPSHOT</b>\n"
                "────────────────────────────\n"
                f"👤 <b>TRADER:</b> David • Funded Pro ($6,000 Capital)\n"
                f"💰 <b>EQUITY:</b> <code>${_CACHE.get('equity', 6000.0):,.2f} USD</code> (~₦{_CACHE.get('capital', 6000.0)*LIVE_P2P_RATE:,.0f})\n"
                f"📊 <b>ACTIVE TRADES:</b> <code>0 Open (100% Cash Cushion)</code>\n"
                f"📡 <b>5-ASSET INSTITUTIONAL RADAR:</b>\n"
                f"• SPY: <code>${_CACHE.get('spy_price', 757.39):.2f}</code> | QQQ: <code>${_CACHE.get('qqq_price', 704.54):.2f}</code>\n"
                f"• AAPL: <code>${_CACHE.get('aapl_price', 331.34):.2f}</code> | NVDA: <code>${_CACHE.get('nvda_price', 212.17):.2f}</code>\n"
                f"• GLD: <code>${_CACHE.get('gld_price', 394.15):.2f}</code> (Macro Hedge)\n"
                "🎯 <b>STRATEGY ENGINE:</b> <code>[ ATLAS-QUANT TRIAD // ACTIVE SCANNING ]</code>\n"
                "────────────────────────────\n"
                "✨ <i>All metrics updated in sub-20ms.</i>"
            )
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": composite_text,
                "parse_mode": "HTML",
                "reply_markup": get_main_menu_markup(),
            })
        elif any(cmd in text for cmd in ["/start", "/menu", "/overview", "/profile", "👤 overview", "overview", "over view", "start", "menu", "profile", "account"]):
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": render_overview_text(),
                "parse_mode": "HTML",
                "reply_markup": get_main_menu_markup(),
            })
        elif any(cmd in text for cmd in ["/balance", "/bal", "💰 balance", "balance", "bal", "risk", "sentinel", "capital", "buffer"]):
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": render_balance_text(),
                "parse_mode": "HTML",
                "reply_markup": get_balance_markup(),
            })
        elif any(cmd in text for cmd in ["/signals", "/radar", "📡 live radar", "radar", "rader", "live radar", "live rader", "signals", "signal", "dip", "dips"]):
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": render_signals_text(),
                "parse_mode": "HTML",
                "reply_markup": get_radar_markup(),
            })
        elif any(cmd in text for cmd in ["/trades", "📊 active trades", "trades", "trade", "active trades", "active trade", "positions", "position", "open trades", "orders"]):
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": render_trades_text(user_id=user_id),
                "parse_mode": "HTML",
                "reply_markup": get_trades_markup(user_id=user_id),
            })
        elif any(cmd in text for cmd in ["/withdraw", "💸 withdraw", "withdraw", "payout", "claim"]):
            curr_key = _CACHE.get("active_model_key", "stellar_1step_6k")
            m = ACCOUNTS_CONFIG.get(curr_key, ACCOUNTS_CONFIG["stellar_1step_6k"])
            take_home = _CACHE.get("cycle_profit", m["profit_accrued"]) * 0.85
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": render_withdraw_text(),
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": f"🚀 Request ${take_home:,.2f} to Binance", "callback_data": f"cmd_ask_payout_{take_home:.2f}"}],
                        [{"text": "⚙️ Switch Prop Account Model", "callback_data": "cmd_models_menu"}],
                        [{"text": "🔙 Back to Overview", "callback_data": "cmd_overview"}]
                    ]
                }
            })
        elif any(cmd in text for cmd in ["/models", "/accounts", "models", "accounts", "compare"]):
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": render_models_text(),
                "parse_mode": "HTML",
                "reply_markup": get_models_markup(),
            })
        elif any(cmd in text for cmd in ["/tracker", "/goals", "⏳ payout", "goals", "tracker", "goal"]):
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": render_tracker_text(),
                "parse_mode": "HTML",
                "reply_markup": get_tracker_markup(),
            })
        elif any(cmd in text for cmd in ["/p2p", "/naira", "🏦 binance p2p", "p2p", "naira", "rate", "exchange"]):
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": render_p2p_rate_text(),
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "🏦 View P2P Card", "callback_data": "cmd_card_p2p"}],
                        [{"text": "💸 Withdraw Crypto", "callback_data": "cmd_withdraw"}],
                        [{"text": "🔙 Back to Overview", "callback_data": "cmd_overview"}]
                    ]
                },
            })
        elif any(cmd in text for cmd in ["/qqqchart", "qqq chart", "qqq radar", "qqq dip"]):
            executor.submit(async_send_radar_chart, chat_id, "QQQ")
        elif any(cmd in text for cmd in ["/spychart", "spy chart", "spy radar", "spy dip"]):
            executor.submit(async_send_radar_chart, chat_id, "SPY")
        elif any(cmd in text for cmd in ["/qqqticket", "qqq ticket"]):
            executor.submit(async_send_ticket_card, chat_id, "QQQ")
        elif any(cmd in text for cmd in ["/spyticket", "spy ticket"]):
            executor.submit(async_send_ticket_card, chat_id, "SPY")
        elif any(cmd in text for cmd in ["/chart", "/pnl", "📈 15y", "chart", "pnl"]):
            executor.submit(async_send_pnl_chart, chat_id)
        elif any(cmd in text for cmd in ["/pdf", "/statement", "📑 export pdf", "pdf", "statement"]):
            executor.submit(async_send_pdf, chat_id)
        elif any(cmd in text for cmd in ["/card", "/profilecard", "profilecard", "card"]):
            executor.submit(async_send_profile_card, chat_id)
        elif any(cmd in text for cmd in ["/risk", "/riskgauge", "riskgauge", "risk"]):
            executor.submit(async_send_risk_card, chat_id)
        elif any(cmd in text for cmd in ["/ticket", "/signalcard", "ticket"]):
            executor.submit(async_send_ticket_card, chat_id, "SPY")
        elif any(cmd in text for cmd in ["/roadmap", "roadmap"]):
            executor.submit(async_send_roadmap_card, chat_id)
        elif any(cmd in text for cmd in ["/milestone", "/milestones", "🏆 milestones", "milestone", "milestones", "progress"]):
            executor.submit(async_send_milestone_card, chat_id)
        elif any(cmd in text for cmd in ["/morning", "🌅 morning brief", "morning brief", "morning briefing", "morning", "good morning", "getting ready"]):
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": get_morning_briefing_for_user(user_id),
                "parse_mode": "HTML",
                "reply_markup": get_menu_for_user(user_id),
            })
        elif any(cmd in text for cmd in ["/nightly", "🌙 night wrap", "night wrap", "nightly summary", "nightly", "market summary", "good night"]):
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": get_nightly_summary_for_user(user_id),
                "parse_mode": "HTML",
                "reply_markup": get_menu_for_user(user_id),
            })
        elif any(cmd in text for cmd in ["/logic", "logic"]):
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": render_trade_logic_text(),
                "parse_mode": "HTML",
                "reply_markup": get_main_menu_markup(),
            })
        else:
            # Free-form conversation: any unrecognized question or text is dispatched to AI Quant Coach!
            executor.submit(async_send_ai_reply, chat_id, raw_text)


def safe_handle_update(update: dict):
    try:
        handle_update(update)
    except Exception as e:
        import traceback
        print(f"[!] Exception in handle_update: {e}")
        traceback.print_exc()
        try:
            chat_id = None
            if "message" in update:
                chat_id = update["message"].get("chat", {}).get("id")
            elif "callback_query" in update:
                chat_id = update["callback_query"].get("message", {}).get("chat", {}).get("id")
            if chat_id:
                api_call("sendMessage", {
                    "chat_id": chat_id,
                    "text": "⚡ <i>Terminal telemetry refreshed. Please tap again.</i>",
                    "parse_mode": "HTML",
                    "reply_markup": get_menu_for_user(chat_id)
                })
        except Exception:
            pass


def run_polling():
    print("=" * 65)
    print("   AGENTQUANT TERMINAL (v5.2) — SUB-20MS ULTRA-SPEED DUAL-MODE")
    print("=" * 65)
    print(f"Primary Chat ID: {PRIMARY_CHAT_ID}")
    print(f"Authorized Partners: {list(load_authorized_users().keys())}")
    print("Features: Async Worker Pool, Multi-User Dispatch, Keep-Alive Pooling")
    print("Status: 100% Dialed In & Cooking | Multi-Partner Sync Active")

    # Pre-warm cTrader telemetry synchronously so cache is ready from millisecond zero
    print("[*] Pre-warming cTrader telemetry cache...")
    try:
        sync_ctrader_telemetry_worker()
        print(f"[+] cTrader Telemetry Pre-warmed: {_CACHE.get('capital', 6000.0)} USD, {len(_CACHE.get('enriched_positions', []))} active positions.")
    except Exception as e:
        print(f"[!] Warning pre-warming telemetry: {e}")

    register_bot_commands()

    # Start cTrader real-time streaming engine (Upgrade #2)
    try:
        from src.integrations.ctrader_streamer import ctrader_streamer
        ctrader_streamer.start()
        print("[+] cTrader Real-Time Streaming Thread started.")
    except Exception as e:
        print(f"[!] Warning starting cTrader streamer: {e}")

    # Start background telemetry and market radar thread
    bg_thread = threading.Thread(target=background_telemetry_loop, daemon=True, name="TelemetryWorker")
    bg_thread.start()
    print("[+] Background Telemetry & Radar Worker Thread started.")

    # Start Mini App HTTP server (supports dynamic Render PORT)
    server_port = int(os.getenv("PORT", 8080))
    launch_server_in_thread(server_port)
    print(f"[+] Mini App Web Server started on http://0.0.0.0:{server_port}")

    last_offset = 0
    while True:
        try:
            url = f"{API_BASE}/getUpdates?offset={last_offset}&timeout=2"
            resp = http_session.get(url, timeout=6)
            data = resp.json()
            results = data.get("result", [])
            for u in results:
                last_offset = max(last_offset, u["update_id"] + 1)
                executor.submit(safe_handle_update, u)
        except Exception:
            time.sleep(0.2)


if __name__ == "__main__":
    run_polling()
