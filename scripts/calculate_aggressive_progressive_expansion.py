"""
Aggressive Maximum Capital Expansion & Profit Forecast Calculator
==================================================================
Models the aggressive reinvestment trajectory where David adds accounts
at maximum capacity each month until hitting the hard regulatory limits
of FundedNext, FTMO, and Funding Pips.
"""

LIVE_P2P_RATE = 1365.0  # USDT/NGN Benchmark

months = [
    {
        "month": 1,
        "label": "Month 1 (Seed Incubation)",
        "capital": 6000,
        "fn_cap": 6000,
        "ftmo_cap": 0,
        "fp_cap": 0,
        "accounts_added": "None (Active #3028655)",
        "reinvest_cost": 0,
        "gross_pct": 0.075,
        "gross_pnl": 450.0,
        "trader_split": 382.50,  # 85%
        "bonus": 90.0,  # 15% Phase 1 bonus on $600
        "note": "Baseline qualification on $6k Stellar 1-Step. Unlock weekly payouts."
    },
    {
        "month": 2,
        "label": "Month 2 (1st Expansion)",
        "capital": 56000,
        "fn_cap": 56000,
        "ftmo_cap": 0,
        "fp_cap": 0,
        "accounts_added": "+1x $50k Stellar Account",
        "reinvest_cost": 329,
        "gross_pct": 0.065,
        "gross_pnl": 3640.0,
        "trader_split": 3094.0,  # 85%
        "bonus": 750.0,  # 15% Phase 1 bonus on $5,000
        "note": "Reinvest $329 from M1 payout ($472.50). $0 out-of-pocket."
    },
    {
        "month": 3,
        "label": "Month 3 (The 4x $50k Surge)",
        "capital": 256000,
        "fn_cap": 256000,
        "ftmo_cap": 0,
        "fp_cap": 0,
        "accounts_added": "+4x $50k Stellar Accounts",
        "reinvest_cost": 1316,  # 4 * $329
        "gross_pct": 0.060,
        "gross_pnl": 15360.0,
        "trader_split": 13056.0,  # 85%
        "bonus": 3000.0,  # 4 * $750 bonus!
        "note": "Reinvest $1,316 from M2 payout ($3,515). Collect 4x $750 cash bonus!"
    },
    {
        "month": 4,
        "label": "Month 4 (Max FN + FTMO Entry)",
        "capital": 506000,
        "fn_cap": 306000,  # Maxed FundedNext!
        "ftmo_cap": 200000,
        "fp_cap": 0,
        "accounts_added": "+1x $50k FN (Max Limit) & +1x $200k FTMO",
        "reinvest_cost": 1409,  # $329 + $1080
        "gross_pct": 0.060,
        "gross_pnl": 30360.0,
        "trader_split": 25806.0,  # 85%
        "bonus": 750.0,  # Bonus on final FN $50k
        "note": "Hit FundedNext $300k ceiling! Branch into FTMO with $200k account."
    },
    {
        "month": 5,
        "label": "Month 5 (Max FTMO + Funding Pips)",
        "capital": 906000,
        "fn_cap": 306000,  # Maxed
        "ftmo_cap": 400000,  # Maxed FTMO!
        "fp_cap": 200000,
        "accounts_added": "+1x $200k FTMO (Max Limit) & +2x $100k Funding Pips",
        "reinvest_cost": 1980,  # $1080 + $900
        "gross_pct": 0.060,
        "gross_pnl": 54360.0,
        "trader_split": 48924.0,  # 90% tier unlocked across accounts
        "bonus": 0.0,
        "note": "Hit FTMO $400k ceiling! 90% profit split across institutional tiers."
    },
    {
        "month": 6,
        "label": "Month 6 (All Firms 100% Maxed)",
        "capital": 1126000,  # Over $1.12 Million!
        "fn_cap": 426000,  # $306k + 40% Scale-Up bonus (+120k free!)
        "ftmo_cap": 400000,  # Maxed
        "fp_cap": 300000,  # Maxed Funding Pips!
        "accounts_added": "+1x $100k Funding Pips & FN 40% Scale Boost (+120k)",
        "reinvest_cost": 450,  # FP $100k fee
        "gross_pct": 0.060,
        "gross_pnl": 67560.0,
        "trader_split": 60804.0,  # 90% split
        "bonus": 0.0,
        "note": "ALL 3 TOP FIRMS 100% MAXED. FundedNext 40% organic scale boost added!"
    }
]

def run():
    cum_net_usdt = 0
    print("=" * 125)
    print(f"{'MONTH':<7} | {'TOTAL CAPITAL':<13} | {'PORTFOLIO BREAKDOWN':<28} | {'GROSS PnL':<10} | {'REINVEST':<9} | {'NET TAKE-HOME (USDT)':<20} | {'NET NAIRA (NGN)':<18}")
    print("=" * 125)

    for r in months:
        net = r["trader_split"] + r["bonus"] - r["reinvest_cost"]
        cum_net_usdt += net
        naira = net * LIVE_P2P_RATE
        cum_naira = cum_net_usdt * LIVE_P2P_RATE
        breakdown = f"FN:${r['fn_cap']/1000:,.0f}k | FTMO:${r['ftmo_cap']/1000:,.0f}k | FP:${r['fp_cap']/1000:,.0f}k"

        print(f"M{r['month']:<6} | ${r['capital']:<12,} | {breakdown:<28} | ${r['gross_pnl']:<9,.1f} | -${r['reinvest_cost']:<7} | ${net:<19,.2f} | NGN {naira:<14,.0f}")
        print(f"   -> Added: {r['accounts_added']}")
        print(f"   -> Status: {r['note']}")
        print(f"   -> Cumulative Banked to Date: ${cum_net_usdt:,.2f} USDT | NGN {cum_naira:,.0f}")
        print("-" * 125)

if __name__ == "__main__":
    run()
