import sys
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

def test_chunks():
    now = datetime.now()
    all_chunks = []
    
    for i in range(4):
        end_date = now - timedelta(days=i*7)
        start_date = end_date - timedelta(days=7)
        print(f"Fetching chunk {i+1}: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}...")
        try:
            df = yf.download("SPY", start=start_date.strftime('%Y-%m-%d'), end=end_date.strftime('%Y-%m-%d'), interval="1m", progress=False)
            if not df.empty:
                print(f"  -> Got {len(df)} rows. Range: {df.index[0]} to {df.index[-1]}")
                all_chunks.append(df)
            else:
                print("  -> Empty")
        except Exception as e:
            print(f"  -> Error: {e}")
            
    if all_chunks:
        full_df = pd.concat(all_chunks).sort_index().drop_duplicates()
        print(f"\nTotal combined 1m bars: {len(full_df)}")
        print(f"Full range: {full_df.index[0]} to {full_df.index[-1]}")

if __name__ == "__main__":
    test_chunks()
