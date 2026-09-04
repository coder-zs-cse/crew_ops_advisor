"""Simulation and recommendation endpoints.

These call the same core functions the agent's tools call, so the workbench and
the chat surface cannot disagree with each other or with the conformance suite.

Every simulation forks the world; nothing here mutates the snapshot. ``/chain``
forks a fork, which is how chained disruptions work.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AfterValidator, BaseModel, Field
from sqlalchemy.orm import Session

from ...core import scenarios as sc
from ...core.candidates import enumerate_cover_for_pairing
from ...core.joint import Opening, solve
from ...core.loader import read_json
from ...core.notification import build_slots, render_fallback
from ...core.rules.engine import check_cover
from ...core.timeutil import parse_dt
from ...core.world import World
from ...config import get_settings
from ...db.models import Decision, Notification
from ...db.session import get_db
from ...obs.tracer import TRACER
from ..deps import get_world

router = APIRouter(prefix="/api", tags=["simulate"])


def _to_naive_utc(value: datetime) -> datetime:
    """Normalise an inbound timestamp to naive UTC.

    The dataset -- and therefore everything in ``app.core`` -- works in naive
    UTC. Pydantic parses a trailing ``Z`` into an aware datetime, and comparing
    the two raises. Normalising once here keeps the core free of timezone
    handling it has no reason to carry.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


#: Use this for every timestamp a request body accepts.
UtcNaive = Annotated[datetime, AfterValidator(_to_naive_utc)]


# --------------------------------------------------------------------------
# Request models
# --------------------------------------------------------------------------


class SickRequest(BaseModel):
    crew_id: str
    pairing_id: str | None = None
    reported_utc: UtcNaive | None = None


class ClosureRequest(BaseModel):
    station: str
    start_utc: UtcNaive
    end_utc: UtcNaive


class DelayRequest(BaseModel):
    aircraft: str
    date: date
    delay_hours: float = Field(gt=0, le=24)


class AssignmentRequest(BaseModel):
    crew_id: str
    pairing_id: str
    day_indexes: list[int] | None = None


class CancellationRequest(BaseModel):
    flight_ids: list[str] = Field(min_length=1)


class CertRequest(BaseModel):
    crew_id: str
    pairing_id: str
    reported_utc: UtcNaive | None = None


class CoverRequest(BaseModel):
    pairing_id: str
    role: str | None = None
    sick_crew_id: str | None = None
    day_indexes: list[int] | None = None


class JointRequest(BaseModel):
    openings: list[CoverRequest] = Field(min_length=1)


class LegalityRequest(BaseModel):
    crew_id: str
    pairing_id: str
    day_indexes: list[int] | None = None
    delay_hours: float = 0.0
    replace_existing: bool = True


class MultiSickRequest(BaseModel):
    events: list[SickRequest] = Field(min_length=2)


class ChainRequest(BaseModel):
    """Apply a sequence of events, each to the world the last one produced."""

    events: list[dict] = Field(min_length=1)


class DecisionRequest(BaseModel):
    run_id: str | None = None
    kind: str = "assignment"
    pairing_id: str | None = None
    crew_id: str | None = None
    option: dict
    chosen_by: str = "controller"


class NotificationRequest(BaseModel):
    crew_id: str
    pairing_id: str
    delay_hours: float = 0.0
    cost_inr: int | None = None
    channel: str = "sms"
    decision_id: int | None = None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _traced(name: str, fn, **attrs):
    """Run a simulation inside its own trace so it gets a run inspector entry.

    These runs have no narration -- the caller reads the engine's own output --
    so ``verified`` is left unset rather than false. There is nothing to verify
    when no model wrote anything.
    """
    with TRACER.run(name) as trace:
        trace.metadata.update({"intent": name, "plan_source": "direct", "verified": None})
        with TRACER.span(name, "sim", input=attrs) as span:
            payload = fn()
            span.output = {"keys": list(payload)[:12]}
            TRACER.record_facts_from(payload, prefix=name, tool=name)
            recorded = TRACER.harvest_rule_evaluations(payload)
            if recorded:
                span.attrs["rule_evaluations"] = recorded
        payload["run_id"] = trace.run_id
    return payload


def _resolve_role(world: World, pairing_id: str, role: str | None, sick_crew_id: str | None) -> str:
    pairing = world.get_pairing(pairing_id)
    if pairing is None:
        raise HTTPException(404, f"pairing {pairing_id} not found")
    if role:
        return role
    if sick_crew_id:
        resolved = pairing.role_of(sick_crew_id)
        if resolved:
            return resolved
        crew = world.get_crew(sick_crew_id)
        if crew:
            return crew.rank
    raise HTTPException(400, "provide role, or a sick_crew_id whose role can be resolved")


# --------------------------------------------------------------------------
# Simulations
# --------------------------------------------------------------------------


@router.post("/simulate/sick")
def simulate_sick(body: SickRequest) -> dict:
    world = get_world()
    if world.get_crew(body.crew_id) is None:
        raise HTTPException(404, f"crew {body.crew_id} not found")
    return _traced(
        "simulate.sick",
        lambda: sc.crew_opening(
            world,
            crew_id=body.crew_id,
            pairing_id=body.pairing_id,
            reported_utc=body.reported_utc,
        ).as_dict(),
        **body.model_dump(mode="json"),
    )


@router.post("/simulate/multi-sick")
def simulate_multi_sick(body: MultiSickRequest) -> dict:
    world = get_world()
    events = []
    for event in body.events:
        if event.pairing_id is None:
            raise HTTPException(400, "each event needs a pairing_id")
        events.append(
            {
                "crew_id": event.crew_id,
                "pairing_id": event.pairing_id,
                "reported_utc": event.reported_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                if event.reported_utc
                else None,
            }
        )
    return _traced(
        "simulate.multi_sick",
        lambda: sc.multi_crew_opening(world, events=events).as_dict(),
        events=events,
    )


@router.post("/simulate/station-closure")
def simulate_closure(body: ClosureRequest) -> dict:
    world = get_world()
    if body.station not in world.stations:
        raise HTTPException(404, f"unknown station {body.station}")
    if body.end_utc <= body.start_utc:
        raise HTTPException(400, "end_utc must be after start_utc")
    return _traced(
        "simulate.station_closure",
        lambda: sc.closure(
            world, station=body.station, start_utc=body.start_utc, end_utc=body.end_utc
        ).as_dict(),
        **body.model_dump(mode="json"),
    )


@router.post("/simulate/delay")
def simulate_delay(body: DelayRequest) -> dict:
    world = get_world()
    return _traced(
        "simulate.delay",
        lambda: sc.delay(
            world, aircraft=body.aircraft, on=body.date, delay_hours=body.delay_hours
        ).as_dict(),
        **body.model_dump(mode="json"),
    )


@router.post("/simulate/cert-lapse")
def simulate_cert(body: CertRequest) -> dict:
    world = get_world()
    if world.get_pairing(body.pairing_id) is None:
        raise HTTPException(404, f"pairing {body.pairing_id} not found")
    return _traced(
        "simulate.cert_lapse",
        lambda: sc.certification_lapse(
            world,
            crew_id=body.crew_id,
            pairing_id=body.pairing_id,
            reported_utc=body.reported_utc,
        ).as_dict(),
        **body.model_dump(mode="json"),
    )


@router.post("/simulate/cancellation")
def simulate_cancellation(body: CancellationRequest) -> dict:
    world = get_world()
    unknown = [f for f in body.flight_ids if world.get_flight(f) is None]
    if unknown:
        raise HTTPException(404, f"unknown flights: {unknown}")
    return _traced(
        "simulate.cancellation",
        lambda: sc.cancellation(world, flight_ids=body.flight_ids).as_dict(),
        flight_ids=body.flight_ids,
    )


@router.post("/simulate/assignment")
def simulate_assignment(body: AssignmentRequest) -> dict:
    from ...tools.catalog import simulate_assignment as tool_fn

    world = get_world()
    return _traced(
        "simulate.assignment",
        lambda: tool_fn(
            world,
            crew_id=body.crew_id,
            pairing_id=body.pairing_id,
            day_indexes=body.day_indexes,
        ),
        **body.model_dump(mode="json"),
    )


@router.post("/simulate/chain")
def simulate_chain(body: ChainRequest) -> dict:
    """Apply events in sequence, each against the world the previous produced."""
    world = get_world()
    steps = []
    with TRACER.run("simulate.chain") as trace:
        for index, event in enumerate(body.events):
            with TRACER.span(f"fork[{index}] {event.get('type')}", "sim", input=event) as span:
                try:
                    result = sc.run_event(world, event)
                except ValueError as exc:
                    raise HTTPException(400, str(exc)) from exc
                world = result.world
                span.output = {"event_type": result.event_type}
                steps.append(
                    {
                        "step": index,
                        "event": event,
                        "result": result.payload,
                        "lineage": [dict(e) for e in world.lineage],
                    }
                )
    return {"run_id": trace.run_id, "step_count": len(steps), "steps": steps}


# --------------------------------------------------------------------------
# Legality & recommendation
# --------------------------------------------------------------------------


@router.post("/legality/check")
def legality_check(body: LegalityRequest) -> dict:
    world = get_world()
    if world.get_crew(body.crew_id) is None:
        raise HTTPException(404, f"crew {body.crew_id} not found")
    pairing = world.get_pairing(body.pairing_id)
    if pairing is None:
        raise HTTPException(404, f"pairing {body.pairing_id} not found")

    days = pairing.days
    if body.day_indexes:
        wanted = set(body.day_indexes)
        days = tuple(d for d in days if d.day_index in wanted)

    def run() -> dict:
        report = check_cover(
            world,
            body.crew_id,
            days,
            exclude_pairing=body.pairing_id if body.replace_existing else None,
            delay_hours=body.delay_hours,
        )
        return {
            **report.as_dict(),
            "pairing_id": body.pairing_id,
            "cover_dates": [d.date.isoformat() for d in days],
        }

    return _traced("legality.check", run, **body.model_dump(mode="json"))


@router.post("/recommend/cover")
def recommend_cover(body: CoverRequest) -> dict:
    world = get_world()
    role = _resolve_role(world, body.pairing_id, body.role, body.sick_crew_id)
    return _traced(
        "recommend.cover",
        lambda: enumerate_cover_for_pairing(
            world,
            pairing_id=body.pairing_id,
            role=role,
            sick_crew_id=body.sick_crew_id,
            day_indexes=body.day_indexes,
        ).as_dict(),
        pairing_id=body.pairing_id,
        role=role,
    )


@router.post("/recommend/joint")
def recommend_joint(body: JointRequest) -> dict:
    world = get_world()
    built, sick = [], set()
    for spec in body.openings:
        role = _resolve_role(world, spec.pairing_id, spec.role, spec.sick_crew_id)
        if spec.sick_crew_id:
            sick.add(spec.sick_crew_id)
        built.append(
            Opening(
                key=spec.pairing_id,
                label=f"{role} on {spec.pairing_id}",
                candidate_set=enumerate_cover_for_pairing(
                    world,
                    pairing_id=spec.pairing_id,
                    role=role,
                    sick_crew_id=spec.sick_crew_id,
                    day_indexes=spec.day_indexes,
                ),
            )
        )

    def run() -> dict:
        plan = solve(built, unavailable=sick)
        return {
            "openings": [
                {"pairing_id": o.key, "label": o.label, **o.candidate_set.as_dict()}
                for o in built
            ],
            "optimal_joint_plan": plan.as_dict(),
        }

    return _traced("recommend.joint", run, openings=[o.key for o in built])


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------


@router.get("/scenarios")
def list_scenarios(include_holdout: bool = False) -> dict:
    data_dir = get_settings().data_dir
    rows = read_json(data_dir, "scenarios")
    if include_holdout:
        rows = rows + read_json(data_dir, "held_out_scenarios")
    return {
        "count": len(rows),
        "scenarios": [
            {
                "scenario_id": s["scenario_id"],
                "title": s.get("title", ""),
                "difficulty": s.get("difficulty"),
                "event": s["event"],
                "narrative": s["event"].get("narrative", ""),
            }
            for s in rows
        ],
    }


@router.post("/scenarios/{scenario_id}/replay")
def replay_scenario(scenario_id: str) -> dict:
    data_dir = get_settings().data_dir
    rows = read_json(data_dir, "scenarios") + read_json(data_dir, "held_out_scenarios")
    scenario = next((s for s in rows if s["scenario_id"] == scenario_id), None)
    if scenario is None:
        raise HTTPException(404, f"scenario {scenario_id} not found")

    world = get_world()
    payload = _traced(
        f"scenario.{scenario_id}",
        lambda: sc.run_event(world, scenario["event"]).as_dict(),
        scenario_id=scenario_id,
    )
    return {
        "scenario_id": scenario_id,
        "title": scenario.get("title"),
        "event": scenario["event"],
        "result": payload,
        "answer_key": scenario.get("answer_key"),
    }


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------


@router.post("/decisions")
def create_decision(body: DecisionRequest, session: Session = Depends(get_db)) -> dict:
    """Log a controller's choice.

    This records the decision; it does not rewrite the roster. The world
    snapshot is read-only by design -- a real deployment would hand this to a
    write-back adapter, and the record here is what that adapter would consume.
    """
    decision = Decision(
        run_id=body.run_id,
        kind=body.kind,
        pairing_id=body.pairing_id,
        crew_id=body.crew_id,
        option=body.option,
        cost_inr=body.option.get("cost_inr"),
        chosen_by=body.chosen_by,
    )
    session.add(decision)
    session.commit()
    return {
        "id": decision.id,
        "status": decision.status,
        "created_at": decision.created_at.isoformat(),
        "note": "Recorded. The roster snapshot is read-only; this is the write-back queue.",
    }


@router.get("/decisions")
def list_decisions(limit: int = 50, session: Session = Depends(get_db)) -> dict:
    from sqlalchemy import select

    rows = session.scalars(
        select(Decision).order_by(Decision.created_at.desc()).limit(limit)
    ).all()
    return {
        "count": len(rows),
        "decisions": [
            {
                "id": d.id,
                "run_id": d.run_id,
                "kind": d.kind,
                "pairing_id": d.pairing_id,
                "crew_id": d.crew_id,
                "cost_inr": d.cost_inr,
                "status": d.status,
                "created_at": d.created_at.isoformat(),
                "option": d.option,
            }
            for d in rows
        ],
    }


@router.post("/notifications/draft")
def draft_notification(body: NotificationRequest, session: Session = Depends(get_db)) -> dict:
    world = get_world()
    if world.get_crew(body.crew_id) is None:
        raise HTTPException(404, f"crew {body.crew_id} not found")
    if world.get_pairing(body.pairing_id) is None:
        raise HTTPException(404, f"pairing {body.pairing_id} not found")

    slots = build_slots(
        world,
        crew_id=body.crew_id,
        pairing_id=body.pairing_id,
        delay_hours=body.delay_hours,
        cost_inr=body.cost_inr,
    )
    text = render_fallback(slots)

    notification = Notification(
        decision_id=body.decision_id,
        crew_id=body.crew_id,
        channel=body.channel,
        body=text,
        slots=slots,
        status="draft",
    )
    session.add(notification)
    session.commit()
    return {"id": notification.id, "status": "draft", "slots": slots, "body": text}


@router.post("/notifications/{notification_id}/send")
def send_notification(notification_id: int, session: Session = Depends(get_db)) -> dict:
    notification = session.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(404, "notification not found")
    notification.status = "sent"
    session.commit()
    return {
        "id": notification.id,
        "status": notification.status,
        "note": "Simulated. No message leaves this system; there is no real crew to page.",
    }
