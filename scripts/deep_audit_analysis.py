import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

from src.integrations.telegram_multi_signal_copier import MultiChannelSignalParser

DATA_DIR = Path("data/deep_channel_audits")

channels = [
    'ssfgold',
    'forexgdpfree',
    'learn2tradenews',
    'anabelsignals',
    'XAUUSD_GOLD_TRADING_FOREX'
]

report = {}

for ch in channels:
    f_path = DATA_DIR / f"{ch}_deep.json"
    if not f_path.exists(): continue
    with open(f_path, "r", encoding="utf-8") as f:
        posts = json.load(f)

    total_posts = len(posts)
    signals_found = []
    promos_spam_count = 0
    updates_celebrations = 0
    general_commentary = 0

    dates_signals = defaultdict(list)
    symbols_breakdown = defaultdict(int)

    for p in posts:
        pid = p["id"]
        dt_str = p.get("datetime", "")
        date_key = dt_str[:10] if dt_str else "Unknown_Date"
        text = p["text"]
        text_lower = text.lower()

        # Check if promotional / spam
        if any(w in text_lower for w in ["tournament", "investment", "double", "profit share", "vip group", "500$ to 8000$"]):
            promos_spam_count += 1
            continue

        if any(w in text_lower for w in ["running", "pips running", "boom", "close half", "congratulations", "tp1 hit", "tp2 hit"]):
            updates_celebrations += 1
            # Could also be an update

        sig = MultiChannelSignalParser.parse_message(text, ch)
        if sig:
            sig["post_id"] = pid
            sig["date"] = date_key
            signals_found.append(sig)
            dates_signals[date_key].append(sig)
            symbols_breakdown[sig["symbol"]] += 1
        else:
            general_commentary += 1

    unique_active_days = len([d for d in dates_signals.keys() if d != "Unknown_Date"])
    avg_per_day = len(signals_found) / max(1, unique_active_days) if unique_active_days > 0 else len(signals_found)

    report[ch] = {
        "total_messages_audited": total_posts,
        "valid_signals_extracted": len(signals_found),
        "promos_spam_filtered": promos_spam_count,
        "trade_updates_celebrations": updates_celebrations,
        "general_commentary": general_commentary,
        "symbols_traded": dict(symbols_breakdown),
        "signals_per_active_day_avg": round(avg_per_day, 1),
        "dates_with_signals": {k: len(v) for k, v in dates_signals.items()},
        "sample_signals": [
            {
                "symbol": s["symbol"],
                "side": s["side"],
                "entry": s.get("entry_mid"),
                "sl": s.get("sl"),
                "tps": s.get("tps")
            } for s in signals_found[:3]
        ]
    }

out_file = Path("data/deep_channel_audits/comprehensive_audit_report.json")
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)

print("\n================ COMPREHENSIVE SIGNAL AUDIT SUMMARY ================\n")
for ch, r in report.items():
    print(f"[{ch.upper()}]")
    print(f"  • Total Messages Audited: {r['total_messages_audited']}")
    print(f"  • Valid Actionable Signals: {r['valid_signals_extracted']}")
    print(f"  • Promos/Spam Filtered: {r['promos_spam_filtered']}")
    print(f"  • Updates/Celebrations: {r['trade_updates_celebrations']}")
    print(f"  • Average Signals/Active Day: ~{r['signals_per_active_day_avg']}")
    print(f"  • Assets Traded: {r['symbols_traded']}")
    print(f"  • Sample Signal: {r['sample_signals'][0] if r['sample_signals'] else 'None'}")
    print()
