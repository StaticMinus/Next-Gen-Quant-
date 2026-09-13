import json

with open("results/compare_10year_all_strategies.json") as f:
    data = json.load(f)

print(f"Data keys: {list(data.keys())}")
print(f"Total configurations tested: {len(data['by_sharpe'])}")

# Sort by lowest drawdown
by_dd = sorted(data['by_sharpe'], key=lambda x: x['max_drawdown_pct'])
by_winrate = sorted(data['by_sharpe'], key=lambda x: x['win_rate_pct'], reverse=True)

print("\n--- TOP 10 BY SHARPE RATIO ---")
for i, item in enumerate(data["by_sharpe"][:10], 1):
    print(f"{i:2d}. {item['asset']} | {item['label']:<18} | Profit: ${item['total_profit_usd']:>10,.2f} | Return: {item['total_return_pct']:>6.1f}% | Sharpe: {item['sharpe']:>4.2f} | MaxDD: {item['max_drawdown_pct']:>5.2f}% | WinRate: {item['win_rate_pct']:>5.1f}% | Trades: {item['total_trades']}")

print("\n--- TOP 10 BY TOTAL PROFIT ---")
for i, item in enumerate(data["by_profit"][:10], 1):
    print(f"{i:2d}. {item['asset']} | {item['label']:<18} | Profit: ${item['total_profit_usd']:>10,.2f} | Return: {item['total_return_pct']:>6.1f}% | Sharpe: {item['sharpe']:>4.2f} | MaxDD: {item['max_drawdown_pct']:>5.2f}% | WinRate: {item['win_rate_pct']:>5.1f}% | Trades: {item['total_trades']}")

print("\n--- TOP 10 BY LOWEST DRAWDOWN (Safest for Prop Firms) ---")
for i, item in enumerate(by_dd[:10], 1):
    print(f"{i:2d}. {item['asset']} | {item['label']:<18} | Profit: ${item['total_profit_usd']:>10,.2f} | Return: {item['total_return_pct']:>6.1f}% | Sharpe: {item['sharpe']:>4.2f} | MaxDD: {item['max_drawdown_pct']:>5.2f}% | WinRate: {item['win_rate_pct']:>5.1f}% | Trades: {item['total_trades']}")

print("\n--- TOP 10 BY WIN RATE (Psychologically easiest / least loss streaks) ---")
for i, item in enumerate(by_winrate[:10], 1):
    print(f"{i:2d}. {item['asset']} | {item['label']:<18} | Profit: ${item['total_profit_usd']:>10,.2f} | Return: {item['total_return_pct']:>6.1f}% | Sharpe: {item['sharpe']:>4.2f} | MaxDD: {item['max_drawdown_pct']:>5.2f}% | WinRate: {item['win_rate_pct']:>5.1f}% | Trades: {item['total_trades']}")
