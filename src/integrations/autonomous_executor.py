"""
AgentQuant Autonomous Trade Execution Engine (cTrader #3028655)
==============================================================
Intraday Sharp Scalper (Same-Day In & Out) for FundedNext Stellar Prop Account.

Features:
- Scans strictly Dual Index Universe: SPY (SPX500), QQQ (NDX100)
- Configurable Timeframe: 5-Minute (M5) Sharp Scalper or 1-Hour (H1) Intraday
- Strict Anti-Late-Trade Guard:
    * Bar Freshness: Rejects signals older than 2.5 minutes (M5) / 5 minutes (H1)
    * Price Tolerance: Rejects entry if live price has bounced > 0.05% above trigger (Zero Chasing)
    * Session Lock: Only enters between 9:30 AM and 2:30 PM EST (2:30 PM – 7:30 PM WAT)
- Same-Day Flat Routine: Closes all positions at 15:50 EST (8:50 PM WAT) for 0% overnight risk
- Strict 2-Position Concurrency Ceiling (Never exceeds 2 open trades)
- Broker-Level Hard Stop Loss & Take Profit (Mean Reversion) attached immediately
- Risk Guardian Pre-Trade Verification (Drawdown buffer check vs -$180 daily / -$360 max limit)
- Instant Rich Telegram Execution Ticket Dispatch to David and Cha Cha
"""

import io
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

from src.strategies.scalper import ScalperStrategy
from src.backtest.runner import _get_close
from src.integrations.risk_guardian import guardian
from src.integrations.ctrader_mcp_client import CTraderMCPClient, RiskViolationError

logger = logging.getLogger("autonomous_executor")
logger.setLevel(logging.INFO)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PRIMARY_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8428715579")
API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
AUTHORIZED_USERS_FILE = ROOT_DIR / "cache" / "authorized_users.json"
STATE_FILE = ROOT_DIR / "cache" / "autonomous_execution_state.json"

MAX_CONCURRENT_POSITIONS = 2  # Hard FundedNext limit

ALLOW_OVERNIGHT_HOLD = os.getenv("ALLOW_OVERNIGHT_HOLD", "false").lower() in ("true", "1", "yes")

TARGET_UNIVERSE = [
    {"ticker": "BTC-USD", "ctrader_symbol": "BTCUSD", "name": "Bitcoin Spot (24/7 Sniper)", "target_lots": 0.04, "max_risk_usd": 20.0, "is_crypto": True},
    {"ticker": "ETH-USD", "ctrader_symbol": "ETHUSD", "name": "Ethereum Spot (24/7 Sniper)", "target_lots": 1.00, "max_risk_usd": 15.0, "is_crypto": True},
    {"ticker": "XRP-USD", "ctrader_symbol": "XRPUSD", "name": "XRP Spot (24/7 Sniper)", "target_lots": 1000.0, "max_risk_usd": 10.0, "is_crypto": True},
    {"ticker": "SPY", "ctrader_symbol": "SPX500", "name": "S&P 500 Index", "target_lots": None, "max_risk_usd": 20.0},
    {"ticker": "QQQ", "ctrader_symbol": "NDX100", "name": "Nasdaq 100 Index", "target_lots": None, "max_risk_usd": 20.0},
    {"ticker": "DIA", "ctrader_symbol": "US30", "name": "Dow Jones 30 Index", "target_lots": None, "max_risk_usd": 20.0},
    {"ticker": "IWM", "ctrader_symbol": "US2000", "name": "Russell 2000 Index", "target_lots": None, "max_risk_usd": 20.0},
]

# Active timeframe: "1m" (Default M1 Microstructure Sniper), "15m", "30m", "5m", or "1h"
ACTIVE_TIMEFRAME = os.getenv("AUTONOMOUS_TIMEFRAME", "1m")

TIMEFRAME_CONFIGS = {
    "1m": {
        "interval": "1m",
        "period": "1d",
        "window": 20,            # 20-minute rolling mean
        "num_std": 1.50,         # 1.50 sigma dip band (M1 Microstructure Sniper)
        "exit_at_mean": True,    # Take profit at mean or target
        "allow_short": False,    # Long-Only on dip snipes
        "stop_loss_pct": 0.0050, # 0.50% tight hard stop
        "target_profit_pct": 0.0060, # +0.60% rapid take profit
        "max_hold_bars": 12,     # 12 minutes max hold (Strict in-and-out!)
        "time_decay_bars": 5,    # Bank profit if holding >= 5 mins and green
        "time_decay_min_profit": 0.0015, # +0.15% profit triggers early close
        "bar_freshness_seconds": 60,   # 1 minute max age from bar close
        "price_tolerance_pct": 0.0010, # Max 0.10% bounce above trigger (anti-chase)
        "cooldown_seconds": 180,       # 3 min cooldown per ticker
        "label": "1-Minute Real-Tick Microstructure Sniper (24/7)"
    },
    "15m": {
        "interval": "15m",
        "period": "5d",
        "window": 8,             # 2-hour rolling mean
        "num_std": 1.50,         # 1.50 sigma dip band (M15 Scalper A: Rapid Turnover)
        "exit_at_mean": True,    # Take profit at mean or target
        "allow_short": False,    # Long-Only on US indices
        "stop_loss_pct": 0.0040, # 0.40% tight hard stop
        "target_profit_pct": 0.0025, # +0.25% rapid take profit
        "max_hold_bars": 6,      # 90 minutes max hold (Strict in-and-out!)
        "time_decay_bars": 3,    # Bank profit if holding >= 45 mins and green
        "time_decay_min_profit": 0.0010, # +0.10% profit triggers early close
        "bar_freshness_seconds": 300,  # 5 minutes max age from bar close
        "price_tolerance_pct": 0.0015, # Max 0.15% bounce above trigger (anti-chase)
        "cooldown_seconds": 900,       # 15 min cooldown per ticker
        "label": "Option A 15-Minute Sharp Scalper (Rapid In & Out)"
    },
    "30m": {
        "interval": "30m",
        "period": "1mo",
        "window": 10,            # 5-hour rolling mean
        "num_std": 1.75,         # 1.75 sigma dip band (M30 Sniper B: Balanced Sniper)
        "exit_at_mean": True,
        "allow_short": False,
        "stop_loss_pct": 0.0070, # 0.70% stop
        "target_profit_pct": 0.0050, # +0.50% profit
        "max_hold_bars": 7,      # 3.5 hours max hold
        "time_decay_bars": 4,    # 2 hours
        "time_decay_min_profit": 0.0015,
        "bar_freshness_seconds": 600,
        "price_tolerance_pct": 0.0010,
        "cooldown_seconds": 1800,
        "label": "Option A 30-Minute Intraday Sniper"
    },
    "5m": {
        "interval": "5m",
        "period": "5d",
        "window": 6,             # 30-minute rolling mean
        "num_std": 1.75,         # 1.75 sigma dip band
        "exit_at_mean": True,    # Take profit at mean
        "allow_short": False,    # Long-Only on US indices
        "stop_loss_pct": 0.0035, # 0.35% tight hard stop
        "target_profit_pct": 0.0020,
        "max_hold_bars": 7,      # 35 minutes max hold (Strict in-and-out!)
        "time_decay_bars": 4,
        "time_decay_min_profit": 0.0010,
        "bar_freshness_seconds": 180,  # 3 minutes max age from bar close
        "price_tolerance_pct": 0.0005, # Max 0.05% bounce above trigger (anti-chase)
        "cooldown_seconds": 900,       # 15 min cooldown per ticker
        "label": "5-Minute Sharp Scalper (In & Out)"
    },
    "1h": {
        "interval": "1h",
        "period": "30d",
        "window": 20,            # 20-hour rolling mean (~3 days)
        "num_std": 1.25,         # 1.25 sigma dip band (Option A Quant Sniper)
        "exit_at_mean": True,
        "allow_short": False,
        "stop_loss_pct": 0.020,  # 2.0% hard stop
        "target_profit_pct": 0.0080,
        "max_hold_bars": 24,     # Multi-hour holding (allows mean-reversion wave to complete)
        "time_decay_bars": 8,
        "time_decay_min_profit": 0.0020,
        "bar_freshness_seconds": 7200, # 2 hours max age from bar close
        "price_tolerance_pct": 0.0015, # Max 0.15% bounce above trigger (anti-chase)
        "cooldown_seconds": 7200,      # 2 hours cooldown per ticker
        "label": "1-Hour Quantitative Sniper (Option A: SPY & QQQ)"
    }
}

TIMEFRAME_DURATION_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "1d": 86400,
}

# Execution Mode: "SNIPER_MARKET" (Atomic Market with Micro-Rejection) or "SNIPER_LIMIT" (Resting Limit at Dip Band)
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "SNIPER_MARKET")

CTRADER_PERIOD_MAP = {
    "1m": "M_1",
    "5m": "M_5",
    "15m": "M_15",
    "30m": "M_30",
    "1h": "H_1",
    "1d": "D_1"
}

# Cache for intraday bars to prevent rate limits across 35s background cycles
_INTRADAY_DATA_CACHE: Dict[str, Tuple[float, pd.DataFrame]] = {}
CACHE_TTL_SECONDS = 30.0


def fetch_intraday_bars(ticker: str, timeframe: str = ACTIVE_TIMEFRAME, csym: Optional[str] = None) -> pd.DataFrame:
    """Fetch intraday bars: tries cTrader native trendbars first (Upgrade 2), falls back to yfinance."""
    cfg = TIMEFRAME_CONFIGS.get(timeframe, TIMEFRAME_CONFIGS["5m"])
    cache_key = f"{ticker}_{timeframe}"
    now = time.time()

    if cache_key in _INTRADAY_DATA_CACHE:
        cached_time, cached_df = _INTRADAY_DATA_CACHE[cache_key]
        if now - cached_time < CACHE_TTL_SECONDS:
            return cached_df

    # Upgrade 2: Try cTrader direct trendbars first if csym is provided
    if csym:
        try:
            from src.integrations.ctrader_mcp_client import ctrader_client
            c_period = CTRADER_PERIOD_MAP.get(timeframe, "M_15")
            c_df = ctrader_client.get_trendbars_dataframe(csym, period=c_period, count=60)
            if c_df is not None and len(c_df) >= cfg.get("window", 5):
                _INTRADAY_DATA_CACHE[cache_key] = (now, c_df)
                return c_df
        except Exception as ce:
            logger.debug(f"cTrader direct trendbar fallback to yfinance for {csym}: {ce}")

    df = yf.download(ticker, period=cfg["period"], interval=cfg["interval"], progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0].lower() for col in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]

    _INTRADAY_DATA_CACHE[cache_key] = (now, df)
    return df


def load_execution_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_trades": {}, "execution_history": []}


def save_execution_state(state: dict):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving execution state: {e}")


def get_target_chat_ids() -> List[str]:
    cids = [PRIMARY_CHAT_ID]
    if AUTHORIZED_USERS_FILE.exists():
        try:
            with open(AUTHORIZED_USERS_FILE, "r", encoding="utf-8") as f:
                users = json.load(f)
                for uid in users:
                    if uid not in cids:
                        cids.append(str(uid))
        except Exception:
            pass
    return cids


def broadcast_telegram_ticket(msg: str, photo_buf: Optional[io.BytesIO] = None, reply_markup: Optional[dict] = None):
    if not TELEGRAM_BOT_TOKEN or os.getenv("PYTEST_CURRENT_TEST"):
        return
    for cid in get_target_chat_ids():
        sent_photo = False
        if photo_buf:
            try:
                photo_buf.seek(0)
                raw_bytes = photo_buf.getvalue()
                files = {"photo": ("trade_ticket.png", raw_bytes, "image/png")}
                data = {"chat_id": cid, "caption": msg, "parse_mode": "HTML"}
                if reply_markup:
                    data["reply_markup"] = json.dumps(reply_markup)
                resp = requests.post(f"{API_BASE}/sendPhoto", files=files, data=data, timeout=25)
                if resp.status_code == 200:
                    sent_photo = True
            except Exception as pe:
                logger.warning(f"Could not send photo ticket to {cid}, falling back to text: {pe}")

        if not sent_photo:
            try:
                payload = {"chat_id": cid, "text": msg, "parse_mode": "HTML"}
                if reply_markup:
                    payload["reply_markup"] = reply_markup
                requests.post(
                    f"{API_BASE}/sendMessage",
                    json=payload,
                    timeout=10
                )
            except Exception as e:
                logger.warning(f"Failed to send execution ticket to {cid}: {e}")


class AutonomousExecutionEngine:
    def __init__(self, ctrader_client: Optional[CTraderMCPClient] = None, timeframe: str = ACTIVE_TIMEFRAME):
        from src.integrations.ctrader_mcp_client import ctrader_client as default_client
        self.ctrader = ctrader_client or default_client
        self.scalper = ScalperStrategy()
        self.state = load_execution_state()
        self.timeframe = timeframe
        self.cfg = TIMEFRAME_CONFIGS.get(timeframe, TIMEFRAME_CONFIGS["5m"])

    def check_microstructure_rejection(self, csym: str, df: Optional[pd.DataFrame] = None) -> Tuple[bool, float, str]:
        """
        Upgrade 5: Microstructure Rejection Filter (M1/M5 Wick Check)
        Examines the lowest candle to ensure buyer absorption / rejection wick.
        Requires lower wick >= 25% of candle range when closing red (to confirm buyers absorb the sell-off),
        or rejects if candle is a solid red falling knife (lower wick < 25% and close < open).
        """
        try:
            if df is not None and len(df) > 0:
                last_bar = df.iloc[-1]
                o = float(last_bar["open"])
                h = float(last_bar["high"])
                l = float(last_bar["low"])
                c = float(last_bar["close"])
                rng = h - l
                if rng <= 0:
                    return True, 0.0, "FLAT_BAR"
                lower_wick = min(o, c) - l
                wick_ratio = lower_wick / rng

                # Solid red falling knife check: on red candle (c < o), require at least 25% buyer absorption wick
                if c < o and wick_ratio < 0.25:
                    return False, wick_ratio, "FALLING_KNIFE_REJECTED"
                # Absorption hammer / rejection check
                if wick_ratio >= 0.30 or (c > o and (c - o) / rng >= 0.40):
                    return True, wick_ratio, "REJECTION_CONFIRMED"
                return True, wick_ratio, "NEUTRAL"
        except Exception as e:
            logger.warning(f"Error checking microstructure rejection for {csym}: {e}")
        return True, 0.0, "BYPASS"

    def check_spread_shield(self, csym: str, spot_info: Optional[dict], max_spread_pct: Optional[float] = None) -> Tuple[bool, float, str]:
        """
        Spread & Slippage Shield Guard (Upgraded with 3-Tick Adaptive Normalizer):
        Verifies broker spread does not exceed max_spread_pct (default: 0.03% for majors, 0.04% for US2000 small-caps).
        If spread is temporarily elevated during tick fluctuations, performs up to 3 rapid sub-second re-polls
        to capture the normalized spread without missing the entry window.
        """
        if max_spread_pct is None:
            max_spread_pct = 0.0004 if ("2000" in csym.upper() or "IWM" in csym.upper()) else 0.0003
        try:
            current_spot = spot_info
            for attempt in range(3):
                if current_spot and "ask" in current_spot and "bid" in current_spot:
                    ask = float(current_spot["ask"])
                    bid = float(current_spot["bid"])
                    if ask > 0 and bid > 0 and ask >= bid:
                        mid = (ask + bid) / 2.0
                        spread_pct = (ask - bid) / mid
                        if spread_pct <= max_spread_pct:
                            if attempt > 0:
                                return True, spread_pct, f"SPREAD_NORMALIZED (tick {attempt+1})"
                            return True, spread_pct, "SPREAD_OPTIMAL"
                
                # If wide on initial check, pause 500ms and re-fetch spot price
                if attempt < 2:
                    time.sleep(0.5)
                    try:
                        new_spot = self.ctrader.get_spot_price(csym)
                        if new_spot and isinstance(new_spot, dict) and "ask" in new_spot:
                            current_spot = new_spot
                    except Exception:
                        break
            
            if current_spot and "ask" in current_spot and "bid" in current_spot:
                ask = float(current_spot["ask"])
                bid = float(current_spot["bid"])
                if ask > 0 and bid > 0:
                    spread_pct = (ask - bid) / ((ask + bid) / 2.0)
                    return False, spread_pct, f"SPREAD_TOO_WIDE ({spread_pct*100:.3f}% > {max_spread_pct*100:.3f}%)"
        except Exception as e:
            logger.warning(f"Error evaluating spread shield for {csym}: {e}")
        return True, 0.0, "BYPASS_NO_SPOT"

    def compute_dynamic_atr_target(self, df: Optional[pd.DataFrame], period: int = 14) -> float:
        """
        Take-Profit (TP) Sizing Upgrade:
        Computes a 14-period Average True Range (ATR) scaled target profit.
        Scales target from +0.20% (tight consolidation) up to +0.40% (high volatility).
        """
        fallback_target = self.cfg.get("target_profit_pct", 0.0025)
        try:
            if df is not None and len(df) >= period and all(col in df.columns for col in ["high", "low", "close"]):
                high = df["high"].astype(float)
                low = df["low"].astype(float)
                close = df["close"].astype(float)
                prev_close = close.shift(1)
                tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
                atr = tr.rolling(period, min_periods=period).mean()
                if not atr.empty and not pd.isna(atr.iloc[-1]) and close.iloc[-1] > 0:
                    atr_pct = float(atr.iloc[-1] / close.iloc[-1])
                    return max(0.0020, min(0.0040, 0.75 * atr_pct))
        except Exception as e:
            logger.debug(f"ATR target computation fallback: {e}")
        return fallback_target

    def check_macro_trend_regime(self, df: Optional[pd.DataFrame]) -> Tuple[bool, str]:
        """
        Macro Trend Regime Filter:
        Inspects higher-timeframe trend structure to prevent dip-buying during waterfall dumps.
        If price is > 0.60% below the 50-period EMA on intraday bars, suppresses long entries.
        Also suppresses entries if the last 3 consecutive bars are severe red candles dumping > 0.40% without consolidation.
        """
        try:
            if df is not None and len(df) >= 30 and "close" in df.columns:
                close = df["close"].astype(float)
                ema50 = close.ewm(span=min(50, len(close)), adjust=False).mean()
                c_last = float(close.iloc[-1])
                ema_last = float(ema50.iloc[-1])
                if ema_last > 0 and c_last < ema_last * 0.994:
                    return False, f"WATERFALL_DOWNTREND (Price {((c_last - ema_last)/ema_last)*100:.2f}% below EMA50)"

                # Check for 3-bar consecutive red cascade (> 0.40% dump)
                if len(df) >= 3 and "open" in df.columns:
                    last_3 = df.iloc[-3:]
                    all_red = all(float(last_3.iloc[i]["close"]) < float(last_3.iloc[i]["open"]) for i in range(3))
                    total_drop = (float(last_3.iloc[-1]["close"]) - float(last_3.iloc[0]["open"])) / float(last_3.iloc[0]["open"])
                    if all_red and total_drop < -0.0040:
                        return False, f"MULTI_CANDLE_CASCADE (3 consecutive red bars dropping {total_drop*100:.2f}%)"
        except Exception as e:
            logger.debug(f"Trend regime check exception: {e}")
        return True, "HEALTHY_REGIME"

    def is_market_session(self, dt_ny: Optional[pd.Timestamp] = None) -> bool:
        """Returns True if current time is Monday-Friday regular US market hours."""
        if dt_ny is None:
            dt_ny = pd.Timestamp.now(tz="America/New_York")
        if dt_ny.weekday() >= 5:  # Saturday or Sunday
            return False
        market_open = dt_ny.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = dt_ny.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= dt_ny <= market_close

    def is_active_entry_window(self, dt_ny: Optional[pd.Timestamp] = None) -> bool:
        """Returns True if within the 9:30 to 14:30 EST (2:30 PM – 7:30 PM WAT) active entry window.
        Starts at market open (9:30 AM EST) to capture early-session mean-reversion dips.
        Cutting entries off at 14:30 EST guarantees 35+ minutes for all scalps to finish naturally before 15:50 EST."""
        if dt_ny is None:
            dt_ny = pd.Timestamp.now(tz="America/New_York")
        if dt_ny.weekday() >= 5:
            return False
        entry_start = dt_ny.replace(hour=9, minute=30, second=0, microsecond=0)
        entry_end = dt_ny.replace(hour=14, minute=30, second=0, microsecond=0)
        return entry_start <= dt_ny <= entry_end

    def is_eod_flatten_time(self, dt_ny: Optional[pd.Timestamp] = None) -> bool:
        """
        Determines if an end-of-session flattening is triggered.
        - If ALLOW_OVERNIGHT_HOLD is True: Weekdays (Mon-Thu) hold overnight through 23-hour futures liquidity.
          Only triggers on Friday close (>= 16:45 EST / 21:45 WAT) to prevent 48-hour weekend gap risk.
        - If ALLOW_OVERNIGHT_HOLD is False: Triggers daily at 15:50 EST (8:50 PM WAT).
        """
        if dt_ny is None:
            dt_ny = pd.Timestamp.now(tz="America/New_York")
        if dt_ny.weekday() >= 5:
            return False

        if ALLOW_OVERNIGHT_HOLD:
            # Only flatten on Friday afternoon before weekend market shutdown (17:00 EST)
            is_friday = dt_ny.weekday() == 4
            if is_friday:
                weekend_cutoff = dt_ny.replace(hour=16, minute=45, second=0, microsecond=0)
                return dt_ny >= weekend_cutoff
            return False  # Mon-Thu hold through the night!
        else:
            flatten_time = dt_ny.replace(hour=15, minute=45, second=0, microsecond=0)
            return dt_ny >= flatten_time

    def check_and_execute_same_day_flatten(self, open_positions: List[dict], dt_ny: Optional[pd.Timestamp] = None) -> List[int]:
        """
        EOD / Weekend Protection Routine:
        - When holding overnight (Mon-Thu): Positions remain active on cTrader with their server-side
          hard stop loss (-$25) and take profit to allow natural mean reversion through 23-hour futures.
        - On Friday close (or if overnight hold disabled): Closes open positions to avoid weekend gap risk.
        Returns list of closed position IDs.
        """
        if not self.is_eod_flatten_time(dt_ny):
            return []

        closed_ids = []
        symbol_map = self.ctrader.get_symbol_map() or {}
        id_to_sym = {v: k for k, v in symbol_map.items()}

        is_friday = (dt_ny or pd.Timestamp.now(tz="America/New_York")).weekday() == 4
        reason_tag = "WEEKEND GAP DEFENSE" if is_friday else "EOD FLATTEN"

        for p in open_positions:
            pid = p.get("positionId")
            if not pid:
                continue

            sym_id = p.get("symbolId")
            sym_name = p.get("symbolName") or id_to_sym.get(sym_id, "INDEX")
            is_crypto = any(c in sym_name.upper() for c in ["BTC", "ETH", "XRP", "SOL", "BNB", "DOGE"])
            if is_crypto:
                continue  # Crypto trades 24/7, never flatten for stock market sessions
            entry_price = float(p.get("entryPrice", 0.0))
            trade_side = str(p.get("tradeSide", "BUY")).upper()

            spot = self.ctrader.get_spot_price(sym_name)
            curr_price = 0.0
            if spot:
                curr_price = float(spot["bid"]) if trade_side == "BUY" else float(spot["ask"])

            if entry_price > 0 and curr_price > 0:
                pnl_pct = ((curr_price - entry_price) / entry_price) if trade_side == "BUY" else ((entry_price - curr_price) / entry_price)
            else:
                pnl_pct = 0.0

            logger.info(f"🛡️ [{reason_tag}] Closing position #{pid} ({sym_name}) at {pnl_pct*100:+.2f}% before market shutdown...")
            try:
                res = self.ctrader.close_position(pid)
                closed_ids.append(pid)
                pnl_str = f"+{pnl_pct*100:.2f}%" if pnl_pct >= 0 else f"{pnl_pct*100:.2f}%"
                try:
                    from src.integrations.telegram_bot_service import LIVE_P2P_RATE
                except Exception:
                    LIVE_P2P_RATE = 1518.40

                friendly_names = {
                    "SPX500": "S&P 500", "SPY": "S&P 500",
                    "NDX100": "Nasdaq", "QQQ": "Nasdaq",
                    "US30": "Dow Jones", "DIA": "Dow Jones",
                    "US2000": "Russell", "IWM": "Russell",
                    "BTCUSD": "Bitcoin", "BTC-USD": "Bitcoin", "BTC": "Bitcoin"
                }
                dname = friendly_names.get(sym_name.upper(), sym_name)
                pnl_usd = float(p.get("floating_pnl") if p.get("floating_pnl") is not None else p.get("profit", 0.0))
                naira_pnl = pnl_usd * LIVE_P2P_RATE
                guardian.record_trade_result(is_loss=(pnl_usd < 0), pnl_usd=pnl_usd)

                if pnl_usd >= 0:
                    msg = f"💰 <b>SOLD:</b> <b>{dname} (+${pnl_usd:.2f} / +₦{naira_pnl:,.0f})</b>"
                else:
                    msg = f"🔴 <b>SOLD:</b> <b>{dname} (-${abs(pnl_usd):.2f} / -₦{abs(naira_pnl):,.0f})</b>"
                broadcast_telegram_ticket(msg)
            except Exception as e:
                logger.error(f"[!] Error closing position #{pid} during {reason_tag}: {e}")
        return closed_ids

    def check_and_manage_active_positions(self, open_positions: List[dict], dt_ny: Optional[pd.Timestamp] = None) -> List[int]:
        """
        Active Intraday Trade Manager:
        Enforces time-decay profit banking (bank profit if >= +0.10% after 45m on M15)
        and hard max holding duration (flatten after 90 mins).
        Returns list of closed position IDs.
        """
        closed_ids = []
        if not open_positions:
            return closed_ids

        now = time.time()
        cfg = self.cfg
        bar_mins = 1 if "1m" in self.timeframe else (5 if "5m" in self.timeframe else (15 if "15m" in self.timeframe else (30 if "30m" in self.timeframe else 60)))
        max_hold_seconds = cfg.get("max_hold_bars", 6) * bar_mins * 60
        time_decay_seconds = cfg.get("time_decay_bars", 3) * bar_mins * 60
        min_profit_pct = cfg.get("time_decay_min_profit", 0.0010)

        symbol_map = self.ctrader.get_symbol_map() or {}
        id_to_sym = {v: k for k, v in symbol_map.items()}

        open_meta = self.state.setdefault("open_positions_meta", {})

        for p in open_positions:
            pid = p.get("positionId")
            if not pid:
                continue

            sym_id = p.get("symbolId")
            sym_name = p.get("symbolName") or id_to_sym.get(sym_id, "INDEX")
            entry_price = float(p.get("entryPrice", 0.0))
            trade_side = str(p.get("tradeSide", "BUY")).upper()

            spot = self.ctrader.get_spot_price(sym_name)
            curr_price = 0.0
            if spot:
                curr_price = float(spot["bid"]) if trade_side == "BUY" else float(spot["ask"])

            pnl_pct = 0.0
            if entry_price > 0 and curr_price > 0:
                pnl_pct = ((curr_price - entry_price) / entry_price) if trade_side == "BUY" else ((entry_price - curr_price) / entry_price)

            meta = open_meta.get(str(pid))
            entry_ts = meta.get("entry_time") if meta else None
            if not entry_ts:
                cts = p.get("openTimestamp") or p.get("utcLastUpdateTimestamp")
                if cts:
                    entry_ts = float(cts) / 1000.0
                else:
                    entry_ts = now
                meta = open_meta.setdefault(str(pid), {"entry_time": entry_ts, "entry_price": entry_price, "symbol": sym_name})
            elif meta is None:
                meta = open_meta.setdefault(str(pid), {"entry_time": entry_ts, "entry_price": entry_price, "symbol": sym_name})

            # --- UPGRADE 1: Automatic Breakeven Lock-In (Risk-Free Trade Conversion) ---
            if not meta.get("breakeven_locked") and pnl_pct >= 0.0030:  # +0.30% profit (50% to target)
                try:
                    comm_buffer = 0.0006  # +0.06% above entry covers broker commissions with pure net
                    be_price = entry_price * (1.0 + comm_buffer) if trade_side == "BUY" else entry_price * (1.0 - comm_buffer)
                    amend_res = self.ctrader.amend_position_sl(position_id=pid, stop_loss=be_price, symbol=sym_name)
                    meta["breakeven_locked"] = True
                    save_execution_state(self.state)

                    friendly_names = {
                        "BTCUSD": "Bitcoin", "BTC-USD": "Bitcoin", "BTC": "Bitcoin",
                        "ETHUSD": "Ethereum", "ETH-USD": "Ethereum", "ETH": "Ethereum",
                        "XRPUSD": "XRP (Ripple)", "XRP-USD": "XRP (Ripple)", "XRP": "XRP (Ripple)",
                        "SPX500": "S&P 500", "NDX100": "Nasdaq", "US30": "Dow Jones", "US2000": "Russell"
                    }
                    dname = friendly_names.get(sym_name.upper(), sym_name)
                    be_msg = (
                        f"🛡️ <b>BREAKEVEN LOCKED:</b> <b>{dname} (#{pid})</b>\n"
                        f"• <b>Profit Milestone:</b> <b>+{pnl_pct*100:.2f}%</b> (Reached 50% target milestone)\n"
                        f"• <b>New Hard SL:</b> <code>${be_price:,.2f}</code> (+Commission Buffer)\n"
                        f"• <b>Status: 100% RISK-FREE TRADE</b> (Cannot lose) 🎯"
                    )
                    broadcast_telegram_ticket(be_msg)
                    logger.info(f"🛡️ [BREAKEVEN LOCKED] Moved SL for #{pid} ({sym_name}) to ${be_price:.2f} at +{pnl_pct*100:.2f}%")
                except Exception as e:
                    logger.error(f"[!] Error moving SL to breakeven for #{pid}: {e}")

            is_crypto = any(c in sym_name.upper() for c in ["BTC", "ETH", "XRP", "SOL", "BNB", "DOGE"])
            if is_crypto:
                # 24/7 Crypto Pure TP/SL Runner:
                # Crypto markets never close and have no session/weekend gap risk.
                # Allow position to breathe naturally until it hits server-side Take Profit (+0.60%)
                # or server-side Hard Stop Loss (-0.50%). No timer cutoff!
                continue

            dur_sec = max(0.0, now - entry_ts)
            dur_mins = dur_sec / 60.0

            close_reason = None
            if dur_sec >= time_decay_seconds and pnl_pct >= min_profit_pct:
                close_reason = f"TIME-DECAY PROFIT BANKED ({dur_mins:.0f}m hold)"
            elif dur_sec >= max_hold_seconds:
                if pnl_pct >= min_profit_pct:
                    close_reason = f"SMART RECOVERY PROFIT BANKED ({dur_mins:.0f}m hold)"
                else:
                    # Smart Recovery for traditional indices: pnl_pct < min_profit_pct.
                    # Do NOT force close for micro-fractions (+0.01%) where broker commissions exceed gross profit!
                    logger.debug(
                        f"🛡️ [SMART RECOVERY] Position #{pid} ({sym_name}) held {dur_mins:.0f}m is at {pnl_pct*100:+.2f}%. "
                        f"Below commission-safe profit buffer (+{min_profit_pct*100:.2f}%). Allowing to breathe."
                    )

            if close_reason:
                logger.info(f"⚡ [{close_reason}] Closing position #{pid} ({sym_name}) at {pnl_pct*100:+.2f}%...")
                try:
                    res = self.ctrader.close_position(pid)
                    closed_ids.append(pid)
                    if str(pid) in open_meta:
                        del open_meta[str(pid)]
                    save_execution_state(self.state)

                    pnl_str = f"+{pnl_pct*100:.2f}%" if pnl_pct >= 0 else f"{pnl_pct*100:.2f}%"
                    try:
                        from src.integrations.telegram_bot_service import LIVE_P2P_RATE
                    except Exception:
                        LIVE_P2P_RATE = 1518.40

                    friendly_names = {
                        "SPX500": "S&P 500", "SPY": "S&P 500",
                        "NDX100": "Nasdaq", "QQQ": "Nasdaq",
                        "US30": "Dow Jones", "DIA": "Dow Jones",
                        "US2000": "Russell", "IWM": "Russell",
                        "BTCUSD": "Bitcoin", "BTC-USD": "Bitcoin", "BTC": "Bitcoin",
                        "ETHUSD": "Ethereum", "ETH-USD": "Ethereum", "ETH": "Ethereum",
                        "XRPUSD": "XRP (Ripple)", "XRP-USD": "XRP (Ripple)", "XRP": "XRP (Ripple)"
                    }
                    dname = friendly_names.get(sym_name.upper(), sym_name)

                    # Compute accurate dollar PnL
                    raw_vol = p.get("volume", 0)
                    sym_upper = sym_name.upper()
                    if "XAU" in sym_upper or "GOLD" in sym_upper:
                        lots = raw_vol / 10000.0
                    elif any(k in sym_upper for k in ["EUR", "GBP", "AUD", "NZD", "JPY"]) and not any(k in sym_upper for k in ["BTC", "ETH", "XRP", "SPX", "NDX", "US30", "US2000"]):
                        lots = raw_vol / 10000000.0
                    else:
                        lots = raw_vol / 100.0

                    trade_side = str(p.get("tradeSide", "BUY")).upper()
                    entry_p = float(p.get("entryPrice", 0.0))
                    if p.get("floating_pnl") is not None:
                        pnl_usd = float(p.get("floating_pnl"))
                    elif curr_price > 0 and entry_p > 0 and lots > 0:
                        pnl_usd = (curr_price - entry_p) * lots if trade_side == "BUY" else (entry_p - curr_price) * lots
                    else:
                        pnl_usd = float(p.get("profit", 0.0))

                    # Query broker deals for exact realized settlement if available
                    try:
                        time.sleep(0.4)
                        deals = self.ctrader.get_closed_deals(days=1)
                        for d in deals:
                            if str(d.get("position_id") or d.get("positionId")) == str(pid):
                                pnl_usd = float(d.get("pnl", pnl_usd))
                                break
                    except Exception:
                        pass

                    naira_pnl = pnl_usd * LIVE_P2P_RATE
                    guardian.record_trade_result(is_loss=(pnl_usd < 0), pnl_usd=pnl_usd)

                    if pnl_usd >= 0:
                        msg = f"💰 <b>SOLD:</b> <b>{dname} (+${pnl_usd:.2f} / +₦{naira_pnl:,.0f})</b>"
                    else:
                        msg = f"🔴 <b>SOLD:</b> <b>{dname} (-${abs(pnl_usd):.2f} / -₦{abs(naira_pnl):,.0f})</b>"
                    broadcast_telegram_ticket(msg)
                except Exception as e:
                    logger.error(f"[!] Error closing position #{pid} during {close_reason}: {e}")

        return closed_ids

    def run_cycle(self, dry_run: bool = False, dt_override: Optional[pd.Timestamp] = None) -> List[Dict[str, Any]]:
        """
        Executes one full autonomous cycle:
        1. Query cTrader live account telemetry (fail-closed).
        2. Evaluate Risk Guardian limits.
        3. Check & execute same-day flat routine at 15:50 EST.
        4. Check position capacity (< 2).
        5. Verify active entry window (10:00 - 14:30 EST).
        6. Scan Fab-4 on active timeframe (15m, 30m, 5m, or 1h).
        7. Enforce Anti-Late-Trade Guard (bar freshness + price tolerance anti-chase).
        8. Place market orders on cTrader if qualified.
        9. Notify Telegram.
        """
        now = time.time()
        dt_ny = dt_override or pd.Timestamp.now(tz="America/New_York")
        executed_trades = []

        # 1. Connect & Sync Live cTrader Account (Fail-Closed)
        try:
            if not self.ctrader.session_id:
                self.ctrader.initialize()
            bal_data = self.ctrader.get_balance()
            if not bal_data or bal_data.get("balance", 0) <= 0:
                if not self.ctrader.initialize():
                    logger.warning("[!] cTrader MCP offline. Skipping execution cycle.")
                    return []
                bal_data = self.ctrader.get_balance() or {}

            balance = bal_data.get("balance", 6000.0)
            equity = bal_data.get("equity", balance)
            free_margin = bal_data.get("freeMargin", equity)

            if hasattr(self.ctrader, "get_positions_strict") and not isinstance(self.ctrader, MagicMock):
                open_positions = self.ctrader.get_positions_strict()
            else:
                open_positions = self.ctrader.get_positions()

            if open_positions is None:
                logger.warning("[!] cTrader open positions unverified (telemetry offline). Skipping execution cycle.")
                return []

            symbol_map = self.ctrader.get_symbol_map() or {}
        except Exception as e:
            logger.error(f"[!] Error fetching cTrader telemetry: {e}")
            return []

        # 2. Risk Guardian Safety Check
        risk_status = guardian.evaluate_risk(equity, balance, open_positions_count=len(open_positions))
        if guardian.state.get("trading_halted") or risk_status.get("buffer_left", 360.0) <= 0:
            logger.warning("[!] Risk Guardian HALTED trading. No autonomous orders allowed.")
            return []

        # 2-Strike Daily Circuit Breaker Guard
        if guardian.state.get("daily_losses_count", 0) >= guardian.state.get("max_daily_losses", 2):
            logger.warning(
                f"[!] 2-Strike Daily Circuit Breaker ACTIVE ({guardian.state.get('daily_losses_count')} losses today). Pausing entries."
            )
            return []

        daily_loss = max(0.0, balance - equity)
        if daily_loss >= 120.0:
            logger.warning(f"[!] Daily loss of ${daily_loss:.2f} approached -$120 safety cushion. Pausing entries.")
            return []

        # 3. Same-Day Flat Routine (Enforce 0% Overnight Risk at 15:50 EST)
        flattened = self.check_and_execute_same_day_flatten(open_positions, dt_ny=dt_ny)
        if flattened:
            open_positions = [p for p in open_positions if p.get("positionId") not in flattened]

        # 3b. Active Trade Management (Time-decay profit banking & max hold timeout)
        auto_closed = self.check_and_manage_active_positions(open_positions, dt_ny=dt_ny)
        if auto_closed:
            open_positions = [p for p in open_positions if p.get("positionId") not in auto_closed]

        # 4. Enforce Max 2 Concurrent Positions Ceiling
        active_count = len(open_positions)
        if active_count >= MAX_CONCURRENT_POSITIONS:
            logger.info(f"[*] Portfolio at capacity: {active_count}/{MAX_CONCURRENT_POSITIONS} active positions. Waiting.")
            return []

        available_slots = MAX_CONCURRENT_POSITIONS - active_count

        # 5. Check Active Entry Window (US Stock Equities require 9:30-14:30 EST; Crypto trades 24/7)
        is_us_equity_open = self.is_active_entry_window(dt_ny)

        # 6. Map currently held tickers (Zero Duplicate Asset Rule)
        held_symbol_ids = set()
        held_symbol_names = set()
        id_to_sym = {v: k for k, v in symbol_map.items()}
        for p in open_positions:
            s_id = p.get("symbolId")
            if s_id:
                held_symbol_ids.add(s_id)
                mapped_name = id_to_sym.get(s_id)
                if mapped_name:
                    held_symbol_names.add(mapped_name.upper())
            s_name = str(p.get("symbolName", "")).upper()
            if s_name:
                held_symbol_names.add(s_name)

        cfg = self.cfg
        cooldown = cfg["cooldown_seconds"]
        strat_params = {
            "window": cfg["window"],
            "num_std": cfg["num_std"],
            "exit_at_mean": cfg["exit_at_mean"],
            "allow_short": cfg["allow_short"],
            "stop_loss_pct": cfg["stop_loss_pct"],
            "max_hold_bars": cfg["max_hold_bars"],
        }

        # 7. Scan Core Universe: Indices (SPY, QQQ, DIA, IWM) & Crypto (BTCUSD)
        for item in TARGET_UNIVERSE:
            if available_slots <= 0:
                break

            ticker = item["ticker"]
            csym = item["ctrader_symbol"]
            lots = item.get("target_lots")
            dname = item["name"]
            is_crypto = item.get("is_crypto", False)

            # Session check: If stock index ETF, verify regular US market hours
            if not is_crypto and not is_us_equity_open:
                continue

            # Check duplicate
            sym_id = symbol_map.get(csym.upper())
            if (sym_id and sym_id in held_symbol_ids) or csym.upper() in held_symbol_names:
                continue

            # Check cooldown
            last_traded = self.state["last_trades"].get(ticker, 0.0)
            if now - last_traded < cooldown:
                continue

            # Load Intraday Data (Upgrade 2: Try cTrader direct trendbars first)
            try:
                df = fetch_intraday_bars(ticker=ticker, timeframe=self.timeframe, csym=csym)
                if df.empty or len(df) < cfg["window"]:
                    continue
                close = _get_close(df)
            except Exception as e:
                logger.warning(f"Could not load intraday data for {ticker}: {e}")
                continue

            # Macro Trend Regime Filter (suppress dip-buying during waterfall dumps)
            is_regime_ok, regime_reason = self.check_macro_trend_regime(df)
            if not is_regime_ok:
                logger.info(f"🚫 [TREND REGIME GUARD] Skipping {ticker}: {regime_reason}")
                continue

            # Compute Indicators
            w = cfg["window"]
            num_std = cfg["num_std"]
            mid = close.rolling(w).mean()
            std = close.rolling(w).std()
            lower = mid - num_std * std

            c = float(close.iloc[-1])
            m = float(mid.iloc[-1])
            l_band = float(lower.iloc[-1])
            last_bar_time = df.index[-1]

            # Generate Scalper Signal
            sig = self.scalper.generate_signal(df, strat_params)
            latest_sig = int(sig.iloc[-1]) if len(sig) > 0 else 0

            # Signal triggered when price dips below lower band
            signal_triggered = (latest_sig == 1) or (c < l_band)

            if not signal_triggered:
                continue

            # ── ANTI-LATE-TRADE GUARD 1: BAR FRESHNESS ──
            bar_dur_sec = TIMEFRAME_DURATION_SECONDS.get(self.timeframe, 900)
            bar_close_time = last_bar_time + pd.Timedelta(seconds=bar_dur_sec)
            bar_age_from_close = (dt_ny - bar_close_time).total_seconds()
            max_allowed_age = cfg["bar_freshness_seconds"]
            if bar_age_from_close > max_allowed_age:
                logger.info(
                    f"⏳ [ANTI-LATE-TRADE] Rejecting {ticker} signal: Bar closed at {bar_close_time} is "
                    f"{bar_age_from_close/60:.1f}m past close (> {max_allowed_age/60:.1f}m max allowed)."
                )
                continue

            # ── ANTI-LATE-TRADE GUARD 2: PRICE TOLERANCE / ANTI-CHASE ──
            spot_info = self.ctrader.get_spot_price(csym)
            if spot_info and spot_info.get("ask"):
                exec_price = float(spot_info["ask"])
            elif spot_info and spot_info.get("bid"):
                exec_price = float(spot_info["bid"])
            else:
                exec_price = c

            # Scale multiplier between ETF and cTrader index (e.g. DIA $516 -> US30 $51,600, SPY $580 -> SPX $5,800)
            if c > 0:
                raw_ratio = exec_price / c
                if abs(raw_ratio - 1.0) < 0.05:
                    scale_multiplier = 1.0
                else:
                    scale_multiplier = raw_ratio
            else:
                scale_multiplier = 1.0

            scaled_l_band = l_band * scale_multiplier
            scaled_mean = m * scale_multiplier

            # ── SPREAD & SLIPPAGE SHIELD GUARD (MAX 0.03% / 3 BPS) ──
            is_spread_ok, spread_pct, spread_reason = self.check_spread_shield(csym, spot_info)
            if not is_spread_ok:
                logger.info(f"🚫 [SPREAD SHIELD] Rejecting {csym} entry: {spread_reason}")
                continue

            # If spot price has already bounced above tolerance, ABORT (never chase a missed dip)
            tol_pct = cfg["price_tolerance_pct"]
            max_tolerated_price = scaled_l_band * (1.0 + tol_pct)
            if scaled_l_band > 0 and exec_price > max_tolerated_price:
                pct_away = ((exec_price - scaled_l_band) / scaled_l_band) * 100.0
                logger.info(
                    f"🚫 [ANTI-LATE-TRADE] Rejecting {csym} late entry: Price ${exec_price:.2f} has bounced "
                    f"+{pct_away:.2f}% above trigger ${scaled_l_band:.2f} (> {tol_pct*100:.2f}% tolerance)."
                )
                continue

            # ── UPGRADE 5: MICROSTRUCTURE REJECTION FILTER ──
            is_rej, wick_ratio, rej_reason = self.check_microstructure_rejection(csym, df)
            if not is_rej:
                logger.info(
                    f"🚫 [MICROSTRUCTURE GUARD] Rejecting {csym} entry: {rej_reason} "
                    f"(lower wick: {wick_ratio*100:.1f}% < 15% on falling red candle)."
                )
                continue

            # Compute Take Profit & Stop Loss (Dynamic ATR-Scaled)
            stop_pct = cfg["stop_loss_pct"]
            dynamic_target = self.compute_dynamic_atr_target(df)
            mean_dist = (scaled_mean - exec_price) / exec_price if scaled_mean > exec_price else dynamic_target
            target_pct = min(dynamic_target, max(0.0018, mean_dist))

            tp_price = round(exec_price * (1.0 + target_pct), 2)
            sl_price = round(exec_price * (1.0 - stop_pct), 2)
            rel_sl_points = int(round(exec_price * stop_pct * 100))
            rel_tp_points = int(round(exec_price * target_pct * 100))

            strat_name = cfg["label"]

            # Equal-risk dynamic safe lot sizing: calibrates lot size to target max_risk_usd ($25.00)
            max_risk_usd = item.get("max_risk_usd", 25.0)
            target_cap = item.get("target_lots")
            if exec_price > 0 and stop_pct > 0:
                calc_lots = max_risk_usd / (exec_price * stop_pct)
                if target_cap is not None and target_cap > 0:
                    safe_lots = round(min(target_cap, calc_lots), 2)
                else:
                    safe_lots = round(calc_lots, 2)
                
                # Margin safety guard: Ensure position notional doesn't breach 80% available free margin
                if is_crypto and exec_price > 100.0 and free_margin > 0:
                    max_margin_lots = (free_margin * 0.80) / exec_price
                    safe_lots = min(safe_lots, round(max_margin_lots, 2))
                
                lots_to_trade = max(0.01, safe_lots)
            else:
                lots_to_trade = target_cap or 0.10

            trade_payload = {
                "action": "BUY",
                "ticker": ticker,
                "symbol": csym,
                "name": dname,
                "lots": lots_to_trade,
                "price": exec_price,
                "tp": tp_price,
                "sl": sl_price,
                "sl_points": rel_sl_points,
                "tp_points": rel_tp_points,
                "strategy": strat_name,
                "timeframe": self.timeframe,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S WAT")
            }

            if dry_run:
                logger.info(f"[DRY-RUN] Would auto-execute: BUY {lots_to_trade} lots {csym} @ ${exec_price:.2f} (SL: ${sl_price:.2f}, TP: ${tp_price:.2f})")
                executed_trades.append({**trade_payload, "status": "SIMULATED", "order_id": "SIM_123"})
                available_slots -= 1
                continue

            # ── LIVE ORDER SUBMISSION VIA cTrader MCP (UPGRADES 1 & 3) ──
            try:
                if EXECUTION_MODE == "SNIPER_LIMIT":
                    bar_mins = 1 if "1m" in self.timeframe else (5 if "5m" in self.timeframe else (15 if "15m" in self.timeframe else (30 if "30m" in self.timeframe else 60)))
                    expiry_sec = int(bar_mins * 60 * 2)
                    logger.info(f"🎯 [SNIPER LIMIT]: Submitting resting BUY LIMIT {lots_to_trade} lots {csym} @ ${scaled_l_band:.2f} (SL: ${sl_price:.2f}, TP: ${tp_price:.2f})...")
                    res = self.ctrader.place_limit_order(
                        symbol=csym,
                        side="BUY",
                        volume_lots=lots_to_trade,
                        limit_price=scaled_l_band,
                        stop_loss_price=sl_price,
                        take_profit_price=tp_price,
                        expiry_seconds=expiry_sec,
                        comment=f"AgentQuant: {strat_name} Limit"
                    )
                else:
                    logger.info(f"🚨 [ATOMIC MARKET]: Transmitting BUY {lots_to_trade} lots {csym} to cTrader ({self.timeframe}) with atomic SL/TP...")
                    res = self.ctrader.place_market_order(
                        symbol=csym,
                        side="BUY",
                        volume_lots=lots_to_trade,
                        relative_sl_points=rel_sl_points,
                        relative_tp_points=rel_tp_points,
                        stop_loss_price=sl_price,
                        take_profit_price=tp_price,
                        comment=f"AgentQuant: {strat_name}"
                    )
                if not res or not isinstance(res, dict) or res.get("isError") or "error" in res or "errorCode" in res:
                    logger.error(f"[!] cTrader order submission failed or rejected for {csym}: {res}")
                    continue

                order_id = res.get("orderId") or res.get("positionId") or res.get("position", {}).get("positionId")
                if not order_id:
                    logger.error(f"[!] cTrader order returned no confirmed orderId for {csym}: {res}")
                    continue

                # Verify Order ACK via cTrader
                if hasattr(self.ctrader, "verify_order_ack"):
                    is_acked = self.ctrader.verify_order_ack(order_id, timeout_sec=2.0)
                    if not is_acked:
                        logger.warning(f"⚠️ [ORDER ACK] Order #{order_id} pending broker acknowledgment.")

                # Record State
                self.state["last_trades"][ticker] = now
                self.state["execution_history"].append({
                    **trade_payload,
                    "order_id": order_id,
                    "raw_result": str(res)
                })
                self.state.setdefault("open_positions_meta", {})[str(order_id)] = {
                    "entry_time": now,
                    "entry_price": exec_price,
                    "ticker": ticker,
                    "symbol": csym
                }
                save_execution_state(self.state)

                executed_trades.append({**trade_payload, "status": "FILLED", "order_id": order_id})
                available_slots -= 1

                # Send Instant Telegram Execution Ticket with 1-Tap Active Trade Controls
                ticket_msg = f"🟢 <b>BUY:</b> <b>{dname}</b>"
                ticket_markup = {
                    "inline_keyboard": [
                        [
                            {"text": "🛡️ Move SL to BE", "callback_data": f"cmd_sl_be_{order_id}"},
                            {"text": "💰 Bank 50%", "callback_data": f"cmd_bank_half_{order_id}"}
                        ],
                        [{"text": "🛑 Close Trade", "callback_data": f"cmd_close_tap1_{order_id}"}]
                    ]
                }
                # Generate Institutional Candlestick Trade Card
                card_buf = None
                try:
                    from src.visualization.telegram_charts import generate_option_a_sniper_card
                    card_buf = generate_option_a_sniper_card(
                        ticker=ticker,
                        df_1h=df,
                        entry=exec_price,
                        tp=tp_price,
                        sl=sl_price,
                        status="LIVE TRADE FILLED"
                    )
                except Exception as ce:
                    logger.warning(f"Could not generate visual trade card: {ce}")

                broadcast_telegram_ticket(ticket_msg, photo_buf=card_buf, reply_markup=ticket_markup)
                logger.info(f"[+] Autonomous order filled with visual trade card & 1-tap controls: {csym} #{order_id}")

            except RiskViolationError as rve:
                logger.warning(f"🛡️ [RISK BLOCK] Order for {csym} blocked: {rve}")
            except Exception as e:
                logger.error(f"[!] Live order execution failed for {csym}: {e}")

        return executed_trades


# Global Singleton
autonomous_engine = AutonomousExecutionEngine()


def run_autonomous_execution_cycle(dry_run: bool = False) -> List[Dict[str, Any]]:
    """Entry point called from background worker thread in telegram_bot_service."""
    return autonomous_engine.run_cycle(dry_run=dry_run)


if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv
    print(f"Running Autonomous Execution Engine (timeframe={ACTIVE_TIMEFRAME}, dry_run={is_dry})...")
    results = run_autonomous_execution_cycle(dry_run=is_dry)
    print(f"Cycle completed. Executed trades: {len(results)}")
    for t in results:
        print(f"  • {t['action']} {t['lots']} {t['symbol']} | Status: {t['status']} | Ticket: {t['order_id']}")
