"""RULE-REST-04 -- Min 12h rest between release and next report.

Evaluated over the merged timeline (rostered duties minus the replaced pairing,
plus the proposed cover), sorted by report time. Two distinct findings come out
of the same walk and the answer keys distinguish them:

* ``rest conflict``       -- the cover itself sits too close to another duty
* ``downstream conflict`` -- the cover is fine today, but it eats the rest
                             before an already-rostered duty later in the week
* ``double-booked``       -- the duties actually overlap

The downstream case is the one a controller misses by eye, and it is why
"consequence blindness" is in the problem statement.
"""

from __future__ import annotations

from ..models import ArithmeticStep, RuleVerdict
from ..rule_params import rule_param
from ..timeutil import EPS, hrs
from .base import CoverContext

RULE_ID = "RULE-REST-04"
#: Sample-dataset fallback only. See ``rule_params.py``.
MIN_REST_HOURS = 12.0
OVERLAP_ID = "CONSTRAINT-OVERLAP"


class MinimumRestRule:
    rule_id = RULE_ID

    def evaluate(self, ctx: CoverContext) -> list[RuleVerdict]:
        min_rest_hours = rule_param(ctx.world, RULE_ID, "min_rest_hours", MIN_REST_HOURS)

        out: list[RuleVerdict] = []
        timeline = ctx.timeline
        for prev, nxt in zip(timeline, timeline[1:]):
            rest = hrs(nxt.report_utc - prev.release_utc)
            if rest >= min_rest_hours - EPS:
                continue
            tag = "downstream" if (not nxt.is_cover and prev.is_cover) else "rest"
            out.append(
                RuleVerdict(
                    rule_id=RULE_ID,
                    verdict="breach",
                    message=(
                        f"RULE-REST-04: only {rest}h rest before {nxt.label} "
                        f"on {nxt.date} ({tag} conflict)"
                    ),
                    subject_crew_id=ctx.crew_id,
                    subject_date=nxt.date,
                    actual=rest,
                    limit=min_rest_hours,
                    margin=round(rest - min_rest_hours, 2),
                    arithmetic=(
                        ArithmeticStep(
                            "Previous release",
                            f"{prev.label} on {prev.date}",
                            prev.release_utc.strftime("%Y-%m-%dT%H:%MZ"),
                        ),
                        ArithmeticStep(
                            "Next report",
                            f"{nxt.label} on {nxt.date}",
                            nxt.report_utc.strftime("%Y-%m-%dT%H:%MZ"),
                        ),
                        ArithmeticStep("Rest available", "report - release", rest, "h"),
                        ArithmeticStep("Required", "RULE-REST-04", min_rest_hours, "h"),
                    ),
                )
            )
        return out


class NoOverlapRule:
    """Not one of the seven, but the generator reports it alongside them."""

    rule_id = OVERLAP_ID

    def evaluate(self, ctx: CoverContext) -> list[RuleVerdict]:
        out: list[RuleVerdict] = []
        timeline = ctx.timeline
        for prev, nxt in zip(timeline, timeline[1:]):
            if nxt.report_utc < prev.release_utc:
                out.append(
                    RuleVerdict(
                        rule_id=OVERLAP_ID,
                        verdict="breach",
                        message=f"double-booked: {prev.label} overlaps {nxt.label} on {nxt.date}",
                        subject_crew_id=ctx.crew_id,
                        subject_date=nxt.date,
                        actual=hrs(prev.release_utc - nxt.report_utc),
                        limit=0.0,
                        arithmetic=(
                            ArithmeticStep(
                                "Overlap",
                                f"{prev.label} releases {prev.release_utc:%H:%M}Z, "
                                f"{nxt.label} reports {nxt.report_utc:%H:%M}Z",
                                hrs(prev.release_utc - nxt.report_utc),
                                "h",
                            ),
                        ),
                    )
                )
        return out


def rest_between(release_utc, report_utc) -> tuple[float, bool]:
    rest = hrs(report_utc - release_utc)
    return rest, rest >= MIN_REST_HOURS - EPS
