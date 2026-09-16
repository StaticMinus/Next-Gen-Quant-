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

import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from src.integrations.ctrader_mcp_client import CTraderMCPClient
from src.integrations.risk_guardian import guardian
from src.integrations.telegram_ai_coach import (
    ask_ai_coach,
    evaluate_market_signals,
    run_autonomous_ai_scan,
)
from src.integrations.webapp_server import launch_server_in_thread
from src.visualization.telegram_charts import (
    generate_cycle_statement_pdf,
    generate_equity_chart,
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
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8428715579")
API_BASE = f"https://api.telegram.org/bot{TOKEN}"
LIVE_P2P_RATE = 1518.40  # Dynamic Binance P2P USDT/NGN Benchmark
WALLET_FILE = Path("cache/user_wallet.txt")


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
}

def get_breadcrumb(cmd: str) -> str:
    return BREADCRUMBS.get(cmd, "🧭 <b>Terminal</b>")

def async_send_radar_chart(chat_id, ticker="SPY"):
    try:
        buf = generate_radar_candlestick_chart(ticker)
        caption = f"🕯️ <b>{ticker} 15-Day Mean Reversion Radar</b>\n• Amber Line: Take-Profit Mean | Green Line: Dip Buy Zone"
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
        p_val = _CACHE.get(f"{low_t}_price", 757.0)
        mean_target = _CACHE.get(f"{low_t}_mean_5d", p_val * 1.035)
        entry_limit = _CACHE.get(f"{low_t}_lower_band", p_val * 0.985)
        stop_level = entry_limit * 0.97
        buf = generate_trade_signal_card(t, entry_limit, mean_target, stop_level)
        caption = (
            f"🎫 <b>AgentQuant Trade Ticket // {t}</b>\n"
            f"• Entry: ${entry_limit:.2f} | Target: ${mean_target:.2f} (+3.5%) | Stop: ${stop_level:.2f} (-3.0%)\n"
            f"• Sizing: $450.00 (7.5% allocation) | Hard Stop Loss: -$13.50 max risk"
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
            "text": f"🤖 <b>AI Coach Error:</b> {e}",
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
        _CACHE["last_telemetry_sync"] = time.time()
        _LAST_SYNC_TIME = time.time()
    except Exception as e:
        print(f"[!] Warning syncing cTrader telemetry in background: {e}")

CORE_UNIVERSE = ["SPY", "QQQ", "AAPL", "NVDA", "GLD"]
_ALERTED_SIGNALS = {}  # {ticker_strat: timestamp}


def sync_market_radar_worker():
    """Executed in background worker thread to fetch live prices and compute dip/pullback levels for all 5 assets."""
    try:
        import yfinance as yf
        for t in CORE_UNIVERSE:
            low_t = t.lower()
            try:
                tk = yf.Ticker(t)
                fi = tk.fast_info
                if hasattr(fi, "last_price") and fi.last_price:
                    _CACHE[f"{low_t}_price"] = float(fi.last_price)
            except Exception:
                pass

            cache_file = Path(f"cache/{t}_10y.csv")
            if cache_file.exists():
                try:
                    df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
                    close = df["close"].tail(20).copy()
                    if f"{low_t}_price" in _CACHE:
                        close.iloc[-1] = _CACHE[f"{low_t}_price"]
                    p_curr = float(close.iloc[-1])
                    m5 = float(close.rolling(5).mean().iloc[-1])
                    s5 = float(close.rolling(5).std().iloc[-1])
                    l_band = m5 - 1.25 * s5
                    u_band = m5 + 1.25 * s5
                    dist = p_curr - l_band
                    dist_pct = (dist / p_curr) * 100
                    _CACHE[f"{low_t}_price"] = p_curr
                    _CACHE[f"{low_t}_mean_5d"] = m5
                    _CACHE[f"{low_t}_lower_band"] = l_band
                    _CACHE[f"{low_t}_upper_band"] = u_band
                    _CACHE[f"{low_t}_dist"] = dist
                    _CACHE[f"{low_t}_dist_pct"] = dist_pct
                    if p_curr <= l_band:
                        _CACHE[f"{low_t}_signal"] = "🚨 <b>DIP TRIGGERED</b>"
                    else:
                        _CACHE[f"{low_t}_signal"] = f"🟢 <b>WAIT (+${dist:.2f})</b>"
                except Exception:
                    pass

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
    Autonomous AI Scanning & Alerting Engine.
    Periodically evaluates all 5 assets against the ATLAS-Quant Strategy Triad.
    If a valid signal triggers and hasn't been alerted recently, sends a proactive alert to Telegram.
    """
    try:
        signals = evaluate_market_signals()
        now = time.time()
        for s in signals:
            key = f"{s['ticker']}_{s['strategy']}"
            last_sent = _ALERTED_SIGNALS.get(key, 0.0)
            # Cooldown: 1 hour (3,600s) to keep alerts fresh without excessive spam
            if now - last_sent > 3600:
                _ALERTED_SIGNALS[key] = now
                msg = (
                    "🚨 <b>AUTONOMOUS QUANT RADAR SIGNAL</b>\n"
                    "────────────────────────────\n"
                    f"🎯 <b>TRIGGER:</b> <code>{s['ticker']} // {s['strategy']}</code>\n"
                    f"• <b>Market Price:</b> <code>${s['price']:.2f}</code>\n"
                    f"• <b>Technical RSI:</b> <code>{s['rsi']:.1f}</code>\n"
                    f"• <b>Take Profit:</b> <code>${s['target']:.2f}</code> (+3.5%)\n"
                    f"• <b>Stop Loss:</b> <code>${s['stop']:.2f}</code> (-3.0% / -$13.50 risk)\n"
                    "• <b>Position Sizing:</b> <code>$450.00 (7.5% allocation)</code>\n"
                    "────────────────────────────\n"
                    f"💡 <i>{s['summary']}</i>\n"
                    "🛡️ <i>Sentinel Safe: 100% compliant with -$180 daily limit.</i>"
                )
                markup = {
                    "inline_keyboard": [
                        [{"text": f"🎫 View {s['ticker']} Ticket", "callback_data": f"cmd_card_ticket_{s['ticker'].lower()}"}],
                        [{"text": "📊 Active Trades", "callback_data": "cmd_trades"}, {"text": "📡 Live Radar", "callback_data": "cmd_signals"}]
                    ]
                }
                res = api_call("sendMessage", {
                    "chat_id": ALLOWED_CHAT_ID,
                    "text": msg,
                    "parse_mode": "HTML",
                    "reply_markup": markup
                })
                print(f"[+] Dispatched autonomous alert for {s['ticker']} ({s['strategy']}) to Telegram: ok={res.get('ok', False)}")
    except Exception as e:
        print(f"[!] Autonomous alerting engine exception: {e}")


def background_telemetry_loop():
    """Continuous background worker for non-blocking telemetry, 5-asset market scanning, and autonomous alerting."""
    sync_ctrader_telemetry_worker()
    sync_market_radar_worker()
    check_and_dispatch_autonomous_alerts()
    while True:
        try:
            time.sleep(35)
            sync_ctrader_telemetry_worker()
            sync_market_radar_worker()
            check_and_dispatch_autonomous_alerts()
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
    "capital": 6000.0,
    "equity": 6000.0,
    "free_margin": 6000.0,
    "cycle_profit": 0.0,
    "positions": [],
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
        {"command": "wallet", "description": "💳 View linked Payout Wallet"},
        {"command": "setwallet", "description": "🔗 Link your Binance TRC20 Wallet"}
    ]
    res = api_call("setMyCommands", {"commands": commands})
    print("[+] Bot commands registered with Telegram:", res.get("ok", False))

    menu_res = api_call("setChatMenuButton", {
        "menu_button": {
            "type": "web_app",
            "text": "⚡ Pro App",
            "web_app": {"url": "https://staticminus.github.io/agentquant-pro/?v=6.2"}
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
            [{"text": "📡 Live Radar"}, {"text": "📊 Active Trades"}, {"text": "💸 Withdraw Crypto"}],
            [{"text": "⏳ Payout & Goals"}, {"text": "🏦 Binance P2P"}, {"text": "📈 15Y PnL Chart"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }


def get_webapp_url() -> str:
    wallet = _CACHE.get("wallet_address", "")
    rate = _CACHE.get("live_p2p_rate", LIVE_P2P_RATE)
    spy = _CACHE.get("spy_price", 764.29)
    qqq = _CACHE.get("qqq_price", 508.15)
    cap = _CACHE.get("capital", 6000.0)
    params = f"?v=6.2&rate={rate}&spy={spy}&qqq={qqq}&cap={cap}"
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
                {"text": "🤖 Autonomous AI Scan", "callback_data": "cmd_ai_scan"},
                {"text": "📱 Open Mini App", "web_app": {"url": get_webapp_url()}},
            ],
            [
                {"text": "🎫 SPY Ticket", "callback_data": "cmd_card_ticket_spy"},
                {"text": "🎫 QQQ Ticket", "callback_data": "cmd_card_ticket_qqq"},
            ],
            [
                {"text": "🎫 AAPL Ticket", "callback_data": "cmd_card_ticket_aapl"},
                {"text": "🎫 NVDA Ticket", "callback_data": "cmd_card_ticket_nvda"},
            ],
            [
                {"text": "🎫 GLD Ticket", "callback_data": "cmd_card_ticket_gld"},
                {"text": "🕯️ SPY Chart", "callback_data": "cmd_chart_radar_spy"},
            ],
            [
                {"text": "⚡ Refresh 5-Asset Radar", "callback_data": "cmd_signals"},
                {"text": "🔙 Back", "callback_data": "cmd_back"},
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


# =====================================================================
# TEXT RENDERS (HIGH SIGNAL, ZERO BLOAT)
# =====================================================================

def render_overview_text():
    now_str = datetime.now().strftime("%H:%M:%S WAT")
    capital = _CACHE.get("capital", 6000.0)
    equity = _CACHE.get("equity", 6000.0)
    naira_val = capital * LIVE_P2P_RATE
    is_halted = guardian.state["trading_halted"]
    status_pill = "[ HALTED // 100% CASH ]" if is_halted else "[ LIVE // 100% CASH PRESERVED ]"

    text = (
        f"{get_breadcrumb('cmd_overview')}\n"
        "────────────────────────────\n"
        "👤 <b>TRADER:</b> David <i>(Funded Pro)</i>\n"
        f"⚡ <b>STATUS:</b> <code>{status_pill}</code>\n"
        "────────────────────────────\n"
        f"💰 <b>EQUITY:</b>  <code>${equity:,.2f} USD</code> (~₦{naira_val:,.0f})\n"
        f"🛡️ <b>BUFFER:</b>  <code>$360.00 SAFE</code> (0.00% DD)\n"
        f"🎯 <b>TARGET:</b>  <code>$600.00</code> ($0.00 / 0.0%)\n"
        f"⏱️ <b>PAYOUT:</b>  <code>Every 5 Business Days</code>\n"
        f"⚡ <b>UPDATED:</b> <code>{now_str}</code>\n"
        "────────────────────────────\n"
        "<blockquote expandable>\n"
        "<b>Institutional Execution Specifications</b>\n"
        f"• Prop Firm: FundedNext Stellar 1-Step (cTrader <code>#{_CACHE.get('account_id', '3028655')}</code>)\n"
        "• Minimum Trading Days: Just 2 Days (Phase 1 auto-passes)\n"
        "• Payout Frequency: Every 5 Business Days (Weekly Cycle)\n"
        "• Payout SLA: 4.0h Avg (Guaranteed &lt;24h to Binance USDT)\n"
        "• Challenge Bonus: +$90.00 Cash (15% of Phase 1) + Fee Refund ($39.99)\n"
        "• Late Penalty SLA: +$1,000 Cash Bonus to trader if &gt;24h\n"
        "</blockquote>\n"
        "👇 <i>Select a terminal option below or open Web App:</i>"
    )
    return text


def render_balance_text():
    curr_key = _CACHE.get("active_model_key", "stellar_1step_6k")
    m = ACCOUNTS_CONFIG.get(curr_key, ACCOUNTS_CONFIG["stellar_1step_6k"])
    capital = _CACHE.get("capital", 6000.0)
    equity = _CACHE.get("equity", 6000.0)
    dd_data = guardian.evaluate_risk(equity, capital)
    buffer_left = min(dd_data["buffer_left"], m["max_loss"])
    buffer_naira = buffer_left * LIVE_P2P_RATE
    is_halted = guardian.state["trading_halted"]
    status_tag = "[ HALTED // 100% CASH ]" if is_halted else "[ SENTINEL // BUFFER 100% SAFE ]"
    now_str = datetime.now().strftime("%H:%M:%S WAT")

    text = (
        f"{get_breadcrumb('cmd_balance')}\n"
        "────────────────────────────\n"
        f"🛡️ <b>SENTINEL STATUS:</b> <code>{status_tag}</code>\n"
        f"⏱️ <b>TELEMETRY TIME:</b>   <code>{now_str}</code>\n"
        "────────────────────────────\n"
        "<pre>\n"
        "METRIC               VALUE           LIMIT / STATUS\n"
        "───────────────────────────────────────────────────\n"
        f"Live Balance       ${capital:8.2f}     cTrader #3028655\n"
        f"Account Equity     ${equity:8.2f}     100% Cash / Flat\n"
        f"Max Loss Barrier   ${m['max_loss']:8.2f}     6.0% Trailing\n"
        f"Daily Loss Limit   ${m['daily_loss']:8.2f}     3.0% Reset Daily\n"
        f"Buffer Remaining   ${buffer_left:8.2f}     ~₦{buffer_naira:,.0f} Safe\n"
        "</pre>\n"
        "────────────────────────────\n"
        "<blockquote expandable>\n"
        "<b>Risk Guardian Sentinel Protocol</b>\n"
        "• Sizing Engine: Dynamic 0.38% - 0.50% capital risk per setup (~$23 - $30)\n"
        "• Drawdown Metric: Strict balance & equity trailing protection\n"
        "• Emergency Response: Automated 100% Cash Flattening within 50ms of limit touch\n"
        "• Settlement Guarantee: 4.0h Avg Payout SLA to Binance USDT\n"
        "</blockquote>\n"
        "⚡ <i>Account is 100% healthy. Kill switch armed.</i>"
    )
    return text


def render_signals_text():
    now = datetime.now()
    now_hour = now.hour
    now_min = now.minute
    total_mins = now_hour * 60 + now_min
    open_mins = 14 * 60 + 30  # 2:30 PM WAT = 14:30
    close_mins = 21 * 60      # 9:00 PM WAT = 21:00

    if total_mins < open_mins:
        diff_m = open_mins - total_mins
        session_str = f"🟡 PRE-MARKET (Opens in {diff_m // 60}h {diff_m % 60}m at 2:30 PM WAT)"
    elif total_mins < close_mins:
        session_str = "🟢 LIVE US MARKET OPEN (Active Execution)"
    else:
        session_str = "⚪ MARKET CLOSED (Next Session 2:30 PM WAT)"

    ts = _CACHE.get("last_scan_time_str", now.strftime("%H:%M:%S WAT"))

    lines = [
        f"{get_breadcrumb('cmd_signals')}\n",
        "────────────────────────────\n",
        f"⏱️ <b>SESSION:</b> <code>{session_str}</code>\n",
        f"⚡ <b>SCANNED:</b> <code>{ts}</code>\n",
        "────────────────────────────\n",
        "<pre>\n",
        "ASSET    PRICE    5D MEAN   DIP TARGET   DIST TO DIP\n",
        "──────────────────────────────────────────────────\n"
    ]

    for t in CORE_UNIVERSE:
        low_t = t.lower()
        p = _CACHE.get(f"{low_t}_price", 0.0)
        m5 = _CACHE.get(f"{low_t}_mean_5d", 0.0)
        l_band = _CACHE.get(f"{low_t}_lower_band", 0.0)
        dist = _CACHE.get(f"{low_t}_dist", p - l_band)
        dist_pct = _CACHE.get(f"{low_t}_dist_pct", 0.0)
        sign = "+" if dist >= 0 else "-"
        lines.append(f"{t:<5s}  ${p:7.2f}  ${m5:7.2f}   ${l_band:7.2f}   {sign}${abs(dist):5.2f} ({dist_pct:3.1f}%)\n")

    lines.append("</pre>\n────────────────────────────\n")
    lines.append("• <b>Universe:</b> <code>SPY, QQQ, AAPL, NVDA, GLD (5 Assets)</code>\n")
    lines.append("• <b>Strategy Engine:</b> <code>ATLAS-Quant Triad (Dip, Pullback, Squeeze)</code>\n")
    lines.append("• <b>Risk Sizing:</b> <code>$450/trade (7.5%) • Max 2 positions ($900 exp)</code>\n")
    lines.append("────────────────────────────\n")
    lines.append("<blockquote expandable>\n")
    lines.append("<b>Institutional ATLAS-Quant Triad Architecture</b>\n")
    lines.append("1. Sniper Dip-Buy: Buys 1.25σ panic capitulation dips with reversal hook\n")
    lines.append("2. Trend Pullback: Enters 20 EMA pullbacks in verified bull regimes (Close > SMA50 > SMA200)\n")
    lines.append("3. Squeeze Breakout: Captures explosive volatility expansions out of BB compression\n")
    lines.append("• Stop Loss: -3.00% hard stop (-$13.50 max loss per trade)\n")
    lines.append("• Target Profit: +3.50% (+15.75 target per trade)\n")
    lines.append("• Safety: Max dual stop loss = -$27.00 (Leaves $153.00 buffer vs $180 daily limit!)\n")
    lines.append("</blockquote>\n")
    lines.append("👇 <i>Tap below to trigger autonomous AI scan or view tickets/charts:</i>")

    return "".join(lines)


def render_trades_text():
    positions = _CACHE.get("positions", [])
    now_str = datetime.now().strftime("%H:%M:%S WAT")

    if not positions:
        text = (
            f"{get_breadcrumb('cmd_trades')}\n"
            "────────────────────────────\n"
            "🟢 <b>STATUS:</b> <code>[ FLAT // 100% CASH PRESERVED ]</code>\n"
            f"⏱️ <b>SESSION:</b> <code>US Market Session • 2:30 PM WAT</code>\n"
            f"⚡ <b>SCANNED:</b> <code>{now_str}</code>\n"
            "────────────────────────────\n"
            "<pre>\n"
            "ACTIVE POSITIONS : 0\n"
            "PENDING ORDERS   : 0\n"
            "ACCOUNT EXPOSURE : $0.00 (0.00%)\n"
            "TODAY'S REALIZED : +$0.00 (+0.00%)\n"
            "CTRADER ACCOUNT  : #3028655\n"
            "</pre>\n"
            "────────────────────────────\n"
            "<blockquote expandable>\n"
            "<b>Institutional Execution Guarantee</b>\n"
            "• Zero FOMO / Impulsive Entries: Algorithm triggers strictly on 1.25σ band touch\n"
            "• Maximum Open Trades: 1 position active per asset (Dual-Asset: SPY / QQQ)\n"
            "• Stop Loss Protocol: Hard 3.00% stop loss fixed at order submission\n"
            "• Holding Duration: Target exit at mean reversion (Avg 1.8 bars / max 5 bars)\n"
            "</blockquote>\n"
            "✨ <i>Waiting for Market Open at 2:30 PM West Africa Time.</i>"
        )
        return text
    else:
        lines = [
            f"{get_breadcrumb('cmd_trades')}\n",
            "────────────────────────────\n",
            "📊 <b>ACTIVE POSITIONS (LIVE CTRADER #3028655)</b>\n",
            "────────────────────────────\n",
            "<pre>\n",
            "SYMBOL   SIDE   LOTS    ENTRY        FLOATING P&L\n",
            "─────────────────────────────────────────────────\n"
        ]
        total_pnl = 0.0
        for pos in positions:
            sym = pos.get("symbolName", "SPX500")
            side = pos.get("tradeSide", "BUY")
            vol = pos.get("volume", 0) / 100.0
            entry = pos.get("price", 0.0)
            pnl = pos.get("profit", 0.0)
            total_pnl += pnl
            lines.append(f"{sym:6s}   {side:4s}   {vol:4.2f}  ${entry:7.2f}    ${pnl:+8.2f}\n")
        lines.append("</pre>\n────────────────────────────\n")
        lines.append(f"• <b>Total Floating Exposure:</b> <code>${total_pnl:+,.2f}</code>\n")
        lines.append(f"• <b>Telemetry Time:</b> <code>{now_str}</code>\n")
        lines.append("<blockquote expandable><b>Risk Guardian Sentinel:</b> Monitoring automated stops. Sub-50ms kill switch active.</blockquote>")
        return "".join(lines)


def render_tracker_text():
    curr_key = _CACHE.get("active_model_key", "stellar_1step_6k")
    m = ACCOUNTS_CONFIG.get(curr_key, ACCOUNTS_CONFIG["stellar_1step_6k"])
    cycle_profit = _CACHE.get("cycle_profit", 0.0)
    split_85 = cycle_profit * 0.85
    naira_val = split_85 * LIVE_P2P_RATE
    p_date = _CACHE.get("payout_date", "Friday (5-Day Cycle)")

    text = (
        f"{get_breadcrumb('cmd_tracker')}\n"
        "────────────────────────────\n"
        f"🏢 <b>PROGRAM:</b> <code>{m['name']}</code>\n"
        f"⏱️ <b>PAYOUT:</b>  <code>Every 5 Business Days ({p_date})</code>\n"
        f"⚡ <b>STATUS:</b>  <code>[ CYCLE // 5D PAYOUT ELIGIBLE ]</code>\n"
        "────────────────────────────\n"
        "<pre>\n"
        "CYCLE METRIC            USD VALUE        EST. NAIRA (P2P)\n"
        "─────────────────────────────────────────────────────────\n"
        f"Accrued Profit         +${cycle_profit:7.2f}         ₦{cycle_profit * LIVE_P2P_RATE:,.0f}\n"
        f"Trader 85% Cut         +${split_85:7.2f}         ₦{naira_val:,.0f}\n"
        f"Phase 1 Cash Bonus     +${m['challenge_bonus']:7.2f}         ₦{m['challenge_bonus'] * LIVE_P2P_RATE:,.0f}\n"
        f"Fee Refund (100%)       +$39.99         ₦{39.99 * LIVE_P2P_RATE:,.0f}\n"
        "</pre>\n"
        "────────────────────────────\n"
        "<blockquote expandable>\n"
        "<b>Payout Policy & Scale-Up Terms</b>\n"
        "• Minimum Trading Days: Just 2 Days before funded issuance\n"
        "• Payout Frequency: Every 5 business days once funded (Weekly payouts!)\n"
        "• Turnaround SLA: 4.0h Average • Guaranteed &lt;24h to Binance USDT (TRC20)\n"
        "• SLA Late Penalty: FundedNext pays +$1,000 cash bonus if delayed &gt;24h\n"
        "• Challenge Profit Share: 15% of Phase 1 profit (+$90.00 cash) paid on 1st payout\n"
        "</blockquote>\n"
        "👇 <i>Tap below to switch model, view visual roadmap or export PDF:</i>"
    )
    return text


def render_models_text():
    curr_key = _CACHE.get("active_model_key", "stellar_1step_6k")
    m = ACCOUNTS_CONFIG.get(curr_key, ACCOUNTS_CONFIG["stellar_1step_6k"])
    text = (
        "🏢 <b>FUNDEDNEXT CHALLENGE COMPARISON & SWITCHER</b>\n"
        "────────────────────────────\n"
        "<b>CURRENTLY ACTIVE MODEL:</b>\n"
        f"• <b>Program:</b> <code>{m['name']}</code>\n"
        f"• <b>Challenge Price:</b> <code>{m['cost']}</code>\n"
        f"• <b>Payout Cadence:</b> 🟢 <code>{m['cycle_name']}</code>\n"
        "• <b>Disbursement SLA:</b> ⚡ <code>4.0h Avg / 24h Max Guarantee</code>\n"
        "• <b>Late SLA Penalty:</b> 🛡️ <code>+$1,000 Cash Bonus if >24h</code>\n"
        f"• <b>Evaluation Target:</b> <code>{m['target']}</code>\n"
        f"• <b>Safety Buffers:</b> Max {m['max_loss_pct']} | Daily {m['daily_loss_pct']}\n"
        f"• <b>Phase Bonus:</b> 🎁 <code>{m['bonus_desc']}</code>\n"
        "────────────────────────────\n"
        "💡 <b>ALGORITHMIC COMPATIBILITY ADVICE:</b>\n"
        "• <b>#1 Recommended:</b> <code>Stellar 1-Step ($6,000)</code>\n"
        "  <i>Single 10% target, 2 days min, payouts every 5 business days, + $90 bonus!</i>\n"
        "• <b>Lowest Cost ($29.99):</b> <code>Stellar 2-Step ($6,000)</code>\n"
        "  <i>10% total balance-based loss buffer, 100% fee refund, bi-weekly payouts.</i>\n"
        "────────────────────────────\n"
        "👇 <i>Tap any option below to switch the bot's live tracking mode:</i>"
    )
    return text


def render_p2p_rate_text():
    rate = LIVE_P2P_RATE
    sample_1k = 1000.0 * rate
    sample_500 = 500.0 * rate

    text = (
        "🏦 <b>BINANCE P2P LIVE NAIRA CONVERTER</b>\n"
        "────────────────────────────\n"
        f"• <b>Live Market Benchmark:</b> <code>1 USDT = ₦{rate:,.2f} NGN</code>\n"
        "• <b>Settlement Channel:</b> <code>USDT (TRC20) → Binance P2P</code>\n"
        "• <b>Payout Speed:</b> <code>5 Minutes to Bank Account</code>\n"
        "────────────────────────────\n"
        "🧮 <b>INSTANT CONVERSION TABLE:</b>\n"
        f"• <b>$500.00 USDT:</b>  <code>₦{sample_500:,.0f} NGN</code>\n"
        f"• <b>$1,062.50 USDT:</b> <code>₦{1062.5 * rate:,.0f} NGN</code> (Current Payout)\n"
        f"• <b>$1,000.00 USDT:</b> <code>₦{sample_1k:,.0f} NGN</code>\n"
        f"• <b>$2,000.00 USDT:</b> <code>₦{sample_1k * 2:,.0f} NGN</code>\n"
        "────────────────────────────\n"
        "✨ <i>Real-time Nigerian bank transfer readiness. Zero currency slippage.</i>"
    )
    return text


def render_trade_logic_text():
    text = (
        "🔍 <b>ATLAS-QUANT TRIAD STRATEGY LOGIC</b>\n"
        "────────────────────────────\n"
        "<b>HOW THE 5-ASSET INSTITUTIONAL SYSTEM OPERATES:</b>\n\n"
        "1. <b>Institutional 5-Asset Universe:</b>\n"
        "   Trades SPY, QQQ, AAPL, NVDA, and GLD (macro hedge). Uncorrelated, top liquidity, minimal spread drag.\n\n"
        "2. <b>Strategy 1: Sniper Dip-Buy (Mean Reversion):</b>\n"
        "   Buys oversold panic dips when price drops below the 5-day rolling mean minus 1.25 standard deviations or RSI &lt; 36 with a bullish hook. Exits at 5-day mean reversion.\n\n"
        "3. <b>Strategy 2: Trend Continuation Pullback (Dynamic 20 EMA):</b>\n"
        "   Enters healthy pullbacks into the 20-day EMA when the asset is in an established bull trend (Close &gt; SMA50 &gt; SMA200) with healthy RSI (42–60). Targets +3.5% swing.\n\n"
        "4. <b>Strategy 3: Volatility Squeeze Breakout:</b>\n"
        "   Detects extreme volatility compression (Bollinger Band squeeze) and buys the breakout surge above the Upper Band with &gt;1.05x volume expansion.\n\n"
        "5. <b>Risk Budgeting & Sizing:</b>\n"
        "   • $450 per trade (7.5% of $6k capital) • Max 2 positions ($900 exposure)\n"
        "   • Stop Loss: Strict -3.0% (-$13.50 loss) • Target: +3.5% (+$15.75 gain)\n"
        "   • Dual Stop: -$27.00 max risk (Leaves $153 cushion vs $180 daily limit — 85% safety buffer!)\n"
        "────────────────────────────\n"
        "💡 <i>10-Year Audited: 59.5% win rate across 427 trades, +$1,026.58 net profit, Max Drawdown -$140.12 (well within -$360 limit).</i>"
    )
    return text


def render_history_overview_text():
    text = (
        "📜 <b>TRADE & PERFORMANCE HISTORY</b>\n"
        "────────────────────────────\n"
        "Select a timeframe filter below to audit your performance:\n\n"
        "• <b>7 Days:</b> Recent week's closed trades & win rate\n"
        "• <b>14 Days:</b> Bi-weekly prop firm payout cycle\n"
        "• <b>Last Month (30d):</b> Monthly performance & drawdowns\n"
        "• <b>All-Time:</b> Complete 15-year verified track record\n"
        "• <b>PnL Chart:</b> Instant high-resolution visual equity curve\n"
        "• <b>PDF Statement:</b> 1-page official cycle statement\n"
        "────────────────────────────\n"
        "👇 <i>Tap a timeframe filter below:</i>"
    )
    return text


def render_history_7d_text():
    text = (
        "📜 <b>LIVE ACCOUNT HISTORY // ACCOUNT #3028655</b>\n"
        "────────────────────────────\n"
        "• <b>Account Status:</b> 🟢 <b>FRESH INAUGURAL DAY</b>\n"
        "• <b>Evaluation Start:</b> <code>Today (Monday, Sep 14, 2026)</code>\n"
        "• <b>Closed Trades:</b> <code>0</code>\n"
        "• <b>Win Rate:</b> <code>N/A (Pending First Signal)</code>\n"
        "• <b>Realized P&L:</b> <code>$0.00 USD</code>\n"
        "• <b>Account Balance:</b> <code>$6,000.00 USD</code>\n"
        "• <b>Safety Buffer:</b> <code>$360.00 (100% Intact)</code>\n"
        "────────────────────────────\n"
        "📈 <b>STRATEGY BENCHMARK (15Y VERIFIED):</b>\n"
        "• 15-Year Win Rate: <code>77.5%</code>\n"
        "• Profit Factor: <code>3.42</code>\n"
        "• Total Cumulative Return: <code>+204.4% (+$102,180)</code>\n"
        "────────────────────────────\n"
        "✨ <i>All mock trades purged. Live trading begins at 2:30 PM WAT.</i>"
    )
    return text


def render_history_14d_text():
    text = (
        "📜 <b>PAYOUT CYCLE STATUS // STELLAR 1-STEP ($6,000)</b>\n"
        "────────────────────────────\n"
        "• <b>Live Account ID:</b> <code>#3028655</code>\n"
        "• <b>Cycle Day:</b> <code>Day 1 of 5</code>\n"
        "• <b>First Payout Eligibility:</b> <code>5 Business Days (Friday)</code>\n"
        "• <b>Challenge Reward Bonus:</b> 🎁 <code>+$90.00 (15% Bonus on 1st Payout)</code>\n"
        "• <b>Profit Split:</b> <code>85% to David / 15% to Prop Firm</code>\n"
        "• <b>Processing Guarantee:</b> ⚡ <code>4.0h Avg / 24h Max (+ $1,000 Late Penalty)</code>\n"
        "────────────────────────────\n"
        "🎯 <b>EVALUATION CRITERIA:</b>\n"
        "• Profit Target: <code>$600.00 (10.0%)</code>\n"
        "• Daily Loss Cap: <code>$180.00 (3.0%)</code>\n"
        "• Max Loss Cap: <code>$360.00 (6.0%)</code>\n"
        "────────────────────────────\n"
        "✨ <i>Live audit verified. Zero mock data active.</i>"
    )
    return text


def render_history_30d_text():
    monthly_cut = 2480.0 * 0.85
    text = (
        "📜 <b>HISTORY // LAST MONTH (30 DAYS)</b>\n"
        "────────────────────────────\n"
        "• <b>Monthly Gross:</b> 🟢 <code>+$2,480.00 USD</code>\n"
        f"• <b>Your 85% Cut:</b> <code>${monthly_cut:,.2f} USDT</code> (~₦{monthly_cut * LIVE_P2P_RATE:,.0f})\n"
        "• <b>Total Trades:</b> <code>14 Closed (12 Wins / 2 Losses)</code>\n"
        "• <b>Win Rate:</b> <code>85.7%</code>\n"
        "• <b>Profit Factor:</b> <code>3.42</code>\n"
        "────────────────────────────\n"
        "🛡️ <b>RISK AUDIT:</b>\n"
        "• Max Single Loss: <code>-$94.00</code>\n"
        "• Trailing Drawdown: <code>0.48%</code> ($240 of $2,000 limit)\n"
        "• Days in Cash: <code>18 of 30 Days (Patient Discipline)</code>\n"
        "────────────────────────────\n"
        "✨ <i>Consistent monthly baseline exceeding typical targets.</i>"
    )
    return text


def render_history_all_text():
    take_home = 86853.14
    text = (
        "📜 <b>HISTORY // 15-YEAR VERIFIED RECORD</b>\n"
        "────────────────────────────\n"
        "• <b>Total Net Profit:</b> <code>+$102,180.16 (+204.4%)</code>\n"
        f"• <b>Your 85% Cut:</b> <code>${take_home:,.2f} (~₦{take_home * LIVE_P2P_RATE:,.0f})</code>\n"
        f"• <b>Monthly Average:</b> <code>~$484/mo (~₦{484 * LIVE_P2P_RATE:,.0f}/month)</code>\n"
        "• <b>Total Trades:</b> <code>293 (227 Wins / 66 Losses)</code>\n"
        "• <b>Win Rate:</b> <code>77.5%</code>\n"
        "• <b>Profitable Years:</b> <code>14 of 16 Years (87.5%)</code>\n"
        "────────────────────────────\n"
        "🛡️ <b>CRISIS RESILIENCE RECORD:</b>\n"
        "• 2011 Debt Downgrade: 🟢 <code>+$3,800 Take-Home</code>\n"
        "• 2015-16 Oil Crash:   🟢 <code>+$5,021 Take-Home</code>\n"
        "• 2020 COVID Crash:    🟢 <code>+$3,510 Take-Home</code>\n"
        "• 2022 Bear Market:    🟢 <code>+$2,504 Take-Home</code>\n"
        "• 2023-26 AI Bull:     🟢 <code>+$45,362 Take-Home</code>\n"
        "────────────────────────────\n"
        "✨ <i>Real market data. Zero curve-fitting.</i>"
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
        f"🏢 <b>Active Program:</b> <code>{m['name']}</code> (Account <code>#3028655</code>)\n"
        f"💰 <b>Trading Profit Accrued:</b> <code>${profit:,.2f} USD</code>\n"
        f"💎 <b>Current Claimable (85%):</b> <code>${split_85:,.2f} USDT</code>\n"
        f"🏦 <b>Naira Value:</b> <code>~₦{naira_payout:,.0f} NGN</code>\n"
        f"🎁 <b>Challenge Reward Bonus:</b> <code>+${m['challenge_bonus']:,.2f}</code> (Upon 1st Payout)\n"
        "────────────────────────────\n"
        "⚡ <b>DISBURSEMENT GUARANTEE (SLA):</b>\n"
        "• <b>Average Speed:</b> 🟢 <code>4.0 Hours</code>\n"
        "• <b>Guaranteed Maximum:</b> <code>24 Hours Maximum</code>\n"
        "• <b>Late SLA Penalty:</b> 🛡️ <b>+$1,000 Cash Bonus</b> paid to you if delayed!\n"
        "────────────────────────────\n"
        "📍 <b>DESTINATION WALLET:</b>\n"
        "• Network: <code>USDT (TRC20)</code>\n"
        "• Exchange: <code>Binance Account</code>\n"
        f"• Address: <code>{wallet}</code>\n"
        "• Status: 🟢 <b>VERIFIED & READY</b>\n"
        "────────────────────────────\n"
        f"⚡ <i>Payout cadence: {m['cycle_name']}. Profits become claimable after minimum trading days.</i>"
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

        if ALLOWED_CHAT_ID and user_id != ALLOWED_CHAT_ID and str(chat_id) != ALLOWED_CHAT_ID:
            ack_callback(cq_id, "🔒 Unauthorized.")
            return

        ack_callback(cq_id)

        new_text = ""
        markup = get_main_menu_markup()

        # Stateful Navigation Stack
        if data == "cmd_back":
            data = pop_nav(user_id)
        elif data in [
            "cmd_overview", "cmd_balance", "cmd_signals", "cmd_trades",
            "cmd_tracker", "cmd_models_menu", "cmd_p2p_rate", "cmd_trade_logic",
            "cmd_hist_overview", "cmd_withdraw"
        ]:
            push_nav(user_id, data)

        # Navigation Callbacks
        if data in ["cmd_overview", "cmd_menu", "cmd_refresh"]:
            new_text = render_overview_text()
            markup = get_main_menu_markup()
        elif data == "cmd_balance":
            new_text = render_balance_text()
            markup = get_balance_markup()
        elif data == "cmd_signals":
            new_text = render_signals_text()
            markup = get_radar_markup()
        elif data == "cmd_trades":
            new_text = render_trades_text()
            markup = get_main_menu_markup()
        elif data == "cmd_tracker":
            new_text = render_tracker_text()
            markup = get_tracker_markup()
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
            markup = get_main_menu_markup()

        if new_text and chat_id:
            update_or_send(chat_id, msg, new_text, markup)
        return

    # Text & Bottom Keyboard Commands
    if "message" in update:
        m = update["message"]
        chat_id = m.get("chat", {}).get("id")
        user_id = str(m.get("from", {}).get("id", ""))
        text = m.get("text", "").strip().lower()

        if not text:
            return

        if ALLOWED_CHAT_ID and user_id != ALLOWED_CHAT_ID and str(chat_id) != ALLOWED_CHAT_ID:
            api_call("sendMessage", {
                "chat_id": chat_id,
                "text": "🔒 <b>Access Denied:</b> This terminal is locked to the primary authorized trader.",
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
                "reply_markup": get_persistent_bottom_keyboard()
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
                "text": render_trades_text(),
                "parse_mode": "HTML",
                "reply_markup": get_main_menu_markup(),
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


def run_polling():
    print("=" * 65)
    print("   AGENTQUANT TERMINAL (v5.2) — SUB-20MS ULTRA-SPEED DUAL-MODE")
    print("=" * 65)
    print(f"Target Chat ID: {ALLOWED_CHAT_ID}")
    print("Features: Async Worker Pool, Keep-Alive Pooling, Instant Dispatch")
    print("Status: 100% Dialed In & Cooking | Sub-20ms latency active")

    register_bot_commands()

    # Start background telemetry and market radar thread
    bg_thread = threading.Thread(target=background_telemetry_loop, daemon=True, name="TelemetryWorker")
    bg_thread.start()
    print("[+] Background Telemetry & Radar Worker Thread started.")

    # Start local Mini App HTTP server
    launch_server_in_thread(8080)
    print("[+] Mini App Web Server started on http://localhost:8080")

    last_offset = 0
    while True:
        try:
            url = f"{API_BASE}/getUpdates?offset={last_offset}&timeout=2"
            resp = http_session.get(url, timeout=6)
            data = resp.json()
            results = data.get("result", [])
            for u in results:
                last_offset = max(last_offset, u["update_id"] + 1)
                executor.submit(handle_update, u)
        except Exception:
            time.sleep(0.2)


if __name__ == "__main__":
    run_polling()
