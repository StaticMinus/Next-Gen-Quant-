"""
Persistent Channel Quirk & Pattern Memory
==========================================
Maintains a high-speed in-memory cache and persistent JSON store (cache/learned_patterns.json)
for channel-specific formatting signatures, syntax quirks, and provider nuances.

Enables the copier to read channel formatting quirks in < 0.1ms, eliminating repeated
regex trial-and-error and bypassing slow external AI calls on known provider patterns.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("pattern_memory")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CACHE_FILE = ROOT_DIR / "cache" / "learned_patterns.json"

DEFAULT_SEEDED_PATTERNS: Dict[str, Dict[str, Any]] = {
    "XAUUSD_GOLD_TRADING_FOREX": {
        "tp1_is_entry_anchor": True,
        "auto_promote_tp": True,
        "sl_label": "STOP LOSS",
        "description": "Gold Scalper: Frequently sets TP1 equal to entry as a break-even anchor. Requires TP2/TP3 promotion."
    },
    "PrimeGoldSignals": {
        "range_separator_dot": True,
        "description": "Prime Gold: Encodes entry ranges with dot syntax (e.g. 4131.4134 -> 4131-4134)."
    },
    "ssfgold": {
        "strip_vip_promos": True,
        "multi_target_split": True,
        "description": "SureShotFX: Uses single-target or close-half updates. Requires synthetic runner target."
    },
    "anabelsignals": {
        "handles_zone_ranges": True,
        "description": "Anabel Signals: Zone range entries with explicit SL/TP format."
    },
    "forexgdpfree": {
        "analysis_heavy": True,
        "require_explicit_action": True,
        "description": "ForexGDP Free: Educational chart posts mixed with high-conviction breakout setups."
    }
}


class PatternMemory:
    """Thread-safe persistent memory for channel quirks and format adjustments."""

    _lock = threading.RLock()
    _cache: Optional[Dict[str, Dict[str, Any]]] = None

    @classmethod
    def _ensure_loaded(cls) -> Dict[str, Dict[str, Any]]:
        if cls._cache is not None:
            return cls._cache

        with cls._lock:
            if cls._cache is not None:
                return cls._cache

            if CACHE_FILE.exists():
                try:
                    with open(CACHE_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        # Merge seeded defaults with loaded data so new defaults appear
                        merged = dict(DEFAULT_SEEDED_PATTERNS)
                        merged.update(data)
                        cls._cache = merged
                        return cls._cache
                except Exception as e:
                    logger.warning(f"Failed to read {CACHE_FILE}: {e}. Initializing with seeded defaults.")

            cls._cache = dict(DEFAULT_SEEDED_PATTERNS)
            cls._save_to_disk()
            return cls._cache

    @classmethod
    def _save_to_disk(cls) -> None:
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cls._cache, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to persist pattern memory to {CACHE_FILE}: {e}")

    @classmethod
    def get_channel_quirks(cls, channel_id: str) -> Dict[str, Any]:
        """Returns in-memory quirks for a given channel in < 0.1ms."""
        cache = cls._ensure_loaded()
        return cache.get(channel_id, {})

    @classmethod
    def get_quirk(cls, channel_id: str, quirk_key: str, default: Any = None) -> Any:
        """Retrieves a specific quirk flag for a channel."""
        quirks = cls.get_channel_quirks(channel_id)
        return quirks.get(quirk_key, default)

    @classmethod
    def record_channel_quirk(cls, channel_id: str, quirk_key: str, value: Any, description: Optional[str] = None) -> None:
        """Persists a newly discovered channel quirk into memory and disk."""
        with cls._lock:
            cls._ensure_loaded()
            if channel_id not in cls._cache:
                cls._cache[channel_id] = {}
            cls._cache[channel_id][quirk_key] = value
            if description:
                cls._cache[channel_id]["description"] = description
            cls._save_to_disk()
            logger.info(f"🧠 [PatternMemory] Learned new quirk for @{channel_id}: {quirk_key} = {value}")

    @classmethod
    def should_promote_tp1(cls, channel_id: str) -> bool:
        """Returns True if the channel is known to use TP1 as an entry anchor."""
        quirks = cls.get_channel_quirks(channel_id)
        return bool(quirks.get("tp1_is_entry_anchor") or quirks.get("auto_promote_tp"))

    @classmethod
    def apply_preflight_normalization(cls, text: str, channel_id: str) -> str:
        """
        Applies fast, zero-latency string normalization based on known channel quirks.
        Executes in < 0.05ms before regex evaluation.
        """
        quirks = cls.get_channel_quirks(channel_id)
        if not quirks:
            return text

        # Quirk: PrimeGold dot-range format e.g. "4131.4134" -> "4131-4134"
        if quirks.get("range_separator_dot"):
            import re
            # Matches 4-digit numbers joined by dot e.g. 4131.4134 (not decimal 4131.5)
            text = re.sub(r"\b(\d{4})\.(\d{4})\b", r"\1-\2", text)

        return text
