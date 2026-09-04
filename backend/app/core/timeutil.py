"""UTC time helpers.

Rounding semantics here MUST match the dataset generator's ``hrs()`` exactly,
because every answer key was produced with it. Do not "improve" the rounding.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

# Floating point slack used by the generator when comparing against limits.
EPS = 1e-6


def parse_dt(value: str) -> datetime:
    """Parse a dataset UTC timestamp (``2026-09-15T06:00:00Z``) as naive UTC."""
    return datetime.strptime(value, ISO_FMT)


def fmt_dt(value: datetime) -> str:
    return value.strftime(ISO_FMT)


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def at(day: date, hhmm: str) -> datetime:
    """Combine a date with an ``HH:MM`` wall-clock string, in UTC."""
    hour, minute = hhmm.split(":")
    return datetime(day.year, day.month, day.day, int(hour), int(minute))


def hrs(delta: timedelta) -> float:
    """Hours, rounded to 2dp -- the generator's canonical duration unit."""
    return round(delta.total_seconds() / 3600.0, 2)


def hours_between(start: datetime, end: datetime) -> float:
    return hrs(end - start)


def calendar_window(end: date, days: int) -> tuple[date, date]:
    """Inclusive calendar window of ``days`` days ending on ``end``."""
    return end - timedelta(days=days - 1), end


def fmt_hm(hours: float) -> str:
    """Render a positive hour count as ``1h20m`` (generator's breach format)."""
    whole = int(hours)
    minutes = int(round((hours - whole) * 60))
    return f"{whole}h{minutes:02d}m"


def is_even_date(day: date) -> bool:
    """Date parity used by the deadhead positioning table (day-of-month)."""
    return day.day % 2 == 0
