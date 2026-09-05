"""RULE-FLT-03 -- Max 100 flight (block) hours in any 28 consecutive calendar days.

Hard gate. History, for anyone reading this after the fact:

The dataset generator (`generate.py`) lists RULE-FLT-03 in every option's
``rules_checked`` array but its own ``check_cover()`` never evaluates it, so no
scenario or question in the shipped answer keys (`scenarios.json`,
`questions.json`) ever contains a FLT-03 breach. For a while this module
computed the real 28-day total honestly but reported it at ``advisory``
severity so it could never exclude a candidate -- deliberately matching the
generator's gap rather than fixing it, on the theory that enforcing the limit
might exclude a candidate the shipped answer keys called legal.

That was the wrong call to make silently. Re-running the full answer-key suite
(`tests/conformance/test_answer_keys.py`) with this rule enforced as a hard
gate shows every one of the 6 shipped scenarios and 38 questions still passes
-- none of them ever came close to 100h/28d, so the "discrepancy" never
actually bit. What it produced instead was a live inconsistency: this rule
would say "legal" for a genuine >100h breach while `simulate_duty_window` (a
separate, engine-free code path answering the same question) said "breach"
for the identical arithmetic. Two tools, one fact, two verdicts -- worse than
either choice made consistently. See `generalization_questions.json`'s GQ16
for the reproduction, and ``docs/LIMITATIONS.md`` §1.1 for the fuller writeup.

RULE-FLT-03 is now enforced exactly like the other six: a breach here makes
the candidate illegal, full stop. There is no advisory mode to flip back on --
that toggle is the mistake being corrected, not a feature to keep around.
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


class TwentyEightDayFlightRule:
    rule_id = RULE_ID

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
            verdict = "breach" if over else "pass"

            out.append(
                RuleVerdict(
                    rule_id=RULE_ID,
                    verdict=verdict,
                    message=(
                        f"RULE-FLT-03: would exceed {max_flight_hours}h/{window_days}d by "
                        f"{round(total - max_flight_hours, 2)}h on {d} (total {total}h)"
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
