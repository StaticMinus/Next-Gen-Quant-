import json
from pathlib import Path

audit_dir = Path("data/channel_audits")

for json_file in audit_dir.glob("*.json"):
    ch_name = json_file.stem
    with open(json_file, "r", encoding="utf-8") as f:
        posts = json.load(f)
    print(f"\n{'='*20} {ch_name} (Total: {len(posts)}) {'='*20}")
    for idx, p in enumerate(posts[:5]):
        txt = p['text'].replace('\n', ' ')
        if len(txt) > 160:
            txt = txt[:160] + "..."
        print(f"[{idx+1}] {txt}")
