"""RULE-FDP-01 -- Max flight duty period 13h, reduced 0.5h per sector beyond the 2nd."""

from __future__ import annotations

from ..duty import fdp_limit, shifted
from ..models import ArithmeticStep, PairingDay, RuleVerdict
from ..timeutil import EPS, hrs
from .base import CoverContext

RULE_ID = "RULE-FDP-01"


class FlightDutyPeriodRule:
    rule_id = RULE_ID

    def evaluate_day(self, ctx: CoverContext, day: PairingDay, index: int) -> RuleVerdict:
        report, release = shifted(day, ctx.delay_hours)
        actual = hrs(release - report)
        sectors = day.sectors
        limit = fdp_limit(sectors)

        steps = [
            ArithmeticStep(
                "FDP limit",
                f"13.0 - 0.5 x max(0, {sectors} - 2)",
                limit,
                "h",
            ),
            ArithmeticStep(
                "Duty period",
                f"{release:%H:%M}Z release - {report:%H:%M}Z report",
                actual,
                "h",
            ),
        ]
        if ctx.delay_hours:
            steps.insert(
                0,
                ArithmeticStep(
                    "Applied delay",
                    f"duty shifted by {ctx.delay_hours}h",
                    ctx.delay_hours,
                    "h",
                ),
            )

        breached = actual > limit + EPS
        return RuleVerdict(
            rule_id=RULE_ID,
            verdict="breach" if breached else "pass",
            message=(
                f"RULE-FDP-01: FDP {actual}h > {limit}h limit ({sectors} sectors)"
                if breached
                else f"FDP {actual}h within {limit}h limit ({sectors} sectors)"
            ),
            subject_crew_id=ctx.crew_id,
            subject_date=day.date,
            actual=actual,
            limit=limit,
            margin=round(limit - actual, 2),
            arithmetic=tuple(steps),
        )


def check_fdp(sectors: int, duty_hours: float) -> tuple[bool, float]:
    """Standalone helper for the /rules calculator and delay simulations."""
    limit = fdp_limit(sectors)
    return duty_hours <= limit + EPS, limit
