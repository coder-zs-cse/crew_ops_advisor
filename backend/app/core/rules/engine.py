"""The rule engine.

Evaluation order is not arbitrary -- it reproduces the reference implementation
that produced the dataset's answer keys, so that our exclusion reasons come out
in the same order and wording:

    1. RULE-QUAL-05                 (short-circuits: no rating -> only reason)
    2. per covered day, in order:   RULE-CERT-06 then RULE-FDP-01
    3. RULE-REST-04                 (walk the merged timeline)
    4. overlap / double-booking     (same walk)
    5. RULE-DUTY-02                 (per covered day)
    6. RULE-FLT-03                  (advisory only -- see flt03.py)

RULE-BASE-07 and the reserve on-call window are gates applied *before* this, in
``candidates.py``, because they determine the delay that this engine then works
against.
"""

from __future__ import annotations

from ..models import LegalityReport, RuleVerdict
from .base import CoverContext
from .cert06 import CertificationRule
from .duty02 import SevenDayDutyRule
from .fdp01 import FlightDutyPeriodRule
from .flt03 import TwentyEightDayFlightRule
from .qual05 import AircraftRatingRule
from .rest04 import MinimumRestRule, NoOverlapRule

ALL_RULE_IDS = (
    "RULE-FDP-01",
    "RULE-DUTY-02",
    "RULE-FLT-03",
    "RULE-REST-04",
    "RULE-QUAL-05",
    "RULE-CERT-06",
    "RULE-BASE-07",
)


class RuleEngine:
    """Stateless. Construct once, reuse everywhere."""

    def __init__(self, *, strict_flight_hours: bool = False) -> None:
        self.qual = AircraftRatingRule()
        self.cert = CertificationRule()
        self.fdp = FlightDutyPeriodRule()
        self.rest = MinimumRestRule()
        self.overlap = NoOverlapRule()
        self.duty = SevenDayDutyRule()
        self.flight = TwentyEightDayFlightRule(strict=strict_flight_hours)

    def evaluate_cover(self, ctx: CoverContext) -> LegalityReport:
        verdicts: list[RuleVerdict] = []

        qual = self.qual.evaluate(ctx)
        verdicts.append(qual)
        if qual.is_breach:
            # Short-circuit, matching the reference implementation.
            return LegalityReport(
                crew_id=ctx.crew_id,
                legal=False,
                verdicts=tuple(verdicts),
                issues=(qual.message,),
            )

        for index, day in enumerate(ctx.cover_days):
            verdicts.append(self.cert.evaluate_day(ctx, day, index))
            verdicts.append(self.fdp.evaluate_day(ctx, day, index))

        verdicts.extend(self.rest.evaluate(ctx))
        verdicts.extend(self.overlap.evaluate(ctx))
        verdicts.extend(self.duty.evaluate(ctx))
        verdicts.extend(self.flight.evaluate(ctx))

        issues = tuple(v.message for v in verdicts if v.is_breach)
        return LegalityReport(
            crew_id=ctx.crew_id,
            legal=not issues,
            verdicts=tuple(verdicts),
            issues=issues,
        )


#: Shared default instance -- the engine holds no state.
ENGINE = RuleEngine()


def check_cover(
    world,
    crew_id: str,
    cover_days,
    *,
    exclude_pairing: str | None = None,
    delay_hours: float = 0.0,
    engine: RuleEngine | None = None,
) -> LegalityReport:
    """Convenience wrapper mirroring the reference ``check_cover`` signature."""
    ctx = CoverContext(
        world=world,
        crew_id=crew_id,
        cover_days=tuple(cover_days),
        exclude_pairing=exclude_pairing,
        delay_hours=delay_hours,
    )
    return (engine or ENGINE).evaluate_cover(ctx)
