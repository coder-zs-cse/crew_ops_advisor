"""Duty-period arithmetic.

Conventions (rules.json ``definitions``):
    report  = first departure - 60 min
    release = last arrival    + 30 min
    FDP     = release - report
    sector  = one flight leg
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import PairingDay
from .timeutil import hrs
from .world import World

REPORT_LEAD_MINUTES = 60
RELEASE_TRAIL_MINUTES = 30

BASE_FDP_HOURS = 13.0
FREE_SECTORS = 2
REDUCTION_PER_EXTRA_SECTOR = 0.5


def fdp_limit(sectors: int) -> float:
    """RULE-FDP-01: 13h, reduced 0.5h for every sector beyond the 2nd."""
    return BASE_FDP_HOURS - REDUCTION_PER_EXTRA_SECTOR * max(0, sectors - FREE_SECTORS)


def duty_length(day: PairingDay) -> float:
    return hrs(day.release_utc - day.report_utc)


def shifted(day: PairingDay, delay_hours: float) -> tuple[datetime, datetime]:
    """Report/release after a uniform delay applied to the whole duty."""
    offset = timedelta(hours=delay_hours)
    return day.report_utc + offset, day.release_utc + offset


def derive_report(first_departure: datetime) -> datetime:
    return first_departure - timedelta(minutes=REPORT_LEAD_MINUTES)


def derive_release(last_arrival: datetime) -> datetime:
    return last_arrival + timedelta(minutes=RELEASE_TRAIL_MINUTES)


def day_block_hours(world: World, day: PairingDay) -> float:
    return round(sum(world.flight(fid).block_hours for fid in day.flight_ids), 2)


def day_seats(world: World, day: PairingDay) -> int:
    return sum(world.flight(fid).seats for fid in day.flight_ids)


def earliest_next_report(release_utc: datetime, min_rest_hours: float = 12.0) -> datetime:
    """RULE-REST-04 forward calculation (question Q23)."""
    return release_utc + timedelta(hours=min_rest_hours)
