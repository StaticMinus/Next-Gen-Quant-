"""
src/integrations/macro_calendar.py
─────────────────────────────────────────────────────────────────────────────
Macro & Economic Calendar Awareness Engine for AgentQuant.
Tracks high-impact macroeconomic events (FOMC, CPI, NFP, PCE) to inform the AI Coach
and the Quant Council on systemic market volatility.
"""

from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

# Major recurring high-impact releases schedule for reference
MACRO_EVENTS_2026_2027 = [
    # 2026 High Impact Highlights
    {"name": "FOMC Interest Rate Decision & Press Conference", "type": "FOMC", "date": "2026-09-23", "impact": "CRITICAL"},
    {"name": "US Non-Farm Payrolls (NFP) & Unemployment", "type": "NFP", "date": "2026-10-02", "impact": "HIGH"},
    {"name": "US Consumer Price Index (CPI) Inflation", "type": "CPI", "date": "2026-10-14", "impact": "HIGH"},
    {"name": "FOMC Interest Rate Decision", "type": "FOMC", "date": "2026-11-04", "impact": "CRITICAL"},
    {"name": "US Non-Farm Payrolls (NFP)", "type": "NFP", "date": "2026-11-06", "impact": "HIGH"},
    {"name": "US Consumer Price Index (CPI) Inflation", "type": "CPI", "date": "2026-11-12", "impact": "HIGH"},
    {"name": "FOMC Interest Rate Decision & Projections", "type": "FOMC", "date": "2026-12-16", "impact": "CRITICAL"},
    {"name": "US Core PCE Price Index", "type": "PCE", "date": "2026-12-23", "impact": "MEDIUM"},
]


def get_upcoming_macro_events(days_ahead: int = 30) -> List[Dict]:
    """Returns list of upcoming high-impact events within the lookahead window."""
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    upcoming = []

    for ev in MACRO_EVENTS_2026_2027:
        try:
            ev_date = datetime.strptime(ev["date"], "%Y-%m-%d").date()
            if today <= ev_date <= cutoff:
                days_until = (ev_date - today).days
                ev_copy = dict(ev)
                ev_copy["days_until"] = days_until
                upcoming.append(ev_copy)
        except Exception:
            continue

    # Sort by nearest date
    upcoming.sort(key=lambda x: x["days_until"])
    return upcoming


def get_macro_calendar_summary() -> str:
    """
    Generates a high-signal, concise macro briefing string for the AI Coach and Council.
    """
    upcoming = get_upcoming_macro_events(days_ahead=21)
    today = date.today()
    now_str = today.strftime("%A, %b %d, %Y")

    if not upcoming:
        return (
            f"MACROECONOMIC CALENDAR [{now_str}]:\n"
            "• Current Environment: Clear macro runway (No tier-1 FOMC or CPI events in the next 7 days).\n"
            "• Market Regime: Technical mean-reversion and trend continuation strategies operating with standard variance."
        )

    lines = [f"MACROECONOMIC CALENDAR TELEMETRY [{now_str}]:"]
    immediate_risk = False
    for ev in upcoming[:3]:
        days = ev["days_until"]
        if days == 0:
            when_str = "TODAY"
            immediate_risk = True
        elif days == 1:
            when_str = "TOMORROW"
            immediate_risk = True
        else:
            when_str = f"in {days} days ({ev['date']})"
        lines.append(f"• {ev['impact']} IMPACT: {ev['name']} — {when_str}")

    if immediate_risk:
        lines.append("• Macro Volatility Posture: ELEVATED ALERT — High-impact data release imminent. Ensure -$25 server stop loss is firmly in place.")
    else:
        lines.append("• Macro Volatility Posture: NORMAL — Standard trading conditions across SPY, QQQ, DIA, IWM.")

    return "\n".join(lines)
