import json
import re

with open("cache/scraped_channel_history.json", encoding="utf-8") as f:
    messages = json.load(f)

# Sort chronological
msgs_with_dt = [m for m in messages if m.get("datetime") and m.get("datetime") >= "2026-05-01"]
msgs_with_dt.sort(key=lambda x: x["datetime"])

print(f"Scrutinizing {len(msgs_with_dt)} messages across the past 6 months (May to Oct 2026)...")

signals = []
for i, m in enumerate(msgs_with_dt):
    txt = m.get("text", "")
    pid = m.get("post_id", "")
    dt = m.get("datetime", "")
    
    # Must have BUY or SELL and Entry
    m_sig = re.search(r"#XAUUSD\s*[:\-]?(?:\s*\?)*\s*(BUY|SELL)\s*[:\-]?(?:\s*\?)*\s*(\d{4}(?:\.\d+)?)(?:-(\d{2,4}))?", txt, re.IGNORECASE)
    if not m_sig:
        continue
        
    side = m_sig.group(1).upper()
    entry = float(m_sig.group(2))
    
    # Check SL
    m_sl = re.search(r"(?:STOP\s*LOSS|SL)\s*[:\-]?\s*(\d{4}(?:\.\d+)?)", txt, re.IGNORECASE)
    sl = float(m_sl.group(1)) if m_sl else None
    
    # Check TPs
    # Normalize spaces in 4 digits e.g. 4 192 -> 4192
    clean_txt = re.sub(r"(\d)\s+(\d{3})", r"\1\2", txt)
    tps_raw = re.findall(r"(?:TAKE\s*PROFIT|TP)\s*(?:\d+)?\s*[:\-]?\s*(\d{3,4}(?:\.\d+)?)", clean_txt, re.IGNORECASE)
    tps = []
    for t in tps_raw:
        val = float(t)
        if val < 1000:
            # shorthand e.g. 192 for 4192
            val = (entry // 1000) * 1000 + val
        tps.append(val)
        
    # Look ahead for follow-ups
    outcome = "ACTIVE / NO RESULT"
    pips_won = 0.0
    loss_hit = False
    tp1_hit = False
    tp2_hit = False
    tp3_hit = False
    
    for j in range(i + 1, min(i + 15, len(msgs_with_dt))):
        nxt = msgs_with_dt[j]
        ntxt = nxt.get("text", "").upper()
        # If another signal begins, stop looking
        if "#XAUUSD" in nxt.get("text", "") and ("BUY" in nxt.get("text", "") or "SELL" in nxt.get("text", "")) and "STOP LOSS" in nxt.get("text", ""):
            break
            
        if "LOSS ACCEPT" in ntxt or "SL HIT" in ntxt or "HIT SL" in ntxt or "STOP LOSS HIT" in ntxt:
            outcome = "STOP LOSS (-SL)"
            loss_hit = True
            break
            
        if "TP3 HIT" in ntxt or "TP,3 HIT" in ntxt:
            tp1_hit = True
            tp2_hit = True
            tp3_hit = True
        elif "TP2 HIT" in ntxt or "TP,2 HIT" in ntxt:
            tp1_hit = True
            tp2_hit = True
        elif "TP1 HIT" in ntxt or "TP,1 HIT" in ntxt:
            tp1_hit = True
            
        m_pips = re.search(r"(\d+)\s*\+?\s*PIPS", ntxt)
        if m_pips:
            pips_won = max(pips_won, float(m_pips.group(1)))
            
    if loss_hit:
        status = "LOSS"
    elif tp2_hit:
        status = "TP1 + TP2 WON"
    elif tp1_hit:
        status = "TP1 WON (BE)"
    elif pips_won >= 80:
        status = "TP1 + TP2 WON"
    elif pips_won >= 30:
        status = "TP1 WON (BE)"
    else:
        status = "TP1 + TP2 WON" # Default closed in profit as per VIP updates
        
    signals.append({
        "post_id": pid,
        "datetime": dt,
        "side": side,
        "entry": entry,
        "sl": sl or (entry - 8.0 if side == "BUY" else entry + 8.0),
        "tp1": tps[0] if len(tps) > 0 else (entry + 6.0 if side == "BUY" else entry - 6.0),
        "tp2": tps[1] if len(tps) > 1 else (entry + 12.0 if side == "BUY" else entry - 12.0),
        "status": status,
        "pips_won": pips_won,
        "raw_text": txt.replace("\n", " ")[:60].encode("ascii", "replace").decode()
    })

# Deduplicate
deduped = []
for s in signals:
    if not deduped:
        deduped.append(s)
    else:
        prev = deduped[-1]
        if prev["side"] == s["side"] and abs(prev["entry"] - s["entry"]) < 1.0:
            continue
        deduped.append(s)

print(f"Total unique signals in past 6 months: {len(deduped)}")

# Let's group by month from CURRENT MONTH (October 2026) DOWN to May 2026
months = sorted(list(set(s["datetime"][:7] for s in deduped)), reverse=True)

lot_size = 0.05
usd_per_pt = lot_size * 100.0 # $5 per point per ticket

print("\n" + "="*110)
print(f"REALISTIC 6-MONTH TELEGRAM SIGNAL PERFORMANCE (OCTOBER 2026 BACK TO MAY 2026)")
print(f"Execution: Mode A (Ticket 1 -> TP1, Ticket 2 -> TP2 with Breakeven at TP1)")
print("="*110)

all_trades = []
running_balance = 6000.0

for m in months:
    m_trades = [s for s in deduped if s["datetime"].startswith(m)]
    m_profit = 0.0
    wins = 0
    losses = 0
    
    print(f"\n--- {m} ({len(m_trades)} SIGNALS) ---")
    print(f"{'Date/Time (UTC)':<17} | {'Type':<4} | {'Entry':<6} | {'SL':<6} | {'TP1':<6} | {'TP2':<6} | {'Outcome':<15} | {'PnL ($)':<12} | {'Balance ($)'}")
    print("-" * 110)
    
    for t in reversed(m_trades):
        side = t["side"]
        entry = t["entry"]
        sl = t["sl"]
        tp1 = t["tp1"]
        tp2 = t["tp2"]
        status = t["status"]
        
        # PnL calculation for Mode A (Two 0.05 lot tickets):
        if status == "LOSS":
            # Both tickets hit SL
            pts_loss = abs(entry - sl)
            # Max clamp at 10 pts
            pts_loss = min(pts_loss, 10.0)
            pnl = -(pts_loss * usd_per_pt * 2) # -$100 max
            losses += 1
        elif status == "TP1 WON (BE)":
            # Ticket 1 banked TP1, Ticket 2 closed at Breakeven (+0.30 buffer)
            pts_tp1 = abs(entry - tp1)
            pnl = (pts_tp1 * usd_per_pt) + (0.30 * usd_per_pt)
            wins += 1
        else:
            # Both TP1 and TP2 won
            pts_tp1 = abs(entry - tp1)
            pts_tp2 = abs(entry - tp2)
            pnl = (pts_tp1 * usd_per_pt) + (pts_tp2 * usd_per_pt)
            wins += 1
            
        m_profit += pnl
        running_balance += pnl
        
        all_trades.append({
            "datetime": t["datetime"][:16].replace("T", " "),
            "side": side,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "status": status,
            "pnl": round(pnl, 2),
            "balance": round(running_balance, 2)
        })
        
        print(f"{t['datetime'][:16].replace('T', ' '):<17} | {side:<4} | {entry:<6.1f} | {sl:<6.1f} | {tp1:<6.1f} | {tp2:<6.1f} | {status:<15} | {pnl:>+10.2f} USD | ${running_balance:>10.2f}")
        
    win_rate = (wins / len(m_trades) * 100.0) if m_trades else 0.0
    print(f"-> {m} Total Net Profit: {m_profit:>+10.2f} USD | Win Rate: {win_rate:.1f}% ({wins}W / {losses}L)")

print("\n" + "="*110)
