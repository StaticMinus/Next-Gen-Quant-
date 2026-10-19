# Rule: Financial Signal Ingestion & Execution Standards

1. **Connection Pooling & Concurrency**: All high-frequency external polling engines must utilize persistent connection pooling (keep-alive) and bounded worker pools (`ThreadPoolExecutor`) to maintain sub-second ingestion latency across external endpoints.
2. **Directional Target Coherence**: Any automated trading signal MUST pass mathematical sanity validation before order submission:
   - For `BUY` orders: `Stop Loss < Entry Price < Take Profit`
   - For `SELL` orders: `Take Profit < Entry Price < Stop Loss`
3. **Author Target Invariance**: Signal copier engines must strictly execute the exact TP1 and TP2 levels specified by the channel author. Synthetic pip overrides are prohibited unless the signal explicitly omits take-profit targets.
4. **Fail-Fast Diagnostic Alerting**: When an invalid, contradictory, or paywalled signal is received, the system must immediately dispatch a Telegram diagnostic alert rather than failing silently.
