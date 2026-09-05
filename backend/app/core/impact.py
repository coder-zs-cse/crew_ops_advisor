"""Consequence analysis -- what breaks, and what breaks next.

"Consequence blindness" is the pain point named in the problem statement: the
broken flight is obvious, the four that break next are not. Everything here is
about making the second-order set explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from .models import Pairing, PairingDay
from .world import World


@dataclass(frozen=True, slots=True)
class FlightImpact:
    flight_id: str
    flight_no: str
    date: str
    dep_station: str
    arr_station: str
    dep_utc: str
    seats: int
    reason: str

    def as_dict(self) -> dict:
        return {
            "flight_id": self.flight_id,
            "flight_no": self.flight_no,
            "date": self.date,
            "dep_station": self.dep_station,
            "arr_station": self.arr_station,
            "dep_utc": self.dep_utc,
            "seats": self.seats,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class UnavailabilityImpact:
    crew_id: str
    crew_name: str
    role: str
    pairing_id: str
    reported_utc: str
    days: tuple[dict, ...]
    uncovered_now: tuple[FlightImpact, ...]
    at_risk_downstream: tuple[FlightImpact, ...]
    seats_at_risk_now: int
    seats_at_risk_total: int
    other_crew_on_pairing: tuple[dict, ...]

    def as_dict(self) -> dict:
        return {
            "crew_id": self.crew_id,
            "crew_name": self.crew_name,
            "role": self.role,
            "pairing_id": self.pairing_id,
            "pairing_broken": self.pairing_id,
            "reported_utc": self.reported_utc,
            "days": list(self.days),
            "uncrewed_flights": [f.flight_id for f in self.uncovered_now],
            "uncovered_flights_day1": [f.flight_id for f in self.uncovered_now],
            "uncovered_flights_day2": [f.flight_id for f in self.at_risk_downstream],
            "downstream_at_risk": [f.flight_id for f in self.at_risk_downstream],
            "flights_detail": [f.as_dict() for f in self.uncovered_now]
            + [f.as_dict() for f in self.at_risk_downstream],
            "passengers_at_risk_day1": self.seats_at_risk_now,
            "passengers_at_risk_total": self.seats_at_risk_total,
            "other_crew_on_pairing": list(self.other_crew_on_pairing),
        }


def _flight_impact(world: World, flight_id: str, reason: str) -> FlightImpact:
    f = world.flight(flight_id)
    return FlightImpact(
        flight_id=f.flight_id,
        flight_no=f.flight_no,
        date=f.date.isoformat(),
        dep_station=f.dep_station,
        arr_station=f.arr_station,
        dep_utc=f.dep_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        seats=f.seats,
        reason=reason,
    )


def find_affected_pairing(
    world: World, crew_id: str, *, pairing_id: str | None = None, on_or_after: date | None = None
) -> Pairing | None:
    """Which pairing does this crew member drop out of?"""
    if pairing_id:
        return world.get_pairing(pairing_id)
    candidates = [
        p
        for p in world.pairings
        if any(cid == crew_id for cid, _ in p.crew)
        and (on_or_after is None or p.days[-1].date >= on_or_after)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.days[0].date)
    return candidates[0]


def crew_unavailable(
    world: World,
    *,
    crew_id: str,
    pairing_id: str | None = None,
    reported_utc: datetime | None = None,
) -> UnavailabilityImpact | None:
    """Impact of one crew member becoming unavailable.

    Day 1 = the first duty day at or after the report time; its legs lose the
    crew member immediately. Later days of the same pairing are *at risk* rather
    than uncovered, because the aircraft (and therefore the opening) carries
    forward -- the flagship pairing P-2291 overnights at DEL.
    """
    reported = reported_utc or world.snapshot_utc
    pairing = find_affected_pairing(
        world, crew_id, pairing_id=pairing_id, on_or_after=reported.date()
    )
    if pairing is None:
        return None

    crew = world.crew_member(crew_id)
    role = pairing.role_of(crew_id) or crew.rank

    remaining = [d for d in pairing.days if d.release_utc >= reported]
    if not remaining:
        remaining = list(pairing.days)

    first_day = remaining[0]
    later_days = remaining[1:]

    uncovered = tuple(
        _flight_impact(world, fid, f"{role} {crew_id} unavailable")
        for fid in first_day.flight_ids
    )
    downstream = tuple(
        _flight_impact(world, fid, f"pairing {pairing.pairing_id} continues without a {role}")
        for day in later_days
        for fid in day.flight_ids
    )

    days_meta = tuple(
        {
            "day_index": d.day_index,
            "date": d.date.isoformat(),
            "report_utc": d.report_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "release_utc": d.release_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sectors": d.sectors,
            "flight_ids": list(d.flight_ids),
            "seats": sum(world.flight(fid).seats for fid in d.flight_ids),
        }
        for d in remaining
    )

    others = tuple(
        {
            "crew_id": cid,
            "role": r,
            "name": world.crew_member(cid).name if world.get_crew(cid) else None,
        }
        for cid, r in pairing.crew
        if cid != crew_id
    )

    return UnavailabilityImpact(
        crew_id=crew_id,
        crew_name=crew.name,
        role=role,
        pairing_id=pairing.pairing_id,
        reported_utc=reported.strftime("%Y-%m-%dT%H:%M:%SZ"),
        days=days_meta,
        uncovered_now=uncovered,
        at_risk_downstream=downstream,
        seats_at_risk_now=sum(f.seats for f in uncovered),
        seats_at_risk_total=sum(f.seats for f in uncovered) + sum(f.seats for f in downstream),
        other_crew_on_pairing=others,
    )


def cancellation_impact(world: World, flight_ids: Iterable[str]) -> dict:
    ids = list(flight_ids)
    missing = [fid for fid in ids if world.get_flight(fid) is None]
    if missing:
        return {"error": f"unknown flight id(s): {', '.join(missing)}", "resolved": False}
    flights = [world.flight(fid) for fid in ids]
    seats = sum(f.seats for f in flights)
    cost = world.costs.cancellation_per_flight * len(flights)

    rotation_breaks = []
    for f in flights:
        later = [
            x
            for x in world.flights_of_tail(f.aircraft)
            if x.dep_utc > f.arr_utc and x.date == f.date
        ]
        if later:
            rotation_breaks.append(
                {
                    "cancelled": f.flight_id,
                    "aircraft": f.aircraft,
                    "strands_aircraft_at": f.dep_station,
                    "subsequent_legs": [x.flight_id for x in later],
                }
            )

    return {
        "flight_ids": ids,
        "flights": [
            {
                "flight_id": f.flight_id,
                "flight_no": f.flight_no,
                "date": f.date.isoformat(),
                "route": f"{f.dep_station}-{f.arr_station}",
                "seats": f.seats,
            }
            for f in flights
        ],
        "passengers_affected": seats,
        "direct_cost_inr": cost,
        "currency": world.costs.currency,
        "rotation_breaks": rotation_breaks,
    }


def seats_at_risk(world: World, flight_ids: Iterable[str]) -> int:
    return sum(world.flight(fid).seats for fid in flight_ids)


def pairing_day_summary(world: World, day: PairingDay) -> dict:
    return {
        "pairing_id": day.pairing_id,
        "date": day.date.isoformat(),
        "sectors": day.sectors,
        "flight_ids": list(day.flight_ids),
        "report_utc": day.report_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "release_utc": day.release_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seats": sum(world.flight(fid).seats for fid in day.flight_ids),
    }
