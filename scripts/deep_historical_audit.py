import json
import re
import sys
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.integrations.telegram_gold_copier import TelegramGoldCopier

def run_deep_audit():
    copier = TelegramGoldCopier(dry_run=True)
    
    out_file = ROOT_DIR / "cache" / "scraped_channel_history.json"
    if out_file.exists():
        print(f"Loading cached history from {out_file}...", flush=True)
        with open(out_file, "r", encoding="utf-8") as f:
            all_messages = json.load(f)
    else:
        url = "https://t.me/s/XAUUSD_GOLD_TRADING_FOREX"
        all_messages = []
        current_url = url
        
        print("Scraping channel pages...", flush=True)
        for page in range(25):
            try:
                resp = requests.get(current_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                if resp.status_code != 200:
                    break
                soup = BeautifulSoup(resp.text, "html.parser")
                wraps = soup.find_all("div", class_="tgme_widget_message_wrap")
                if not wraps:
                    break
                for w in wraps:
                    msg_div = w.find("div", class_="tgme_widget_message")
                    if not msg_div:
                        continue
                    post_id = msg_div.get("data-post")
                    txt_div = w.find("div", class_="tgme_widget_message_text")
                    text = txt_div.get_text(separator=" ").strip() if txt_div else ""
                    time_tag = w.find("time")
                    dt = time_tag.get("datetime") if time_tag else ""
                    if post_id and text:
                        all_messages.append({"post_id": post_id, "text": text, "datetime": dt})
                
                prev_link = soup.find("a", class_="tme_messages_more")
                if prev_link and "before=" in prev_link.get("href", ""):
                    current_url = "https://t.me" + prev_link.get("href")
                else:
                    break
            except Exception as e:
                print(f"Error on page {page}: {e}", flush=True)
                break
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(all_messages, f, indent=2)
            
    # Deduplicate
    unique = {}
    for m in all_messages:
        unique[m["post_id"]] = m
        
    print(f"Total unique messages scraped: {len(unique)}", flush=True)
    
    # Save raw messages for analysis
    out_file = ROOT_DIR / "cache" / "scraped_channel_history.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(list(unique.values()), f, indent=2)
        
    print(f"Saved to {out_file}", flush=True)
    
    # Analyze by date
    parsed_signals = []
    unparsed_candidates = []
    
    for pid, m in sorted(unique.items(), key=lambda x: x[1].get("datetime") or ""):
        dt = m.get("datetime") or ""
        txt = m.get("text") or ""
        
        # Test with copier's parser
        sig, reason = copier.parse_and_validate_signal(txt, current_spot=None)
        
        if sig:
            parsed_signals.append({"post_id": pid, "datetime": dt, "signal": sig, "raw": txt})
        else:
            # Check if this might have been an intended trade signal that was missed
            if any(w in txt.upper() for w in ["BUY", "SELL", "XAUUSD", "GOLD", "ENTRY", "SL", "TP"]) and not any(w in txt.lower() for w in ["shering", "profit share", "vip"]):
                unparsed_candidates.append({"post_id": pid, "datetime": dt, "reason": reason, "raw": txt})
                
    print(f"Successfully parsed signals: {len(parsed_signals)}", flush=True)
    print(f"Unparsed candidate messages: {len(unparsed_candidates)}", flush=True)
    
    # Group parsed signals by date
    by_date = {}
    for s in parsed_signals:
        d = s["datetime"][:10] if s["datetime"] else "Unknown"
        by_date.setdefault(d, []).append(s)
        
    print("\n--- PARSED SIGNALS BY DATE ---", flush=True)
    for d, sigs in sorted(by_date.items()):
        print(f"\nDate: {d} ({len(sigs)} signals):", flush=True)
        for s in sigs:
            sig_info = s["signal"]
            print(f"  [{s['datetime']}] {sig_info['side']} @ {sig_info['entry']} | SL: {sig_info['safe_sl']} | TPs: {sig_info['tps']}", flush=True)
            print(f"     Raw: {s['raw'][:80]}...", flush=True)
            
    print("\n--- UNPARSED CANDIDATES (POTENTIAL MISSED SIGNALS) ---", flush=True)
    for u in unparsed_candidates[:30]:
        print(f"\n[{u['datetime']}] Reason: {u['reason']}", flush=True)
        print(f"  Raw: {u['raw']}", flush=True)

if __name__ == "__main__":
    run_deep_audit()
