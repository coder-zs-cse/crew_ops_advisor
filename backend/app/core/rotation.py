"""Aircraft rotation and delay propagation.

A delay does not stop at the delayed leg. It walks the tail's remaining
rotation, and somewhere down that chain the operating crew's duty period stops
being legal. This module produces both:

* ``fdp_after_delay``  -- the reference figure the answer keys use: the crew
  reported on time, the aircraft is late, so release slides but report does not.
* ``max_legal_sectors`` -- how many legs the rostered crew *can* still operate,
  which turns "you have a breach" into "hand over after leg 3".

REFERENCE-MODEL NOTE. The dataset generator computes the full-duty figure with
the report time held fixed (duty_length + delay) but computes its partial-duty
figure with the report shifted by the delay. Those two conventions disagree.
We reproduce both, label them, and use the reference convention wherever an
answer key depends on it. See docs/LIMITATIONS.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .duty import fdp_limit
from .models import PairingDay
from .timeutil import EPS, hrs
from .world import World


@dataclass(frozen=True, slots=True)
class LegShift:
    flight_id: str
    flight_no: str
    scheduled_dep: str
    revised_dep: str
    scheduled_arr: str
    revised_arr: str
    delay_hours: float
    seats: int

    def as_dict(self) -> dict:
        return {
            "flight_id": self.flight_id,
            "flight_no": self.flight_no,
            "scheduled_dep_utc": self.scheduled_dep,
            "revised_dep_utc": self.revised_dep,
            "scheduled_arr_utc": self.scheduled_arr,
            "revised_arr_utc": self.revised_arr,
            "delay_hours": self.delay_hours,
            "seats": self.seats,
        }


@dataclass(frozen=True, slots=True)
class DelayImpact:
    aircraft: str
    date: str
    delay_hours: float
    pairing_id: str
    sectors: int
    fdp_scheduled: float
    fdp_after_delay: float
    fdp_limit: float
    breach: bool
    breach_detail: str
    max_legal_sectors: int
    partial_fdp_hours: float
    partial_fdp_limit: float
    reference_partial_fdp_hours: float
    handover_after_flight: str | None
    legs_needing_recrew: tuple[str, ...]
    leg_shifts: tuple[LegShift, ...]
    seats_downstream: int

    def as_dict(self) -> dict:
        return {
            "aircraft": self.aircraft,
            "date": self.date,
            "delay_hours": self.delay_hours,
            "pairing_id": self.pairing_id,
            "sectors": self.sectors,
            "fdp_scheduled": self.fdp_scheduled,
            "fdp_after_delay": self.fdp_after_delay,
            "fdp_limit": self.fdp_limit,
            "breach": self.breach,
            "breach_detail": self.breach_detail,
            "max_legal_sectors": self.max_legal_sectors,
            "partial_fdp_hours": self.partial_fdp_hours,
            "partial_fdp_limit": self.partial_fdp_limit,
            "reference_partial_fdp_hours": self.reference_partial_fdp_hours,
            "handover_after_flight": self.handover_after_flight,
            "legs_needing_recrew": list(self.legs_needing_recrew),
            "leg_shifts": [s.as_dict() for s in self.leg_shifts],
            "seats_downstream": self.seats_downstream,
        }


def propagate(world: World, *, day: PairingDay, delay_hours: float) -> tuple[LegShift, ...]:
    """Shift every leg of the duty by the delay (no turn-time absorption)."""
    offset = timedelta(hours=delay_hours)
    out = []
    for fid in day.flight_ids:
        f = world.flight(fid)
        out.append(
            LegShift(
                flight_id=f.flight_id,
                flight_no=f.flight_no,
                scheduled_dep=f.dep_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                revised_dep=(f.dep_utc + offset).strftime("%Y-%m-%dT%H:%M:%SZ"),
                scheduled_arr=f.arr_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                revised_arr=(f.arr_utc + offset).strftime("%Y-%m-%dT%H:%M:%SZ"),
                delay_hours=delay_hours,
                seats=f.seats,
            )
        )
    return tuple(out)


def partial_fdp(
    world: World, day: PairingDay, delay_hours: float, k: int, *, shift_report: bool
) -> float:
    """FDP of operating only the first ``k`` legs of a delayed duty.

    ``shift_report=False`` is the operationally correct reading and the one the
    breach test uses: the crew reported at the scheduled time and then waited.
    ``shift_report=True`` reproduces the reference implementation's partial-duty
    figure, which assumes the crew was told to come in late.
    """
    offset = timedelta(hours=delay_hours)
    report = day.report_utc + (offset if shift_report else timedelta())
    release = world.flight(day.flight_ids[k - 1]).arr_utc + offset + timedelta(minutes=30)
    return hrs(release - report)


def max_legal_sectors(world: World, day: PairingDay, delay_hours: float) -> tuple[int, float, float]:
    """Largest k such that operating the first k legs stays inside RULE-FDP-01.

    Uses the fixed-report convention, consistently with the breach test above.
    """
    best_k, best_fdp, best_limit = 0, 0.0, fdp_limit(1, world)
    for k in range(1, day.sectors + 1):
        fdp = partial_fdp(world, day, delay_hours, k, shift_report=False)
        limit = fdp_limit(k, world)
        if fdp <= limit + EPS:
            best_k, best_fdp, best_limit = k, fdp, limit
        else:
            break
    return best_k, round(best_fdp, 2), best_limit


def aircraft_delay(
    world: World, *, aircraft: str, on, delay_hours: float, day_index: int = 0
) -> DelayImpact | None:
    pairing = world.pairing_for(aircraft, on)
    if pairing is None:
        return None
    day = pairing.days[day_index]

    scheduled = hrs(day.release_utc - day.report_utc)
    # Reference convention: crew reported on time, release slides.
    after = round(scheduled + delay_hours, 2)
    limit = fdp_limit(day.sectors, world)
    breach = after > limit + EPS

    k, k_fdp, k_limit = max_legal_sectors(world, day, delay_hours)
    reference_k_fdp = (
        partial_fdp(world, day, delay_hours, k, shift_report=True) if k else 0.0
    )
    handover = day.flight_ids[k - 1] if 0 < k < day.sectors else None
    needing = tuple(day.flight_ids[k:]) if breach else ()

    detail = (
        f"RULE-FDP-01: delayed duty runs {after}h vs {limit}h limit "
        f"({day.sectors} sectors) — the rostered crew cannot legally complete "
        f"{world.flight(day.flight_ids[-1]).flight_no}."
        if breach
        else f"Delayed duty runs {after}h vs {limit}h limit ({day.sectors} sectors) — legal."
    )

    return DelayImpact(
        aircraft=aircraft,
        date=day.date.isoformat(),
        delay_hours=delay_hours,
        pairing_id=pairing.pairing_id,
        sectors=day.sectors,
        fdp_scheduled=scheduled,
        fdp_after_delay=after,
        fdp_limit=limit,
        breach=breach,
        breach_detail=detail,
        max_legal_sectors=k,
        partial_fdp_hours=k_fdp,
        partial_fdp_limit=k_limit,
        reference_partial_fdp_hours=reference_k_fdp,
        handover_after_flight=handover,
        legs_needing_recrew=needing,
        leg_shifts=propagate(world, day=day, delay_hours=delay_hours),
        seats_downstream=sum(world.flight(fid).seats for fid in needing),
    )


def tail_rotation(world: World, aircraft: str, on) -> list[dict]:
    """The tail's legs for a date, with turn times -- the fragility view."""
    legs = [f for f in world.flights_of_tail(aircraft) if f.date == on]
    out = []
    for i, f in enumerate(legs):
        turn = None
        if i + 1 < len(legs):
            turn = hrs(legs[i + 1].dep_utc - f.arr_utc)
        out.append(
            {
                "flight_id": f.flight_id,
                "flight_no": f.flight_no,
                "route": f"{f.dep_station}-{f.arr_station}",
                "dep_utc": f.dep_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "arr_utc": f.arr_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "block_hours": f.block_hours,
                "seats": f.seats,
                "turn_hours_to_next": turn,
            }
        )
    return out
