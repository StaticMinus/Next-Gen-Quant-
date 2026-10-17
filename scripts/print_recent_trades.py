import sys
sys.path.insert(0, "scripts")
import realistic_6month_backtest as rb

for m in ["2026-10", "2026-09", "2026-08"]:
    print(f"\n=== {m} TRADES ===")
    trades = [x for x in rb.all_trades if x["datetime"].startswith(m)]
    for t in trades:
        print(f"{t['datetime']} | {t['side']:<4} {t['entry']:<6.1f} | SL {t['sl']:<6.1f} | TP1 {t['tp1']:<6.1f} | TP2 {t['tp2']:<6.1f} | {t['status']:<15} | {t['pnl']:>+8.2f} USD")
