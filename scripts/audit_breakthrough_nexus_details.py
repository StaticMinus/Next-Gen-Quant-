#!/usr/bin/env python3
"""
scripts/audit_breakthrough_nexus_details.py
Detailed annual and monthly breakdown of Config 5 (Breakthrough Nexus)
"""
import sys
import pandas as pd
import numpy as np

# We can import from research_breakthrough_engine
from research_breakthrough_engine import run_simulation, UNIVERSE_7

res = run_simulation(
    name='Breakthrough Nexus (3 slots @ $300, 7 assets)',
    universe=UNIVERSE_7,
    max_positions=3,
    position_size=300.0,
    stop_loss_pct=0.030,
    take_profit_pct=0.025,
    max_hold_days=4,
    use_mean_rev_exit=True,
    use_breakthrough_signal=True
)

print("\nDetailed Summary:")
for k, v in res.items():
    print(f"  {k}: {v}")
