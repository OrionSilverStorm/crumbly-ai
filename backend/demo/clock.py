"""Timezone-aware clock with a demo time scale (e.g. 60x makes a 30-minute chase happen in 30 s)."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.config import settings

# All business times are Europe/London (configurable via APP_TZ).
TZ = ZoneInfo(settings.tz)
# Manual offset so tests can move time forward without sleeping.
_offset = timedelta(0)


def now() -> datetime:
    """Current wall-clock time in the bakery's timezone (plus any test offset)."""
    return datetime.now(TZ) + _offset


def advance(delta: timedelta) -> None:
    """Move the clock forward (tests only)."""
    global _offset
    _offset += delta


def scale() -> float:
    """Demo time multiplier; 1 means real time."""
    return max(settings.time_scale, 1e-6)


def business(minutes: float) -> timedelta:
    """Real-time duration of a business-time interval, compressed by the demo scale."""
    return timedelta(minutes=minutes) / scale()


def tomorrow() -> date:
    """Tomorrow's production date in the bakery's timezone."""
    return (now() + timedelta(days=1)).date()


def at(day: date, hhmm: str) -> datetime:
    """Aware datetime for a local 'HH:MM' on a given day."""
    h, m = (int(p) for p in hhmm.split(":"))
    return datetime.combine(day, time(h, m), TZ)


def local(dt: datetime | None) -> datetime | None:
    """Normalise any datetime to the bakery timezone (naive values are treated as UTC, as warehouses return them)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TZ)


def hhmm(dt: datetime | None) -> str:
    """Format a datetime as local HH:MM ('' for None)."""
    return local(dt).strftime("%H:%M") if dt else ""
