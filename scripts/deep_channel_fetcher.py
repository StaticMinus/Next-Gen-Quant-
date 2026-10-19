import requests
import json
import re
import time
from pathlib import Path
from datetime import datetime

CHANNELS = [
    'ssfgold',
    'forexgdpfree',
    'learn2tradenews',
    'anabelsignals',
    'XAUUSD_GOLD_TRADING_FOREX'
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

def fetch_channel_history(channel: str, pages: int = 5):
    """
    Paginates backwards through public Telegram channel preview using ?before=
    to gather a deep historical dataset.
    """
    all_messages = {}
    url = f"https://t.me/s/{channel}"
    
    for page in range(pages):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                print(f"[{channel}] Page {page+1} HTTP {r.status_code}")
                break
                
            # Extract data-post, message text, and timestamp
            pattern = r'data-post="([^"]+)"[\s\S]*?<time[^>]*datetime="([^"]*)"[^>]*>[\s\S]*?<div class="tgme_widget_message_text[^>]*>([\s\S]*?)</div>'
            matches = re.findall(pattern, r.text)
            if not matches:
                # Fallback if time tag is differently structured
                pattern_fallback = r'data-post="([^"]+)"[\s\S]*?<div class="tgme_widget_message_text[^>]*>([\s\S]*?)</div>'
                matches_fallback = re.findall(pattern_fallback, r.text)
                for pid, raw_html in matches_fallback:
                    if pid not in all_messages:
                        clean = re.sub(r'<br\s*/?>', '\n', raw_html)
                        clean = re.sub(r'<[^>]+>', '', clean).strip()
                        all_messages[pid] = {'id': pid, 'datetime': '', 'text': clean}
            else:
                for pid, dt_str, raw_html in matches:
                    if pid not in all_messages:
                        clean = re.sub(r'<br\s*/?>', '\n', raw_html)
                        clean = re.sub(r'<[^>]+>', '', clean).strip()
                        all_messages[pid] = {'id': pid, 'datetime': dt_str, 'text': clean}
            
            # Find the lowest post ID to paginate backwards
            post_nums = []
            for pid in all_messages.keys():
                try:
                    num = int(pid.split('/')[-1])
                    post_nums.append(num)
                except Exception:
                    pass
            
            if not post_nums:
                break
                
            min_num = min(post_nums)
            url = f"https://t.me/s/{channel}?before={min_num}"
            time.sleep(1)
        except Exception as e:
            print(f"[{channel}] Error page {page}: {e}")
            break
            
    return list(all_messages.values())

def main():
    out_dir = Path("data/deep_channel_audits")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    summary = {}
    for ch in CHANNELS:
        print(f"Fetching deep history for {ch}...")
        msgs = fetch_channel_history(ch, pages=4)
        out_file = out_dir / f"{ch}_deep.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(msgs, f, indent=2, ensure_ascii=False)
        summary[ch] = len(msgs)
        print(f"[{ch}] Saved {len(msgs)} messages.")
        
    print("\nDeep History Summary:")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
