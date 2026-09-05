"""RULE-FDP-01 -- Max flight duty period 13h, reduced 0.5h per sector beyond the 2nd."""

from __future__ import annotations

from ..duty import fdp_limit, shifted
from ..models import ArithmeticStep, PairingDay, RuleVerdict
from ..rule_params import rule_param
from ..timeutil import EPS, hrs
from ..world import World
from .base import CoverContext

RULE_ID = "RULE-FDP-01"


def _fdp_formula(world: World | None, sectors: int) -> str:
    """The formula string shown in the arithmetic trace, from this dataset's own params."""
    base = rule_param(world, RULE_ID, "base_fdp_hours", 13.0)
    free = rule_param(world, RULE_ID, "free_sectors", 2)
    reduction = rule_param(world, RULE_ID, "reduction_per_extra_sector_hours", 0.5)
    return f"{base} - {reduction} x max(0, {sectors} - {free})"


class FlightDutyPeriodRule:
    rule_id = RULE_ID

    def evaluate_day(self, ctx: CoverContext, day: PairingDay, index: int) -> RuleVerdict:
        report, release = shifted(day, ctx.delay_hours)
        actual = hrs(release - report)
        sectors = day.sectors
        limit = fdp_limit(sectors, ctx.world)

        steps = [
            ArithmeticStep(
                "FDP limit",
                _fdp_formula(ctx.world, sectors),
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


def check_fdp(sectors: int, duty_hours: float, world: World | None = None) -> tuple[bool, float]:
    """Standalone helper for the /rules calculator and delay simulations."""
    limit = fdp_limit(sectors, world)
    return duty_hours <= limit + EPS, limit
