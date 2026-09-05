"""Candidate enumeration -- the flagship deterministic routine.

Given an opening (a pairing, a role, and who dropped out), enumerate EVERY
crew member who could take it, decide legality for each, price the legal ones,
and record a reason for each rejection.

Two things about this that matter more than they look:

1. The candidate pool is **every active crew member of the required rank**, not
   just the reserve pool. Most of the answer keys' options are day-off callouts
   of ordinary line crew. A reserve-only search returns a short, wrong list.

2. The rejections are the product. ``CandidateSet.excluded`` carries a reason
   per crew member, citing the rule and the arithmetic. That is what a
   controller challenges, and it is what turns a ranked list into a decision
   they can defend.

Gate order (matters, because each gate feeds the next):
    status/rank filter -> RULE-BASE-07 positioning -> reserve on-call window
    -> the seven-rule legality engine -> costing
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from .costing import CostBreakdown, callout_cost, cancellation_cost
from .models import PILOT_ROLES, Crew, LegalityReport, PairingDay, RuleVerdict
from .positioning import PositioningOption, find_positioning
from .rules.base import CoverContext
from .rules.engine import ALL_RULE_IDS, ENGINE, RuleEngine
from .timeutil import at
from .world import World

CANCEL_ACTION_RULES: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverCandidate:
    """A crew member who *can* take the opening."""

    crew_id: str
    crew: Crew
    action: str
    cost: CostBreakdown
    delay_hours: float
    is_reserve: bool
    positioning: PositioningOption | None
    legality: LegalityReport
    rank: int = 0
    ops_rank: int = 0
    ops_score: float = 0.0
    ops_factors: dict = field(default_factory=dict)

    @property
    def cost_inr(self) -> int:
        return self.cost.total

    def as_answer_key_dict(self) -> dict:
        """The exact shape the dataset's answer keys use."""
        return {
            "action": self.action,
            "crew_id": self.crew_id,
            "legal": True,
            "rules_checked": list(ALL_RULE_IDS),
            "cost_inr": self.cost_inr,
            "delay_hours": self.delay_hours,
            "rank": self.rank,
        }

    def as_dict(self, world: World | None = None, cover_pairing_id: str | None = None) -> dict:
        base = self.as_answer_key_dict()
        base.update(
            {
                "crew_name": self.crew.name,
                "crew_rank": self.crew.rank,
                "base": self.crew.base,
                "ratings": list(self.crew.ratings),
                "seniority": self.crew.seniority,
                "reachability_minutes": self.crew.reachability_minutes,
                "source": "reserve" if self.is_reserve else "day-off",
                "cost_breakdown": self.cost.as_dict(),
                "positioning": self.positioning.as_dict() if self.positioning else None,
                "ops_rank": self.ops_rank,
                "ops_score": self.ops_score,
                "ops_factors": self.ops_factors,
                "verdicts": [v.as_dict() for v in self.legality.verdicts],
            }
        )
        if world is not None:
            from .schedule_view import crew_schedule_window
            base["schedule_window"] = crew_schedule_window(
                world,
                self.crew_id,
                cover_pairing_id=cover_pairing_id,
            )
        return base


@dataclass(frozen=True, slots=True)
class CancelOption:
    n_flights: int
    cost: CostBreakdown
    flight_ids: tuple[str, ...]
    seats_at_risk: int
    rank: int = 0

    @property
    def cost_inr(self) -> int:
        return self.cost.total

    def as_answer_key_dict(self) -> dict:
        return {
            "action": f"Cancel all {self.n_flights} flights of the pairing",
            "crew_id": None,
            "legal": True,
            "rules_checked": [],
            "cost_inr": self.cost_inr,
            "delay_hours": 0.0,
            "rank": self.rank,
        }

    def as_dict(self) -> dict:
        base = self.as_answer_key_dict()
        base.update(
            {
                "cost_breakdown": self.cost.as_dict(),
                "flight_ids": list(self.flight_ids),
                "seats_at_risk": self.seats_at_risk,
                "source": "cancellation",
            }
        )
        return base


@dataclass(frozen=True, slots=True)
class ExcludedCandidate:
    crew_id: str
    reason: str
    rule_ids: tuple[str, ...]
    verdicts: tuple[RuleVerdict, ...] = ()

    def as_answer_key_dict(self) -> dict:
        return {"crew_id": self.crew_id, "reason": self.reason}

    def as_dict(self) -> dict:
        return {
            "crew_id": self.crew_id,
            "reason": self.reason,
            "rule_ids": list(self.rule_ids),
            "verdicts": [v.as_dict() for v in self.verdicts],
        }


@dataclass(frozen=True, slots=True)
class CandidateSet:
    role: str
    pairing_id: str | None
    cover_dates: tuple[str, ...]
    eligible: tuple[CoverCandidate, ...]
    excluded: tuple[ExcludedCandidate, ...]
    cancel: CancelOption | None
    evaluated_count: int

    @property
    def options(self) -> list[dict]:
        """Ranked options in answer-key order (cost asc, cancel last)."""
        out = [c.as_answer_key_dict() for c in self.eligible]
        if self.cancel is not None:
            out.append(self.cancel.as_answer_key_dict())
        return out

    def exclusion_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for ex in self.excluded:
            key = ex.rule_ids[0] if ex.rule_ids else "OTHER"
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def as_dict(self, world: World | None = None) -> dict:
        return {
            "role": self.role,
            "pairing_id": self.pairing_id,
            "cover_dates": list(self.cover_dates),
            "evaluated_count": self.evaluated_count,
            "eligible_count": len(self.eligible),
            "excluded_count": len(self.excluded),
            "exclusion_summary": self.exclusion_summary(),
            "options": [
                c.as_dict(world=world, cover_pairing_id=self.pairing_id)
                for c in self.eligible
            ] + ([self.cancel.as_dict()] if self.cancel else []),
            "excluded_candidates": [e.as_dict() for e in self.excluded],
        }


# --------------------------------------------------------------------------


def _rule_ids_in(reason: str) -> tuple[str, ...]:
    found = [rid for rid in ALL_RULE_IDS if rid in reason]
    if "double-booked" in reason:
        found.append("CONSTRAINT-OVERLAP")
    if "on-call window" in reason:
        found.append("CONSTRAINT-RESERVE-WINDOW")
    return tuple(found) or ("OTHER",)


def _reserve_window_covers(world: World, crew_id: str, required_report: datetime) -> tuple[bool, str]:
    reserve = world.reserve(crew_id)
    if reserve is None:
        return True, ""
    start = at(required_report.date(), reserve.oncall_start)
    end = at(required_report.date(), reserve.oncall_end)
    if start <= required_report <= end:
        return True, ""
    return False, (
        f"reserve on-call window {reserve.oncall_start}-{reserve.oncall_end}Z "
        f"does not cover required report {required_report.strftime('%H:%M')}Z"
    )


def enumerate_cover(
    world: World,
    *,
    cover_days: Iterable[PairingDay],
    role: str,
    sick_crew_id: str | None = None,
    exclude_pairing: str | None = None,
    engine: RuleEngine | None = None,
    include_cancel: bool = True,
    forbid: Iterable[str] = (),
) -> CandidateSet:
    """Enumerate, judge, price and rank every candidate for one opening.

    ``forbid`` lets the joint solver rule out crew already committed elsewhere.
    """
    engine = engine or ENGINE
    days = tuple(cover_days)
    if not days:
        raise ValueError("cover_days must not be empty")

    first_flight = world.flight(days[0].flight_ids[0])
    base_needed = first_flight.dep_station
    is_pilot = role in PILOT_ROLES
    forbidden = set(forbid)
    reserve_ids = world.reserve_ids

    eligible: list[CoverCandidate] = []
    excluded: list[ExcludedCandidate] = []
    evaluated = 0

    for crew in world.crew:
        cid = crew.crew_id
        if cid == sick_crew_id or crew.rank != role or crew.status != "active":
            continue
        if cid in forbidden:
            excluded.append(
                ExcludedCandidate(
                    cid,
                    "already committed to another opening in this plan",
                    ("CONSTRAINT-DOUBLE-ASSIGN",),
                )
            )
            continue
        if not world.is_available(cid):
            excluded.append(
                ExcludedCandidate(cid, "unavailable in this scenario", ("CONSTRAINT-UNAVAILABLE",))
            )
            continue

        evaluated += 1
        is_reserve = cid in reserve_ids

        # --- Gate 1: RULE-BASE-07 positioning ---------------------------
        positioning: PositioningOption | None = None
        delay_hours = 0.0
        if crew.base != base_needed:
            positioning = find_positioning(
                world,
                from_station=crew.base,
                to_station=base_needed,
                on=days[0].date,
                required_departure=first_flight.dep_utc,
            )
            if positioning is None:
                excluded.append(
                    ExcludedCandidate(
                        cid,
                        "RULE-BASE-07: no same-day positioning flight from base",
                        ("RULE-BASE-07",),
                    )
                )
                continue
            delay_hours = positioning.delay_hours

        # --- Gate 2: reserve on-call window -----------------------------
        if is_reserve:
            required_report = days[0].report_utc + _hours(delay_hours)
            ok, reason = _reserve_window_covers(world, cid, required_report)
            if not ok:
                excluded.append(
                    ExcludedCandidate(cid, reason, ("CONSTRAINT-RESERVE-WINDOW",))
                )
                continue

        # --- Gate 3: the seven-rule engine ------------------------------
        # required_role=role is redundant here -- the filter at the top of
        # this loop already guarantees crew.rank == role -- but it's cheap and
        # keeps this call site consistent with check_legality's, so a future
        # change to the filter above can't silently reopen the rank gap that
        # check_legality had (see rules/precondition.py).
        ctx = CoverContext(
            world=world,
            crew_id=cid,
            cover_days=days,
            exclude_pairing=exclude_pairing,
            delay_hours=delay_hours,
            required_role=role,
        )
        report = engine.evaluate_cover(ctx)
        if not report.legal:
            reason = "; ".join(report.issues)
            excluded.append(
                ExcludedCandidate(cid, reason, _rule_ids_in(reason), report.breaches)
            )
            continue

        # --- Pricing -----------------------------------------------------
        cost = callout_cost(
            world.costs,
            is_reserve=is_reserve,
            is_pilot=is_pilot,
            delay_hours=delay_hours,
            deadhead=positioning is not None,
        )
        label = "reserve callout" if is_reserve else "day-off callout"
        if positioning is not None:
            label += (
                f" + deadhead from {crew.base} "
                f"(first departure delayed ~{delay_hours}h)"
            )

        eligible.append(
            CoverCandidate(
                crew_id=cid,
                crew=crew,
                action=f"Assign {crew.rank} {cid} ({label})",
                cost=cost,
                delay_hours=delay_hours,
                is_reserve=is_reserve,
                positioning=positioning,
                legality=report,
            )
        )

    # --- Ranking (imported late to avoid a cycle) -----------------------
    from .ranking import apply_rankings

    all_flight_ids = tuple(fid for day in days for fid in day.flight_ids)
    cancel = None
    if include_cancel:
        cancel = CancelOption(
            n_flights=len(all_flight_ids),
            cost=cancellation_cost(world.costs, len(all_flight_ids)),
            flight_ids=all_flight_ids,
            seats_at_risk=sum(world.flight(fid).seats for fid in all_flight_ids),
        )

    eligible, cancel = apply_rankings(world, eligible, cancel)

    return CandidateSet(
        role=role,
        pairing_id=days[0].pairing_id,
        cover_dates=tuple(d.date.isoformat() for d in days),
        eligible=tuple(eligible),
        excluded=tuple(excluded),
        cancel=cancel,
        evaluated_count=evaluated,
    )


def _hours(value: float):
    from datetime import timedelta

    return timedelta(hours=value)


def enumerate_cover_for_pairing(
    world: World,
    *,
    pairing_id: str,
    role: str,
    sick_crew_id: str | None = None,
    day_indexes: Iterable[int] | None = None,
    **kw,
) -> CandidateSet:
    """Convenience entry point: cover a pairing (or some of its days)."""
    pairing = world.pairing(pairing_id)
    days = pairing.days
    if day_indexes is not None:
        wanted = set(day_indexes)
        days = tuple(d for d in days if d.day_index in wanted)
    return enumerate_cover(
        world,
        cover_days=days,
        role=role,
        sick_crew_id=sick_crew_id,
        exclude_pairing=pairing_id,
        **kw,
    )
