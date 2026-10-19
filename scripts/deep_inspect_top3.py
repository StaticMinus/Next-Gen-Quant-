import json
from pathlib import Path

channels = ['ssfgold', 'forexgdpfree', 'learn2tradenews']

for ch in channels:
    p = Path(f"data/channel_audits/{ch}.json")
    if not p.exists(): continue
    with open(p, "r", encoding="utf-8") as f:
        posts = json.load(f)
    print(f"\n==================== FULL POSTS FOR {ch} ====================")
    for i, post in enumerate(posts):
        print(f"--- POST {i+1} (ID: {post['id']}) ---")
        print(post['text'])
        print()
