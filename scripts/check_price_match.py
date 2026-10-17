import json
import pandas as pd
import yfinance as yf

df = yf.download('GC=F', start='2026-04-01', end='2026-10-18', interval='1h')
df.index = df.index.tz_convert('UTC')

with open('cache/scraped_channel_history.json', encoding='utf-8') as f:
    msgs = json.load(f)

print(f"Total messages: {len(msgs)}")
for m in msgs:
    dt_str = m.get('datetime')
    if not dt_str:
        continue
    txt = m.get('text', '')
    if 'BUY' in txt or 'SELL' in txt:
        dt = pd.to_datetime(dt_str)
        hist = df.loc[df.index <= dt]
        if len(hist) > 0:
            market_price = hist['Close'].values[-1]
            if hasattr(market_price, '__iter__'):
                market_price = market_price[0]
            clean_txt = txt.replace('\n', ' ')[:50].encode('ascii', 'replace').decode()
            print(f"{dt_str[:16]} | Market: {market_price:.1f} | Text: {clean_txt}")
