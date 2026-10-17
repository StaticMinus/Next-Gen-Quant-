import json

with open("cache/scraped_channel_history.json", encoding="utf-8") as f:
    msgs = json.load(f)

print(f"Total posts: {len(msgs)}")
for m in msgs[-35:]:
    pid = m.get("post_id", "")
    dt = m.get("datetime", "")[:16]
    txt = m.get("text", "").replace("\n", " ")[:90]
    safe_txt = txt.encode("ascii", "replace").decode()
    print(f"{pid:<30} | {dt} | {safe_txt}")
