"""Deterministic read endpoints.

These exist for two reasons. The console uses them directly for everything that
is a lookup rather than a question -- no model in the path at all. And they make
the boundary demonstrable: every figure the chat surface cites is reachable here
without going near the agent.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from ...core import queries as q
from ...core.briefing import morning_briefing
from ...core.rotation import tail_rotation
from ...core.timeutil import fmt_dt
from ...core.windows import DUTY, FLIGHT, window_breakdown
from ..deps import get_clock, get_world

router = APIRouter(prefix="/api", tags=["world"])


def _today() -> date:
    return get_clock().now.date()


@router.get("/snapshot")
def snapshot() -> dict:
    world = get_world()
    start, end = world.date_range()
    return {
        "snapshot_utc": fmt_dt(world.snapshot_utc),
        "clock": get_clock().as_dict(),
        "schedule": {"start": start.isoformat(), "end": end.isoformat()},
        "counts": {
            "flights": len(world.flights),
            "crew": len(world.crew),
            "pairings": len(world.pairings),
            "reserves": len(world.reserves),
            "certifications": len(world.certifications),
        },
        "stations": list(world.stations),
        "aircraft": sorted({f.aircraft for f in world.flights}),
        "currency": world.costs.currency,
        "flagged_exceptions": [dict(x) for x in world.flagged_exceptions],
    }


# ---- crew ----------------------------------------------------------------


@router.get("/crew")
def list_crew(
    rank: str | None = None,
    base: str | None = None,
    rating: str | None = None,
    status: str | None = None,
    limit: int = Query(500, le=1000),
) -> dict:
    return q.search_crew(
        get_world(), rank=rank, base=base, rating=rating, status=status, limit=limit
    )


@router.get("/crew/{crew_id}")
def crew_detail(crew_id: str) -> dict:
    detail = q.crew_detail(get_world(), crew_id)
    if detail is None:
        raise HTTPException(404, f"crew {crew_id} not found")
    return detail


@router.get("/crew/{crew_id}/duty-clock")
def crew_duty_clock(crew_id: str, as_of: date | None = None) -> dict:
    detail = q.duty_clock(get_world(), crew_id, as_of or _today())
    if detail is None:
        raise HTTPException(404, f"crew {crew_id} not found")
    return detail


@router.get("/crew/{crew_id}/timeline")
def crew_timeline(crew_id: str, as_of: date | None = None) -> dict:
    """The 28-day duty/block chart plus the published roster strip."""
    world = get_world()
    if world.get_crew(crew_id) is None:
        raise HTTPException(404, f"crew {crew_id} not found")
    end = as_of or _today()
    return {
        "crew_id": crew_id,
        "as_of": end.isoformat(),
        "duty_28d": window_breakdown(world, crew_id, end, 28, DUTY),
        "flight_28d": window_breakdown(world, crew_id, end, 28, FLIGHT),
        "roster": q.roster_for_crew(world, crew_id)["duties"],
        "clock": q.duty_clock(world, crew_id, end),
        "limits": {"duty_7d": 60.0, "flight_28d": 100.0},
    }


@router.get("/crew/{crew_id}/roster")
def crew_roster(crew_id: str) -> dict:
    world = get_world()
    if world.get_crew(crew_id) is None:
        raise HTTPException(404, f"crew {crew_id} not found")
    return q.roster_for_crew(world, crew_id)


@router.get("/duty-scan")
def duty_scan(
    as_of: date | None = None, threshold_hours: float = 45.0, days: int = 7
) -> dict:
    return q.duty_window_scan(
        get_world(), on=as_of or _today(), threshold_hours=threshold_hours, days=days
    )


# ---- flights & network ---------------------------------------------------


@router.get("/flights")
def list_flights(
    flight_date: date | None = Query(None, alias="date"),
    dep_station: str | None = None,
    arr_station: str | None = None,
    flight_no: str | None = None,
    aircraft: str | None = None,
) -> dict:
    return q.search_flights(
        get_world(),
        on=flight_date,
        dep_station=dep_station,
        arr_station=arr_station,
        flight_no=flight_no,
        aircraft=aircraft,
    )


@router.get("/flights/{flight_id}")
def flight_detail(flight_id: str) -> dict:
    detail = q.flight_detail(get_world(), flight_id=flight_id)
    if detail is None:
        raise HTTPException(404, f"flight {flight_id} not found")
    return detail


@router.get("/network/summary")
def network_summary(
    on: date | None = None, from_station: str | None = None
) -> dict:
    return q.network_summary(get_world(), on=on, from_station=from_station)


@router.get("/rotations/{aircraft}")
def rotation(aircraft: str, on: date | None = None) -> dict:
    world = get_world()
    day = on or _today()
    legs = tail_rotation(world, aircraft, day)
    if not legs:
        raise HTTPException(404, f"no legs for {aircraft} on {day}")
    return {"aircraft": aircraft, "date": day.isoformat(), "legs": legs}


@router.get("/gantt")
def gantt(start: date | None = None, days: int = 7) -> dict:
    """Tail lines x days -- the operational picture behind the console."""
    world = get_world()
    first, last = world.date_range()
    begin = start or first
    tails = sorted({f.aircraft for f in world.flights})

    rows = []
    for tail in tails:
        pairings = []
        for pairing in world.pairings:
            if pairing.aircraft != tail:
                continue
            for day in pairing.days:
                if not (begin <= day.date <= last):
                    continue
                pairings.append(
                    {
                        "pairing_id": pairing.pairing_id,
                        "date": day.date.isoformat(),
                        "day_index": day.day_index,
                        "report_utc": fmt_dt(day.report_utc),
                        "release_utc": fmt_dt(day.release_utc),
                        "sectors": day.sectors,
                        "seats": sum(world.flight(f).seats for f in day.flight_ids),
                        "crew": [{"crew_id": c, "role": r} for c, r in pairing.crew],
                        "legs": [
                            {
                                "flight_id": fid,
                                "flight_no": world.flight(fid).flight_no,
                                "route": f"{world.flight(fid).dep_station}-{world.flight(fid).arr_station}",
                                "dep_utc": fmt_dt(world.flight(fid).dep_utc),
                                "arr_utc": fmt_dt(world.flight(fid).arr_utc),
                            }
                            for fid in day.flight_ids
                        ],
                    }
                )
        rows.append(
            {
                "aircraft": tail,
                "aircraft_type": next(
                    (f.aircraft_type for f in world.flights if f.aircraft == tail), ""
                ),
                "pairings": sorted(pairings, key=lambda p: p["report_utc"]),
            }
        )

    return {
        "start": begin.isoformat(),
        "end": last.isoformat(),
        "dates": [d.isoformat() for d in world.dates if d >= begin],
        "rows": rows,
    }


# ---- pairings, reserves, certs, rules ------------------------------------


@router.get("/pairings")
def list_pairings(on: date | None = None, aircraft: str | None = None) -> dict:
    world = get_world()
    rows = []
    for pairing in world.pairings:
        if aircraft and pairing.aircraft != aircraft:
            continue
        if on and not any(d.date == on for d in pairing.days):
            continue
        rows.append(
            {
                "pairing_id": pairing.pairing_id,
                "aircraft": pairing.aircraft,
                "days": len(pairing.days),
                "start_date": pairing.days[0].date.isoformat(),
                "total_sectors": pairing.total_sectors,
                "crew_count": len(pairing.crew),
            }
        )
    return {"count": len(rows), "pairings": rows}


@router.get("/pairings/{pairing_id}")
def pairing_detail(pairing_id: str) -> dict:
    detail = q.pairing_detail(get_world(), pairing_id)
    if detail is None:
        raise HTTPException(404, f"pairing {pairing_id} not found")
    return detail


@router.get("/reserves")
def reserves(
    on: date | None = None,
    base: str | None = None,
    rank: str | None = None,
    report_utc: str | None = None,
) -> dict:
    from ...core.timeutil import parse_dt

    return q.reserves(
        get_world(),
        on=on or _today(),
        base=base,
        rank=rank,
        covering_report=parse_dt(report_utc) if report_utc else None,
    )


@router.get("/certifications/expiring")
def certifications_expiring(
    within_days: int = 30, as_of: date | None = None, crew_id: str | None = None
) -> dict:
    return q.certifications_expiring(
        get_world(), as_of=as_of or _today(), within_days=within_days, crew_id=crew_id
    )


@router.get("/rules")
def rules() -> dict:
    return q.rules_reference(get_world())


@router.get("/rules/{rule_id}")
def rule(rule_id: str) -> dict:
    result = q.rules_reference(get_world(), rule_id)
    if not result["rules"]:
        raise HTTPException(404, f"rule {rule_id} not found")
    return result["rules"][0]


@router.get("/costs")
def costs() -> dict:
    return q.cost_reference(get_world())


@router.get("/risk")
def risk(crew_id: str | None = None, top: int = 10) -> dict:
    world = get_world()
    if crew_id:
        detail = q.risk_signal(world, crew_id)
        if detail is None:
            raise HTTPException(404, f"no risk signal for {crew_id}")
        return detail
    return q.top_risk(world, limit=top)


@router.get("/briefing")
def briefing(on: date | None = None) -> dict:
    return morning_briefing(get_world(), on=on or _today())
