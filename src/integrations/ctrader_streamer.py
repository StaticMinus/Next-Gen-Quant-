"""
Direct cTrader Real-Time Streaming Engine
==========================================
Maintains high-frequency streaming quote feeds for SPX500 and NDX100 via cTrader MCP.
Batches multi-symbol spot updates into a single round-trip every 1-2 seconds,
updating a thread-safe, sub-millisecond in-memory cache for zero-latency execution.
"""

import json
import logging
import threading
import time
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("CTraderStreamer")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Global In-Memory Quote Cache (symbol -> quote dict)
_LIVE_STREAM_CACHE: Dict[str, dict] = {}
_CACHE_LOCK = threading.Lock()
_TICK_LISTENERS: List[Callable[[str, dict], None]] = []

# Symbol mappings for the Fab-4 US Indices universe
STREAM_SYMBOLS = {
    "SPX500": 113,
    "NDX100": 112,
    "US30": 115,
    "US2000": 117,
}
ID_TO_SYMBOL = {v: k for k, v in STREAM_SYMBOLS.items()}


class CTraderRealtimeStreamer:
    def __init__(self, interval_sec: float = 1.5):
        self.interval_sec = interval_sec
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.last_update_time: float = 0.0
        self.ticks_count: int = 0
        self.consecutive_errors: int = 0
        self.status: str = "INITIALIZING"

    def register_tick_listener(self, callback: Callable[[str, dict], None]):
        """Register a callback to be notified whenever a fresh spot price tick arrives."""
        with _CACHE_LOCK:
            if callback not in _TICK_LISTENERS:
                _TICK_LISTENERS.append(callback)

    def get_spot(self, symbol: str, max_age_seconds: float = 5.0) -> Optional[dict]:
        """
        Retrieves the latest streamed spot price from in-memory cache.
        Returns None if cache is empty or older than max_age_seconds.
        """
        sym_key = symbol.upper()
        with _CACHE_LOCK:
            data = _LIVE_STREAM_CACHE.get(sym_key)
            if data and (time.time() - data.get("updated_at", 0.0)) <= max_age_seconds:
                return dict(data)
        return None

    def get_telemetry(self) -> dict:
        """Returns streamer health, latency, and latest prices."""
        now = time.time()
        with _CACHE_LOCK:
            cached_copy = {k: dict(v) for k, v in _LIVE_STREAM_CACHE.items()}
        
        age_ms = int((now - self.last_update_time) * 1000) if self.last_update_time > 0 else -1
        return {
            "status": self.status,
            "is_running": self.is_running,
            "interval_sec": self.interval_sec,
            "ticks_count": self.ticks_count,
            "cache_age_ms": age_ms,
            "symbols_tracked": list(STREAM_SYMBOLS.keys()),
            "quotes": cached_copy,
        }

    def _stream_loop(self):
        from src.integrations.ctrader_mcp_client import ctrader_client
        logger.info(f"⚡ [cTrader Streamer]: Active. Streaming {list(STREAM_SYMBOLS.keys())} at {self.interval_sec}s cadence...")
        self.status = "CONNECTED"

        symbol_ids = list(STREAM_SYMBOLS.values())
        div = 100000.0  # cTrader indices/metals digit divisor

        while not self._stop_event.is_set():
            try:
                # Ensure MCP session is valid
                if not ctrader_client.session_id:
                    ctrader_client.initialize()

                # Call get_spot_prices in batched multi-symbol mode
                raw = ctrader_client.call_tool("get_spot_prices", {"symbolId": symbol_ids})
                data = ctrader_client._parse_content_json(raw)

                if data and isinstance(data, dict) and "prices" in data and len(data["prices"]) > 0:
                    now = time.time()
                    self.last_update_time = now
                    self.consecutive_errors = 0
                    self.status = "STREAMING_LIVE"

                    updated_quotes = []
                    with _CACHE_LOCK:
                        for p in data["prices"]:
                            sym_id = p.get("symbolId")
                            sym_name = ID_TO_SYMBOL.get(sym_id)
                            if not sym_name:
                                continue

                            bid = (p.get("bid") or 0) / div
                            ask = (p.get("ask") or 0) / div
                            high = (p.get("high") or 0) / div
                            low = (p.get("low") or 0) / div
                            close = (p.get("sessionClose") or 0) / div
                            ts = p.get("timestamp")

                            quote = {
                                "symbol": sym_name,
                                "symbolId": sym_id,
                                "bid": bid,
                                "ask": ask,
                                "mid": round((bid + ask) / 2.0, 2),
                                "spread": round(ask - bid, 2),
                                "high": high,
                                "low": low,
                                "sessionClose": close,
                                "timestamp": ts,
                                "updated_at": now,
                            }
                            _LIVE_STREAM_CACHE[sym_name] = quote
                            updated_quotes.append((sym_name, quote))
                            self.ticks_count += 1

                    # Dispatch tick listeners
                    for s_name, q in updated_quotes:
                        for listener in list(_TICK_LISTENERS):
                            try:
                                listener(s_name, q)
                            except Exception as e:
                                logger.debug(f"Tick listener error for {s_name}: {e}")

                else:
                    self.consecutive_errors += 1
                    if self.consecutive_errors >= 3:
                        self.status = "RECONNECTING"
                        ctrader_client.session_id = None
                        time.sleep(2.0)

            except Exception as e:
                self.consecutive_errors += 1
                logger.warning(f"cTrader streamer error (retry #{self.consecutive_errors}): {e}")
                if self.consecutive_errors >= 3:
                    self.status = "ERROR_RETRY"
                    from src.integrations.ctrader_mcp_client import ctrader_client
                    ctrader_client.session_id = None
                    time.sleep(2.0)

            time.sleep(self.interval_sec)

        self.status = "STOPPED"
        self.is_running = False
        logger.info("⚡ [cTrader Streamer]: Stream thread terminated gracefully.")

    def start(self):
        """Starts the streaming daemon thread."""
        if self.is_running:
            return
        self.is_running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._stream_loop, daemon=True, name="CTraderStreamer")
        self._thread.start()

    def stop(self):
        """Signals the streaming thread to stop."""
        self._stop_event.set()
        self.is_running = False


# Global Singleton Streamer
ctrader_streamer = CTraderRealtimeStreamer(interval_sec=1.5)


def get_streamed_spot_price(symbol: str) -> Optional[dict]:
    """Public helper to get instant sub-millisecond quote from stream cache."""
    return ctrader_streamer.get_spot(symbol)
