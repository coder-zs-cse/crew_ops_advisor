"""Proactive watchers.

The problem statement calls the desk reactive: something breaks, then a
controller reasons about it. These jobs invert that where the data allows it --
they scan the forward schedule for conditions that are *already* true and will
become somebody's 05:00 emergency.

The strongest of them is ``cert_expiry_watch``: scenario S5 is a certification
that lapsed on the 17th against a duty on the 19th. That is visible in the data
on the 14th. Nobody needs to call in sick for the system to find it.

Every watcher returns alerts in the same shape: a grounded finding, a severity,
and the question a controller would ask next -- so the alert card can hand
straight off to the advisor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from ..core.briefing import morning_briefing
from ..core.duty import fdp_limit
from ..core.rules.duty02 import MAX_DUTY_HOURS
from ..core.rules.flt03 import MAX_FLIGHT_HOURS
from ..core.timeutil import at, fmt_dt, hrs
from ..core.windows import DUTY, FLIGHT, window_sum
from ..core.world import World

CRITICAL, WARNING, INFO = "critical", "warning", "info"


@dataclass
class AlertDraft:
    id: str
    type: str
    severity: str
    title: str
    detail: str
    entity_ref: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    suggested_question: str | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "entity_ref": self.entity_ref,
            "payload": self.payload,
            "suggested_question": self.suggested_question,
        }


Watcher = Callable[[World, datetime], list[AlertDraft]]
WATCHERS: dict[str, Watcher] = {}


def watcher(name: str):
    def decorate(fn: Watcher) -> Watcher:
        WATCHERS[name] = fn
        return fn

    return decorate


def _horizon(world: World, now: datetime, days: int) -> list[date]:
    end = (now + timedelta(days=days)).date()
    return [d for d in world.dates if now.date() <= d <= end]


# --------------------------------------------------------------------------


@watcher("cert_expiry")
def cert_expiry_watch(world: World, now: datetime) -> list[AlertDraft]:
    """A certificate that lapses before a duty the crew member is rostered on.

    Not "expiring soon" -- actually invalid on a date they are scheduled to fly.
    That is a grounded illegality sitting in the published roster.
    """
    alerts: list[AlertDraft] = []
    for crew in world.crew:
        duties = [s for s in world.week_duties(crew.crew_id) if s.date >= now.date()]
        if not duties:
            continue
        for cert in world.certs(crew.crew_id).values():
            blocked = [s for s in duties if cert.valid_to < s.date]
            if not blocked:
                continue
            first = blocked[0]
            alerts.append(
                AlertDraft(
                    id=f"cert:{crew.crew_id}:{cert.cert_type}:{first.date}",
                    type="CERT_LAPSE_BEFORE_DUTY",
                    severity=CRITICAL,
                    title=f"{crew.rank} {crew.crew_id}: {cert.cert_type} expires before a rostered duty",
                    detail=(
                        f"{cert.cert_type} is valid to {cert.valid_to.isoformat()}, but "
                        f"{crew.crew_id} is rostered on {first.label} on {first.date.isoformat()}. "
                        f"RULE-CERT-06 makes that assignment illegal."
                    ),
                    entity_ref=crew.crew_id,
                    payload={
                        "crew_id": crew.crew_id,
                        "cert_type": cert.cert_type,
                        "valid_to": cert.valid_to.isoformat(),
                        "blocked_duties": [
                            {"date": s.date.isoformat(), "pairing_id": s.label} for s in blocked
                        ],
                        "rule": "RULE-CERT-06",
                    },
                    suggested_question=(
                        f"{crew.crew_id}'s {cert.cert_type} lapsed. Resolve their "
                        f"{first.date.isoformat()} assignment on {first.label}."
                    ),
                )
            )
    return alerts


@watcher("cert_expiring_soon")
def cert_expiring_soon_watch(world: World, now: datetime) -> list[AlertDraft]:
    today = now.date()
    cutoff = today + timedelta(days=30)
    rows = [
        c
        for c in world.certifications
        if today <= c.valid_to <= cutoff
        and (crew := world.get_crew(c.crew_id))
        and crew.status == "active"
    ]
    if not rows:
        return []
    rows.sort(key=lambda c: c.valid_to)
    return [
        AlertDraft(
            id=f"certsoon:{today}",
            type="CERTS_EXPIRING",
            severity=INFO,
            title=f"{len(rows)} certifications expire within 30 days",
            detail="; ".join(
                f"{c.crew_id} {c.cert_type} {c.valid_to.isoformat()}" for c in rows[:5]
            ),
            payload={
                "count": len(rows),
                "certifications": [
                    {
                        "crew_id": c.crew_id,
                        "cert_type": c.cert_type,
                        "valid_to": c.valid_to.isoformat(),
                        "days_remaining": (c.valid_to - today).days,
                    }
                    for c in rows
                ],
            },
            suggested_question=f"List all certifications expiring within 30 days of {today.isoformat()}.",
        )
    ]


@watcher("duty_limit")
def duty_limit_watch(world: World, now: datetime, threshold: float = 0.90) -> list[AlertDraft]:
    """Crew whose 7-day duty will sit within 10% of the 60h ceiling."""
    alerts: list[AlertDraft] = []
    for day in _horizon(world, now, 2):
        for crew in world.crew:
            if crew.status != "active":
                continue
            if not any(s.date == day for s in world.week_duties(crew.crew_id)):
                continue
            used = window_sum(world, crew.crew_id, day, 7, DUTY)
            if used < MAX_DUTY_HOURS * threshold:
                continue
            headroom = round(MAX_DUTY_HOURS - used, 2)
            alerts.append(
                AlertDraft(
                    id=f"duty:{crew.crew_id}:{day}",
                    type="DUTY_LIMIT_APPROACHING",
                    severity=CRITICAL if headroom <= 2 else WARNING,
                    title=f"{crew.rank} {crew.crew_id}: {headroom}h duty headroom on {day.isoformat()}",
                    detail=(
                        f"{used}h of the 60h RULE-DUTY-02 ceiling in the 7 days ending "
                        f"{day.isoformat()}. Any extension needs checking before it is offered."
                    ),
                    entity_ref=crew.crew_id,
                    payload={
                        "crew_id": crew.crew_id,
                        "date": day.isoformat(),
                        "duty_hours_7d": used,
                        "headroom_hours": headroom,
                        "rule": "RULE-DUTY-02",
                    },
                    suggested_question=(
                        f"How many duty hours does {crew.crew_id} have in the 7 days "
                        f"ending {day.isoformat()}?"
                    ),
                )
            )
    return alerts


@watcher("flight_hours")
def flight_hour_watch(world: World, now: datetime, threshold: float = 0.90) -> list[AlertDraft]:
    alerts: list[AlertDraft] = []
    today = now.date()
    for crew in world.crew:
        if crew.status != "active":
            continue
        used = window_sum(world, crew.crew_id, today, 28, FLIGHT)
        if used < MAX_FLIGHT_HOURS * threshold:
            continue
        alerts.append(
            AlertDraft(
                id=f"blockhours:{crew.crew_id}:{today}",
                type="FLIGHT_HOURS_APPROACHING",
                severity=WARNING,
                title=f"{crew.rank} {crew.crew_id}: {round(MAX_FLIGHT_HOURS - used, 2)}h block headroom",
                detail=f"{used}h of the 100h RULE-FLT-03 ceiling in the 28 days to {today.isoformat()}.",
                entity_ref=crew.crew_id,
                payload={"crew_id": crew.crew_id, "flight_hours_28d": used, "rule": "RULE-FLT-03"},
                suggested_question=f"What are {crew.crew_id}'s flight hours over the last 28 days?",
            )
        )
    return alerts


@watcher("fdp_margin")
def fdp_margin_watch(world: World, now: datetime, margin_hours: float = 1.0) -> list[AlertDraft]:
    """Duties so close to their FDP limit that any delay breaks them.

    This is what makes scenario S4 predictable rather than surprising: the
    90-minute delay only bites because that duty had 0.75h of margin to begin
    with, and that was knowable the day before.
    """
    alerts: list[AlertDraft] = []
    for day in _horizon(world, now, 2):
        for pairing in world.pairings:
            for pairing_day in pairing.days:
                if pairing_day.date != day:
                    continue
                fdp = hrs(pairing_day.release_utc - pairing_day.report_utc)
                limit = fdp_limit(pairing_day.sectors)
                margin = round(limit - fdp, 2)
                if margin > margin_hours:
                    continue
                alerts.append(
                    AlertDraft(
                        id=f"fdp:{pairing.pairing_id}:{day}",
                        type="FDP_MARGIN_THIN",
                        severity=WARNING if margin > 0.25 else CRITICAL,
                        title=f"{pairing.aircraft} {pairing.pairing_id}: {margin}h FDP margin on {day.isoformat()}",
                        detail=(
                            f"Planned duty {fdp}h against a {limit}h limit for "
                            f"{pairing_day.sectors} sectors. A delay beyond {margin}h forces a "
                            f"re-crew of the tail legs."
                        ),
                        entity_ref=pairing.pairing_id,
                        payload={
                            "pairing_id": pairing.pairing_id,
                            "aircraft": pairing.aircraft,
                            "date": day.isoformat(),
                            "fdp_hours": fdp,
                            "fdp_limit": limit,
                            "margin_hours": margin,
                            "rule": "RULE-FDP-01",
                        },
                        suggested_question=(
                            f"{pairing.aircraft} is delayed 90 minutes on {day.isoformat()}. "
                            f"Does the rostered crew breach any limit?"
                        ),
                    )
                )
    return alerts


@watcher("reserve_coverage")
def reserve_coverage_watch(world: World, now: datetime) -> list[AlertDraft]:
    """Openings on a line that no reserve could legally take.

    A reserve count is meaningless on its own -- what matters is how many
    reserves are rated for *this* aircraft, based at *this* station, with an
    on-call window covering *this* report time.
    """
    alerts: list[AlertDraft] = []
    for day in _horizon(world, now, 2):
        for pairing in world.pairings:
            pairing_day = next((d for d in pairing.days if d.date == day), None)
            if pairing_day is None:
                continue
            actype = world.flight(pairing_day.flight_ids[0]).aircraft_type
            station = world.flight(pairing_day.flight_ids[0]).dep_station

            depth: dict[str, int] = {}
            for reserve in world.reserves:
                if day not in reserve.dates or reserve.base != station:
                    continue
                crew = world.crew_member(reserve.crew_id)
                if actype not in crew.ratings:
                    continue
                start, end = at(day, reserve.oncall_start), at(day, reserve.oncall_end)
                if start <= pairing_day.report_utc <= end:
                    depth[crew.rank] = depth.get(crew.rank, 0) + 1

            uncovered = sorted({role for _, role in pairing.crew if depth.get(role, 0) == 0})
            if not uncovered:
                continue
            alerts.append(
                AlertDraft(
                    id=f"reserve:{pairing.pairing_id}:{day}",
                    type="RESERVE_GAP",
                    severity=WARNING,
                    title=f"{pairing.aircraft} {day.isoformat()}: no on-call reserve for {', '.join(uncovered)}",
                    detail=(
                        f"Report is {fmt_dt(pairing_day.report_utc)} at {station} on {actype}. "
                        f"No {actype}-rated reserve at {station} has an on-call window covering it "
                        f"for: {', '.join(uncovered)}. Cover would be a day-off callout."
                    ),
                    entity_ref=pairing.pairing_id,
                    payload={
                        "pairing_id": pairing.pairing_id,
                        "aircraft": pairing.aircraft,
                        "date": day.isoformat(),
                        "report_utc": fmt_dt(pairing_day.report_utc),
                        "station": station,
                        "aircraft_type": actype,
                        "depth_by_rank": depth,
                        "uncovered_roles": uncovered,
                        "rules": ["RULE-BASE-07", "RULE-QUAL-05"],
                    },
                    suggested_question=(
                        f"Who is on reserve at {station} on {day.isoformat()}, and what are "
                        f"their on-call windows?"
                    ),
                )
            )
    return alerts


@watcher("rotation_fragility")
def rotation_fragility_watch(world: World, now: datetime, min_turn: float = 0.75) -> list[AlertDraft]:
    alerts: list[AlertDraft] = []
    for day in _horizon(world, now, 2):
        for tail in sorted({f.aircraft for f in world.flights}):
            legs = [f for f in world.flights_of_tail(tail) if f.date == day]
            tight = []
            for current, following in zip(legs, legs[1:]):
                turn = hrs(following.dep_utc - current.arr_utc)
                if turn <= min_turn:
                    tight.append(
                        {"after": current.flight_id, "before": following.flight_id, "turn_hours": turn}
                    )
            if not tight:
                continue
            alerts.append(
                AlertDraft(
                    id=f"turn:{tail}:{day}",
                    type="ROTATION_FRAGILE",
                    severity=INFO,
                    title=f"{tail} on {day.isoformat()}: {len(tight)} turns at or under {min_turn}h",
                    detail="A delay on any of these legs propagates straight into the next.",
                    entity_ref=tail,
                    payload={"aircraft": tail, "date": day.isoformat(), "tight_turns": tight},
                    suggested_question=f"Show the rotation for {tail} on {day.isoformat()}.",
                )
            )
    return alerts


@watcher("high_risk_thin_cover")
def high_risk_thin_cover_watch(world: World, now: datetime, score: float = 0.6) -> list[AlertDraft]:
    """High disruption-risk crew rostered where cover would be expensive.

    The risk score is a provided input -- we do not model it. What we add is the
    consequence: this person is likely to drop out, and if they do, here is what
    it costs, computed now rather than at 05:00.
    """
    from ..core.candidates import enumerate_cover_for_pairing

    alerts: list[AlertDraft] = []
    for day in _horizon(world, now, 1):
        for pairing in world.pairings:
            if not any(d.date == day for d in pairing.days):
                continue
            for crew_id, role in pairing.crew:
                signal = world.risk(crew_id)
                if signal is None or signal.disruption_risk_score < score:
                    continue
                candidates = enumerate_cover_for_pairing(
                    world, pairing_id=pairing.pairing_id, role=role, sick_crew_id=crew_id
                )
                best = candidates.eligible[0] if candidates.eligible else None
                alerts.append(
                    AlertDraft(
                        id=f"risk:{crew_id}:{pairing.pairing_id}",
                        type="HIGH_RISK_CREW_ROSTERED",
                        severity=WARNING if best else CRITICAL,
                        title=(
                            f"{role} {crew_id} (risk {signal.disruption_risk_score}) operates "
                            f"{pairing.pairing_id} on {day.isoformat()}"
                        ),
                        detail=(
                            (
                                f"If they drop out, the cheapest legal cover is "
                                f"{best.crew_id} at INR {best.cost_inr:,} "
                                f"({len(candidates.eligible)} legal of {candidates.evaluated_count} evaluated)."
                            )
                            if best
                            else "If they drop out there is no legal cover — only cancellation."
                        ),
                        entity_ref=crew_id,
                        payload={
                            "crew_id": crew_id,
                            "role": role,
                            "pairing_id": pairing.pairing_id,
                            "date": day.isoformat(),
                            "risk_score": signal.disruption_risk_score,
                            "drivers": list(signal.drivers),
                            "precomputed_cover": best.as_answer_key_dict() if best else None,
                            "legal_options": len(candidates.eligible),
                            "evaluated": candidates.evaluated_count,
                        },
                        suggested_question=f"{crew_id} is out for {pairing.pairing_id}. What should I do?",
                    )
                )
    return alerts


@watcher("flagged_roster_exception")
def flagged_exception_watch(world: World, now: datetime) -> list[AlertDraft]:
    return [
        AlertDraft(
            id=f"flagged:{x.get('crew_id')}:{x.get('date')}",
            type="ROSTER_EXCEPTION",
            severity=CRITICAL,
            title=f"Flagged roster exception: {x.get('crew_id')} on {x.get('date')}",
            detail=str(x.get("note", "")),
            entity_ref=x.get("crew_id"),
            payload=dict(x),
            suggested_question=(
                f"Can {x.get('crew_id')} legally operate their rostered duty on {x.get('date')}?"
            ),
        )
        for x in world.flagged_exceptions
    ]


# --------------------------------------------------------------------------


def run_all(world: World, now: datetime, *, only: list[str] | None = None) -> list[AlertDraft]:
    alerts: list[AlertDraft] = []
    for name, fn in WATCHERS.items():
        if only and name not in only:
            continue
        try:
            alerts.extend(fn(world, now))
        except Exception:  # noqa: BLE001 - one bad watcher must not blank the board
            continue

    order = {CRITICAL: 0, WARNING: 1, INFO: 2}
    alerts.sort(key=lambda a: (order.get(a.severity, 3), a.type, a.id))
    return alerts


def build_briefing(world: World, now: datetime) -> dict:
    return morning_briefing(world, on=now.date())
