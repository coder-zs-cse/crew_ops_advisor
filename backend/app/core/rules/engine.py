"""The rule engine.

Evaluation order is not arbitrary -- it reproduces the reference implementation
that produced the dataset's answer keys, so that our exclusion reasons come out
in the same order and wording:

    1. CONSTRAINT-STATUS            (short-circuits: not active -> only reason)
    2. CONSTRAINT-RANK              (short-circuits: only when a required_role
                                      was given -- see ``CoverContext``)
    3. RULE-QUAL-05                 (short-circuits: no rating -> only reason)
    4. per covered day, in order:   RULE-CERT-06 then RULE-FDP-01
    5. RULE-REST-04                 (walk the merged timeline)
    6. overlap / double-booking     (same walk)
    7. RULE-DUTY-02                 (per covered day)
    8. RULE-FLT-03                  (hard gate -- see flt03.py)

RULE-BASE-07 and the reserve on-call window are gates applied *before* this, in
``candidates.py``, because they determine the delay that this engine then works
against. CONSTRAINT-STATUS and CONSTRAINT-RANK are *also* applied redundantly
by ``candidates.py``'s enumeration path before it ever builds a ``CoverContext``
-- they live here too so that ``check_legality`` / ``simulate_assignment``, which
call this engine directly on a single named crew member with no upstream
filter, cannot report a leave-status or wrong-rank candidate as legal. See
``docs/LIMITATIONS.md`` for the reproduction that motivated this.
"""

from __future__ import annotations

from ..models import LegalityReport, RuleVerdict
from .base import CoverContext
from .cert06 import CertificationRule
from .duty02 import SevenDayDutyRule
from .fdp01 import FlightDutyPeriodRule
from .flt03 import TwentyEightDayFlightRule
from .precondition import AvailabilityRule, SeatRankRule
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

    def __init__(self) -> None:
        self.availability = AvailabilityRule()
        self.seat_rank = SeatRankRule()
        self.qual = AircraftRatingRule()
        self.cert = CertificationRule()
        self.fdp = FlightDutyPeriodRule()
        self.rest = MinimumRestRule()
        self.overlap = NoOverlapRule()
        self.duty = SevenDayDutyRule()
        self.flight = TwentyEightDayFlightRule()

    def evaluate_cover(self, ctx: CoverContext) -> LegalityReport:
        verdicts: list[RuleVerdict] = []

        # Preconditions: neither is one of the seven numbered rules (like
        # RULE-REST-04's overlap check, they're CONSTRAINT-* ids), but each one
        # makes every other check moot, so each short-circuits exactly like
        # RULE-QUAL-05 does below.
        availability = self.availability.evaluate(ctx)
        if availability is not None:
            verdicts.append(availability)
            if availability.is_breach:
                return LegalityReport(
                    crew_id=ctx.crew_id,
                    legal=False,
                    verdicts=tuple(verdicts),
                    issues=(availability.message,),
                )

        seat_rank = self.seat_rank.evaluate(ctx)
        if seat_rank is not None:
            verdicts.append(seat_rank)
            if seat_rank.is_breach:
                return LegalityReport(
                    crew_id=ctx.crew_id,
                    legal=False,
                    verdicts=tuple(verdicts),
                    issues=(seat_rank.message,),
                )

        qual = self.qual.evaluate(ctx)
        verdicts.append(qual)
        if qual.is_breach:
            # Short-circuit, matching the reference implementation.
            return LegalityReport(
                crew_id=ctx.crew_id,
                legal=False,
                verdicts=tuple(verdicts),
                issues=tuple(v.message for v in verdicts if v.is_breach),
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
    required_role: str | None = None,
    engine: RuleEngine | None = None,
) -> LegalityReport:
    """Convenience wrapper mirroring the reference ``check_cover`` signature.

    ``required_role`` is optional and defaults to ``None`` (no seat/rank check)
    so every existing caller that never specified a seat keeps its exact prior
    behaviour. Pass it when the question names which seat is being covered
    (e.g. "can this First Officer cover the *Captain's* seat") -- callers that
    already filter by rank upstream (``candidates.py``'s enumeration) may pass
    it too, redundantly and harmlessly, for consistent messaging.
    """
    ctx = CoverContext(
        world=world,
        crew_id=crew_id,
        cover_days=tuple(cover_days),
        exclude_pairing=exclude_pairing,
        delay_hours=delay_hours,
        required_role=required_role,
    )
    return (engine or ENGINE).evaluate_cover(ctx)
