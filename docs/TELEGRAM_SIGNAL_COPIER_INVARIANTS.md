# Telegram Signal Copier Invariants

## 1. Multi-Channel Monitoring Policy
- Never rely on a single signal provider channel.
- Always maintain an active multi-channel roster across vetted Telegram groups:
  * **SureShotFX Gold** (`t.me/ssfgold`) — High-precision intraday XAU/USD scalps (~1.8 signals/day).
  * **ForexGDP Free** (`t.me/forexgdpfree`) — Multi-target swing setups for Gold, EUR/USD, AUD/NZD, and JPY crosses (~1.0 signals/day).
  * **Learn 2 Trade** (`t.me/learn2tradenews`) — Breakout zones across Gold, GBP/USD, USD/CHF, and NZD/USD (~1.0 signals/day).
  * **AnabelSignals** (`t.me/anabelsignals`) — Price action setups with verified Stop Loss levels (~1.4 signals/day).
- Combined expected volume is **3 to 5 high-conviction trade calls per trading day**.

## 2. Strict Noise & Spam Filtration
- Immediately reject messages containing promotional bait:
  `tournament`, `investment`, `double`, `profit share`, `vip group`, `locked`, `weekend market brief`, `week ahead`, `bonus`.
- Never execute conversational updates or celebrations (`running`, `boom`, `congratulations`) as new orders.
- Only execute messages containing explicit Direction (`BUY`/`SELL`), Entry Level or Bounded Range, and Stop Loss.

## 3. Multi-Asset Precision & Point Sizing
- Delineate asset class calculations:
  * **Gold (`XAUUSD`):** Clamped 10.0-point hard stop, 2.50-point anti-chase guard, +0.30 point commission buffer for Breakeven locks. Volume: `volume_lots * 100 * 100`.
  * **Forex Majors (`EURUSD`, `GBPUSD`):** Clamped 50-pip stop loss, 12-pip anti-chase limit, +2 pip Breakeven buffer. Volume: `volume_lots * 100000`.
  * **JPY Crosses (`EURJPY`, `GBPJPY`):** Clamped 60-pip stop loss, 15-pip anti-chase limit, +2 pip Breakeven buffer.
- Never apply Gold dollar-point calculations to Forex 5-decimal pips.

## 4. Directional Conflict Arbiter & Concurrency Ceiling
- **Opposing Trade Prohibition:** If Channel A issues a `BUY` and Channel B issues a `SELL` on the same asset within 30 minutes, halt execution on that asset to prevent destructive hedging.
- **Concurrency Ceiling:** Never hold more than 2 active concurrent asset positions simultaneously to protect the FundedNext daily drawdown buffer.
- **Safety Floor Circuit Breaker:** Freeze all automated execution if account equity approaches the $5,650 safety floor.

## 5. Cold-Start Watermark Armor
- Every channel must persist an independent `last_processed_post_id` in state storage.
- On startup, watermark any uninitialized channel to its latest post ID. Historical messages are never executed retroactively.

## 6. Swing Target Policy & 48-Hour Time-Decay Exit
- **TP1 Anchor ("The Banker"):** For any multi-target swing signal (e.g. Target 1 through Target 4):
  * **Ticket 1 (0.07 lots volume):** Targets Target 1 exclusively (+50 to +60 pips / 5.0 pts Gold) to bank realized cash profit directly into account equity.
  * **Ticket 2 (0.07 lots volume - "The Runner"):** Targets the deepest advertised target (`TP3`/`TP4` / `tps[-1]`) to capture massive swings (+200 to +300 pips / 20.0-30.0 pts Gold) with zero risk once Ticket 1 banks.
- **Zero-Risk Breakeven Lock:** The instant Ticket 1 closes at Target 1 (or price reaches 50% distance to TP1), Ticket 2's Stop Loss is immediately amended on cTrader to Entry (+ commission buffer). Ticket 2 is now a risk-free trade.
- **Hard Stop-Loss Clamping:** Automatically clamp wide swing stops (e.g. 80-pip stops) to the asset's maximum allowable risk cushion (max 60 pips JPY crosses, max 50 pips majors, max 10.0 pts Gold).
- **48-Hour Time-Decay Exit:** If a swing position does not reach Target 1 within 48 hours (2 trading days), it is automatically closed at market to liberate margin and eliminate swap/weekend exposure.

## 7. Institutional "Banker + Trailing Runner" & Dynamic Ratcheting Trailing Stop
- **Ratcheting Trailing Mechanism:** Once Ticket 2 generates positive floating gain exceeding the activation threshold (+40 pips / +4.0 pts Gold), a dynamic trailing stop trails market spot at a fixed distance (30 pips / 3.0 pts Gold).
- **Unidirectional Ratchet:** Stop Loss amendments strictly follow the price trend (upwards for BUYs, downwards for SELLs) and NEVER loosen or move against the trade.
- **Profit Preservation vs. Deep Reversal:** If a 300-pip target runs +180 pips and then reverses sharply, the trailing stop ensures the position exits with +150 pips banked, rather than returning to breakeven or hitting a loss.
- **Funded Account Capital Protection:** By banking 0.07 lots at TP1 and ratcheting gains on Ticket 2 (0.07 lots), account equity constantly climbs toward the 10% FundedNext Phase 1 target while keeping maximum drawdown virtually zero.

## 8. False Alert Suppression & Twin-Ticket Sizing Invariants
- **Zero False-Alert Mandate:** Automated execution alerts (`NEW SIGNAL EXECUTED`, `Trailing Stop Advanced`) MUST NEVER be transmitted to the live Telegram chat when operating in `dry_run=True` mode, during local testing, or during backtest sweeps. Only broker-acknowledged live fills generate order alerts.
- **Twin-Ticket 0.07 Sizing:** For multi-target setups, both Ticket 1 (Banker) and Ticket 2 (Runner) are sized at precisely 0.07 lots each (`0.07 lots x 2 = 0.14 lots total`). Single-target scalp setups execute as 0.07 lots total.

## 9. Multi-Channel Signal Invariants
- **Pending Order Support:** The copier must recognize `BUY STOP`, `SELL STOP`, `BUY LIMIT`, and `SELL LIMIT` notations alongside direct market calls.
- **Deepest Target Binding:** In multi-target setups (ForexGDP, Learn2Trade), Ticket 1 executes at TP1, and Ticket 2 strictly targets the deepest target (`tps[-1]`), protected by a 30-pip ratcheting trailing stop once profit exceeds +40 pips.
- **Broker Asset Whitelist:** Orders are only placed if the instrument is an active tradeable asset on the cTrader broker with live spot feed. Unrecognized or non-FX equity symbols are safely bypassed.

## 10. Cloud Runner Freshness & Continuous Session Invariant
- **Stale Container Prohibition:** A GitHub Actions cloud runner must never continue executing an obsolete commit after parser or copier updates are merged into `main`. The deployment pipeline must ensure the active runner is always executing the latest HEAD.
- **Round-the-Clock Session Coverage:** Trading signals frequently arrive during the Tokyo open (00:00–04:00 UTC) and London open (07:00–10:00 UTC). Cloud runners must maintain uninterrupted monitoring throughout these sessions so that early-morning setups are never missed.

## 11. Directional Target Coherence Invariant
- **Mathematical Side Coherence:** Take Profit targets and Stop Losses must be strictly coherent with order side:
  * **BUY Orders:** Every TP target must be strictly greater than entry (`TP > entry`), and SL must be strictly lower than entry (`SL < entry`).
  * **SELL Orders:** Every TP target must be strictly less than entry (`TP < entry`), and SL must be strictly higher than entry (`SL > entry`).
- **Inverted Signal Neutralization:** Any signal where targets are inverted (e.g., `SELL 4145` with TP `4150`) is flagged as `is_valid: False` and blocked immediately before broker transmission.
- **Paywalled / Missing SL Prohibition:** Signals hiding stop losses behind marketing prompts (e.g., `STOP LOSS VIP GROUP`) are strictly rejected. The copier never assumes unbounded risk on promotional free-channel bait.

## 12. Signal Rejection Transparency Invariant
- **Zero Silent-Drops Mandate:** When a signal is parsed from a target channel but rejected by pre-flight validation (Inverted Targets, Paywalled SL, Anti-Chase Slippage, or Conflict Shield), the copier must NEVER silently drop the message.
- **User Explanation Alert:** The copier must immediately transmit a clear Telegram notification to David's personal bot detailing:
  * Channel Source and Post ID
  * Attempted Action and Price
  * Specific Failure Reason (e.g. `Inverted Take Profit`, `Anti-Chase Limit Exceeded`, `Opposing Position Active`)
  * Affirmation that capital was safely protected from toxic execution.

## 13. Channel Quality Tiering & Session Window Invariant
- **Empirical Audit Mandate:** Every monitored channel must be backed by an empirical historical audit (minimum 30+ scraped messages) tracking actionable signal yield and active hours.
- **Quality Tiers:**
  * **Tier 1 (Institutional Clean, >=20% Yield):** High-density providers with explicit SL, TP, and clean execution syntax (`PrimeGoldSignals`, `anabelsignals`, `ForexEliteSignals`, `ForexPipsFactory`, `forexgdpfree`, `ssfgold`, `learn2tradenews`).
  * **Tier 2 (Direct Reliable, 8%–19% Yield):** Clean direct calls with lower daily frequency (`top_tradingsignals`, `pipchasers`, `Crown Gold Signals`).
  * **Tier 3 (Guarded / High-Noise, <8% Yield):** Channels with high marketing volume or paywalled stop loss attempts (`XAUUSD_GOLD_TRADING_FOREX`). Strictly guarded by Directional Coherence & Paywall filters.
- **Global Session Awareness:** The system explicitly maps to global market liquidity windows:
  * **London Session (07:00–13:00 UTC / 08:00–14:00 BST):** 40.8% of daily signal volume.
  * **New York Session (13:00–21:00 UTC / 14:00–22:00 BST):** 35.4% of daily signal volume.
  * **Tokyo Session (00:00–07:00 UTC / 01:00–08:00 BST):** 19.9% of daily signal volume.

## 14. Speed, Accuracy & Efficiency Invariants
- **Parallel Connection Pool Mandate:** All channel harvesting must utilize persistent HTTPS connection pooling (`requests.Session` with `HTTPAdapter(pool_connections=30)`) to eliminate redundant TLS handshakes.
- **Sub-Second Parallel Polling:** Channels must be harvested concurrently using a worker pool (`ThreadPoolExecutor`), maintaining a total cycle latency of under 500 milliseconds across all monitored channels.
- **Tier-Weighted Execution Cadence:**
  * Tier 1 channels are evaluated on every rapid 5-second tick.
  * Tier 2 channels are evaluated every 10 seconds.
  * Tier 3 channels are evaluated every 15 seconds.
- **Hybrid AI Fallback Guard:** For unstructured natural-language signals where regex produces no match, the parser triggers an AI extraction fallback to ensure zero high-conviction trades are discarded.

## 15. Late-Signal & Anti-Chase Protection Invariant
- **Strict Anti-Chase Enforcement:** If a signal provider publishes a trade call after price has already moved beyond `max_slippage` (2.50 pts for Gold / 12 pips for FX), the trade MUST remain blocked.
- **Never Widen SL to Chase:** Never chase a late signal if doing so expands the real risk beyond the maximum allowable loss per trade. Entering late degrades the Risk-to-Reward ratio and increases the probability of immediate drawdown on normal market retracements.
- **Rejection Notification:** Always dispatch a clear explanation specifying the exact entry distance and why capital was preserved so the operator understands why the trade was skipped.

## 16. Trend-Alignment & Counter-Trend Scalp Protection
- **Multi-Timeframe Trend Coherence:** When executing single-target scalps (e.g. from intraday providers like `ssfgold`), orders must not conflict with dominant higher-timeframe momentum (M15/H1 trend).
- **Hard Stop-Loss Integrity:** All scalp orders must maintain their strict stop-loss boundaries; never widen stops on counter-trend setups. In high-volatility sessions (e.g. London Open), counter-trend setups must be subject to tighter slippage tolerances.




