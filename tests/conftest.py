"""
Shared test fixtures.

Time determinism guard: `execute_signal` rejects every Forex order inside the
Invariant 38 Asian Rollover blackout (21:00-00:30 UTC). When the real wall clock
runs inside that window, the Forex execution tests would fail purely because of
when CI happens to run (observed 2026-11-13 21:04 UTC). The copier's clock is
therefore frozen to a safe off-window anchor, but ONLY while the real time is
inside the blackout — at every other hour the tests run on the real clock.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import src.integrations.telegram_multi_signal_copier as _copier_module


def pytest_configure(config):
    real = datetime.now(timezone.utc)
    in_blackout = real.hour in (21, 22, 23) or (real.hour == 0 and real.minute <= 30)
    if not in_blackout:
        return

    if real.hour == 0:
        # 00:00-00:30 UTC -> step back to 23:50 of the previous day (off-window)
        anchor = (real - timedelta(days=1)).replace(hour=23, minute=50, second=0, microsecond=0)
    else:
        # 21:00-23:59 UTC -> step back to 20:45 of the same day (off-window)
        anchor = real.replace(hour=20, minute=45, second=0, microsecond=0)

    class _ShiftedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return anchor.replace(tzinfo=None)
            return anchor if tz == timezone.utc else anchor.astimezone(tz)

    _copier_module.datetime = _ShiftedDateTime
