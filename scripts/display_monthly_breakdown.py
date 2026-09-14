"""
Display full 10-year monthly breakdown tables for SPY vs Dual-Asset Scalper
"""
import json
import pandas as pd

with open("results/spy_vs_dual_scalper_10year_monthly.json", "r", encoding="utf-8") as f:
    data = json.load(f)

records = data["monthly_records"]
df = pd.DataFrame(records)

print("\n=== ALL 120 MONTHS: PROFIT & TRADES (2016 - 2026) ===")
print(f"{'Month':<8} | {'SPY Trades':<10} {'SPY Profit ($)':<15} | {'Dual Trades':<11} {'Dual Profit ($)':<16} | {'Status':<15}")
print("-" * 75)

for _, r in df.iterrows():
    m = r["month"]
    st = r["spy_trades"]
    sp = r["spy_pnl"]
    dt = r["dual_trades"]
    dp = r["dual_pnl"]
    
    status = "Both Active" if (st > 0 and dt > st) else ("SPY Active" if st > 0 else ("QQQ Only" if dt > 0 else "Zero Trades"))
    print(f"{m:<8} | {st:<10} ${sp:<14.2f} | {dt:<11} ${dp:<15.2f} | {status:<15}")

print("-" * 75)
