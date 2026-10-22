# Rule: Financial Signal Ingestion & Execution Standards

1. **Connection Pooling & Concurrency**: All high-frequency external polling engines must utilize persistent connection pooling (keep-alive) and bounded worker pools (`ThreadPoolExecutor`) to maintain sub-second ingestion latency across external endpoints.
2. **Directional Target Coherence**: Any automated trading signal MUST pass mathematical sanity validation before order submission:
   - For `BUY` orders: `Stop Loss < Entry Price < Take Profit`
   - For `SELL` orders: `Take Profit < Entry Price < Stop Loss`
3. **Author Target Invariance**: Signal copier engines must strictly execute the exact TP1 and TP2 levels specified by the channel author. Synthetic pip overrides are prohibited unless the signal explicitly omits take-profit targets.
4. **Fail-Fast Diagnostic Alerting**: When an invalid, contradictory, or paywalled signal is received, the system must immediately dispatch a Telegram diagnostic alert rather than failing silently.
5. **Defensive Broker Telemetry Unwrapping**: Broker API and MCP responses may return `null` for price, volume, commission, or timestamp attributes during off-tick or quiescent market states. Ingestion code must never assume non-null dictionary values when applying mathematical operators; all incoming broker numbers MUST be defensively guarded (e.g., `(float(val) / div) if val is not None else 0.0`) to guarantee fail-safe execution.
6. **Direct Action Parsing Precedence**: In multi-channel signal parsers, direct execution and actionable order patterns (`m_action_direct`, `m_action_buy_now`) MUST be evaluated before broad entry zone search patterns. Take profit and stop loss definition blocks (e.g., `3/TAKE PROFIT 4150-60`) must be excluded from generic hyphenated zone searches to prevent false entry matches and inverted stop loss rejections.
7. **Asset-Class Volume Multiplier Invariant**: When placing market or limit orders via cTrader MCP, the lot size multiplier must be determined strictly by asset class:
   - Metals (Gold/XAUUSD): `raw_volume = round(lots * 100 * 100)`
   - Forex Currencies (EURUSD, EURAUD, GBPJPY): `raw_volume = round(lots * 100000 * 100)`
   - Indices & Crypto (US30, BTCUSD): `raw_volume = round(lots * 1 * 100)`
   Sending an unscaled lot count on Forex triggers an immediate broker rejection (Order volume < minimum allowed volume).
8. **Dynamic Single-Slot Allocation (Invariant 26)**: If a runner position is currently open (concurrency = 1/2) and a new valid signal arrives, the engine must scale the incoming order to a single ticket targeting TP1 (0.07 lots) rather than rejecting the trade or exceeding the 2-position concurrency ceiling. When 2 slots are free, twin tickets (Banker TP1 + Trailing Runner TP_max) are deployed.
9. **Hermetic Test State Isolation**: Automated test suites running against the signal copier must execute with hermetic state isolation. Unit tests must never share or mutate the production state file `cache/multi_signal_copier_state.json` or persist accumulated mock tickets into subsequent test runs.
10. **Commission-Aware Breakeven Buffer (Zero-Loss Invariant)**: Any automated or dynamic Stop-Loss movement to Breakeven (BE) MUST strictly account for broker round-trip commission plus spread. The minimum BE buffer must exceed commission costs (e.g. $\ge 0.30$ pts on Gold for 0.07 lots = $2.10 gross vs $1.28 fee) so that no position exiting at Breakeven ever closes at a net financial loss.
11. **Stop-Loss Tightening-Only Invariant**: Algorithmic, price-action, and dynamic volatility engines (including PASL) are strictly prohibited from widening any signal provider's stated Stop-Loss. Dynamic engines may only tighten wide stops to protect account equity, synthesize missing stops, or enforce the 5.0 pt ($35/ticket) Gold maximum loss ceiling.
12. **Channel Retainment & Fleet Expectancy Standard**: Channels admitted into the active copier fleet must maintain non-negative multi-session expectancy. Isolated scalp wins cannot override catastrophic morning drawdowns or erratic counter-trend entries into demand/supply extremes.


