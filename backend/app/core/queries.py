"""Tier-1 deterministic lookups.

Every function returns a rich dict: the answer, plus the context a controller
needs to trust it (the rule cited, the window used, the as-of date). The agent
narrates these; it never computes them.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

from .duty import earliest_next_report
from .models import PILOT_ROLES
from .rule_params import rule_param
from .rules.duty02 import MAX_DUTY_HOURS
from .rules.flt03 import MAX_FLIGHT_HOURS
from .timeutil import at, fmt_dt
from .windows import DUTY, FLIGHT, window_breakdown, window_sum
from .world import World


# --------------------------------------------------------------------------
# Crew
# --------------------------------------------------------------------------


def crew_detail(world: World, crew_id: str) -> dict | None:
    crew = world.get_crew(crew_id)
    if crew is None:
        return None
    reserve = world.reserve(crew_id)
    signal = world.risk(crew_id)
    return {
        "crew_id": crew.crew_id,
        "name": crew.name,
        "rank": crew.rank,
        "base": crew.base,
        "ratings": list(crew.ratings),
        "seniority": crew.seniority,
        "reachability_minutes": crew.reachability_minutes,
        "status": crew.status,
        "is_reserve": reserve is not None,
        "reserve_window": (
            {"start": reserve.oncall_start, "end": reserve.oncall_end} if reserve else None
        ),
        "disruption_risk_score": signal.disruption_risk_score if signal else None,
        "risk_drivers": list(signal.drivers) if signal else [],
        "certifications": [
            {
                "cert_type": c.cert_type,
                "valid_from": c.valid_from.isoformat(),
                "valid_to": c.valid_to.isoformat(),
            }
            for c in sorted(world.certs(crew_id).values(), key=lambda c: c.valid_to)
        ],
    }


def search_crew(
    world: World,
    *,
    rank: str | None = None,
    base: str | None = None,
    rating: str | None = None,
    status: str | None = None,
    limit: int | None = None,
) -> dict:
    matches = world.crew_where(rank=rank, base=base, rating=rating, status=status)
    rows = [
        {
            "crew_id": c.crew_id,
            "name": c.name,
            "rank": c.rank,
            "base": c.base,
            "ratings": list(c.ratings),
            "seniority": c.seniority,
            "reachability_minutes": c.reachability_minutes,
            "status": c.status,
        }
        for c in matches
    ]
    return {
        "filters": {"rank": rank, "base": base, "rating": rating, "status": status},
        "count": len(rows),
        "crew_ids": [r["crew_id"] for r in rows][: limit or len(rows)],
        "crew": rows[: limit or len(rows)],
    }


def duty_clock(world: World, crew_id: str, as_of: date | None = None) -> dict | None:
    crew = world.get_crew(crew_id)
    if crew is None:
        return None
    end = as_of or world.snapshot_utc.date()

    max_duty_hours = rule_param(world, "RULE-DUTY-02", "max_duty_hours", MAX_DUTY_HOURS)
    duty_window_days = int(rule_param(world, "RULE-DUTY-02", "window_days", 7))
    max_flight_hours = rule_param(world, "RULE-FLT-03", "max_flight_hours", MAX_FLIGHT_HOURS)
    flight_window_days = int(rule_param(world, "RULE-FLT-03", "window_days", 28))

    duty_7d = window_sum(world, crew_id, end, duty_window_days, DUTY)
    flight_28d = window_sum(world, crew_id, end, flight_window_days, FLIGHT)
    clock = world.clock(crew_id) if crew_id in {d.crew_id for d in world.duty_clocks} else None

    return {
        "crew_id": crew_id,
        "rank": crew.rank,
        "as_of": end.isoformat(),
        "duty_hours_7d": duty_7d,
        "duty_limit_7d": max_duty_hours,
        "headroom_hours": round(max_duty_hours - duty_7d, 2),
        "duty_window": {
            "days": duty_window_days,
            "start": (end - timedelta(days=duty_window_days - 1)).isoformat(),
            "end": end.isoformat(),
            "rule": "RULE-DUTY-02",
        },
        "flight_hours_28d": flight_28d,
        "flight_limit_28d": max_flight_hours,
        "flight_headroom_hours": round(max_flight_hours - flight_28d, 2),
        "flight_window": {
            "days": flight_window_days,
            "start": (end - timedelta(days=flight_window_days - 1)).isoformat(),
            "end": end.isoformat(),
            "rule": "RULE-FLT-03",
        },
        "last_rest_ended": fmt_dt(clock.last_rest_ended) if clock and clock.last_rest_ended else None,
        "daily_breakdown_7d": window_breakdown(world, crew_id, end, duty_window_days, DUTY),
    }


def duty_window_scan(
    world: World, *, on: date, threshold_hours: float = 45.0, days: int = 7
) -> dict:
    """Q26: everyone at or above a duty-hour threshold in the window ending ``on``."""
    max_duty_hours = rule_param(world, "RULE-DUTY-02", "max_duty_hours", MAX_DUTY_HOURS)
    rows = []
    for crew in world.crew:
        total = window_sum(world, crew.crew_id, on, days, DUTY)
        if total >= threshold_hours:
            rows.append(
                {
                    "crew_id": crew.crew_id,
                    "name": crew.name,
                    "rank": crew.rank,
                    "base": crew.base,
                    "duty_hours": total,
                    "headroom_hours": round(max_duty_hours - total, 2),
                }
            )
    rows.sort(key=lambda r: (-r["duty_hours"], r["crew_id"]))
    return {
        "as_of": on.isoformat(),
        "window_days": days,
        "threshold_hours": threshold_hours,
        "rule": "RULE-DUTY-02",
        "count": len(rows),
        "crew": rows,
    }


def risk_signal(world: World, crew_id: str) -> dict | None:
    signal = world.risk(crew_id)
    if signal is None:
        return None
    return {
        "crew_id": crew_id,
        "score": signal.disruption_risk_score,
        "drivers": list(signal.drivers),
        "as_of_utc": fmt_dt(signal.as_of_utc),
        "note": "Provided pre-computed input. This system does not build the prediction.",
    }


def top_risk(world: World, limit: int = 10) -> dict:
    ranked = sorted(
        world.risk_signals, key=lambda s: (-s.disruption_risk_score, s.crew_id)
    )[:limit]
    return {
        "count": len(ranked),
        "crew": [
            {
                "crew_id": s.crew_id,
                "name": world.crew_member(s.crew_id).name,
                "rank": world.crew_member(s.crew_id).rank,
                "score": s.disruption_risk_score,
                "drivers": list(s.drivers),
            }
            for s in ranked
        ],
    }


# --------------------------------------------------------------------------
# Reserves
# --------------------------------------------------------------------------


def reserves(
    world: World,
    *,
    on: date,
    base: str | None = None,
    rank: str | None = None,
    covering_report: datetime | None = None,
) -> dict:
    rows = []
    for reserve in world.reserves:
        if on not in reserve.dates:
            continue
        if base and reserve.base != base:
            continue
        crew = world.crew_member(reserve.crew_id)
        if rank and crew.rank != rank:
            continue

        covers = None
        if covering_report is not None:
            start = at(covering_report.date(), reserve.oncall_start)
            end = at(covering_report.date(), reserve.oncall_end)
            covers = start <= covering_report <= end

        rows.append(
            {
                "crew_id": reserve.crew_id,
                "name": crew.name,
                "rank": crew.rank,
                "base": reserve.base,
                "ratings": list(crew.ratings),
                "window": {"start": reserve.oncall_start, "end": reserve.oncall_end},
                "reachability_minutes": crew.reachability_minutes,
                "covers_report_time": covers,
            }
        )
    return {
        "date": on.isoformat(),
        "base": base,
        "rank": rank,
        "covering_report_utc": fmt_dt(covering_report) if covering_report else None,
        "count": len(rows),
        "reserves": rows,
        "rule": "RULE-BASE-07",
    }


# --------------------------------------------------------------------------
# Flights & network
# --------------------------------------------------------------------------


def _flight_row(world: World, f) -> dict:
    found = world.pairing_of_flight(f.flight_id)
    return {
        "flight_id": f.flight_id,
        "flight_no": f.flight_no,
        "date": f.date.isoformat(),
        "dep_station": f.dep_station,
        "arr_station": f.arr_station,
        "dep_utc": fmt_dt(f.dep_utc),
        "arr_utc": fmt_dt(f.arr_utc),
        "block_hours": f.block_hours,
        "aircraft": f.aircraft,
        "aircraft_type": f.aircraft_type,
        "seats": f.seats,
        "pairing_id": found[0].pairing_id if found else None,
    }


def search_flights(
    world: World,
    *,
    on: date | None = None,
    dep_station: str | None = None,
    arr_station: str | None = None,
    flight_no: str | None = None,
    aircraft: str | None = None,
    after_utc: datetime | None = None,
    before_utc: datetime | None = None,
) -> dict:
    rows = []
    for f in world.flights:
        if on and f.date != on:
            continue
        if dep_station and f.dep_station != dep_station:
            continue
        if arr_station and f.arr_station != arr_station:
            continue
        if flight_no and f.flight_no != flight_no:
            continue
        if aircraft and f.aircraft != aircraft:
            continue
        if after_utc and f.dep_utc < after_utc:
            continue
        if before_utc and f.dep_utc > before_utc:
            continue
        rows.append(_flight_row(world, f))
    rows.sort(key=lambda r: r["dep_utc"])
    return {
        "filters": {
            "date": on.isoformat() if on else None,
            "dep_station": dep_station,
            "arr_station": arr_station,
            "flight_no": flight_no,
            "aircraft": aircraft,
        },
        "count": len(rows),
        "flight_nos": [r["flight_no"] for r in rows],
        "flight_ids": [r["flight_id"] for r in rows],
        "flights": rows,
        "seats_total": sum(r["seats"] for r in rows),
    }


def flight_detail(world: World, *, flight_id: str | None = None, flight_no: str | None = None, on: date | None = None) -> dict | None:
    f = None
    if flight_id:
        f = world.get_flight(flight_id)
    elif flight_no and on:
        f = world.find_flight(flight_no, on)
    if f is None:
        return None

    row = _flight_row(world, f)
    found = world.pairing_of_flight(f.flight_id)
    if found:
        pairing, day = found
        row["pairing_id"] = pairing.pairing_id
        row["crew"] = [
            {"crew_id": cid, "role": role, "name": world.crew_member(cid).name}
            for cid, role in pairing.crew
        ]
        row["duty_date"] = day.date.isoformat()
        row["report_utc"] = fmt_dt(day.report_utc)
        row["release_utc"] = fmt_dt(day.release_utc)
        row["sectors_in_duty"] = day.sectors
    return row


def network_summary(world: World, *, on: date | None = None, from_station: str | None = None) -> dict:
    flights = world.flights_on(on) if on else world.flights

    longest = max((f.block_hours for f in world.flights), default=0.0)
    longest_flights = sorted({f.flight_no for f in world.flights if f.block_hours == longest})

    max_seats = max((f.seats for f in world.flights), default=0)
    seat_types = sorted({(f.aircraft_type, f.seats) for f in world.flights}, key=lambda x: -x[1])

    nonstop = None
    if from_station:
        nonstop = sorted({f.arr_station for f in world.flights if f.dep_station == from_station})

    return {
        "date": on.isoformat() if on else None,
        "flight_count": len(flights),
        "stations": list(world.stations),
        "aircraft": sorted({f.aircraft for f in world.flights}),
        "aircraft_types": sorted({f.aircraft_type for f in world.flights}),
        "seats_by_type": [{"aircraft_type": t, "seats": s} for t, s in seat_types],
        "longest_block_hours": longest,
        "longest_block_flights": longest_flights,
        "max_seats_per_leg": max_seats,
        "total_seats": sum(f.seats for f in flights),
        "nonstop_from": from_station,
        "nonstop_destinations": nonstop,
    }


# --------------------------------------------------------------------------
# Pairings & rosters
# --------------------------------------------------------------------------


def pairing_detail(world: World, pairing_id: str) -> dict | None:
    pairing = world.get_pairing(pairing_id)
    if pairing is None:
        return None
    return {
        "pairing_id": pairing.pairing_id,
        "aircraft": pairing.aircraft,
        "aircraft_type": world.flight(pairing.days[0].flight_ids[0]).aircraft_type,
        "total_sectors": pairing.total_sectors,
        "crew": [
            {"crew_id": cid, "role": role, "name": world.crew_member(cid).name}
            for cid, role in pairing.crew
        ],
        "days": [
            {
                "day_index": d.day_index,
                "date": d.date.isoformat(),
                "report_utc": fmt_dt(d.report_utc),
                "release_utc": fmt_dt(d.release_utc),
                "duty_hours": round((d.release_utc - d.report_utc).total_seconds() / 3600, 2),
                "sectors": d.sectors,
                "flights": [_flight_row(world, world.flight(fid)) for fid in d.flight_ids],
                "seats": sum(world.flight(fid).seats for fid in d.flight_ids),
            }
            for d in pairing.days
        ],
    }


def pairing_for_tail(world: World, *, aircraft: str, on: date) -> dict | None:
    pairing = world.pairing_for(aircraft, on)
    if pairing is None:
        for p in world.pairings:
            if p.aircraft == aircraft and any(d.date == on for d in p.days):
                pairing = p
                break
    return pairing_detail(world, pairing.pairing_id) if pairing else None


def roster_for_crew(world: World, crew_id: str) -> dict:
    segments = world.week_duties(crew_id)
    return {
        "crew_id": crew_id,
        "duty_count": len(segments),
        "duties": [
            {
                "date": s.date.isoformat(),
                "pairing_id": s.label,
                "report_utc": fmt_dt(s.report_utc),
                "release_utc": fmt_dt(s.release_utc),
                "duty_hours": s.duty_hours,
                "flight_hours": s.flight_hours,
            }
            for s in segments
        ],
    }


# --------------------------------------------------------------------------
# Certifications & rest
# --------------------------------------------------------------------------


def certifications_expiring(
    world: World, *, as_of: date, within_days: int = 30, crew_id: str | None = None
) -> dict:
    cutoff = as_of + timedelta(days=within_days)
    rows = []
    for cert in world.certifications:
        if crew_id and cert.crew_id != crew_id:
            continue
        if cert.valid_to > cutoff:
            continue
        crew = world.get_crew(cert.crew_id)
        rows.append(
            {
                "crew_id": cert.crew_id,
                "name": crew.name if crew else None,
                "rank": crew.rank if crew else None,
                "cert_type": cert.cert_type,
                "valid_to": cert.valid_to.isoformat(),
                "days_remaining": (cert.valid_to - as_of).days,
                "already_expired": cert.valid_to < as_of,
            }
        )
    rows.sort(key=lambda r: (r["valid_to"], r["crew_id"]))
    return {
        "as_of": as_of.isoformat(),
        "within_days": within_days,
        "cutoff": cutoff.isoformat(),
        "rule": "RULE-CERT-06",
        "count": len(rows),
        "certifications": rows,
    }


def rest_calculation(release_utc: datetime, min_rest_hours: float = 12.0) -> dict:
    earliest = earliest_next_report(release_utc, min_rest_hours)
    return {
        "released_utc": fmt_dt(release_utc),
        "min_rest_hours": min_rest_hours,
        "earliest_report_utc": fmt_dt(earliest),
        "rule": "RULE-REST-04",
        "arithmetic": f"{fmt_dt(release_utc)} + {min_rest_hours}h = {fmt_dt(earliest)}",
    }


def rules_reference(world: World, rule_id: str | None = None) -> dict:
    rules = [r for r in world.rules if rule_id is None or r.rule_id == rule_id]
    return {
        "count": len(rules),
        "rules": [
            {"rule_id": r.rule_id, "text": r.text, "params": dict(r.params)} for r in rules
        ],
    }


def cost_reference(world: World) -> dict:
    c = world.costs
    return {
        "currency": c.currency,
        "reserve_callout_pilot": c.reserve_callout_pilot,
        "reserve_callout_cabin": c.reserve_callout_cabin,
        "dayoff_callout_pilot": c.dayoff_callout_pilot,
        "dayoff_callout_cabin": c.dayoff_callout_cabin,
        "deadhead_positioning": c.deadhead_positioning,
        "delay_cost_per_duty_hour": c.delay_cost_per_duty_hour,
        "cancellation_per_flight": c.cancellation_per_flight,
        "hotel_overnight": c.hotel_overnight,
    }
