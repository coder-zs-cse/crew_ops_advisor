"""Station closure impact.

A station closes for a window. Every departure from it and every arrival into
it inside that window is affected. For each, we compute the minimum delay to
push the operation past reopening (+30 min turnaround) and then re-test the
operating crew's flight duty period against the shifted release.

Where the extended duty busts RULE-FDP-01 the tail legs need a fresh crew or
cancellation -- that is the recovery decision, and it is why a closure is a
*crew* problem and not just a schedule problem.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .duty import fdp_limit
from .timeutil import EPS, hrs
from .world import World

REOPEN_BUFFER_MINUTES = 30


@dataclass(frozen=True, slots=True)
class ClosureFlightAssessment:
    flight_id: str
    pairing_id: str
    min_delay_hours: float
    crew_fdp_after_delay: float
    fdp_limit: float
    action: str
    feasible: bool
    sectors: int
    seats: int

    def as_answer_key_dict(self) -> dict:
        return {
            "flight_id": self.flight_id,
            "pairing_id": self.pairing_id,
            "min_delay_hours": self.min_delay_hours,
            "crew_fdp_after_delay": self.crew_fdp_after_delay,
            "fdp_limit": self.fdp_limit,
            "action": self.action,
        }

    def as_dict(self) -> dict:
        base = self.as_answer_key_dict()
        base.update({"feasible": self.feasible, "sectors": self.sectors, "seats": self.seats})
        return base


@dataclass(frozen=True, slots=True)
class ClosureImpact:
    station: str
    window_start: str
    window_end: str
    affected_flights: tuple[str, ...]
    assessments: tuple[ClosureFlightAssessment, ...]
    seats_affected: int
    pairings_affected: tuple[str, ...]

    def as_dict(self) -> dict:
        infeasible = [a for a in self.assessments if not a.feasible]
        return {
            "station": self.station,
            "window_utc": {"start": self.window_start, "end": self.window_end},
            "affected_flights": list(self.affected_flights),
            "per_flight_assessment": [a.as_dict() for a in self.assessments],
            "seats_affected": self.seats_affected,
            "pairings_affected": list(self.pairings_affected),
            "flights_requiring_recrew_or_cancel": [a.flight_id for a in infeasible],
            "note": (
                "Delays are measured to reopening +30min turnaround. Where the extended "
                "duty exceeds RULE-FDP-01, tail legs need reserve re-crew or cancellation."
            ),
        }


ACTION_LEGAL = "delay (crew legal)"
ACTION_BREACH = "delay exceeds crew FDP — re-crew tail legs from reserves or cancel"


def station_closure(
    world: World, *, station: str, start_utc: datetime, end_utc: datetime
) -> ClosureImpact:
    on = start_utc.date()

    affected: list[str] = []
    for f in world.flights:
        if f.date != on:
            continue
        hit = (f.dep_station == station and start_utc <= f.dep_utc < end_utc) or (
            f.arr_station == station and start_utc <= f.arr_utc < end_utc
        )
        if hit:
            affected.append(f.flight_id)

    assessments: list[ClosureFlightAssessment] = []
    pairings: list[str] = []
    for fid in affected:
        f = world.flight(fid)
        found = world.pairing_of_flight(fid)
        if found is None:
            continue
        pairing, day = found
        if pairing.pairing_id not in pairings:
            pairings.append(pairing.pairing_id)

        # Anchor on whichever operation the closure actually blocks.
        blocks_departure = f.dep_station == station and start_utc <= f.dep_utc < end_utc
        anchor = f.dep_utc if blocks_departure else f.arr_utc
        shift = hrs((end_utc + timedelta(minutes=REOPEN_BUFFER_MINUTES)) - anchor)

        new_release = day.release_utc + timedelta(hours=shift)
        new_fdp = hrs(new_release - day.report_utc)
        limit = fdp_limit(day.sectors, world)
        feasible = new_fdp <= limit + EPS

        assessments.append(
            ClosureFlightAssessment(
                flight_id=fid,
                pairing_id=pairing.pairing_id,
                min_delay_hours=round(shift, 2),
                crew_fdp_after_delay=round(new_fdp, 2),
                fdp_limit=limit,
                action=ACTION_LEGAL if feasible else ACTION_BREACH,
                feasible=feasible,
                sectors=day.sectors,
                seats=f.seats,
            )
        )

    return ClosureImpact(
        station=station,
        window_start=start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        window_end=end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        affected_flights=tuple(affected),
        assessments=tuple(assessments),
        seats_affected=sum(world.flight(fid).seats for fid in affected),
        pairings_affected=tuple(pairings),
    )
