"""RULE-FLT-03 -- Max 100 flight (block) hours in any 28 consecutive calendar days.

KNOWN DATASET DISCREPANCY -- read before "fixing" this.

The dataset generator lists RULE-FLT-03 in every option's ``rules_checked``
array but its ``check_cover()`` never evaluates it. Two consequences:

1. Cover segments carry ``flight_hours = 0.0``, so a simulated assignment adds
   no block hours to the 28-day window at all.
2. If we enforced the rule as a hard gate we could exclude a candidate that the
   shipped answer keys list as legal.

So we compute it honestly and report it, but at ``advisory`` severity: it never
removes a candidate from the eligible list. ``STRICT`` flips it to a hard gate
for anyone who wants to see the difference; the conformance harness runs both
and reports whether the two disagree.
"""

from __future__ import annotations

from datetime import timedelta

from ..duty import day_block_hours
from ..models import ArithmeticStep, RuleVerdict
from ..rule_params import rule_param
from ..timeutil import EPS
from ..windows import FLIGHT, window_sum
from .base import CoverContext

RULE_ID = "RULE-FLT-03"
#: Sample-dataset fallbacks only. See ``rule_params.py``.
MAX_FLIGHT_HOURS = 100.0
WINDOW_DAYS = 28

#: Set True to make the 28-day block limit a hard exclusion.
STRICT = False


class TwentyEightDayFlightRule:
    rule_id = RULE_ID

    def __init__(self, strict: bool = STRICT) -> None:
        self.strict = strict

    def evaluate(self, ctx: CoverContext) -> list[RuleVerdict]:
        max_flight_hours = rule_param(ctx.world, RULE_ID, "max_flight_hours", MAX_FLIGHT_HOURS)
        window_days = int(rule_param(ctx.world, RULE_ID, "window_days", WINDOW_DAYS))

        out: list[RuleVerdict] = []
        for day in ctx.cover_days:
            d = day.date

            base = window_sum(ctx.world, ctx.crew_id, d, window_days, FLIGHT)
            removed = 0.0
            if ctx.exclude_pairing is not None:
                window_start = d - timedelta(days=window_days - 1)
                for seg in ctx.world.week_duties(ctx.crew_id):
                    if seg.label == ctx.exclude_pairing and window_start <= seg.date <= d:
                        removed += seg.flight_hours
            base = round(base - removed, 2)

            # The block hours the candidate would actually fly on the cover.
            added = round(
                sum(day_block_hours(ctx.world, x) for x in ctx.cover_days if x.date <= d), 2
            )
            total = round(base + added, 2)

            over = total > max_flight_hours + EPS
            verdict = ("breach" if self.strict else "advisory") if over else "pass"

            out.append(
                RuleVerdict(
                    rule_id=RULE_ID,
                    verdict=verdict,
                    message=(
                        f"RULE-FLT-03: would reach {total}h block in {window_days} days vs "
                        f"{max_flight_hours}h limit on {d} "
                        "(advisory: the reference ruleset does not gate on this)"
                        if over
                        else f"{window_days}-day block {total}h of {max_flight_hours}h "
                        f"({round(max_flight_hours - total, 2)}h headroom) on {d}"
                    ),
                    subject_crew_id=ctx.crew_id,
                    subject_date=d,
                    actual=total,
                    limit=max_flight_hours,
                    margin=round(max_flight_hours - total, 2),
                    arithmetic=(
                        ArithmeticStep(
                            "Existing block in window",
                            f"{window_days} calendar days ending {d.isoformat()}",
                            base,
                            "h",
                        ),
                        ArithmeticStep("Plus cover block hours", f"+{added}h", added, "h"),
                        ArithmeticStep(
                            "Total vs limit", f"{total} vs {max_flight_hours}", total, "h"
                        ),
                    ),
                )
            )
        return out
