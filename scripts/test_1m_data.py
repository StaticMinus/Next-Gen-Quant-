import sys
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

def test_fetch():
    print("Testing 1m fetch...")
    # Yahoo allows up to 7 days per 1m call, within last 30 days
    # Let's see if period='7d' or period='1mo' works
    for period in ["7d", "30d", "1mo"]:
        try:
            df = yf.download("SPY", period=period, interval="1m", progress=False)
            print(f"Period {period}: {len(df)} rows. Range: {df.index[0] if len(df) else 'None'} -> {df.index[-1] if len(df) else 'None'}")
        except Exception as e:
            print(f"Period {period} failed: {e}")

if __name__ == "__main__":
    test_fetch()
