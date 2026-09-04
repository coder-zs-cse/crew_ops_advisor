"""RULE-BASE-07 -- Reserve callout from own base only; otherwise deadhead.

This rule is a gate applied *before* the legality walk, because whether a
candidate needs positioning changes the report time, which in turn changes both
the reserve on-call window test and every downstream duty calculation.

The positioning table itself lives in ``core/positioning.py`` -- it is data, not
logic, so adding a second city pair does not touch this file.
"""

from __future__ import annotations

from ..models import ArithmeticStep, RuleVerdict
from ..positioning import PositioningOption, find_positioning
from .base import CoverContext

RULE_ID = "RULE-BASE-07"


class BaseAndPositioningRule:
    rule_id = RULE_ID

    def evaluate(self, ctx: CoverContext) -> tuple[RuleVerdict, PositioningOption | None]:
        crew = ctx.crew
        needed = ctx.departure_station

        if crew.base == needed:
            return (
                RuleVerdict(
                    rule_id=RULE_ID,
                    verdict="pass",
                    message=f"based at {needed} - no positioning required",
                    subject_crew_id=ctx.crew_id,
                    arithmetic=(
                        ArithmeticStep("Crew base", "crew.base", crew.base),
                        ArithmeticStep("Duty departs", "first leg", needed),
                    ),
                ),
                None,
            )

        first_day = ctx.cover_days[0]
        option = find_positioning(
            ctx.world,
            from_station=crew.base,
            to_station=needed,
            on=first_day.date,
            required_departure=ctx.world.flight(first_day.flight_ids[0]).dep_utc,
        )

        if option is None:
            return (
                RuleVerdict(
                    rule_id=RULE_ID,
                    verdict="breach",
                    message="RULE-BASE-07: no same-day positioning flight from base",
                    subject_crew_id=ctx.crew_id,
                    subject_date=first_day.date,
                    arithmetic=(
                        ArithmeticStep("Crew base", "crew.base", crew.base),
                        ArithmeticStep("Duty departs", "first leg", needed),
                    ),
                ),
                None,
            )

        return (
            RuleVerdict(
                rule_id=RULE_ID,
                verdict="pass",
                message=(
                    f"positioning {crew.base}->{needed} on {option.flight_no}, "
                    f"first departure delayed ~{option.delay_hours}h"
                ),
                subject_crew_id=ctx.crew_id,
                subject_date=first_day.date,
                actual=option.delay_hours,
                arithmetic=(
                    ArithmeticStep("Positioning flight", option.flight_no, option.arrival.strftime("%H:%MZ")),
                    ArithmeticStep("New report", "arrival + 15 min transit", option.new_report.strftime("%H:%MZ")),
                    ArithmeticStep("Delay to first departure", "new report + 60 min vs schedule", option.delay_hours, "h"),
                ),
            ),
            option,
        )
