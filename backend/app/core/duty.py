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
from .rule_params import rule_param
from .timeutil import hrs
from .world import World

REPORT_LEAD_MINUTES = 60
RELEASE_TRAIL_MINUTES = 30

#: Sample-dataset fallbacks only -- used when no ``World`` is available (a few
#: unit tests exercise this arithmetic in isolation). Whenever a ``World`` is
#: passed, ``rules.json``'s own params win; see ``rule_params.py``.
BASE_FDP_HOURS = 13.0
FREE_SECTORS = 2
REDUCTION_PER_EXTRA_SECTOR = 0.5


def fdp_limit(sectors: int, world: World | None = None) -> float:
    """RULE-FDP-01: base hours, reduced per sector beyond the free count.

    Reads ``base_fdp_hours`` / ``free_sectors`` / ``reduction_per_extra_sector_hours``
    from ``rules.json`` when ``world`` is given, so a regenerated dataset with a
    different FDP formula is honoured instead of silently ignored.
    """
    base = rule_param(world, "RULE-FDP-01", "base_fdp_hours", BASE_FDP_HOURS)
    free = rule_param(world, "RULE-FDP-01", "free_sectors", FREE_SECTORS)
    reduction = rule_param(
        world, "RULE-FDP-01", "reduction_per_extra_sector_hours", REDUCTION_PER_EXTRA_SECTOR
    )
    return base - reduction * max(0, sectors - free)


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
