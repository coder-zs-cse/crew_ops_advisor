"""RULE-DUTY-02 -- Max 60 duty hours in any 7 consecutive calendar days.

The window is calendar-day based and inclusive of the duty date. For a
*replacement* candidate the arithmetic is:

    total = (history + roster duties in [d-6, d])
          - (duties of the pairing being replaced, in that window)
          + (cover duties on dates <= d)

The subtraction matters: a candidate already rostered on the pairing they are
taking over must not be double-counted. The final ``+ cover`` term uses the
*undelayed* duty length, exactly as the generator does -- a positioning delay
shifts a duty in time but does not lengthen it for window purposes.
"""

from __future__ import annotations

from datetime import timedelta

from ..duty import duty_length
from ..models import ArithmeticStep, RuleVerdict
from ..rule_params import rule_param
from ..timeutil import EPS, fmt_hm
from ..windows import window_sum
from .base import CoverContext

RULE_ID = "RULE-DUTY-02"
#: Sample-dataset fallbacks only. See ``rule_params.py``.
MAX_DUTY_HOURS = 60.0
WINDOW_DAYS = 7


class SevenDayDutyRule:
    rule_id = RULE_ID

    def evaluate(self, ctx: CoverContext) -> list[RuleVerdict]:
        max_duty_hours = rule_param(ctx.world, RULE_ID, "max_duty_hours", MAX_DUTY_HOURS)
        window_days = int(rule_param(ctx.world, RULE_ID, "window_days", WINDOW_DAYS))

        out: list[RuleVerdict] = []
        for day in ctx.cover_days:
            d = day.date

            base = window_sum(ctx.world, ctx.crew_id, d, window_days)
            removed = 0.0
            if ctx.exclude_pairing is not None:
                window_start = d - timedelta(days=window_days - 1)
                for seg in ctx.world.week_duties(ctx.crew_id):
                    if seg.label == ctx.exclude_pairing and window_start <= seg.date <= d:
                        removed += seg.duty_hours
            base = round(base - removed, 2)

            added = round(sum(duty_length(x) for x in ctx.cover_days if x.date <= d), 2)
            total = round(base + added, 2)

            breached = total > max_duty_hours + EPS
            excess = round(total - max_duty_hours, 2)

            steps = [
                ArithmeticStep(
                    "Existing duty in window",
                    f"{window_days} calendar days {(d - timedelta(days=window_days - 1)).isoformat()} .. {d.isoformat()}",
                    base,
                    "h",
                ),
            ]
            if removed:
                steps.append(
                    ArithmeticStep(
                        "Less pairing being replaced",
                        f"-{removed}h from {ctx.exclude_pairing}",
                        -removed,
                        "h",
                    )
                )
            steps.append(
                ArithmeticStep("Plus proposed cover", f"+{added}h through {d.isoformat()}", added, "h")
            )
            steps.append(
                ArithmeticStep(
                    "Total vs limit", f"{base} + {added} = {total} vs {max_duty_hours}", total, "h"
                )
            )

            out.append(
                RuleVerdict(
                    rule_id=RULE_ID,
                    verdict="breach" if breached else "pass",
                    message=(
                        f"RULE-DUTY-02: would exceed {max_duty_hours}h/{window_days}d by {fmt_hm(excess)} "
                        f"on {d} (total {total}h)"
                        if breached
                        else f"{window_days}-day duty {total}h of {max_duty_hours}h "
                        f"({round(max_duty_hours - total, 2)}h headroom) on {d}"
                    ),
                    subject_crew_id=ctx.crew_id,
                    subject_date=d,
                    actual=total,
                    limit=max_duty_hours,
                    margin=round(max_duty_hours - total, 2),
                    arithmetic=tuple(steps),
                )
            )
        return out
