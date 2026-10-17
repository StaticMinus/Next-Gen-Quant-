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
        "account_id": "5942153",
        "model": "Stellar 1-Step ($6,000)",
        "initial_capital": 6000.0,
        "profit_target": 480.0,
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
        "universe": ["Spot Gold (XAUUSD • symbolId 41)"],
        "strategy_name": "Telegram Gold Copier (Mode A: TP1 & TP2)",
        "signal_source": "t.me/XAUUSD_GOLD_TRADING_FOREX (0-Latency MTProto Push)",
        "max_concurrent_positions": 2,
        "position_size": "0.07 lot per ticket (TP1 +10 pts / TP2 +20 pts, 0.14 lot total)",
        "stop_loss_type": "Server-side hard stop clamped to max 10.0 pts (-$70/ticket, $140 max daily risk)",
        "breakeven_shield": "Automatic Breakeven (+0.30pt commission buffer) moved on Ticket 2 when Ticket 1 hits TP1",
        "anti_chase_guard": "2.50 pts max price deviation limit from signal entry",
        "spread_filter": "Max 1.50 pts broker spread limit",
        "circuit_breaker": "Daily Drawdown Floor $5,650.00 USD strict equity halt",
        "ai_execution_policy": "STRICTLY READ-ONLY - AI Coach has ZERO order execution or trade modification ability. All execution is strictly algorithmic."
    },
    "learned_lessons": [
        "Gold Telegram Copier: Mode A (2 Tickets: TP1 & TP2, 0.07 lot each = 0.14 lot total) provides maximum safe velocity to pass the $6,000 challenge in 4-6 winning trading days while strictly respecting the $180 daily drawdown floor.",
        "Breakeven Shield Discipline: Moving Ticket 2 to Entry + 0.30pt buffer upon TP1 hit completely eliminates risk on the runner while covering cTrader commissions.",
        "Anti-Chase Guard: Rejecting entries slipped > 2.50 pts from channel call prevents chasing late spikes and protects prop firm drawdown."
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
        for item in lessons[-3:]:
            lines.append(f"  - {item}")
    if notes:
        lines.append("• Active User Notes:")
        for n in notes[-3:]:
            lines.append(f"  - {n}")

    return "\n".join(lines)
