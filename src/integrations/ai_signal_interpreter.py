"""
Deterministic Semantic Signal Parser (Zero-Latency, Fully Offline)
==================================================================
Replaces unreliable external LLM APIs (OpenRouter) with a 100% deterministic,
high-precision pattern engine for irregular, multi-line, spaced, or unconventional
Telegram signal posts across all major providers.
"""

import re
import logging
from typing import Optional, Dict, Any, List
from src.integrations.pattern_memory import PatternMemory

logger = logging.getLogger("ai_signal_interpreter")


class AISignalInterpreter:
    """Zero-dependency deterministic offline signal extractor."""

    @classmethod
    def is_available(cls) -> bool:
        """Always available locally with zero external network or API dependencies."""
        return True

    @classmethod
    def interpret_signal(cls, text: str, channel_id: str) -> Optional[Dict[str, Any]]:
        """
        Extracts structured trading parameters from noisy or unstructured text
        using advanced multi-pass regex and semantic pattern matching.
        """
        if not text:
            return None

        # Clean markdown, formatting artifacts, emojis
        t = text.replace("**", " ").replace("__", " ").replace("`", " ")
        t_upper = t.upper()

        # 1. Detect Action (Direction)
        side = None
        m_side = re.search(r"\b(BUY|SELL|LONG|SHORT)\b", t_upper)
        if m_side:
            s_raw = m_side.group(1)
            side = "BUY" if s_raw in ("BUY", "LONG") else "SELL"
        else:
            return None

        # 2. Detect Symbol
        symbol = None
        # Check explicit pairs
        m_sym = re.search(r"\b(XAUUSD|GOLD|EURUSD|GBPUSD|USDJPY|AUDUSD|USDCAD|USDCHF|NZDUSD|EURJPY|GBPJPY|AUDJPY|CADCHF|GBPAUD|GBPCAD|EURAUD|EURGBP|US30|SPX500|NDX100|BTCUSD|ETHUSD)\b", t_upper)
        if m_sym:
            s_raw = m_sym.group(1)
            symbol = "XAUUSD" if s_raw == "GOLD" else s_raw
        else:
            # Check composite or spaced symbols (e.g. "XAU USD", "EUR USD")
            m_spaced = re.search(r"\b(XAU|EUR|GBP|AUD|NZD|USD|CAD|CHF)\s+(USD|JPY|GBP|CAD|CHF|AUD)\b", t_upper)
            if m_spaced:
                symbol = f"{m_spaced.group(1)}{m_spaced.group(2)}"
            elif "GOLD" in t_upper:
                symbol = "XAUUSD"

        if not symbol:
            return None

        # 3. Detect Entry Price
        entry_mid = None
        entry_min = None
        entry_max = None

        # Pattern A: Range entry (e.g., 4060 - 4065, 4060/4065, 4060 - 65)
        m_range = re.search(r"(?:ENTRY|AT|@|PRICE)?\s*[:=\s]*([1-9]\d{1,4}(?:\.\d+)?)\s*(?:-|/|TO)\s*([1-9]\d{0,4}(?:\.\d+)?)", t, re.IGNORECASE)
        if m_range:
            p1 = float(m_range.group(1))
            p2_str = m_range.group(2)
            if len(p2_str) <= 2 and "." not in p2_str and p1 > 100:
                p2 = float(str(int(p1))[:-len(p2_str)] + p2_str)
            else:
                p2 = float(p2_str)
            entry_min = min(p1, p2)
            entry_max = max(p1, p2)
            entry_mid = round((entry_min + entry_max) / 2.0, 5)
        else:
            # Pattern B: Single entry level
            m_ent = re.search(r"(?:ENTRY|NOW|PRICE|AT|@)?\s*[:=\s]*([1-9]\d{1,4}(?:\.\d+)?)", t, re.IGNORECASE)
            if m_ent:
                p = float(m_ent.group(1))
                entry_mid = entry_min = entry_max = p

        # 4. Detect Stop Loss
        sl = None
        m_sl = re.search(r"(?:SL|STOP\s*LOSS|STOP)\s*[:=\s]*([1-9]\d{0,4}(?:\.\d+)?)", t, re.IGNORECASE)
        if m_sl:
            raw_sl = float(m_sl.group(1))
            # Handle shorthand 2-digit Gold SL (e.g. "SL 54.66" when entry is ~4048)
            if entry_mid and "XAU" in symbol and raw_sl < 100.0:
                base_100 = (int(entry_mid) // 100) * 100
                sl = base_100 + raw_sl
            else:
                sl = raw_sl

        # 5. Detect Take Profits (TP1, TP2, TP3...)
        tps = []
        # Find explicit TP listings
        tp_matches = re.findall(r"(?:TP|TARGET|TAKE\s*PROFIT)\s*\d*[:=\s]*([1-9]\d{0,4}(?:\.\d+)?)", t, re.IGNORECASE)
        for tp_str in tp_matches:
            val = float(tp_str)
            if entry_mid and "XAU" in symbol and val < 100.0:
                # Could be shorthand or relative points
                if val <= 20.0:
                    # Relative points (e.g. TP: 3.0 points or 30 pips)
                    calc_tp = round(entry_mid + val if side == "BUY" else entry_mid - val, 2)
                    tps.append(calc_tp)
                else:
                    # Shorthand 2-digit price (e.g. 68.50 -> 4068.50)
                    base_100 = (int(entry_mid) // 100) * 100
                    tps.append(base_100 + val)
            else:
                tps.append(val)

        # De-duplicate while preserving order
        clean_tps = []
        for x in tps:
            if x not in clean_tps:
                clean_tps.append(x)

        # Filter and sort TPs logically by direction (Invariant 21: Directional Coherence)
        if clean_tps and entry_mid:
            if side == "BUY":
                clean_tps = [x for x in clean_tps if x > entry_mid]
                clean_tps.sort()
            else:
                clean_tps = [x for x in clean_tps if x < entry_mid]
                clean_tps.sort(reverse=True)

        if not entry_mid:
            return None

        # Build standardized signal structure
        parsed = {
            "channel": channel_id,
            "type": "DETERMINISTIC_PARSER",
            "symbol": symbol,
            "side": side,
            "entry_mid": entry_mid,
            "entry_min": entry_min or entry_mid,
            "entry_max": entry_max or entry_mid,
            "sl": sl,
            "tps": clean_tps,
            "is_valid": True,
            "validation_error": None
        }

        logger.info(f"✨ [DeterministicParser] Successfully parsed signal for @{channel_id}: {side} {symbol} @ {entry_mid} | SL: {sl} | TPs: {clean_tps}")
        return parsed
