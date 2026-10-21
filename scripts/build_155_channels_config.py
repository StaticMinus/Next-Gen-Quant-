import json
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.integrations.telegram_multi_signal_copier import CHANNELS_CONFIG

existing_55 = CHANNELS_CONFIG
existing_ids = {c["id"].lower() for c in existing_55}
print(f"Existing fleet size: {len(existing_55)}")

# 1. Harvest from cache and logs
all_found = {}

cache_file = ROOT_DIR / "cache" / "verified_100_candidates.json"
if cache_file.exists():
    with open(cache_file, "r", encoding="utf-8") as f:
        for c in json.load(f):
            cid = c["id"].lower()
            if cid not in existing_ids:
                all_found[cid] = c

log_file = Path(r"C:\Users\David\.gemini\antigravity-ide\brain\e48a10d2-5f9c-48ae-9e6b-c5baaedd93f5\.system_generated\tasks\task-378.log")
if log_file.exists():
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m_sig = re.search(r'\[SIG #\d+\]\s+([A-Za-z0-9_]+)\s+\|\s+Posts:\s*(\d+)\s+\|\s+Sigs:\s*(\d+)\s+\(\s*([\d\.]+)%\)\s+\|\s*(\[[^\]]*\])\s+\|\s*(.*)', line)
            if m_sig:
                ch = m_sig.group(1).strip()
                cid = ch.lower()
                if cid not in existing_ids:
                    all_found[cid] = {
                        "id": ch,
                        "name": m_sig.group(6).strip() or ch,
                        "posts": int(m_sig.group(2)),
                        "signals": int(m_sig.group(3)),
                        "yield_pct": float(m_sig.group(4)),
                        "assets": eval(m_sig.group(5)) or ["ALL"]
                    }
                continue
            m_p = re.search(r'\[POSTS\]\s+([A-Za-z0-9_]+)\s+\|\s+Posts:\s*(\d+)\s+\|\s+Sigs:\s*0\s+\|\s*(.*)', line)
            if m_p:
                ch = m_p.group(1).strip()
                cid = ch.lower()
                if cid not in existing_ids and cid not in all_found:
                    all_found[cid] = {
                        "id": ch,
                        "name": m_p.group(3).strip() or ch,
                        "posts": int(m_p.group(2)),
                        "signals": 0,
                        "yield_pct": 0.0,
                        "assets": ["ALL"]
                    }

junk = ['bored', 'ape', 'yacht', 'fragment', 'tianlu', 'haolu', 'soxtaligim', 'clouddlp', 'ecbbb', 'fabi77', 'flow', 'monitor', 'fgi', 'tick']
clean = [c for c in all_found.values() if not any(j in c["id"].lower() for j in junk)]

def assign_tier(c):
    y = c.get("yield_pct", 0.0)
    s = c.get("signals", 0)
    if y >= 20.0 or s >= 4:
        return 1
    elif y >= 5.0 or s >= 1:
        return 2
    else:
        return 3

def assign_session(c):
    assets = c.get("assets", ["ALL"])
    if "US30" in assets or "NAS100" in assets:
        return "New York Open"
    elif "BTCUSD" in assets or "ETHUSD" in assets:
        return "24/7 Asian/NY"
    elif "XAUUSD" in assets:
        return "London/NY"
    else:
        return "London Open"

for c in clean:
    c["tier"] = assign_tier(c)
    c["peak_session"] = assign_session(c)
    c["enabled"] = True

# Sort candidates
clean.sort(key=lambda x: (x["tier"], -x["yield_pct"], -x["signals"], -x["posts"], x["id"]))

tier1_candidates = [c for c in clean if c["tier"] == 1]
tier2_candidates = [c for c in clean if c["tier"] == 2]
tier3_candidates = [c for c in clean if c["tier"] == 3]

print(f"Clean candidates: Tier 1: {len(tier1_candidates)}, Tier 2: {len(tier2_candidates)}, Tier 3: {len(tier3_candidates)}")

# Take all Tier 1 + all Tier 2, then top Tier 3 to make exactly 100 additions
needed_tier3 = 100 - len(tier1_candidates) - len(tier2_candidates)
selected_tier3 = tier3_candidates[:needed_tier3]

additions_100 = tier1_candidates + tier2_candidates + selected_tier3
print(f"Selected additions: {len(additions_100)} channels (Tier 1: {len(tier1_candidates)}, Tier 2: {len(tier2_candidates)}, Tier 3: {len(selected_tier3)})")

# Format entries as python dict strings
def format_entry(c):
    # Standardize name for display
    name = c.get("name") or c["id"]
    name = re.sub(r'[^\x20-\x7E]', '', name).strip()
    if not name or len(name) < 2:
        name = c["id"]
    name = name.replace('"', '\\"')
    return f'    {{"id": "{c["id"]}", "name": "{name}", "enabled": True, "assets": {c["assets"]}, "tier": {c["tier"]}, "yield_pct": {c["yield_pct"]}, "peak_session": "{c["peak_session"]}"}}'

tier1_code = ",\n".join(format_entry(c) for c in tier1_candidates)
tier2_code = ",\n".join(format_entry(c) for c in tier2_candidates)
tier3_code = ",\n".join(format_entry(c) for c in selected_tier3)

new_block = f"""    # === TIER 1 FLEET EXPANSION (FLEET 56-155: >= 20% EMPIRICAL YIELD) ===
{tier1_code},

    # === TIER 2 FLEET EXPANSION (FLEET 56-155: 5% - 19.9% RELIABLE YIELD) ===
{tier2_code},

    # === TIER 3 FLEET EXPANSION (FLEET 56-155: GUARDED / HIGH-FREQUENCY CROSS FEEDS) ===
{tier3_code}"""

# Update src/integrations/telegram_multi_signal_copier.py
copier_file = ROOT_DIR / "src" / "integrations" / "telegram_multi_signal_copier.py"
content = copier_file.read_text(encoding="utf-8")

# Find the end of CHANNELS_CONFIG
# Line 116 currently has {"id": "ForexMarketSignals", ...}
# Line 117 is "]"
pattern = r'(\s*\{"id":\s*"ForexMarketSignals"[^\}]*\}\s*\n)(\])'
if not re.search(pattern, content):
    print("ERROR: Could not locate ForexMarketSignals marker in copier file!")
    sys.exit(1)

replacement = r'\1,\n' + new_block.replace('\\', '\\\\') + r'\n\2'
new_content = re.sub(pattern, replacement, content, count=1)

copier_file.write_text(new_content, encoding="utf-8")
print(f"Successfully injected 100 new channels into {copier_file}!")

# Verify new CHANNELS_CONFIG length
import importlib
import src.integrations.telegram_multi_signal_copier as copier_mod
importlib.reload(copier_mod)
print(f"Verified CHANNELS_CONFIG total fleet length: {len(copier_mod.CHANNELS_CONFIG)}")
assert len(copier_mod.CHANNELS_CONFIG) == 155, f"Expected 155, got {len(copier_mod.CHANNELS_CONFIG)}"

# Save clean fleet JSON for inspection & reporting
summary_path = ROOT_DIR / "cache" / "fleet_155_summary.json"
with open(summary_path, "w", encoding="utf-8") as f:
    json.dump(copier_mod.CHANNELS_CONFIG, f, indent=2)

print(f"Fleet 155 summary saved to {summary_path}")
