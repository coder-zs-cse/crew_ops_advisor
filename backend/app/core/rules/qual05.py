"""RULE-QUAL-05 -- Crew must hold a valid rating for the assigned aircraft type.

This rule short-circuits. When a candidate is not type-rated the generator
returns that as the *only* reason, without running any other check, and the
answer keys reflect that ("C-2091: RULE-QUAL-05: no A320 rating" and nothing
else). We preserve the short-circuit so exclusion reasons match, and because it
is also the honest thing to report: an unrated pilot's duty hours are moot.
"""

from __future__ import annotations

from ..models import ArithmeticStep, RuleVerdict
from .base import CoverContext

RULE_ID = "RULE-QUAL-05"


class AircraftRatingRule:
    rule_id = RULE_ID
    short_circuits = True

    def evaluate(self, ctx: CoverContext) -> RuleVerdict:
        actype = ctx.aircraft_type
        rated = actype in ctx.crew.ratings
        return RuleVerdict(
            rule_id=RULE_ID,
            verdict="pass" if rated else "breach",
            message=(
                f"holds {actype} rating"
                if rated
                else f"RULE-QUAL-05: no {actype} rating"
            ),
            subject_crew_id=ctx.crew_id,
            arithmetic=(
                ArithmeticStep("Aircraft type required", "first leg of the cover", actype),
                ArithmeticStep("Ratings held", "crew.ratings", ", ".join(ctx.crew.ratings) or "none"),
            ),
        )
