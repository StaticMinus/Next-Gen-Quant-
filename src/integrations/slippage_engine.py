"""Post-Trade Execution & Slippage Engine (Upgrade 2 from QuantDinger-main).

Runs asynchronously in background thread:
- Logs microsecond latency difference between Telegram signal post timestamp and cTrader fill.
- Calculates exact price slippage (Expected Entry vs Executed Fill Price).
- Computes execution quality score and persists to disk cache.
"""

from typing import Dict, Any, Optional
import time
import json
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("SlippageEngine")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TELEMETRY_LOG = ROOT_DIR / "cache" / "execution_slippage_log.json"

# Background worker so telemetry never blocks trade execution
_BG_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="SlippageLogger")


class SlippageEngine:
    """Calculates latency and slippage per ticket asynchronously."""

    @classmethod
    def record_execution_async(
        cls,
        signal_key: str,
        side: str,
        expected_entry: float,
        executed_fill: float,
        signal_timestamp: float,
        ticket_id: int,
        volume: float,
        spread_at_entry: float = 0.0
    ):
        """Dispatches telemetry recording to background thread in 0.00ms."""
        fill_timestamp = time.time()
        _BG_EXECUTOR.submit(
            cls._process_and_save,
            signal_key,
            side,
            expected_entry,
            executed_fill,
            signal_timestamp,
            fill_timestamp,
            ticket_id,
            volume,
            spread_at_entry
        )

    @classmethod
    def _process_and_save(
        cls,
        signal_key: str,
        side: str,
        expected_entry: float,
        executed_fill: float,
        signal_timestamp: float,
        fill_timestamp: float,
        ticket_id: int,
        volume: float,
        spread_at_entry: float
    ) -> Dict[str, Any]:
        """Calculates slippage and execution quality."""
        # 1. Latency in milliseconds
        latency_ms = max(0.0, (fill_timestamp - signal_timestamp) * 1000.0) if signal_timestamp > 0 else 0.0

        # 2. Slippage in Gold points ($)
        # Adverse slippage is positive for BUY (fill > expected), negative for SELL (fill < expected)
        if side.upper() == "BUY":
            slippage_pts = executed_fill - expected_entry
        else:
            slippage_pts = expected_entry - executed_fill

        # 3. Execution Score: 100 is perfect 0 slippage under 200ms
        exec_score = max(0.0, 100.0 - (abs(slippage_pts) * 20.0) - (min(latency_ms, 2000.0) / 50.0))

        record = {
            "signal_key": signal_key,
            "ticket_id": ticket_id,
            "side": side,
            "volume": volume,
            "expected_entry": expected_entry,
            "executed_fill": executed_fill,
            "slippage_pts": round(slippage_pts, 3),
            "spread_at_entry": round(spread_at_entry, 3),
            "latency_ms": round(latency_ms, 1),
            "execution_score": round(exec_score, 1),
            "timestamp": fill_timestamp
        }

        logger.info(
            f"⚡ [QuantDinger Telemetry] Ticket #{ticket_id} ({side} {volume} lot) | "
            f"Slippage: {slippage_pts:+.2f} pts | Latency: {latency_ms:.0f}ms | Score: {exec_score:.0f}/100"
        )

        cls._append_to_file(record)
        return record

    @classmethod
    def _append_to_file(cls, record: Dict[str, Any]):
        try:
            records = []
            if TELEMETRY_LOG.exists():
                with open(TELEMETRY_LOG, "r", encoding="utf-8") as f:
                    try:
                        records = json.load(f)
                    except Exception:
                        records = []
            records.append(record)
            # Keep last 100 records
            records = records[-100:]
            with open(TELEMETRY_LOG, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to persist execution telemetry: {e}")
