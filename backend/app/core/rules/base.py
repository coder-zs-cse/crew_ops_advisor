"""Rule context and protocol.

Every rule is a small class with one job and its own arithmetic trace. Adding a
regulator means adding a module here; nothing else in the system changes.

The generator's ``check_cover`` produced reason strings in a specific order and
a specific wording. Those strings are part of the answer keys, so each rule
emits its message in exactly that form via ``RuleVerdict.message``. The richer
structured fields (actual/limit/margin/arithmetic) are ours, for the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from typing import Protocol

from ..models import DutySegment, PairingDay, RuleVerdict
from ..timeutil import hrs
from ..world import World


@dataclass
class CoverContext:
    """Everything a rule needs to judge one candidate against one cover."""

    world: World
    crew_id: str
    cover_days: tuple[PairingDay, ...]
    exclude_pairing: str | None = None
    delay_hours: float = 0.0
    #: The rank the seat being covered requires, when the caller knows it (e.g.
    #: the pairing's own incumbent, or a role named explicitly in the
    #: question). ``None`` means "not specified" -- the seat/rank check is
    #: skipped entirely, not assumed to pass silently.
    required_role: str | None = None

    @cached_property
    def crew(self):
        return self.world.crew_member(self.crew_id)

    @cached_property
    def aircraft_type(self) -> str:
        return self.world.flight(self.cover_days[0].flight_ids[0]).aircraft_type

    @cached_property
    def departure_station(self) -> str:
        return self.world.flight(self.cover_days[0].flight_ids[0]).dep_station

    @cached_property
    def cover_segments(self) -> list[DutySegment]:
        """The proposed duties, shifted by any positioning delay.

        Flight hours are deliberately 0.0 on cover segments: the generator does
        the same, so the 28-day block-hour window is unaffected by a simulated
        assignment. See RULE-FLT-03's note about this.
        """
        from ..duty import shifted

        out = []
        for day in self.cover_days:
            report, release = shifted(day, self.delay_hours)
            out.append(
                DutySegment(
                    date=day.date,
                    report_utc=report,
                    release_utc=release,
                    duty_hours=hrs(release - report),
                    flight_hours=0.0,
                    label="COVER",
                )
            )
        return out

    @cached_property
    def timeline(self) -> list[DutySegment]:
        from ..windows import merged_timeline

        return merged_timeline(
            self.world,
            self.crew_id,
            exclude_pairing=self.exclude_pairing,
            extra=self.cover_segments,
        )

    @property
    def cover_dates(self) -> list[date]:
        return [d.date for d in self.cover_days]


class PerDayRule(Protocol):
    """A rule evaluated once per covered duty day."""

    rule_id: str

    def evaluate_day(self, ctx: CoverContext, day: PairingDay, index: int) -> RuleVerdict | None:
        ...


class TimelineRule(Protocol):
    """A rule evaluated across the merged duty timeline."""

    rule_id: str

    def evaluate(self, ctx: CoverContext) -> list[RuleVerdict]:
        ...
