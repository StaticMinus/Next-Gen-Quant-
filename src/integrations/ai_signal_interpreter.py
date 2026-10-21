"""
Zero-Cost AI Signal Interpreter
================================
Asynchronous semantic signal extractor powered by OpenRouter's Free Tier frontier models
(minimax-m3.1-flash:free, google/gemma-4-26b-a4b-it:free, nvidia/nemotron-3-nano:free).

Operates as a high-precision fallback when regex parsing is inconclusive or encounters
unconventional syntax, complex natural language, or multi-target formatting quirks.
Automatically discovers and records new channel quirks into PatternMemory.
"""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

from src.integrations.pattern_memory import PatternMemory

logger = logging.getLogger("ai_signal_interpreter")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Prioritized cascade of verified 100% Free Frontier Models on OpenRouter
FREE_MODELS_CASCADE = [
    "minimax/minimax-m3.1-flash:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "nvidia/nemotron-3.5-lightning:free",
]


class AISignalInterpreter:
    """Semantic parser and intent extractor utilizing free frontier AI models."""

    @classmethod
    def is_available(cls) -> bool:
        """Returns True if AI extraction is enabled and an API key is configured."""
        enabled = os.getenv("AI_SIGNAL_EXTRACTION_ENABLED", "true").lower() == "true"
        return enabled and bool(OPENROUTER_API_KEY)

    @classmethod
    def interpret_signal(cls, text: str, channel_id: str) -> Optional[Dict[str, Any]]:
        """
        Extracts structured trading parameters from noisy or unstructured text.
        Returns parsed signal dict or None if text contains no actionable trading call.
        """
        if not cls.is_available():
            return None

        # Quick pre-filter: text must contain at least an action and an asset candidate
        has_dir = bool(re.search(r"\b(BUY|SELL|LONG|SHORT)\b", text, re.IGNORECASE))
        has_asset = bool(re.search(r"(?:XAU|GOLD|EUR|GBP|USD|JPY|AUD|CAD|NZD|CHF|OIL|US30|SPX|NDX|BTC)", text, re.IGNORECASE))
        if not (has_dir and has_asset):
            return None

        system_prompt = (
            "You are an institutional FX and Commodities Trade Signal Extractor.\n"
            "Your objective is to extract exact trading parameters from Telegram messages.\n"
            "Rules:\n"
            "1. Identify symbol (e.g. XAUUSD, EURUSD, GBPJPY, USOIL, US30).\n"
            "2. Identify side (BUY or SELL).\n"
            "3. Identify entry price (midpoint if range, e.g. 4150.0).\n"
            "4. Identify stop loss (SL). If missing or 'VIP', return null.\n"
            "5. Identify all Take Profits (tps). If TP1 equals or sits behind entry for the side "
            "(e.g. SELL 4150 with TP1 4150), omit the invalid TP1 and include only valid targets in 'tps'.\n"
            "6. Set 'quirk_detected': 'tp1_at_entry' if TP1 was an entry anchor, else null.\n"
            "7. Return ONLY valid JSON or null if not a trading signal.\n"
            "Format:\n"
            "{\n"
            '  "symbol": "XAUUSD",\n'
            '  "side": "BUY" | "SELL",\n'
            '  "entry_mid": 4150.0,\n'
            '  "entry_min": 4150.0,\n'
            '  "entry_max": 4150.0,\n'
            '  "sl": 4157.0,\n'
            '  "tps": [4130.0, 4120.0],\n'
            '  "quirk_detected": "tp1_at_entry" | null,\n'
            '  "reasoning": "brief note"\n'
            "}"
        )

        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://agentquant.internal",
            "X-Title": "AgentQuant AI Interpreter"
        }

        # Try models in cascade order
        for model in FREE_MODELS_CASCADE:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Channel: @{channel_id}\nMessage:\n{text[:800]}"}
                ],
                "temperature": 0.0,
                "max_tokens": 200
            }

            try:
                resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=3.5)
                if resp.status_code != 200:
                    continue

                res_json = resp.json()
                choices = res_json.get("choices", [])
                if not choices:
                    continue

                content = choices[0].get("message", {}).get("content", "").strip()
                if not content or content.lower() == "null":
                    return None

                # Robust JSON extraction from model response
                m_json = re.search(r"\{[\s\S]*\}", content)
                if not m_json:
                    continue
                parsed = json.loads(m_json.group(0))
                if not isinstance(parsed, dict) or not parsed.get("symbol") or not parsed.get("side"):
                    continue

                # Standardize output
                parsed["channel"] = channel_id
                parsed["type"] = "AI_INTERPRETER"
                parsed["is_valid"] = True
                parsed["validation_error"] = None
                parsed["symbol"] = parsed["symbol"].upper()
                parsed["side"] = parsed["side"].upper()
                if "GOLD" in parsed["symbol"]:
                    parsed["symbol"] = "XAUUSD"

                # Check if a quirk was discovered and record it into PatternMemory
                quirk = parsed.get("quirk_detected")
                if quirk == "tp1_at_entry":
                    PatternMemory.record_channel_quirk(
                        channel_id,
                        "tp1_is_entry_anchor",
                        True,
                        description="Auto-learned: Provider broadcasts TP1 as entry anchor."
                    )

                logger.info(f"✨ [AIInterpreter] Successfully parsed signal via {model} for @{channel_id}: {parsed['side']} {parsed['symbol']} @ {parsed.get('entry_mid')}")
                return parsed

            except Exception as e:
                logger.debug(f"[AIInterpreter] Model {model} pass exception: {e}")
                continue

        logger.warning(f"[AIInterpreter] All free tier models exhausted for @{channel_id} message.")
        return None
