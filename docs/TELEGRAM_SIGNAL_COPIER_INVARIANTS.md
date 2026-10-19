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
