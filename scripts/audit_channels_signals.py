import requests
import json
import re
from pathlib import Path

CHANNELS = [
    'ssfgold',
    'forexgdpfree',
    'anabelsignals',
    'XAUUSD_GOLD_TRADING_FOREX',
    'VasilyTrading',
    'dailyforex1',
    'fxstreetforex',
    'learn2tradenews'
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

def fetch_channel(ch: str):
    url = f"https://t.me/s/{ch}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        
        # Extract data-post and message text
        pattern = r'data-post="([^"]+)"[\s\S]*?<div class="tgme_widget_message_text[^>]*>([\s\S]*?)</div>'
        matches = re.findall(pattern, r.text)
        results = []
        for pid, raw_html in matches:
            clean = re.sub(r'<br\s*/?>', '\n', raw_html)
            clean = re.sub(r'<[^>]+>', '', clean).strip()
            if clean:
                results.append({'id': pid, 'text': clean})
        return results
    except Exception as e:
        print(f"Error fetching {ch}: {e}")
        return []

def main():
    output_dir = Path("data/channel_audits")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    summary = {}
    for ch in CHANNELS:
        posts = fetch_channel(ch)
        print(f"[{ch}] Extracted {len(posts)} messages")
        out_file = output_dir / f"{ch}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(posts, f, indent=2, ensure_ascii=False)
        summary[ch] = len(posts)
        
    print("\nExtraction Summary:")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
