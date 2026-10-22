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

import copy
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
    # === PURE INTRADAY & SESSION SCALPING FLEET (Resolves within active session • Invariant 28) ===
    {"id": "ssfgold", "name": "SureShotFX Gold", "enabled": True, "assets": ["XAUUSD"], "tier": 1, "yield_pct": 25.0, "peak_session": "London Pre-Market"},
    {"id": "anabelsignals", "name": "Anabel Signals", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 63.2, "peak_session": "New York/London"},
    {"id": "DailyForexSignals", "name": "Daily Forex Signals", "enabled": True, "assets": ["XAUUSD", "ALL"], "tier": 1, "yield_pct": 35.7, "peak_session": "London Open"},
    {"id": "XAUUSDSignalsFree", "name": "XAUUSD Signals Free", "enabled": True, "assets": ["XAUUSD"], "tier": 1, "yield_pct": 57.1, "peak_session": "New York"},
    {"id": "ForexEliteSignals", "name": "Forex Elite Signals", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 45.0, "peak_session": "London Open"},
    {"id": "PrimeForexSignals", "name": "Prime Forex Signals", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 37.8, "peak_session": "London Open"},
    {"id": "xauusd_signals", "name": "Gold Signals VIP", "enabled": True, "assets": ["XAUUSD"], "tier": 1, "yield_pct": 35.1, "peak_session": "New York/London"},
    {"id": "elitetrading_signals", "name": "Elite Trading Signals", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 35.0, "peak_session": "London Open"},
    {"id": "FreeForexSignals24", "name": "Free Forex Signals 24", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 75.0, "peak_session": "London Open"},
    {"id": "gold_forex_signals", "name": "Gold & Forex Signals", "enabled": True, "assets": ["XAUUSD", "ALL"], "tier": 1, "yield_pct": 75.0, "peak_session": "London/NY"},
    {"id": "CryptoBullSignals", "name": "Crypto Bull Signals", "enabled": True, "assets": ["BTCUSD", "ETHUSD", "ALL"], "tier": 1, "yield_pct": 70.0, "peak_session": "24/7 Asian/NY"},
    {"id": "top_tradingsignals", "name": "TopTradingSignals", "enabled": True, "assets": ["ALL"], "tier": 2, "yield_pct": 15.4, "peak_session": "London/Asian"},
    {"id": "pipchasers", "name": "PipChasers", "enabled": True, "assets": ["ALL"], "tier": 2, "yield_pct": 15.0, "peak_session": "Asian/London"},
    {"id": "prosignalsfxx", "name": "ProSignalsFx", "enabled": True, "assets": ["ALL"], "tier": 2, "yield_pct": 11.1, "peak_session": "London/NY"},
    {"id": "BestForexSignalsFree", "name": "Best Forex Signals", "enabled": True, "assets": ["ALL"], "tier": 2, "yield_pct": 66.7, "peak_session": "New York"},
    {"id": "US30_Forex_Signals", "name": "US30 Index Signals", "enabled": True, "assets": ["US30", "NAS100"], "tier": 2, "yield_pct": 20.0, "peak_session": "New York Open"},
    {"id": "ICT_Forex_Signals", "name": "ICT Forex Signals", "enabled": True, "assets": ["ALL"], "tier": 2, "yield_pct": 15.4, "peak_session": "New York Killzone"},
    {"id": "signalsproviderfx", "name": "Signals Provider FX", "enabled": True, "assets": ["ALL"], "tier": 2, "yield_pct": 76.5, "peak_session": "London/Tokyo"},
    {"id": "forexgdpfree", "name": "Forex GDP Free Signals", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 84.0, "peak_session": "London/NY"},
    # === CATEGORY A: SNIPER ENTRY SPECIALISTS (Order Blocks, SMC, Tight SL) ===
    {"id": "elite_pips_hunter", "name": "Elite Pips Hunter", "enabled": True, "assets": ["XAUUSD"], "tier": 1, "yield_pct": 75.0, "peak_session": "London Open"},
    {"id": "fxscalpingpro", "name": "FX Scalping Pro", "enabled": True, "assets": ["XAUUSD"], "tier": 1, "yield_pct": 90.0, "peak_session": "London/NY"},
    {"id": "royal_pips_fx", "name": "Royal Pips FX", "enabled": True, "assets": ["XAUUSD"], "tier": 1, "yield_pct": 78.9, "peak_session": "London Pre-Market"},
    {"id": "price_action_traders", "name": "Price Action Traders", "enabled": True, "assets": ["EURUSD", "GBPUSD", "XAUUSD"], "tier": 1, "yield_pct": 35.0, "peak_session": "London Open"},
    {"id": "smart_pips_signals", "name": "Smart Pips Signals", "enabled": True, "assets": ["XAUUSD"], "tier": 1, "yield_pct": 40.0, "peak_session": "New York Open"},
    {"id": "purepipsofficial", "name": "Pure Pips Official", "enabled": True, "assets": ["XAUUSD"], "tier": 1, "yield_pct": 40.0, "peak_session": "London/NY"},
    {"id": "alphatradesfx", "name": "Alpha Trades FX", "enabled": True, "assets": ["XAUUSD"], "tier": 1, "yield_pct": 41.2, "peak_session": "New York Open"},
    # === CATEGORY B: MULTI-DAY SWING TRADERS (Forex GDP Style, 60-150+ Pip Targets) ===
    {"id": "oanda", "name": "Oanda Swings", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 100.0, "peak_session": "London/Tokyo"},
    {"id": "DailyForexPipsFree", "name": "Daily Forex Pips Free", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 90.0, "peak_session": "London/NY"},
    {"id": "UniversalForexSignals", "name": "Universal Forex Signals", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 75.0, "peak_session": "London Open"},
    {"id": "vipfx1", "name": "VIP FX Crosses", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 75.0, "peak_session": "London/Tokyo"},
    {"id": "ultreos_forex", "name": "Ultreos Forex", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 65.0, "peak_session": "London Open"},
    {"id": "ForexPipsFactory", "name": "Forex Pips Factory", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 42.5, "peak_session": "London/NY"},
    {"id": "purefxvip", "name": "Pure FX VIP", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 55.0, "peak_session": "London Open"},
    # === CATEGORY C: MACRO & CPI VOLATILITY SPECIALISTS (US CPI, NFP, Indices) ===
    {"id": "dow_jones_signals", "name": "Dow Jones Signals", "enabled": True, "assets": ["US30", "NAS100", "XAUUSD"], "tier": 1, "yield_pct": 45.0, "peak_session": "New York Open"},
    {"id": "protrades1", "name": "Pro Trades Macro", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 70.0, "peak_session": "New York/London"},
    {"id": "fx_signals", "name": "FX Signals Macro", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 65.0, "peak_session": "London/NY"},
    {"id": "wallstreet_pips", "name": "Wall Street Pips", "enabled": True, "assets": ["NAS100", "US30", "XAUUSD", "ALL"], "tier": 1, "yield_pct": 42.1, "peak_session": "New York Open"},
    {"id": "FXTradingSignalsFree", "name": "FX Trading Signals Free", "enabled": True, "assets": ["ALL"], "tier": 1, "yield_pct": 38.9, "peak_session": "London Open"},
    {"id": "UniversalCryptoSignals", "name": "Universal Crypto Macro", "enabled": True, "assets": ["BTCUSD", "ETHUSD", "XAUUSD"], "tier": 1, "yield_pct": 30.0, "peak_session": "24/7 Asian/NY"}
]


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}


class MultiChannelSignalParser:
    """Universal signal signature extractor across all target Telegram channels."""

    @classmethod
    def clean_text(cls, raw: str) -> str:
        # Standardize HTML entities
        t = (raw.replace("&#33;", "!")
                .replace("&#036;", "$")
                .replace("&amp;", "&")
                .replace("&#39;", "'")
                .replace("&#092;", "/")
                .replace("&nbsp;", " "))
        # Strip commas in formatted numbers e.g. 4,172.50 -> 4172.50
        t = re.sub(r'(\d+),(\d+)', r'\1\2', t)
        # Fix numbers split across newlines by channel admins (e.g. "41\n38" -> "4138")
        t = re.sub(r'(\b\d{2})\s*\n\s*(\d{2}\b)', r'\1\2', t)
        # Expand shorthand ranges (e.g. "4150-60" -> "4150-4160")
        t = re.sub(r'(\b\d{2})(\d{2})\s*-\s*(\d{2}\b)', r'\1\2-\1\3', t)
        # Normalize en-dash and em-dash to regular hyphen
        t = t.replace("–", "-").replace("—", "-")
        # Clean unicode emojis and directional arrows
        t = re.sub(r'[➡️👉►▶️|]', ' ', t)
        t = re.sub(r'[🎯🚫✅🔘🚀✔️🟢🔴🔷♦️⭐️🥇📊📈📉💐🍀👑✍️⭕💡🔥🔗📞📍🛑📡😊❤️🌸👍]', ' ', t)
        # Strip trailing dot after letters e.g. "GOLD." -> "GOLD "
        t = re.sub(r'([A-Za-z]+)\.', r'\1 ', t)
        return t

    @classmethod
    def normalize_symbol(cls, raw_sym: str) -> str:
        s = raw_sym.upper().replace("/", "").replace("#", "").replace("-", "").strip()
        if s in ["GOLD", "XAU"]:
            return "XAUUSD"
        if s in ["CRUDEOIL", "OIL", "USOIL", "WTI"]:
            return "USOIL"
        if s in ["BTC", "BITCOIN"]:
            return "BTCUSD"
        if s in ["ETH", "ETHEREUM"]:
            return "ETHUSD"
        if s in ["US30", "DJ30", "DOW", "DOWJONES"]:
            return "US30"
        if s in ["NAS100", "USTEC", "NASDAQ", "NDX"]:
            return "NAS100"
        if s in ["SPX500", "SP500", "SPX"]:
            return "SPX500"
        return s

    @classmethod
    def get_default_sl_distance(cls, symbol: str, entry: float, tps: Optional[List[float]] = None) -> float:
        """
        Invariant 20: Stop-Loss Synthesis Guard.
        Calculates a safe default Stop Loss distance if the provider omitted SL.
        Uses 1:1 R:R of TP1 if reasonable, else standardized asset risk parameters.
        """
        sym = symbol.upper()
        if "XAU" in sym or "GOLD" in sym:
            def_dist = 8.0  # 80 pips Gold
            max_dist = 12.0
        elif "BTC" in sym:
            def_dist = 400.0
            max_dist = 600.0
        elif "ETH" in sym:
            def_dist = 25.0
            max_dist = 40.0
        elif "US30" in sym or "DJ30" in sym:
            def_dist = 60.0  # 60 points US30
            max_dist = 120.0
        elif "NAS" in sym or "USTEC" in sym:
            def_dist = 30.0  # 30 points NAS100
            max_dist = 60.0
        elif "OIL" in sym:
            def_dist = 1.0
            max_dist = 1.5
        elif "JPY" in sym:
            def_dist = 0.40  # 40 pips JPY
            max_dist = 0.60
        else:
            # Forex Major / Cross (e.g. EURUSD, EURCAD, GBPUSD)
            def_dist = 0.0035  # 35 pips FX
            max_dist = 0.0050

        # If a valid TP is provided, synthesize SL to maintain a favorable 1:1 risk-to-reward
        if tps and len(tps) > 0 and tps[0] is not None:
            tp_dist = abs(tps[0] - entry)
            if 0 < tp_dist <= max_dist:
                return round(tp_dist, 5)

        return round(def_dist, 5)

    @classmethod
    def validate_directional_coherence(cls, sig: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Directional Target Coherence Invariant:
        Ensures Take Profit targets and Stop Losses are mathematically valid for the order side.
        - BUY: TP must be > entry, SL must be < entry
        - SELL: TP must be < entry, SL must be > entry
        - Invariant 20: If Stop Loss was omitted or paywalled, automatically synthesize safety SL.
        """
        side = sig.get("side", "").upper()
        entry = sig.get("entry_mid", 0.0)
        tps = sig.get("tps", [])
        sl = sig.get("sl")

        if not side or entry <= 0:
            return False, "Missing side or entry price"

        # Invariant 20: Auto-synthesize Stop Loss if missing or paywalled
        if sl is None or sig.get("sl_paywalled"):
            sl_dist = cls.get_default_sl_distance(sig.get("symbol", "XAUUSD"), entry, tps)
            sl = round(entry - sl_dist if side == "BUY" else entry + sl_dist, 5)
            sig["sl"] = sl
            sig["sl_synthesized"] = True
            sig["sl_paywalled"] = False

        if side == "BUY":
            if sl is not None and sl >= entry:
                return False, f"Inverted Stop Loss: BUY SL ({sl}) >= Entry ({entry})"
            valid_tps = [tp for tp in tps if tp > entry]
            if not valid_tps and tps:
                return False, f"Inverted Take Profit: BUY all TPs <= Entry ({entry})"
            if len(valid_tps) < len(tps):
                logger.info(f"🎯 Invariant 23 (Smart TP Promotion): Filtered at-entry/inverted TP targets. Original: {tps} -> Active: {valid_tps} (Promoting TP2/TP3)")
                sig["tps"] = valid_tps
                sig["tp1_promoted_from_runner"] = True
        elif side == "SELL":
            if sl is not None and sl <= entry:
                return False, f"Inverted Stop Loss: SELL SL ({sl}) <= Entry ({entry})"
            valid_tps = [tp for tp in tps if tp < entry]
            if not valid_tps and tps:
                return False, f"Inverted Take Profit: SELL all TPs >= Entry ({entry})"
            if len(valid_tps) < len(tps):
                logger.info(f"🎯 Invariant 23 (Smart TP Promotion): Filtered at-entry/inverted TP targets. Original: {tps} -> Active: {valid_tps} (Promoting TP2/TP3)")
                sig["tps"] = valid_tps
                sig["tp1_promoted_from_runner"] = True

        return True, None

    @classmethod
    def _should_attempt_ai_fallback(cls, text: str) -> bool:
        if os.getenv("AI_SIGNAL_EXTRACTION_ENABLED", "").lower() != "true":
            return False
        if not os.getenv("OPENROUTER_API_KEY"):
            return False
        has_dir = bool(re.search(r"\b(BUY|SELL|LONG|SHORT)\b", text, re.IGNORECASE))
        has_asset = bool(re.search(r"\b(XAU|GOLD|EUR|GBP|USD|JPY|AUD|CAD|NZD|CHF|OIL|BTC)\b", text, re.IGNORECASE))
        is_spam = any(w in text.lower() for w in ["tournament", "bonus", "deposit", "affiliate", "weekend brief"])
        return has_dir and has_asset and not is_spam

    @classmethod
    def _ai_extract_signal(cls, text: str, channel: str) -> Optional[Dict[str, Any]]:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            return None
        model = os.getenv("OPENROUTER_MODEL", "nex-agi/nex-n2.5-mini")
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://agentquant.internal",
            "X-Title": "AgentQuant Parser"
        }
        prompt = (
            "Extract trading signal parameters from the text. Respond ONLY with valid JSON or null.\n"
            "Format: {\"symbol\": \"XAUUSD\", \"side\": \"BUY\"|\"SELL\", \"entry_mid\": float, \"sl\": float|null, \"tps\": [float]}\n"
            f"Text:\n{text[:600]}"
        )
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 150
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=3.5)
            if r.status_code == 200:
                data = r.json()
                content = data["choices"][0]["message"]["content"].strip()
                m_json = re.search(r"\{[\s\S]*\}", content)
                if m_json:
                    parsed = json.loads(m_json.group(0))
                    if parsed and "symbol" in parsed and "side" in parsed and "entry_mid" in parsed:
                        sym = cls.normalize_symbol(parsed["symbol"])
                        side = parsed["side"].upper()
                        entry = float(parsed["entry_mid"])
                        sl = float(parsed["sl"]) if parsed.get("sl") is not None else (entry - 10 if side == "BUY" else entry + 10)
                        raw_tps = parsed.get("tps") or []
                        tps = [float(x) for x in raw_tps if isinstance(x, (int, float))]
                        return {
                            "channel": channel,
                            "symbol": sym,
                            "side": side,
                            "entry_min": entry,
                            "entry_max": entry,
                            "entry_mid": entry,
                            "sl": sl,
                            "tps": tps,
                            "type": "AI_FALLBACK"
                        }
        except Exception as e:
            logger.debug(f"AI extraction fallback error: {e}")
        return None

    @classmethod
    def parse_message(cls, text: str, channel: str) -> Optional[Dict[str, Any]]:
        from src.integrations.pattern_memory import PatternMemory
        # Preflight sub-millisecond normalization from learned channel quirks
        normalized_text = PatternMemory.apply_preflight_normalization(text, channel)

        sig = cls._raw_parse_message(normalized_text, channel)
        if not sig and cls._should_attempt_ai_fallback(text):
            try:
                from src.integrations.ai_signal_interpreter import AISignalInterpreter
                sig = AISignalInterpreter.interpret_signal(text, channel)
            except Exception as e:
                logger.debug(f"AISignalInterpreter fallback exception: {e}")
            if not sig:
                sig = cls._ai_extract_signal(text, channel)

        if not sig:
            return None

        # Check if channel is known to use TP1 as entry anchor
        if PatternMemory.should_promote_tp1(channel):
            sig["force_tp1_promotion"] = True

        valid, err = cls.validate_directional_coherence(sig)
        sig["is_valid"] = valid
        sig["validation_error"] = err
        return sig

    @classmethod
    def _raw_parse_message(cls, text: str, channel: str) -> Optional[Dict[str, Any]]:
        text_clean = cls.clean_text(text)
        text_lower = text_clean.lower()

        # Hard filters: locked teasers, tournament spam, recaps
        if any(w in text_lower for w in ["locked", "tournament", "weekend market brief", "week ahead", "bonus"]):
            return None
        if "to get full trade management" in text_lower and not ("sl:" in text_lower or "tp:" in text_lower or "stop loss" in text_lower):
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
            if "GOLD" in raw_sym:
                raw_sym = "XAUUSD"
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
        if channel == "anabelsignals" or "✍️" in text_clean or "anabel" in text_lower:
            m_ana_header = re.search(r"✍️\s*#?([A-Z0-9]+)\b.*?\b(BUY|SELL)", text_clean, re.IGNORECASE)
            if not m_ana_header:
                m_ana_header = re.search(r"#([A-Z0-9]{3,7})\b.*?\b(BUY|SELL)", text_clean, re.IGNORECASE)
            if not m_ana_header:
                m_ana_header = re.search(r"\b([A-Z0-9]{3,7})\b.*?\b(BUY|SELL)", text_clean, re.IGNORECASE)
            m_ana_sl = re.search(r"(?:Stop\s*Loss|My\s*Stop\s*Loss|Recommended\s*Stop\s*Loss|Safe\s*Stop\s*Loss)\s*[:=\-]?\s*(\d+(?:\.\d+)?)", text_clean, re.IGNORECASE)
            m_ana_target = re.search(r"(?:Target|Goal)\s*[:=\-]?\s*(\d+(?:\.\d+)?)", text_clean, re.IGNORECASE)
            m_ana_level = re.search(r"(?:tests|level|trading on|around).*?(\d+(?:\.\d+)?)", text_clean, re.IGNORECASE)

            if m_ana_header and (m_ana_sl or (m_ana_level and m_ana_target)):
                raw_sym = m_ana_header.group(1).upper()
                if "GOLD" in raw_sym:
                    raw_sym = "XAUUSD"
                side = m_ana_header.group(2).upper()
                entry = float(m_ana_level.group(1)) if m_ana_level else None
                tp = float(m_ana_target.group(1)) if m_ana_target else None

                if m_ana_sl:
                    sl = float(m_ana_sl.group(1))
                    if not entry:
                        entry = sl + 10.0 if side == "SELL" else sl - 10.0
                else:
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

        # --- UNIVERSAL EXPANDED MULTI-CHANNEL PARSER ---
        # Detect direction/side
        side = None
        m_action = re.search(r"\b(BUY\s+NOW|SELL\s+NOW|BUY\s+STOP|SELL\s+STOP|BUY\s+LIMIT|SELL\s+LIMIT|BUY|SELL|LONG|SHORT)\b", text_clean, re.IGNORECASE)
        if m_action:
            act = m_action.group(1).upper()
            side = "BUY" if "BUY" in act or "LONG" in act else "SELL"

        # Detect symbol using known asset and currency combinations
        sym_match = re.search(
            r"(?:#|\b)((?:EUR|GBP|USD|AUD|NZD|CAD|CHF|JPY|XAU|BTC){2}|XAUUSD|GOLD|USOIL|CRUDE\s*OIL|BTCUSD|BTC|ETHUSD|ETH|US30|DJ30|DOW|NAS100|USTEC|NASDAQ|SPX500|SP500|(?:EUR|GBP|USD|AUD|NZD|CAD|CHF|JPY)[/_\-\s](?:EUR|GBP|USD|AUD|NZD|CAD|CHF|JPY))\b",
            text_clean, re.IGNORECASE
        )
        detected_sym = "XAUUSD"
        if sym_match:
            cand = sym_match.group(1).replace(" ", "").replace("-", "").replace("/", "").replace("_", "")
            detected_sym = cls.normalize_symbol(cand)

        # Standardized parameter tags
        m_entry_tag = re.search(r"(?:Entry(?:\s*Level)?|CURRENT\s*PRICE|Precio(?:\s*de\s*referencia)?|Precio|BUY\s*AREA|SELL\s*AREA)\s*[:=\-@]?\s*[\$]?(\d+(?:\.\d+)?)", text_clean, re.IGNORECASE)
        m_sl_tag = re.search(r"(?:Stop\s*Loss|Stoploss|SL|Safe\s*Stop\s*Loss|Recommended\s*Stop\s*Loss)\s*[:=\-]?\s*[\(\[]?\s*[\$]?(\d+(?:\.\d+)?)", text_clean, re.IGNORECASE)
        m_tp_tag = re.findall(r"(?:\b(?:Take\s*Profit|Target(?:\s*Level)?|TP|Goal)(?:\s*[1-9¹²³⁴])?\b|\bTP[1-9]\b)[\s:=-–—]*[\(\[]?\s*[\$]?(\d+(?:\.\d+)?)", text_clean, re.IGNORECASE)

        # 5. TAG STRUCTURED FORMAT (EliteTradingSignals, ProSignalsFx, xauusd_signals, TopTradingSignals, BestForexSignals)
        if m_entry_tag and side:
            entry = float(m_entry_tag.group(1))
            tps = [float(x) for x in m_tp_tag]
            if m_sl_tag:
                sl = float(m_sl_tag.group(1))
            else:
                sl_dist = cls.get_default_sl_distance(detected_sym, entry, tps)
                sl = round(entry - sl_dist if side == "BUY" else entry + sl_dist, 5)
            return {
                "channel": channel,
                "symbol": detected_sym,
                "side": side,
                "entry_min": entry,
                "entry_max": entry,
                "entry_mid": entry,
                "sl": sl,
                "tps": tps,
                "type": "TAG_STRUCTURED"
            }

        # 6. ACTION-LINKED ZONE RANGE FORMAT (e.g. "XAUUSD BUY 4162-4158", "BUY (4130-4135)")
        m_action_zone = re.search(
            r"(?:(?:#|\b)[A-Z0-9]{3,7}\b\s+)?\b(BUY|SELL)(?:\s+(?:NOW|LIMIT|STOP))?\s+(?:(?:#|\b)[A-Z0-9]{3,7}\b\s+)?(?:AT|@)?\s*[\(@]?\s*(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)\)?",
            text_clean, re.IGNORECASE
        )
        if m_action_zone and side:
            e1, e2 = float(m_action_zone.group(2)), float(m_action_zone.group(3))
            entry_mid = (e1 + e2) / 2.0
            tps = [float(x) for x in m_tp_tag]
            if m_sl_tag:
                sl = float(m_sl_tag.group(1))
            else:
                sl_dist = cls.get_default_sl_distance(detected_sym, entry_mid, tps)
                sl = round(entry_mid - sl_dist if side == "BUY" else entry_mid + sl_dist, 5)
            return {
                "channel": channel,
                "symbol": detected_sym,
                "side": side,
                "entry_min": min(e1, e2),
                "entry_max": max(e1, e2),
                "entry_mid": entry_mid,
                "sl": sl,
                "tps": tps,
                "type": "ZONE_EXECUTION"
            }

        # 7. DIRECT ACTION ENTRY FORMAT (e.g. "#XAUUSD BUY 4133", "BUY GOLD 4133", "BUY 4133", "SELL NOW 4150")
        m_action_direct = re.search(
            r"(?:(?:#|\b)[A-Z0-9]{3,7}\b\s+)?\b(BUY|SELL)(?:\s+(?:NOW|LIMIT|STOP))?\s+(?:(?:#|\b)[A-Z0-9]{3,7}\b\s+)?(?:AT|@)?\s*(\d+(?:\.\d+)?)",
            text_clean, re.IGNORECASE
        )
        if m_action_direct and side:
            entry = float(m_action_direct.group(2))
            tps = [float(x) for x in m_tp_tag]
            if m_sl_tag:
                sl = float(m_sl_tag.group(1))
            else:
                sl_dist = cls.get_default_sl_distance(detected_sym, entry, tps)
                sl = round(entry - sl_dist if side == "BUY" else entry + sl_dist, 5)
            return {
                "channel": channel,
                "symbol": detected_sym,
                "side": side,
                "entry_min": entry,
                "entry_max": entry,
                "entry_mid": entry,
                "sl": sl,
                "tps": tps,
                "type": "DIRECT_AT"
            }

        # 8. GENERAL ZONE RANGE FORMAT (Filtered: Excludes ranges on TP / TAKE PROFIT / TARGET / SL / STOP LOSS lines)
        non_tp_sl_lines = [
            line for line in text_clean.splitlines()
            if not re.search(r"\b(TP\d?|TAKE\s*PROFIT|TARGET|SL\b|STOP\s*LOSS|STOPLOSS)\b|[¹²³]\s*/\s*TAKE", line, re.IGNORECASE)
        ]
        non_tp_sl_text = "\n".join(non_tp_sl_lines)
        m_zone = re.search(r"(?:between\s+(\d+(?:\.\d+)?)\s+till\s+(\d+(?:\.\d+)?)|[\(@]?\s*(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)\)?)", non_tp_sl_text, re.IGNORECASE)
        if m_zone and side:
            if m_zone.group(1) and m_zone.group(2):
                e1, e2 = float(m_zone.group(1)), float(m_zone.group(2))
            else:
                e1, e2 = float(m_zone.group(3)), float(m_zone.group(4))
            entry_mid = (e1 + e2) / 2.0
            tps = [float(x) for x in m_tp_tag]
            if m_sl_tag:
                sl = float(m_sl_tag.group(1))
            else:
                sl_dist = cls.get_default_sl_distance(detected_sym, entry_mid, tps)
                sl = round(entry_mid - sl_dist if side == "BUY" else entry_mid + sl_dist, 5)
            return {
                "channel": channel,
                "symbol": detected_sym,
                "side": side,
                "entry_min": min(e1, e2),
                "entry_max": max(e1, e2),
                "entry_mid": entry_mid,
                "sl": sl,
                "tps": tps,
                "type": "ZONE_EXECUTION"
            }

        # 9. AT / DIRECT EXECUTION (ForexEliteSignals, ForexPipsFactory, PrimeForexSignals, GoldEliteTrading, Ultreos, GoldSignalsOfficial)
        m_at_price = re.search(r"(?:@|AT)\s*[\$]?(\d+(?:\.\d+)?)", text_clean, re.IGNORECASE)
        if m_at_price and side:
            entry = float(m_at_price.group(1))
            tps = [float(x) for x in m_tp_tag]
            if m_sl_tag:
                sl = float(m_sl_tag.group(1))
            else:
                sl_dist = cls.get_default_sl_distance(detected_sym, entry, tps)
                sl = round(entry - sl_dist if side == "BUY" else entry + sl_dist, 5)
            return {
                "channel": channel,
                "symbol": detected_sym,
                "side": side,
                "entry_min": entry,
                "entry_max": entry,
                "entry_mid": entry,
                "sl": sl,
                "tps": tps,
                "type": "DIRECT_AT"
            }

        m_direct = re.search(
            r"(?:(BUY|SELL)(?:\s+(?:LIMIT|STOP|NOW))?\s+)?(?:([A-Z]{6}|XAUUSD|GOLD|BTCUSD|USOIL)\s+)?(?:(BUY|SELL)(?:\s+(?:LIMIT|STOP|NOW))?\s+)?\s*(\d+(?:\.\d+)?)",
            text_clean, re.IGNORECASE
        )
        if m_direct and side:
            entry = float(m_direct.group(4))
            tps = [float(x) for x in m_tp_tag]
            if m_sl_tag:
                sl = float(m_sl_tag.group(1))
            else:
                sl_dist = cls.get_default_sl_distance(detected_sym, entry, tps)
                sl = round(entry - sl_dist if side == "BUY" else entry + sl_dist, 5)
            return {
                "channel": channel,
                "symbol": detected_sym,
                "side": side,
                "entry_min": entry,
                "entry_max": entry,
                "entry_mid": entry,
                "sl": sl,
                "tps": tps,
                "type": "DIRECT_AT"
            }

        # 8. NATURAL LANGUAGE FORMAT (PipChasers)
        m_nat = re.search(r"(?:current\s*price(?:\s*at)?|trading\s*on|around|level)\s*[:=\-@]?\s*(\d+(?:\.\d+)?)", text_clean, re.IGNORECASE)
        if m_nat and side:
            entry = float(m_nat.group(1))
            tps = [float(x) for x in m_tp_tag]
            if m_sl_tag:
                sl = float(m_sl_tag.group(1))
            else:
                sl_dist = cls.get_default_sl_distance(detected_sym, entry, tps)
                sl = round(entry - sl_dist if side == "BUY" else entry + sl_dist, 5)
            return {
                "channel": channel,
                "symbol": detected_sym,
                "side": side,
                "entry_min": entry,
                "entry_max": entry,
                "entry_mid": entry,
                "sl": sl,
                "tps": tps,
                "type": "NATURAL_LANGUAGE"
            }

        # 9. COMPACT SHORTHAND FORMAT (forexsignalsdaily, ImperialForexSignals, GreenForexSignals)
        m_short = re.search(r"\b(BUY|SELL)\s+(\d+(?:\.\d+)?)", text_clean, re.IGNORECASE)
        if m_short:
            entry = float(m_short.group(2))
            tps = [float(x) for x in m_tp_tag]
            if m_sl_tag:
                sl = float(m_sl_tag.group(1))
            else:
                sl_dist = cls.get_default_sl_distance(detected_sym, entry, tps)
                sl = round(entry - sl_dist if side == "BUY" else entry + sl_dist, 5)
            return {
                "channel": channel,
                "symbol": detected_sym,
                "side": m_short.group(1).upper(),
                "entry_min": entry,
                "entry_max": entry,
                "entry_mid": entry,
                "sl": sl,
                "tps": tps,
                "type": "SHORTHAND_DIRECT"
            }

        # 10. LEGACY DIRECT FORMAT: "BUY GOLD 4280 SL 4270 TP 4288"
        m_legacy = re.search(r"(BUY|SELL)(?:\s+(?:NOW|MORE|GOLD|XAUUSD|AT|@))*[\s:\-@]*(\d{4}(?:\.\d+)?)", text_clean, re.IGNORECASE)
        if m_legacy:
            side = m_legacy.group(1).upper()
            entry = float(m_legacy.group(2))
            has_vip_sl = bool(re.search(r"(?:STOP\s*LOSS|SL)[\s:\-@]*VIP", text_clean, re.IGNORECASE))
            m_sl = re.search(r"(?:STOP\s*LOSS|SL)[\s:\-@]*(\d{4}(?:\.\d+)?)", text_clean, re.IGNORECASE)
            sl = float(m_sl.group(1)) if m_sl else (entry - 10 if side == "BUY" else entry + 10)
            tp_matches = re.findall(r"(?:TAKE\s*PROFIT|TP)(?:\s*[123¹²³]|\s*\d(?!\d))?[\s:\-@]*(\d{4}(?:\.\d+)?)", text_clean, re.IGNORECASE)
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
                "type": "LEGACY_DIRECT",
                "sl_paywalled": has_vip_sl
            }

        return None


class TelegramMultiSignalCopier:
    def __init__(self, dry_run: bool = False, ctrader_client: Optional[CTraderMCPClient] = None, state_file: Optional[Path] = None, max_concurrent_positions: Optional[int] = None):
        self.dry_run = dry_run
        self.ctrader = ctrader_client if ctrader_client is not None else CTraderMCPClient()
        self.max_concurrent_positions = max_concurrent_positions if max_concurrent_positions is not None else int(os.getenv("MAX_CONCURRENT_POSITIONS", "6"))
        if state_file is not None:
            self.state_file = state_file
            self.state = self.load_state()
        elif "PYTEST_CURRENT_TEST" in os.environ:
            self.state_file = ROOT_DIR / "cache" / "multi_signal_copier_dry_run_state.json"
            self.state = {
                "watermarks": {},
                "executed_signal_keys": [],
                "active_positions": []
            }
        elif dry_run:
            self.state_file = ROOT_DIR / "cache" / "multi_signal_copier_dry_run_state.json"
            self.state = self.load_state()
        else:
            self.state_file = STATE_FILE
            self.state = self.load_state()
        self.guard = RestrictedActionsGuard(max_volume=0.20, max_sl_points=10.0, floor_equity=5650.0)


        # Persistent HTTP connection pool for sub-second Telegram harvesting
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=30, pool_maxsize=30, max_retries=1)
        self.session.mount("https://", adapter)
        self.session.headers.update(HEADERS)
        self._last_channel_poll = {}

        # Cold-start watermark initialization per channel (concurrent, only in live mode)
        watermarks = self.state.setdefault("watermarks", {})
        if not self.dry_run and "PYTEST_CURRENT_TEST" not in os.environ:
            from concurrent.futures import ThreadPoolExecutor
            def init_wm(ch):
                ch_id = ch["id"]
                if not watermarks.get(ch_id):
                    try:
                        msgs = self.fetch_channel_posts(ch_id)
                        if msgs:
                            watermarks[ch_id] = msgs[-1]["post_id"]
                            logger.info(f"🛡️ Cold-start [{ch_id}]: Watermark set to {watermarks[ch_id]}")
                    except Exception as e:
                        logger.warning(f"Could not set watermark for {ch_id}: {e}")
            with ThreadPoolExecutor(max_workers=10) as executor:
                list(executor.map(init_wm, CHANNELS_CONFIG))
        self.save_state()

    def load_state(self) -> dict:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load state, creating fresh: {e}")
        return {
            "watermarks": {},
            "executed_signal_keys": [],
            "active_positions": []
        }

    def save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
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
            self.session.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to dispatch Telegram alert: {e}")

    def fetch_channel_posts(self, channel_id: str) -> List[Dict[str, Any]]:
        url = f"https://t.me/s/{channel_id}"
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                return []
            pattern = r'data-post="([^"]+)"[\s\S]*?<div class="tgme_widget_message_text[^>]*>([\s\S]*?)</div>'
            matches = re.findall(pattern, resp.text)
            messages = []
            for pid, raw_html in matches:
                clean_text = re.sub(r'<br\s*/?>', '\n', raw_html)
                clean_text = re.sub(r'<[^>]+>', '', clean_text).strip()
                if clean_text:
                    post_url = f"https://t.me/{pid}"
                    messages.append({"post_id": pid, "post_url": post_url, "text": clean_text})
            return messages
        except Exception as e:
            logger.error(f"Error fetching channel {channel_id}: {e}")
            return []

    def get_asset_parameters(self, symbol: str) -> Dict[str, Any]:
        sym = symbol.upper()
        if "XAU" in sym or "GOLD" in sym:
            configured_lot = float(os.getenv("GOLD_COPIER_LOT_SIZE", "0.07"))
            gold_lot = max(0.07, configured_lot)  # Immutable Invariant 25: 0.07 lot floor per ticket (0.14 total)
            return {
                "lot_size": gold_lot,
                "min_sl_distance": 1.50,           # 1.50 pts Gold noise floor (15 pips)
                "max_sl_distance": 5.0,           # 5.0 pts Gold tolerance ($35 max risk per ticket)
                "max_slippage": 2.50,
                "be_buffer": 0.30,
                "scalp_tp1_dist": 2.00,           # 20 pips micro-banker for scalps
                "scalp_be_activation": 1.00,      # Lock BE at +10 pips gain (Invariant 27)
                "trailing_distance": 3.00,       # 30 pips / 3.0 pts Gold
                "trailing_activation": 4.00,     # Activate trailing once +4.0 pts in profit
                "pip_multiplier": 1.0
            }
        elif "JPY" in sym:
            return {
                "lot_size": max(0.07, float(os.getenv("FOREX_COPIER_LOT_SIZE", "0.07"))),
                "min_sl_distance": 0.08,          # 8 pips noise floor (0.080)
                "max_sl_distance": 0.60,
                "max_slippage": 0.15,
                "be_buffer": 0.02,
                "scalp_tp1_dist": 0.20,           # 20 pips
                "scalp_be_activation": 0.15,      # 15 pips
                "trailing_distance": 0.30,       # 30 pips
                "trailing_activation": 0.40,     # Activate trailing once +40 pips in profit
                "pip_multiplier": 100.0
            }
        elif "BTC" in sym:
            return {
                "lot_size": float(os.getenv("CRYPTO_COPIER_LOT_SIZE", "0.01")),
                "min_sl_distance": 50.0,
                "max_sl_distance": 500.0,
                "max_slippage": 50.0,
                "be_buffer": 20.0,
                "scalp_tp1_dist": 200.0,
                "scalp_be_activation": 150.0,
                "trailing_distance": 150.0,
                "trailing_activation": 250.0,
                "pip_multiplier": 1.0
            }
        elif "OIL" in sym or "USOIL" in sym:
            return {
                "lot_size": float(os.getenv("OIL_COPIER_LOT_SIZE", "0.10")),
                "min_sl_distance": 0.30,
                "max_sl_distance": 1.50,
                "max_slippage": 0.25,
                "be_buffer": 0.10,
                "scalp_tp1_dist": 0.40,
                "scalp_be_activation": 0.30,
                "trailing_distance": 0.50,
                "trailing_activation": 0.80,
                "pip_multiplier": 1.0
            }
        else:
            return {
                "lot_size": max(0.07, float(os.getenv("FOREX_COPIER_LOT_SIZE", "0.07"))),
                "min_sl_distance": 0.0008,        # 8 pips noise floor (0.00080)
                "max_sl_distance": 0.0050,  # 50 pips
                "max_slippage": 0.0012,     # 12 pips
                "be_buffer": 0.0002,        # 2 pips
                "scalp_tp1_dist": 0.0020,   # 20 pips
                "scalp_be_activation": 0.0015, # 15 pips
                "trailing_distance": 0.0030,     # 30 pips
                "trailing_activation": 0.0040,   # Activate trailing once +40 pips in profit
                "pip_multiplier": 10000.0
            }

    def execute_signal(self, sig: Dict[str, Any], spot_price: float) -> Optional[List[dict]]:
        symbol = sig["symbol"]
        side = sig["side"]
        channel = sig["channel"]
        params = self.get_asset_parameters(symbol)
        entry = spot_price  # Fill at live market spot
        raw_sl = sig.get("sl")
        max_dist = params["max_sl_distance"]

        # Invariant 24: Institutional Price Action Stop-Loss (PASL) & Structural Shield Guard
        df_bars = None
        try:
            df_bars = self.ctrader.get_trendbars_dataframe(symbol, period="M_5", count=25)
        except Exception as te:
            logger.debug(f"Trendbars feed skipped/unavailable for {symbol}: {te}")

        spread = 0.0
        try:
            live_spot = self.ctrader.get_spot_price(symbol)
            if live_spot and "ask" in live_spot and "bid" in live_spot:
                spread = abs(float(live_spot["ask"]) - float(live_spot["bid"]))
        except Exception:
            spread = 0.0

        from src.strategies.price_action_sl_engine import PriceActionSLEngine
        safe_sl, sl_reason = PriceActionSLEngine.reconcile_structural_sl(
            provider_sl=raw_sl,
            df_bars=df_bars,
            side=side,
            entry_price=entry,
            symbol=symbol,
            max_allowed_distance=max_dist,
            spread_cushion=spread if side == "SELL" else 0.0
        )
        logger.info(f"🛡️ [PASL Engine] {symbol} {side} SL: {safe_sl} (Reason: {sl_reason} | Spread Cushion: {spread:.4f}) | Provider: {raw_sl}")

        tps = sig["tps"]
        # Sanitize targets relative to actual fill entry spot
        if side == "BUY":
            tps = [tp for tp in tps if tp > entry]
        else:
            tps = [tp for tp in tps if tp < entry]

        if not tps:
            # Fallback 1.5:1 R:R target
            dist = abs(entry - safe_sl)
            tps = [round(entry + (dist * 1.5) if side == "BUY" else entry - (dist * 1.5), 5)]

        # Invariant 28: Target Scaling & Intraday Ceilings (Never Reject Good Signals)
        # USER DIRECTIVE: A good signal must NEVER be rejected simply because its TP target is far away!
        # Downside risk is strictly controlled by Stop Loss ($35 max risk) and Breakeven Lock (+10 pips).
        dist_tp1 = abs(tps[0] - entry)
        sym_upper = symbol.upper()
        if "XAU" in sym_upper or "GOLD" in sym_upper:
            max_intraday_tp = 60.0  # 60.0 pts Gold (600 pips)
        elif "JPY" in sym_upper:
            max_intraday_tp = 1.80  # 180 pips JPY
        elif "BTC" in sym_upper or "ETH" in sym_upper:
            max_intraday_tp = 2500.0
        elif "US30" in sym_upper or "NAS100" in sym_upper:
            max_intraday_tp = 400.0
        else:
            max_intraday_tp = 0.0150  # 150 pips standard Forex (EURUSD, GBPUSD, AUDUSD, etc.)

        # USER DIRECTIVE: Authorized swing channels have full target pass-through
        authorized_swing_channels = {
            "forexgdpfree", "forexgdp", "oanda", "dailyforexpipsfree", "universalforexsignals",
            "vipfx1", "ultreos_forex", "forexpipsfactory", "purefxvip", "elitetrading_signals"
        }
        is_swing_authorized = str(channel).lower() in authorized_swing_channels
        if dist_tp1 > max_intraday_tp and not is_swing_authorized:
            # DO NOT REJECT: Clamp TP1 to max_intraday_tp so Ticket 1 banks intraday profit,
            # while preserving the deep target for Ticket 2 runner!
            original_tp = tps[0]
            clamped_tp1 = round(entry + max_intraday_tp if side == "BUY" else entry - max_intraday_tp, 5)
            logger.info(
                f"ℹ️ [Invariant 28] Signal from {channel} on {symbol} {side} has wide TP1 ({dist_tp1:.4f} > {max_intraday_tp:.4f}). "
                f"Clamping Ticket 1 TP to {clamped_tp1} while keeping deep target {original_tp} for runner."
            )
            if len(tps) == 1:
                tps = [clamped_tp1, original_tp]
            else:
                tps[0] = clamped_tp1

        lot_size = params["lot_size"]  # 0.07 lots per ticket
        executed_orders = []

        # 2-Ticket Split Architecture ("Banker + Trailing Runner"):
        # Ticket 1 (0.07 lots) targets TP1 to bank immediate profit into balance.
        # Ticket 2 (0.07 lots) targets the deepest target (tps[-1]) to capture massive swing runs with trailing protection.
        # For single-target scalp calls (e.g. ssfgold) where the advertised TP is wide (> 1.25x scalp_tp1_dist),
        # synthetically split into Ticket 1 Micro-Banker (+20 pips) + Ticket 2 Full Target Runner so early gains are locked!
        has_multi_targets = len(tps) > 1
        scalp_tp1 = params.get("scalp_tp1_dist", 2.0)
        dist_to_tp = abs(tps[0] - entry)

        # Strict Invariant 25: 0.07 lots per ticket (0.14 lots total across twin tickets)
        ticket_vol = max(0.07, lot_size)

        # Invariant 26: Dynamic Capacity & Twin-Slot Allocation.
        # Check current active positions on broker to determine available slots.
        try:
            live_pos = self.ctrader.get_positions_strict() if not self.dry_run else [p for p in self.state.get("active_positions", [])]
            current_count = len(live_pos) if live_pos is not None else len(self.state.get("active_positions", []))
        except Exception:
            current_count = len(self.state.get("active_positions", []))

        max_allowed_pos = getattr(self, "max_concurrent_positions", 6)
        free_slots = max(0, max_allowed_pos - current_count)

        if free_slots == 0:
            logger.warning(f"🛑 [Invariant 26] Max Concurrent Positions limit ({max_allowed_pos}) reached ({current_count} active). Skipping signal for {symbol}.")
            return None

        # Universal Twin-Ticket Allocation:
        # Every trade executes twin tickets of 0.07 lots (0.14 total) when at least 2 slots are free.
        if has_multi_targets:
            if free_slots == 1:
                tickets_plan = [{"ticket": 1, "vol": ticket_vol, "tp": tps[0]}]
            else:
                tickets_plan = [
                    {"ticket": 1, "vol": ticket_vol, "tp": tps[0]},
                    {"ticket": 2, "vol": ticket_vol, "tp": tps[-1]}
                ]
        elif dist_to_tp > (scalp_tp1 * 1.25):
            t1_tp = round(entry + scalp_tp1 if side == "BUY" else entry - scalp_tp1, 5)
            if free_slots == 1:
                tickets_plan = [{"ticket": 1, "vol": ticket_vol, "tp": t1_tp}]
            else:
                tickets_plan = [
                    {"ticket": 1, "vol": ticket_vol, "tp": t1_tp},
                    {"ticket": 2, "vol": ticket_vol, "tp": tps[0]}
                ]
        else:
            # Single tight target call across any asset (Gold, Forex Major, Cross, Index):
            # Synthesize Ticket 1 (advertised TP) + Ticket 2 (extended runner target)
            ext_runner = round(tps[0] + (scalp_tp1 if side == "BUY" else -scalp_tp1), 5)
            if free_slots == 1:
                tickets_plan = [{"ticket": 1, "vol": ticket_vol, "tp": tps[0]}]
            else:
                tickets_plan = [
                    {"ticket": 1, "vol": ticket_vol, "tp": tps[0]},
                    {"ticket": 2, "vol": ticket_vol, "tp": ext_runner}
                ]


        total_vol = round(sum(t["vol"] for t in tickets_plan), 2)
        logger.info(f"🚀 Executing {side} {symbol} ({len(tickets_plan)} tickets • {total_vol} total lots) | Entry ~{entry} | SL: {safe_sl} | TP1: {tickets_plan[0]['tp']} | Runner TP: {tickets_plan[-1]['tp']} | Channel: {channel}")

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
                    if order_res and ("result" in order_res or "positionId" in order_res or "orderId" in order_res):
                        pos_id = (
                            order_res.get("positionId")
                            or (order_res.get("result", {}).get("positionId") if isinstance(order_res.get("result"), dict) else None)
                            or order_res.get("orderId")
                        )
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
                is_rollover = sig.get("is_target_rollover", False)
                rollover_badge = " (Target-Rollover • Invariant 22)" if is_rollover else ""
                rollover_note = f"\n🎯 <b>Rollover Mode:</b> TP1 passed. Riding momentum to Target {sig.get('rollover_tp')} with Ratcheted SL at {safe_sl}" if is_rollover else ""
                tps_str = f"TP1: {tps[0]}" + (f" | Runner TP: {tps[-1]} ({len(tps)} targets)" if len(tps) > 1 else "")
                post_url = sig.get("post_url") or (f"https://t.me/{sig.get('post_id')}" if sig.get("post_id") else None)
                post_link_str = f"\n🔗 <b>Original Post:</b> <a href=\"{post_url}\">View in Telegram</a>" if post_url else ""
                alert_msg = (
                    f"⚡ <b>NEW SIGNAL EXECUTED{rollover_badge}</b>\n"
                    f"📡 <b>Source:</b> {channel}{post_link_str}\n"
                    f"📈 <b>Action:</b> {side} {symbol}\n"
                    f"📍 <b>Fill Price:</b> {entry}\n"
                    f"🛡️ <b>Stop Loss:</b> {safe_sl}\n"
                    f"🎯 <b>Targets:</b> {tps_str}\n"
                    f"📦 <b>Tickets:</b> {len(executed_orders)} tickets ({total_vol} lots total){rollover_note}"
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
        if self.dry_run:
            return

        try:
            live_positions = self.ctrader.get_positions() or []
            active = self.state.setdefault("active_positions", [])
            if not active and not live_positions:
                return

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

            # Adopt any live positions on the broker that have Sig_ comment or AgentQuant label
            for lp in live_positions:
                lp_id = lp.get("positionId")
                comment = lp.get("comment") or ""
                label = lp.get("label") or ""
                if (comment.startswith("Sig_") or label == "AgentQuant") and not any(p.get("positionId") == lp_id for p in active):
                    ticket_num = 2 if "_T2" in comment else (1 if "_T1" in comment else 1)
                    active.append({
                        "positionId": lp_id,
                        "ticket": ticket_num,
                        "symbol": lp.get("symbolName") or "EURAUD",
                        "side": lp.get("tradeSide", "BUY"),
                        "entry": float(lp.get("entryPrice", 0.0)),
                        "sl": float(lp.get("stopLoss", 0.0)) if lp.get("stopLoss") else None,
                        "tp": float(lp.get("takeProfit", 0.0)) if lp.get("takeProfit") else None,
                        "be_locked": False,
                        "time": now_utc.isoformat()
                    })

            # 2. Invariant 23: Direct Broker-Label-Linked Reconciliation & Companion Breakeven
            # First, reconcile broker-level positions tagged with _T2 if companion _T1 has closed
            for lp in live_positions:
                lp_id = lp.get("positionId")
                comment = lp.get("comment") or ""
                if "_T2" in comment:
                    t1_comment = comment.replace("_T2", "_T1")
                    t1_open = any((p.get("comment") or "") == t1_comment for p in live_positions)
                    if not t1_open:
                        # T1 has already closed on the broker!
                        pos_in_active = next((p for p in active if p.get("positionId") == lp_id), None)
                        if not pos_in_active:
                            # Reconstruct from broker position
                            sym_name = lp.get("symbolName") or "XAUUSD"
                            pos_in_active = {
                                "positionId": lp_id,
                                "ticket": 2,
                                "symbol": sym_name,
                                "side": lp.get("tradeSide", "BUY"),
                                "entry": float(lp.get("entryPrice", 0.0)),
                                "sl": float(lp.get("stopLoss", 0.0)) if lp.get("stopLoss") else None,
                                "tp": float(lp.get("takeProfit", 0.0)) if lp.get("takeProfit") else None,
                                "be_locked": False,
                                "time": now_utc.isoformat()
                            }
                            active.append(pos_in_active)

            # Check if Ticket 1 has hit TP1 to advance Ticket 2 to Breakeven
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
                            spot = self.ctrader.get_spot_price(sym)
                            curr_price = float(spot["bid"] if side == "BUY" else spot["ask"]) if spot else None
                            can_move = (curr_price >= be_price) if (curr_price and side == "BUY") else (curr_price <= be_price if curr_price else True)
                            if can_move:
                                try:
                                    self.ctrader.amend_position(rem_id, stop_loss=be_price, symbol=sym)
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
                            else:
                                rem["be_pending"] = True
                                logger.info(f"⏳ Ticket #1 filled, but spot {curr_price} is adverse to BE {be_price}. Awaiting price recovery for #{rem_id}.")

            # Also check any pending Ticket 2s whose T1 is confirmed closed
            for rem in remaining_tickets:
                rem_id = rem.get("positionId")
                if rem_id and rem_id in live_pos_ids and not rem.get("be_locked") and rem.get("be_pending"):
                    sym = rem.get("symbol")
                    side = rem.get("side", "BUY")
                    entry_p = rem.get("entry")
                    params = self.get_asset_parameters(sym)
                    be_price = round(entry_p + params["be_buffer"] if side == "BUY" else entry_p - params["be_buffer"], 5)
                    spot = self.ctrader.get_spot_price(sym)
                    curr_price = float(spot["bid"] if side == "BUY" else spot["ask"]) if spot else None
                    can_move = (curr_price >= be_price) if (curr_price and side == "BUY") else (curr_price <= be_price if curr_price else False)
                    if can_move:
                        try:
                            self.ctrader.amend_position(rem_id, stop_loss=be_price)
                            rem["be_locked"] = True
                            rem["sl"] = be_price
                            rem["be_pending"] = False
                            logger.info(f"🛡️ [Invariant 23] T1 closed! Ticket #2 (#{rem_id}) SL moved to Breakeven {be_price}")
                            self.send_telegram_alert(
                                f"🎯 <b>Companion Breakeven Activated!</b>\n"
                                f"Symbol: {sym} | Ticket #2 (#{rem_id})\n"
                                f"Price at favorable level. SL locked @ <code>{be_price}</code>"
                            )
                        except Exception as ae:
                            logger.error(f"Failed to amend Ticket #{rem_id} to Breakeven: {ae}")
                    else:
                        rem["be_pending"] = True
                        logger.info(f"⏳ [Invariant 23] T1 closed! Ticket #2 (#{rem_id}) awaiting price {curr_price} to reach BE {be_price}")

            # 3. Dynamic Breakeven for individual running tickets past 50% TP distance & Companion Sync
            for pos in active:
                pos_id = pos.get("positionId")
                if not pos_id or pos_id not in live_pos_ids:
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
                scalp_be_thresh = params.get("scalp_be_activation", half_tp_distance)

                if not pos.get("be_locked") and (gain >= half_tp_distance or gain >= scalp_be_thresh):
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

                # Invariant 27: Companion Breakeven Synchronization
                # If this position is be_locked, synchronously advance any unlocked companion tickets
                if pos.get("be_locked"):
                    for comp in active:
                        comp_id = comp.get("positionId")
                        if (
                            comp_id
                            and comp_id in live_pos_ids
                            and not comp.get("be_locked")
                            and comp.get("symbol") == symbol
                            and comp.get("side") == side
                            and comp_id != pos_id
                        ):
                            c_entry = comp.get("entry", entry)
                            c_be = round(c_entry + params["be_buffer"] if side == "BUY" else c_entry - params["be_buffer"], 5)
                            can_move_comp = (curr_price >= c_be) if side == "BUY" else (curr_price <= c_be)
                            if can_move_comp:
                                try:
                                    self.ctrader.amend_position(comp_id, stop_loss=c_be)
                                    comp["be_locked"] = True
                                    comp["sl"] = c_be
                                    logger.info(f"🛡️ [Invariant 27] Companion Position #{comp_id} ({symbol}) synchronized to Breakeven @ {c_be}")
                                    self.send_telegram_alert(
                                        f"🛡️ <b>Companion Breakeven Synchronized!</b>\n"
                                        f"Symbol: {symbol} | Position #{comp_id}\n"
                                        f"SL synchronized to BE: <code>{c_be}</code>"
                                    )
                                except Exception as cae:
                                    logger.error(f"Failed to amend companion #{comp_id} to Breakeven: {cae}")

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
                    df_bars = None
                    try:
                        df_bars = self.ctrader.get_trendbars_dataframe(symbol, period="M_5", count=20)
                    except Exception as tbe:
                        logger.debug(f"Trendbars unavailable for trailing {symbol}: {tbe}")

                    spread = abs(float(spot.get("ask", 0.0)) - float(spot.get("bid", 0.0))) if spot else 0.0

                    from src.strategies.price_action_sl_engine import PriceActionSLEngine
                    structural_sl = PriceActionSLEngine.calculate_m5_trailing_sl(
                        df=df_bars,
                        side=side,
                        entry_price=entry,
                        current_sl=current_sl,
                        current_price=curr_price,
                        symbol=symbol,
                        lookback_bars=6,
                        spread_cushion=spread if side == "SELL" else 0.0
                    )

                    new_sl = None
                    trail_mode = "Distance Dynamic"
                    if structural_sl is not None:
                        new_sl = structural_sl
                        trail_mode = "M5 Structure Pivot"
                    else:
                        if side == "BUY":
                            new_sl = round(curr_price - trail_dist, 5)
                        else:
                            new_sl = round(curr_price + trail_dist + (spread if side == "SELL" else 0.0), 5)

                    if side == "BUY":
                        # Ratchet constraint: only ratchet SL upwards
                        if new_sl and new_sl > current_sl + (params["be_buffer"] * 0.5):
                            try:
                                self.ctrader.amend_position(pos_id, stop_loss=new_sl)
                                pos["sl"] = new_sl
                                pos["be_locked"] = True
                                logger.info(f"🏃 [{trail_mode} TRAILING] Ticket #{pos.get('ticket', 2)} (#{pos_id} {symbol}) SL trailed up to {new_sl} (gain: +{gain:.4f})")
                                self.send_telegram_alert(
                                    f"🏃 <b>Trailing Stop Advanced ({trail_mode})</b>\n"
                                    f"Symbol: {symbol} | Ticket #{pos.get('ticket')} (#{pos_id})\n"
                                    f"Floating Gain: +{gain:.4f}\n"
                                    f"New Protected SL: <code>{new_sl}</code>"
                                )
                            except Exception as ae:
                                logger.error(f"Failed to trail SL for #{pos_id}: {ae}")
                    else:  # SELL
                        # Ratchet constraint: only ratchet SL downwards
                        if new_sl and new_sl < current_sl - (params["be_buffer"] * 0.5):
                            try:
                                self.ctrader.amend_position(pos_id, stop_loss=new_sl)
                                pos["sl"] = new_sl
                                pos["be_locked"] = True
                                logger.info(f"🏃 [{trail_mode} TRAILING] Ticket #{pos.get('ticket', 2)} (#{pos_id} {symbol}) SL trailed down to {new_sl} (gain: +{gain:.4f})")
                                self.send_telegram_alert(
                                    f"🏃 <b>Trailing Stop Advanced ({trail_mode})</b>\n"
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
        now_ts = time.time()

        # 1. Tier-Weighted Interval Filtering (Speed & Bandwidth Efficiency)
        channels_to_poll = []
        for ch in CHANNELS_CONFIG:
            if not ch.get("enabled"):
                continue
            ch_id = ch["id"]
            tier = ch.get("tier", 2)
            # Tier 1 (Institutional Clean): Polled on every tick (0s delay)
            # Tier 2 (Direct Reliable): Polled every 10s
            # Tier 3 (Guarded / High-Noise): Polled every 15s
            min_interval = 0 if tier == 1 else (10 if tier == 2 else 15)
            last_p = self._last_channel_poll.get(ch_id, 0)
            if now_ts - last_p >= min_interval:
                channels_to_poll.append(ch)
                self._last_channel_poll[ch_id] = now_ts

        if not channels_to_poll:
            return

        # 2. Parallel Concurrent Harvester across all eligible channels (<350ms total)
        from concurrent.futures import ThreadPoolExecutor
        channel_posts_map = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_ch = {executor.submit(self.fetch_channel_posts, ch["id"]): ch["id"] for ch in channels_to_poll}
            for fut in future_to_ch:
                ch_id = future_to_ch[fut]
                try:
                    channel_posts_map[ch_id] = fut.result()
                except Exception as e:
                    logger.debug(f"Error fetching {ch_id}: {e}")

        for ch in channels_to_poll:
            ch_id = ch["id"]
            posts = channel_posts_map.get(ch_id, [])
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
                post_url = p.get("post_url") or f"https://t.me/{pid}"
                watermarks[ch_id] = pid
                self.save_state()

                sig = MultiChannelSignalParser.parse_message(p["text"], ch_id)
                if not sig:
                    continue

                sig["post_id"] = pid
                sig["post_url"] = post_url

                # 1. Validation Check (Directional Coherence & Integrity)
                if not sig.get("is_valid", True):
                    err = sig.get("validation_error", "Unknown validation failure")
                    logger.warning(f"🚫 [REJECTED MALFORMED SIGNAL] {ch_id} (Post #{pid}): {err}")
                    if not self.dry_run:
                        self.send_telegram_alert(
                            f"⚠️ <b>SIGNAL BLOCKED: Malformed / Inverted Signal</b>\n\n"
                            f"📡 <b>Source:</b> {ch_id} (Post #{pid})\n"
                            f"🔗 <b>Original Post:</b> <a href=\"{post_url}\">View in Telegram</a>\n"
                            f"📈 <b>Action:</b> {sig.get('side')} {sig.get('symbol')} @ {sig.get('entry_mid')}\n"
                            f"❌ <b>Reason:</b> {err}\n"
                            f"🛡️ <b>Protection:</b> Blocked automatically to protect your capital."
                        )
                    continue

                symbol = sig["symbol"]
                side = sig["side"]

                # Invariant 30: Channel Asset Whitelist Guard
                # If a channel has an explicit asset specialization, reject non-whitelisted assets.
                allowed_assets = ch.get("assets", ["ALL"])
                if "ALL" not in allowed_assets and symbol not in allowed_assets:
                    logger.info(
                        f"⏭️ [Invariant 30] Blocked {symbol} {side} from {ch_id}: "
                        f"asset '{symbol}' is not authorized in channel whitelist {allowed_assets}."
                    )
                    continue

                sig_key = f"{symbol}_{side}_{round(sig['entry_mid'], 2)}_{ch_id}"

                if sig_key in self.state.get("executed_signal_keys", []):
                    logger.debug(f"Skipping already executed signal {sig_key}")
                    continue

                if self.check_conflicts(symbol, side):
                    if not self.dry_run:
                        self.send_telegram_alert(
                            f"🛡️ <b>CONFLICT SHIELD ACTIVATED</b>\n\n"
                            f"📡 <b>Source:</b> {ch_id} (Post #{pid})\n"
                            f"🔗 <b>Original Post:</b> <a href=\"{post_url}\">View in Telegram</a>\n"
                            f"📈 <b>Attempted:</b> {side} {symbol} @ {sig.get('entry_mid')}\n"
                            f"⚠️ <b>Reason:</b> Opposing position already active on account.\n"
                            f"🛡️ <b>Action:</b> Order skipped to avoid hedging conflict."
                        )
                    continue

                # Verify live spot price and anti-chase
                spot = self.ctrader.get_spot_price(symbol)
                if not spot:
                    logger.warning(f"Could not fetch spot price for {symbol}. Skipping.")
                    continue

                curr_spot = float(spot["ask"] if side == "BUY" else spot["bid"])
                params = self.get_asset_parameters(symbol)

                # Check if price is within acceptable distance from entry range (Directional Anti-Chase)
                e_min = sig["entry_min"]
                e_max = sig["entry_max"]
                raw_sl = sig.get("sl")
                dist_from_zone = 0.0

                if side == "BUY":
                    if curr_spot > e_max:
                        # Price is running away upwards towards TP (Adverse Chasing)
                        dist_from_zone = curr_spot - e_max
                    elif curr_spot < e_min:
                        # Price is at a discount (favorable dip for scalping!)
                        if raw_sl and curr_spot <= (raw_sl + params["be_buffer"]):
                            # Price dipped too far and has breached or reached the Stop Loss
                            logger.info(f"⏭️ Signal Invalidation: {symbol} spot {curr_spot} reached or breached SL {raw_sl}. Skipping.")
                            if not self.dry_run:
                                self.send_telegram_alert(
                                    f"⏭️ <b>SIGNAL INVALIDATED: Stop Loss Already Reached</b>\n\n"
                                    f"📡 <b>Source:</b> {ch_id} (Post #{pid})\n"
                                    f"🔗 <b>Original Post:</b> <a href=\"{post_url}\">View in Telegram</a>\n"
                                    f"📈 <b>Action:</b> {side} {symbol} @ {sig.get('entry_mid')}\n"
                                    f"📍 <b>Live Market Spot:</b> {curr_spot}\n"
                                    f"🛡️ <b>SL Level:</b> {raw_sl}\n"
                                    f"⚠️ <b>Status:</b> Setup aborted because market reached SL prior to entry."
                                )
                            continue
                        else:
                            # Valid discount scalp entry!
                            dist_from_zone = 0.0
                else:  # SELL
                    if curr_spot < e_min:
                        # Price is running away downwards towards TP (Adverse Chasing)
                        dist_from_zone = e_min - curr_spot
                    elif curr_spot > e_max:
                        # Price rallied into a premium (favorable rally for selling!)
                        if raw_sl and curr_spot >= (raw_sl - params["be_buffer"]):
                            # Price spiked too high and reached Stop Loss
                            logger.info(f"⏭️ Signal Invalidation: {symbol} spot {curr_spot} reached or breached SL {raw_sl}. Skipping.")
                            if not self.dry_run:
                                self.send_telegram_alert(
                                    f"⏭️ <b>SIGNAL INVALIDATED: Stop Loss Already Reached</b>\n\n"
                                    f"📡 <b>Source:</b> {ch_id} (Post #{pid})\n"
                                    f"🔗 <b>Original Post:</b> <a href=\"{post_url}\">View in Telegram</a>\n"
                                    f"📈 <b>Action:</b> {side} {symbol} @ {sig.get('entry_mid')}\n"
                                    f"📍 <b>Live Market Spot:</b> {curr_spot}\n"
                                    f"🛡️ <b>SL Level:</b> {raw_sl}\n"
                                    f"⚠️ <b>Status:</b> Setup aborted because market reached SL prior to entry."
                                )
                            continue
                        else:
                            # Valid premium scalp entry!
                            dist_from_zone = 0.0

                if dist_from_zone > params["max_slippage"]:
                    # Invariant 22/29: Smart Multi-Target Rollover & Momentum Anti-Chase Gate
                    # If spot has run past entry zone, scan all remaining candidate targets to find the first target offering >= 1.5:1 R:R
                    candidate_tps = [tp for tp in sig.get("tps", []) if (tp > curr_spot if side == "BUY" else tp < curr_spot)]
                    rollover_executed = False

                    if candidate_tps:
                        ratcheted_sl = round(e_max if side == "BUY" else e_min, 5)
                        ratcheted_risk = abs(curr_spot - ratcheted_sl)
                        min_risk_dist = params.get("be_buffer", 0.5)
                        eff_risk = max(ratcheted_risk, min_risk_dist)

                        # Evaluate all remaining candidate targets for asymmetric risk:reward
                        viable_tp = None
                        viable_index = None
                        for i, tp in enumerate(candidate_tps):
                            reward = abs(tp - curr_spot)
                            if reward >= (1.5 * eff_risk):
                                viable_tp = tp
                                viable_index = i
                                break

                        if viable_tp is not None:
                            remaining_tps = candidate_tps[viable_index:]
                            remaining_reward = abs(viable_tp - curr_spot)
                            logger.info(
                                f"🎯 Invariant 29 Smart Multi-Target Rollover: {symbol} spot {curr_spot} passed entry zone, but target {viable_tp} "
                                f"offers {remaining_reward:.2f} pts reward vs {eff_risk:.2f} pts ratcheted risk (>= 1.5 R:R). Proceeding with ratcheted SL {ratcheted_sl}."
                            )
                            rollover_sig = copy.deepcopy(sig)
                            rollover_sig["sl"] = ratcheted_sl
                            rollover_sig["tps"] = remaining_tps
                            rollover_sig["is_target_rollover"] = True
                            rollover_sig["rollover_tp"] = viable_tp
                            self.execute_signal(rollover_sig, curr_spot)
                            rollover_executed = True

                    if rollover_executed:
                        continue

                    # If rollover was not eligible, block with Anti-Chase skip alert
                    orig_sl = sig.get("sl")
                    sl_risk_str = ""
                    if orig_sl:
                        expanded_risk = abs(curr_spot - orig_sl)
                        sl_risk_str = f"\n⚠️ <b>Risk Warning:</b> Chasing would expand SL risk to {expanded_risk:.2f} pts"

                    logger.info(f"⏭️ Anti-Chase Filter: {symbol} spot {curr_spot} is {dist_from_zone:.2f} adverse pts from entry zone (max {params['max_slippage']}). Skipping.")
                    if not self.dry_run:
                        self.send_telegram_alert(
                            f"⏭️ <b>SIGNAL SKIPPED: Anti-Chase Limit Exceeded</b>\n\n"
                            f"📡 <b>Source:</b> {ch_id} (Post #{pid})\n"
                            f"🔗 <b>Original Post:</b> <a href=\"{post_url}\">View in Telegram</a>\n"
                            f"📈 <b>Action:</b> {side} {symbol} @ {sig.get('entry_mid')}\n"
                            f"📍 <b>Live Market Spot:</b> {curr_spot}\n"
                            f"📏 <b>Adverse Distance:</b> +{dist_from_zone:.2f} pts towards TP (Max Allowed: {params['max_slippage']}){sl_risk_str}\n"
                            f"🛡️ <b>Protection:</b> Trade blocked to prevent chasing after price has already run away (no valid rollover target with >= 1.5:1 R:R)."
                        )
                    continue

                # Execute order
                self.execute_signal(sig, curr_spot)

        # Manage active trades (Breakeven locks)
        self.manage_active_breakeven()


def start_multi_copier_daemon(interval_sec: int = 5, dry_run: bool = False):
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
    start_multi_copier_daemon(interval_sec=5, dry_run=False)


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
