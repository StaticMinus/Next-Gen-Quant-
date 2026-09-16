import pandas as pd
from pathlib import Path

df_spy = pd.read_csv('cache/SPY_10y.csv', index_col=0, parse_dates=True)
c_spy = df_spy['close'].tail(10)
m_s = c_spy.rolling(5).mean().iloc[-1]
s_s = c_spy.rolling(5).std().iloc[-1]
p_s = c_spy.iloc[-1]
dip_s = m_s - 1.25 * s_s
dist_s = p_s - dip_s
pct_s = (dist_s / p_s) * 100
print(f"SPY: Price=${p_s:.2f} | 5d Mean=${m_s:.2f} | Dip Trigger=${dip_s:.2f} | Dist=+${dist_s:.2f} ({pct_s:.2f}%)")

df_q = pd.read_csv('cache/QQQ_10y.csv', index_col=0, parse_dates=True)
c_q = df_q['close'].tail(10)
m_q = c_q.rolling(5).mean().iloc[-1]
s_q = c_q.rolling(5).std().iloc[-1]
p_q = c_q.iloc[-1]
dip_q = m_q - 1.25 * s_q
dist_q = p_q - dip_q
pct_q = (dist_q / p_q) * 100
print(f"QQQ: Price=${p_q:.2f} | 5d Mean=${m_q:.2f} | Dip Trigger=${dip_q:.2f} | Dist=+${dist_q:.2f} ({pct_q:.2f}%)")
