import json
import re

with open("cache/scraped_channel_history.json", encoding="utf-8") as f:
    messages = json.load(f)

print(f"Total posts: {len(messages)}")

# Let's extract all signals and look at the messages following each signal
signals = []
for i, m in enumerate(messages):
    text = m.get("text", "")
    pid = m.get("post_id", "")
    dt = m.get("datetime")
    
    # Check if this post is a signal
    m_sig = re.search(r"#XAUUSD\s*[:\-]?(?:\s*\?)*\s*(BUY|SELL)\s*[:\-]?(?:\s*\?)*\s*(\d{4}(?:\.\d+)?)(?:-(\d{2,4}))?", text, re.IGNORECASE)
    if m_sig:
        side = m_sig.group(1).upper()
        entry = float(m_sig.group(2))
        
        # Check SL
        m_sl = re.search(r"(?:STOP\s*LOSS|SL)\s*[:\-]?\s*(\d{4}(?:\.\d+)?)", text, re.IGNORECASE)
        sl = float(m_sl.group(1)) if m_sl else None
        
        # Check TPs
        tps = [float(p.replace(" ", "")) for p in re.findall(r"(?:TAKE\s*PROFIT|TP)\s*(?:\d+)?\s*[:\-]?\s*(\d{1,2}\s*\d{2,3}(?:\.\d+)?)", text, re.IGNORECASE)]
        
        # Look ahead at the next 10 messages for outcome/hits
        followups = []
        for j in range(i + 1, min(i + 12, len(messages))):
            next_m = messages[j]
            next_txt = next_m.get("text", "")
            if "#XAUUSD" in next_txt and ("BUY" in next_txt or "SELL" in next_txt) and ("STOP LOSS" in next_txt or "SL" in next_txt):
                # Another signal started, stop lookahead
                break
            if any(k in next_txt.lower() for k in ["hit", "running", "sl", "loss", "closed", "boom"]):
                followups.append(next_txt.replace("\n", " ")[:60].encode("ascii", "replace").decode())
        
        signals.append({
            "idx": i,
            "post_id": pid,
            "datetime": dt,
            "side": side,
            "entry": entry,
            "sl": sl,
            "tps": tps,
            "followups": followups,
            "raw": text.replace("\n", " ")[:70].encode("ascii", "replace").decode()
        })

print(f"Detected {len(signals)} raw signals.")

# Deduplicate identical consecutive broadcasts
unique_signals = []
for s in signals:
    if not unique_signals:
        unique_signals.append(s)
    else:
        prev = unique_signals[-1]
        if prev["side"] == s["side"] and abs(prev["entry"] - s["entry"]) < 1.0:
            # same trade re-broadcast
            continue
        unique_signals.append(s)

print(f"Unique signals: {len(unique_signals)}")

# Print from newest (October 2026) backwards to April 2026
print("\n" + "="*100)
print(f"{'Date':<16} | {'Side':<4} | {'Entry':<6} | {'SL':<6} | {'TP1':<6} | {'TP2':<6} | {'Follow-ups / Results Reported in Channel'}")
print("="*100)

for s in reversed(unique_signals):
    dt_str = s['datetime'][:16] if s['datetime'] else "Unknown"
    tp1 = s['tps'][0] if len(s['tps']) > 0 else 0
    tp2 = s['tps'][1] if len(s['tps']) > 1 else 0
    fu_str = " | ".join(s['followups']) if s['followups'] else "No immediate channel update"
    print(f"{dt_str:<16} | {s['side']:<4} | {s['entry']:<6.1f} | {s['sl'] or 0:<6.1f} | {tp1:<6.1f} | {tp2:<6.1f} | {fu_str}")
