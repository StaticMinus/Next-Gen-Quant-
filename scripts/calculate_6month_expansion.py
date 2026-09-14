"""
6-Month Maximum Expansion & Profit Forecast Calculator
======================================================
Models the progressive scaling from David's initial $6,000 FundedNext account
up to the maximum prop firm allocation ($300k on FundedNext + multi-firm to $500k+).
"""

LIVE_P2P_RATE = 1665.0  # USDT to NGN

months = [
    {
        "month": 1,
        "label": "Month 1 (Inaugural Launch)",
        "account_desc": "$6,000 Seed (Account #3028655)",
        "active_capital": 6000,
        "reinvest_cost": 0,
        "gross_pct": 0.075,  # 7.5% gross conservative monthly
        "split_pct": 0.85,
        "bonus": 90.0,  # 15% Phase 1 profit bonus ($600 * 15%)
        "scale_desc": "Baseline qualification, unlock 5-day payouts"
    },
    {
        "month": 2,
        "label": "Month 2 (1st Scale-Up)",
        "account_desc": "$56,000 ($6k base + $50k Stellar 1-Step)",
        "active_capital": 56000,
        "reinvest_cost": 329,  # Funded strictly from M1 profit
        "gross_pct": 0.065,
        "split_pct": 0.85,
        "bonus": 750.0,  # 15% Phase 1 bonus ($5,000 * 15%)
        "scale_desc": "Zero out-of-pocket upgrade to $50k account"
    },
    {
        "month": 3,
        "label": "Month 3 (Multi-Account Scaling)",
        "account_desc": "$106,000 ($6k + 2x $50k Stellar Accounts)",
        "active_capital": 106000,
        "reinvest_cost": 329,  # Funded strictly from M2 profit
        "gross_pct": 0.060,
        "split_pct": 0.85,
        "bonus": 750.0,  # 15% Phase 1 bonus on 2nd $50k
        "scale_desc": "Synchronized cTrader Remote MCP multi-account copy"
    },
    {
        "month": 4,
        "label": "Month 4 (Institutional Tier)",
        "account_desc": "$206,000 ($106k + $100k Stellar Account)",
        "active_capital": 206000,
        "reinvest_cost": 549,  # Funded strictly from M3 profit
        "gross_pct": 0.060,
        "split_pct": 0.85,
        "bonus": 1500.0,  # 15% Phase 1 bonus on $100k ($10,000 * 15%)
        "scale_desc": "Cross the $200k barrier; first 40% FundedNext scale-up window"
    },
    {
        "month": 5,
        "label": "Month 5 (FundedNext Ceiling)",
        "account_desc": "$306,000 ($206k + $100k Stellar - Max FN Limit)",
        "active_capital": 306000,
        "reinvest_cost": 549,  # Funded strictly from M4 profit
        "gross_pct": 0.060,
        "split_pct": 0.90,  # Payout scale-up to 90% profit split
        "bonus": 1500.0,  # 15% Phase 1 bonus on $100k
        "scale_desc": "Hit maximum single-trader ceiling on FundedNext ($300k+)"
    },
    {
        "month": 6,
        "label": "Month 6 (Multi-Firm Master Portfolio)",
        "account_desc": "$506,000 ($306k FN + $200k FTMO/Funding Pips)",
        "active_capital": 506000,
        "reinvest_cost": 1080,  # Funded strictly from M5 profit
        "gross_pct": 0.060,
        "split_pct": 0.90,  # 90% split across institutional tiers
        "bonus": 0.0,  # Fully funded ongoing distributions
        "scale_desc": "Institutional multi-firm syndicate under single cTrader gateway"
    }
]

def run_calc():
    cum_net_usdt = 0
    print("=" * 115)
    print(f"{'MONTH':<7} | {'CAPITAL':<10} | {'GROSS PnL':<11} | {'TRADER SPLIT':<13} | {'BONUS':<10} | {'REINVEST':<9} | {'NET TAKE-HOME (USDT)':<21} | {'NET NAIRA (NGN)':<18}")
    print("=" * 115)
    
    for row in months:
        gross = row["active_capital"] * row["gross_pct"]
        trader_pnl = gross * row["split_pct"]
        net_takehome = trader_pnl + row["bonus"] - row["reinvest_cost"]
        cum_net_usdt += net_takehome
        naira = net_takehome * LIVE_P2P_RATE
        cum_naira = cum_net_usdt * LIVE_P2P_RATE
        
        print(f"M{row['month']:<6} | ${row['active_capital']:<9,} | ${gross:<10,.2f} | ${trader_pnl:<12,.2f} | +${row['bonus']:<8,.2f} | -${row['reinvest_cost']:<7} | ${net_takehome:<20,.2f} | NGN {naira:<14,.0f}")
        print(f"   -> Sub-details: {row['account_desc']} // {row['scale_desc']}")
        print(f"   -> Cumulative to Date: ${cum_net_usdt:,.2f} USDT | NGN {cum_naira:,.0f}")
        print("-" * 115)

if __name__ == "__main__":
    run_calc()
