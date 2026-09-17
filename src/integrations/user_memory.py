"""
src/integrations/user_memory.py
─────────────────────────────────────────────────────────────────────────────
Persistent Long-Term Memory Store for AgentQuant AI Quant Council.
Stores account limits, trading rules, user milestones, and lessons learned in cache/user_memory.json.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("user_memory")

MEMORY_FILE = Path("cache/user_memory.json")

DEFAULT_MEMORY = {
    "account_profile": {
        "broker": "cTrader (FundedNext)",
        "account_id": "3028655",
        "model": "Stellar 1-Step ($6,000)",
        "initial_capital": 6000.0,
        "profit_target": 600.0,
        "daily_loss_limit": 180.0,
        "max_trailing_drawdown": 360.0,
        "payout_split": "85% to David",
        "payout_cadence": "Every 5 business days",
    },
    "traders": {
        "primary": "David (Owner & Master Trader)",
        "partner": "Cha Cha (Trading Partner)",
    },
    "strategy_rules": {
        "universe": ["SPY (SPX500)", "QQQ (NDX100)", "DIA (US30)", "IWM (US2000)"],
        "max_concurrent_positions": 2,
        "position_size": "0.10 lots / $25 max risk per trade",
        "stop_loss_type": "Server-side hard stop loss (-$25)",
        "overnight_holding": "APPROVED - Hold through night with hard server stops. Flatten on Friday afternoon before weekend market close.",
        "ai_execution_policy": "STRICTLY READ-ONLY - AI Coach has ZERO order execution or trade modification ability. All execution is strictly algorithmic."
    },
    "learned_lessons": [
        "Gold Trade Autopsy: Closed trade smashed full TP target overnight at 08:15 WAT without ever triggering stop loss. Overnight holding with server stops is mathematically superior.",
        "Drawdown Cushion Discipline: Two simultaneous maximum losses (-$50 total) leaves a massive $130 cushion against the $180 daily stop.",
        "Patience on Dips: Only execute mean-reversion entries when price reaches the 1.25 sigma lower band or RSI drops below 36."
    ],
    "user_notes": []
}


def load_user_memory() -> Dict[str, Any]:
    """Loads persistent memory from disk, returning default if not yet created."""
    if not MEMORY_FILE.exists():
        save_user_memory(DEFAULT_MEMORY)
        return DEFAULT_MEMORY
    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        # Ensure all default top-level keys exist
        for k, v in DEFAULT_MEMORY.items():
            if k not in data:
                data[k] = v
        return data
    except Exception as e:
        logger.warning(f"Error loading user memory: {e}. Falling back to default.")
        return DEFAULT_MEMORY


def save_user_memory(data: Dict[str, Any]) -> bool:
    """Saves memory data to cache/user_memory.json."""
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"Error saving user memory: {e}")
        return False


def add_user_note(note: str) -> bool:
    """Appends a new note or lesson to persistent memory."""
    mem = load_user_memory()
    if "user_notes" not in mem:
        mem["user_notes"] = []
    mem["user_notes"].append(note.strip())
    return save_user_memory(mem)


def get_memory_prompt_context() -> str:
    """Formats persistent memory into a concise prompt block for the AI Coach."""
    mem = load_user_memory()
    rules = mem.get("strategy_rules", {})
    lessons = mem.get("learned_lessons", [])
    notes = mem.get("user_notes", [])

    lines = [
        "INSTITUTIONAL MEMORY & PERSISTENT RULES:",
        f"• Traders: {mem.get('traders', {}).get('primary', 'David')} & {mem.get('traders', {}).get('partner', 'Cha Cha')}",
        f"• Approved Universe: {', '.join(rules.get('universe', []))}",
        f"• Overnight Policy: {rules.get('overnight_holding', 'Hold with server stops')}",
        f"• AI Execution Policy: {rules.get('ai_execution_policy', 'STRICTLY READ-ONLY')}",
        f"• Sizing & Risk: {rules.get('position_size', '0.10 lots / $25 max risk')}, Max {rules.get('max_concurrent_positions', 2)} positions",
    ]
    if lessons:
        lines.append("• Key Historical Lessons:")
        for l in lessons[-3:]:
            lines.append(f"  - {l}")
    if notes:
        lines.append("• Active User Notes:")
        for n in notes[-3:]:
            lines.append(f"  - {n}")

    return "\n".join(lines)
