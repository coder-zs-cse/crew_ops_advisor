"""Scenario execution -- one entry point per disruption type.

Every scenario is ``World.apply(event) -> World'``: the base snapshot is never
mutated, so chaining disruptions is just repeated forking and the lineage
records the chain. The same functions back the REST simulation endpoints, the
agent's tools and the conformance harness, so the chat surface and the
workbench cannot disagree with each other or with the answer keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from .candidates import CandidateSet, enumerate_cover, enumerate_cover_for_pairing
from .closure import ClosureImpact, station_closure
from .costing import complement_callout_cost
from .impact import UnavailabilityImpact, cancellation_impact, crew_unavailable
from .joint import Opening, solve
from .rotation import DelayImpact, aircraft_delay
from .rules.cert06 import certs_valid_on
from .timeutil import parse_date, parse_dt
from .world import World

SICK = "SICK_CREW"
MULTI_SICK = "MULTI_SICK"
CLOSURE = "STATION_CLOSURE"
DELAY = "DELAY"
CERT_EXPIRY = "CERT_EXPIRY"
CANCELLATION = "CANCELLATION"

SUPPORTED_EVENTS = (SICK, MULTI_SICK, CLOSURE, DELAY, CERT_EXPIRY, CANCELLATION)


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    event_type: str
    world: World
    payload: dict[str, Any]

    def as_dict(self) -> dict:
        out = dict(self.payload)
        out["event_type"] = self.event_type
        out["lineage"] = [dict(e) for e in self.world.lineage]
        return out


# --------------------------------------------------------------------------
# SICK_CREW / CERT_EXPIRY -- an opening on a pairing
# --------------------------------------------------------------------------


def _role_for(world: World, crew_id: str, pairing_id: str) -> str:
    pairing = world.pairing(pairing_id)
    return pairing.role_of(crew_id) or world.crew_member(crew_id).rank


def crew_opening(
    world: World,
    *,
    crew_id: str,
    pairing_id: str | None = None,
    reported_utc: datetime | None = None,
    reason: str = SICK,
    day_indexes: Iterable[int] | None = None,
) -> ScenarioResult:
    """A crew member drops off a pairing: impact + ranked cover options."""
    impact: UnavailabilityImpact | None = crew_unavailable(
        world, crew_id=crew_id, pairing_id=pairing_id, reported_utc=reported_utc
    )
    if impact is None:
        return ScenarioResult(
            reason,
            world,
            {
                "resolved": False,
                "detail": f"{crew_id} has no pairing at or after the reported time",
            },
        )

    forked = world.with_crew_unavailable(
        [crew_id],
        {
            "type": reason,
            "crew_id": crew_id,
            "pairing_id": impact.pairing_id,
            "reported_utc": impact.reported_utc,
        },
    )

    role = _role_for(world, crew_id, impact.pairing_id)
    candidates = enumerate_cover_for_pairing(
        forked,
        pairing_id=impact.pairing_id,
        role=role,
        sick_crew_id=crew_id,
        day_indexes=day_indexes,
    )

    return ScenarioResult(
        reason,
        forked,
        {
            "resolved": True,
            "role": role,
            "impact": impact.as_dict(),
            **candidates.as_dict(),
            "options": [c.as_dict() for c in candidates.eligible]
            + ([candidates.cancel.as_dict()] if candidates.cancel else []),
            "answer_key_options": candidates.options,
            "excluded_candidates": [e.as_dict() for e in candidates.excluded],
            "expected_choice": (
                candidates.eligible[0].as_answer_key_dict() if candidates.eligible else None
            ),
        },
    )


def certification_lapse(
    world: World,
    *,
    crew_id: str,
    pairing_id: str,
    reported_utc: datetime | None = None,
) -> ScenarioResult:
    """A certificate lapses, making a rostered duty illegal under RULE-CERT-06."""
    pairing = world.pairing(pairing_id)
    duty_date = pairing.days[0].date
    ok, expired = certs_valid_on(world, crew_id, duty_date)

    result = crew_opening(
        world,
        crew_id=crew_id,
        pairing_id=pairing_id,
        reported_utc=reported_utc,
        reason=CERT_EXPIRY,
    )
    payload = dict(result.payload)
    payload["illegal_assignment"] = {
        "crew_id": crew_id,
        "date": duty_date.isoformat(),
        "rule": "RULE-CERT-06",
        "expired_certifications": expired,
        "currently_legal": ok,
    }
    return ScenarioResult(CERT_EXPIRY, result.world, payload)


# --------------------------------------------------------------------------
# MULTI_SICK -- competing openings against one scarce pool
# --------------------------------------------------------------------------


def multi_crew_opening(
    world: World,
    *,
    events: list[dict],
    reported_utc: datetime | None = None,
) -> ScenarioResult:
    per_opening: list[tuple[str, str, CandidateSet]] = []
    impacts: dict[str, Any] = {}
    sick_ids = [e["crew_id"] for e in events]

    forked = world
    for event in events:
        forked = forked.with_crew_unavailable(
            [event["crew_id"]],
            {
                "type": SICK,
                "crew_id": event["crew_id"],
                "pairing_id": event.get("pairing_id"),
                "reported_utc": event.get("reported_utc"),
            },
        )

    # Each opening is enumerated against the BASE world, excluding only its own
    # sick crew. That matches the reference implementation, and it is also the
    # more useful output: a controller wants to see why every other captain was
    # rejected from this opening, including ones busy elsewhere in the event.
    # Cross-opening conflicts (the same person, or a crew member sick on the
    # other pairing) are resolved by the joint solver below.
    for event in events:
        crew_id = event["crew_id"]
        pairing_id = event["pairing_id"]
        role = _role_for(world, crew_id, pairing_id)
        impact = crew_unavailable(
            world,
            crew_id=crew_id,
            pairing_id=pairing_id,
            reported_utc=parse_dt(event["reported_utc"]) if event.get("reported_utc") else reported_utc,
        )
        cs = enumerate_cover_for_pairing(
            world, pairing_id=pairing_id, role=role, sick_crew_id=crew_id
        )
        per_opening.append((pairing_id, role, cs))
        impacts[pairing_id] = impact.as_dict() if impact else None

    plan = solve(
        [
            Opening(key=pid, label=f"{role} on {pid}", candidate_set=cs)
            for pid, role, cs in per_opening
        ],
        unavailable=set(sick_ids),
    )

    return ScenarioResult(
        MULTI_SICK,
        forked,
        {
            "resolved": True,
            "sick_crew": sick_ids,
            "impacts": impacts,
            "openings": [
                {
                    "pairing_id": pid,
                    "role": role,
                    **cs.as_dict(),
                    "answer_key_options": cs.options,
                }
                for pid, role, cs in per_opening
            ],
            "optimal_joint_plan": plan.as_dict(),
        },
    )


# --------------------------------------------------------------------------
# STATION_CLOSURE
# --------------------------------------------------------------------------


def closure(
    world: World, *, station: str, start_utc: datetime, end_utc: datetime
) -> ScenarioResult:
    impact: ClosureImpact = station_closure(
        world, station=station, start_utc=start_utc, end_utc=end_utc
    )
    forked = world.apply(
        {
            "type": CLOSURE,
            "station": station,
            "window_utc": {
                "start": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        }
    )

    recovery = []
    for assessment in impact.assessments:
        if assessment.feasible:
            continue
        pairing = world.pairing(assessment.pairing_id)
        day = next(
            (d for d in pairing.days if assessment.flight_id in d.flight_ids), pairing.days[0]
        )
        tail_legs = list(day.flight_ids[day.flight_ids.index(assessment.flight_id) :])
        recovery.append(
            {
                "pairing_id": assessment.pairing_id,
                "trigger_flight": assessment.flight_id,
                "min_delay_hours": assessment.min_delay_hours,
                "fdp_after_delay": assessment.crew_fdp_after_delay,
                "fdp_limit": assessment.fdp_limit,
                "tail_legs_needing_recrew": tail_legs,
                "seats_at_risk": sum(world.flight(f).seats for f in tail_legs),
                "cancellation_cost_inr": world.costs.cancellation_per_flight * len(tail_legs),
                "recommended": (
                    "re-crew the tail legs from the reserve pool; cancel only if no "
                    "legal complement is available inside the delay window"
                ),
            }
        )

    payload = impact.as_dict()
    payload["recovery_plan"] = recovery
    payload["resolved"] = True
    return ScenarioResult(CLOSURE, forked, payload)


# --------------------------------------------------------------------------
# DELAY
# --------------------------------------------------------------------------

RESERVE_SET_ROLES = ["Captain", "First Officer", "Senior Cabin Crew", "Cabin Crew", "Cabin Crew", "Cabin Crew"]


def delay(
    world: World, *, aircraft: str, on: date, delay_hours: float, day_index: int = 0
) -> ScenarioResult:
    impact: DelayImpact | None = aircraft_delay(
        world, aircraft=aircraft, on=on, delay_hours=delay_hours, day_index=day_index
    )
    if impact is None:
        return ScenarioResult(
            DELAY, world, {"resolved": False, "detail": f"no pairing for {aircraft} on {on}"}
        )

    forked = world.apply(
        {
            "type": DELAY,
            "aircraft": aircraft,
            "date": on.isoformat(),
            "delay_hours": delay_hours,
        }
    )

    payload = impact.as_dict()
    payload["resolved"] = True
    payload["options"] = []

    if impact.breach and impact.legs_needing_recrew:
        recrew_cost = complement_callout_cost(world.costs, RESERVE_SET_ROLES)
        kept = impact.max_legal_sectors
        first_legs = world.pairing(impact.pairing_id).days[day_index].flight_ids[:kept]
        tail_nos = ", ".join(world.flight(f).flight_no for f in impact.legs_needing_recrew)
        kept_nos = f"{world.flight(first_legs[0]).flight_no}–{world.flight(first_legs[-1]).flight_no}"
        payload["options"] = [
            {
                "rank": 1,
                "action": (
                    f"Original crew operates {kept_nos} (delayed); full reserve set "
                    f"(CPT, FO, SCC, 3 CC) operates {tail_nos}"
                ),
                "legal": True,
                "cost_inr": recrew_cost.total,
                "cost_breakdown": recrew_cost.as_dict(),
                "reasoning": (
                    f"Delayed {kept}-leg duty FDP {impact.partial_fdp_hours}h vs "
                    f"{impact.partial_fdp_limit}h limit — legal. Reserve set covers the "
                    f"last sector (callout window and 12h-rest all satisfied)."
                ),
            },
            {
                "rank": 2,
                "action": f"Cancel {tail_nos}",
                "legal": True,
                "cost_inr": world.costs.cancellation_per_flight * len(impact.legs_needing_recrew),
                "reasoning": (
                    f"Legal but ~{round(world.costs.cancellation_per_flight * len(impact.legs_needing_recrew) / max(1, recrew_cost.total), 1)}x "
                    f"more expensive than re-crewing; {impact.seats_downstream} passengers stranded."
                ),
            },
        ]
        payload["expected_choice"] = payload["options"][0]

    return ScenarioResult(DELAY, forked, payload)


# --------------------------------------------------------------------------
# CANCELLATION
# --------------------------------------------------------------------------


def cancellation(world: World, *, flight_ids: list[str]) -> ScenarioResult:
    forked = world.apply({"type": CANCELLATION, "flight_ids": list(flight_ids)})
    payload = cancellation_impact(world, flight_ids)
    payload["resolved"] = True
    return ScenarioResult(CANCELLATION, forked, payload)


# --------------------------------------------------------------------------
# Dispatcher -- used by the dataset scenarios, the API and the agent
# --------------------------------------------------------------------------


def run_event(world: World, event: dict[str, Any]) -> ScenarioResult:
    etype = event.get("type")

    if etype == SICK:
        return crew_opening(
            world,
            crew_id=event["crew_id"],
            pairing_id=event.get("pairing_id"),
            reported_utc=parse_dt(event["reported_utc"]) if event.get("reported_utc") else None,
        )

    if etype == MULTI_SICK:
        return multi_crew_opening(world, events=list(event["events"]))

    if etype == CLOSURE:
        window = event["window_utc"]
        return closure(
            world,
            station=event["station"],
            start_utc=parse_dt(window["start"]),
            end_utc=parse_dt(window["end"]),
        )

    if etype == DELAY:
        return delay(
            world,
            aircraft=event["aircraft"],
            on=parse_date(event["date"]),
            delay_hours=float(event["delay_hours"]),
        )

    if etype == CERT_EXPIRY:
        return certification_lapse(
            world,
            crew_id=event["crew_id"],
            pairing_id=event["pairing_id"],
            reported_utc=parse_dt(event["reported_utc"]) if event.get("reported_utc") else None,
        )

    if etype == CANCELLATION:
        return cancellation(world, flight_ids=list(event["flight_ids"]))

    raise ValueError(
        f"Unsupported event type {etype!r}. Supported: {', '.join(SUPPORTED_EVENTS)}"
    )
