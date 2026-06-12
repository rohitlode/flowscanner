from __future__ import annotations
import time
from datetime import datetime, date
from pathlib import Path
import config

_HOLIDAYS: set[date] = {
    date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17),
    date(2025, 4, 18), date(2025, 5, 26), date(2025, 6, 19),
    date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27),
    date(2025, 12, 25),
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3),  date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3),  date(2026, 9, 7),  date(2026, 11, 26),
    date(2026, 12, 25),
}

def market_is_open(now: datetime | None = None) -> bool:
    try:
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        tz = ZoneInfo(config.MARKET_TZ)
        local = (now or datetime.now(tz)).astimezone(tz)
    except Exception:
        local = now or datetime.now()
    if local.weekday() >= 5:
        return False
    if local.date() in _HOLIDAYS:
        return False
    open_t  = local.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = local.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_t <= local <= close_t


class ScanLock:
    class Busy(Exception): pass
    _path = config.DATA_DIR / "scan.lock"
    _STALE_SECS = 300

    def __enter__(self):
        p = self._path
        if p.exists():
            age = time.time() - p.stat().st_mtime
            if age < self._STALE_SECS:
                raise ScanLock.Busy(f"Scan already running (lock age {age:.0f}s)")
            p.unlink()
        p.write_text(str(time.time()))
        return self

    def __exit__(self, *_):
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
