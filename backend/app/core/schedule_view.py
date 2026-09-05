"""A crew member's week, before and after a proposed cover -- for the UI.

Built on ``windows.merged_timeline`` -- the exact primitive the rule engine
itself evaluates against (see ``rules/base.py:CoverContext.timeline``) -- so
the "after" schedule shown to a controller can never disagree with the
timeline RULE-REST-04, RULE-DUTY-02 and the others actually judged. This is
deliberately not a second implementation of "what does the week look like":
it calls the same function, with the same inputs, that produced the legality
verdict being explained.

Cover segments carry ``flight_hours = 0.0``, matching ``CoverContext``'s own
convention (see ``rules/flt03.py`` / ``docs/LIMITATIONS.md`` §1.1) --
the reference generator's ``check_cover`` does the same, so a simulated
assignment leaves the 28-day block-hour total exactly as the rule engine sees
it.
"""

from __future__ import annotations

from .models import DutySegment
from .timeutil import fmt_dt, hrs
from .windows import merged_timeline
from .world import World


def _segment_dict(seg: DutySegment) -> dict:
    return {
        "date": seg.date.isoformat(),
        "pairing_id": seg.label,
        "report_utc": fmt_dt(seg.report_utc),
        "release_utc": fmt_dt(seg.release_utc),
        "duty_hours": seg.duty_hours,
        "flight_hours": seg.flight_hours,
        "is_cover": seg.is_cover,
    }


def _day_conflicts(world: World, crew_id: str, day) -> list[dict]:
    conflicts: list[dict] = []
    day_s = day.isoformat()
    for row in world.flagged_exceptions:
        if row.get("crew_id") == crew_id and str(row.get("date")) == day_s:
            conflicts.append(
                {"rule": "FLAGGED", "message": str(row.get("note") or "flagged roster exception")}
            )
    for cert in world.certs(crew_id).values():
        if cert.valid_to < day:
            conflicts.append(
                {
                    "rule": "RULE-CERT-06",
                    "message": f"{cert.cert_type} valid to {cert.valid_to.isoformat()}",
                }
            )
    return conflicts


def _days_grid(world: World, crew_id: str, segments: list[DutySegment]) -> list[dict]:
    by_date = {s.date: s for s in segments}
    days = []
    for day in world.dates:
        seg = by_date.get(day)
        conflicts = _day_conflicts(world, crew_id, day) if seg is not None else []
        if seg is None:
            status = "off"
        elif conflicts:
            status = "conflict"
        elif seg.is_cover:
            status = "cover"
        else:
            status = "rostered"
        days.append(
            {
                "date": day.isoformat(),
                "status": status,
                "pairing_id": None if seg is None else seg.label,
                "duty_hours": None if seg is None else seg.duty_hours,
                "flight_hours": None if seg is None else seg.flight_hours,
                "report_utc": None if seg is None else fmt_dt(seg.report_utc),
                "release_utc": None if seg is None else fmt_dt(seg.release_utc),
                "conflicts": conflicts,
            }
        )
    return days


def crew_schedule_window(
    world: World,
    crew_id: str,
    *,
    cover_pairing_id: str | None = None,
) -> dict:
    """The crew member's published week as a day grid the profile can render.

    Always includes ``days`` (one cell per published date). When a cover
    pairing is given, also returns ``before`` / ``after`` / ``added_dates``
    so a proposed assignment can be shown as a diff.
    """
    before = merged_timeline(world, crew_id)
    cover_segments: list[DutySegment] = []
    added_dates: list[str] = []
    if cover_pairing_id:
        pairing = world.get_pairing(cover_pairing_id)
        if pairing is not None:
            cover_segments = [
                DutySegment(
                    date=day.date,
                    report_utc=day.report_utc,
                    release_utc=day.release_utc,
                    duty_hours=hrs(day.release_utc - day.report_utc),
                    flight_hours=0.0,
                    label="COVER",
                )
                for day in pairing.days
            ]
            added_dates = [day.date.isoformat() for day in pairing.days]

    after = merged_timeline(world, crew_id, extra=cover_segments) if cover_segments else before
    days = _days_grid(world, crew_id, after)
    conflict_count = sum(len(d["conflicts"]) for d in days)

    result: dict = {
        "crew_id": crew_id,
        "window_start": world.dates[0].isoformat() if world.dates else None,
        "window_end": world.dates[-1].isoformat() if world.dates else None,
        "cover_pairing_id": cover_pairing_id,
        "conflict_count": conflict_count,
        "safe_to_assign": conflict_count == 0,
        "days": days,
        "before": [_segment_dict(s) for s in before],
    }
    if cover_pairing_id is not None:
        result["after"] = [_segment_dict(s) for s in after]
        result["added_dates"] = added_dates
    return result
