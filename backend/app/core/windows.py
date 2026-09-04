"""Rolling calendar-day windows over a crew member's duty timeline.

Two sources feed every window:

* ``daily_history``  -- duty_clocks.json, 2026-08-18 .. 2026-09-14
* ``week_duties``    -- derived from the published roster, 2026-09-14 .. 09-20

Both are summed. Note that 2026-09-14 appears in *both* sources; the dataset
generator sums them the same way (its ``duty_hours_7d`` figures are produced by
exactly this function), so we reproduce that behaviour rather than
de-duplicating. Changing it would put us out of step with every answer key.
"""

from __future__ import annotations

from datetime import date, timedelta

from .models import DutySegment
from .world import World

DUTY = 0
FLIGHT = 1


def window_sum(
    world: World,
    crew_id: str,
    end_date: date,
    days: int,
    kind: int = DUTY,
    *,
    include_roster: bool = True,
    exclude_pairing: str | None = None,
) -> float:
    """Sum duty (kind=0) or block (kind=1) hours over a calendar window.

    The window is ``days`` calendar days ending on ``end_date`` inclusive.
    """
    start = end_date - timedelta(days=days - 1)

    total = 0.0
    for day, values in world.history(crew_id).items():
        if start <= day <= end_date:
            total += values[kind]

    if include_roster:
        for seg in world.week_duties(crew_id):
            if exclude_pairing is not None and seg.label == exclude_pairing:
                continue
            if start <= seg.date <= end_date:
                total += seg.duty_hours if kind == DUTY else seg.flight_hours

    return round(total, 2)


def duty_hours_7d(world: World, crew_id: str, end_date: date, **kw) -> float:
    return window_sum(world, crew_id, end_date, 7, DUTY, **kw)


def flight_hours_28d(world: World, crew_id: str, end_date: date, **kw) -> float:
    return window_sum(world, crew_id, end_date, 28, FLIGHT, **kw)


def rostered_segments(
    world: World, crew_id: str, *, exclude_pairing: str | None = None
) -> list[DutySegment]:
    """The crew member's published duties, optionally minus one pairing.

    Used when simulating a *replacement*: the crew being replaced no longer
    flies the excluded pairing, so it must not count against their limits.
    """
    return [
        seg
        for seg in world.week_duties(crew_id)
        if exclude_pairing is None or seg.label != exclude_pairing
    ]


def merged_timeline(
    world: World,
    crew_id: str,
    *,
    exclude_pairing: str | None = None,
    extra: list[DutySegment] | None = None,
) -> list[DutySegment]:
    """Rostered duties plus any simulated cover, sorted by report time.

    Sorting by report time (not date) matters: a cover duty and a rostered duty
    can fall on the same date, and rest is measured between consecutive duties
    in chronological order.
    """
    timeline = rostered_segments(world, crew_id, exclude_pairing=exclude_pairing)
    if extra:
        timeline = timeline + list(extra)
    timeline.sort(key=lambda s: s.report_utc)
    return timeline


def headroom(limit: float, used: float) -> float:
    return round(limit - used, 2)


def window_breakdown(
    world: World, crew_id: str, end_date: date, days: int, kind: int = DUTY
) -> list[dict]:
    """Per-day contributions inside a window -- powers the duty-budget chart."""
    start = end_date - timedelta(days=days - 1)
    history = world.history(crew_id)
    roster = {seg.date: seg for seg in world.week_duties(crew_id)}

    out = []
    cursor = start
    while cursor <= end_date:
        hist = history.get(cursor, (0.0, 0.0))[kind]
        seg = roster.get(cursor)
        planned = 0.0
        if seg is not None:
            planned = seg.duty_hours if kind == DUTY else seg.flight_hours
        out.append(
            {
                "date": cursor.isoformat(),
                "history_hours": round(hist, 2),
                "rostered_hours": round(planned, 2),
                "pairing_id": seg.label if seg else None,
                "total_hours": round(hist + planned, 2),
            }
        )
        cursor += timedelta(days=1)
    return out
