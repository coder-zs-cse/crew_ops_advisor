"""Structural preconditions -- not one of the seven numbered rules, but each
one makes every rule after it moot, exactly the way RULE-QUAL-05 already
short-circuits an unrated pilot's duty-hour arithmetic.

Both checks already exist, correctly, in ``candidates.py``'s enumeration path
(``crew.rank != role or crew.status != "active"`` is the very first filter it
applies, before it ever builds a ``CoverContext``). That path is the
recommendation engine -- ``enumerate_cover_candidates`` / ``resolve_disruption``
/ ``solve_joint_assignment`` -- and it was never the gap.

The gap was everything else that reaches ``check_cover`` directly on one named
crew member with no upstream filter: ``check_legality`` and
``simulate_assignment``. Reproduced and documented in
``generalization_questions.json`` (GQ06, GQ11) and ``docs/LIMITATIONS.md``:
asking whether a crew member *on leave* can legally cover a pairing, or
whether a *First Officer* can legally take a *Captain's* seat, both came back
``legal=True`` -- fluent, confident, and wrong, because nothing in the rule
engine itself ever looked at ``status`` or compared rank to the seat.

Putting both checks here, run first by the engine (see ``engine.py``), means
every entry point enforces them identically instead of relying on whichever
caller happens to filter upstream.
"""

from __future__ import annotations

from ..models import ArithmeticStep, RuleVerdict
from .base import CoverContext

STATUS_ID = "CONSTRAINT-STATUS"
RANK_ID = "CONSTRAINT-RANK"


class AvailabilityRule:
    """Crew must be active. Always checked -- there is no "unspecified" case."""

    rule_id = STATUS_ID

    def evaluate(self, ctx: CoverContext) -> RuleVerdict | None:
        crew = ctx.crew
        available = crew.status == "active"
        return RuleVerdict(
            rule_id=STATUS_ID,
            verdict="pass" if available else "breach",
            message=(
                "active and available"
                if available
                else f"{STATUS_ID}: {ctx.crew_id} is on {crew.status}, not available for duty"
            ),
            subject_crew_id=ctx.crew_id,
            arithmetic=(ArithmeticStep("Status", "crew.status", crew.status),),
        )


class SeatRankRule:
    """The candidate's rank must match the seat, when the caller named one.

    Silent by design when ``required_role`` is ``None`` -- "not specified" is
    not the same claim as "matches", and every existing caller that never
    named a seat keeps its exact prior behaviour (this returns ``None`` and
    the engine skips it entirely, same as if it were never run).
    """

    rule_id = RANK_ID

    def evaluate(self, ctx: CoverContext) -> RuleVerdict | None:
        if ctx.required_role is None:
            return None
        crew = ctx.crew
        matches = crew.rank == ctx.required_role
        return RuleVerdict(
            rule_id=RANK_ID,
            verdict="pass" if matches else "breach",
            message=(
                f"holds {ctx.required_role} rank"
                if matches
                else f"{RANK_ID}: {ctx.crew_id} is a {crew.rank}, not a {ctx.required_role} -- "
                f"cannot legally hold the {ctx.required_role}'s seat regardless of duty-hour, "
                f"rest or rating headroom"
            ),
            subject_crew_id=ctx.crew_id,
            arithmetic=(
                ArithmeticStep("Seat requires", "required_role", ctx.required_role),
                ArithmeticStep("Crew holds", "crew.rank", crew.rank),
            ),
        )
