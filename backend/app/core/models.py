"""Domain value objects.

Plain dataclasses. No ORM, no pydantic, no framework imports -- this module and
everything else under ``app.core`` must stay importable with nothing but the
standard library (enforced by tests/test_core_purity.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

Role = str  # "Captain" | "First Officer" | "Senior Cabin Crew" | "Cabin Crew"
PILOT_ROLES = frozenset({"Captain", "First Officer"})
CABIN_ROLES = frozenset({"Senior Cabin Crew", "Cabin Crew"})


@dataclass(frozen=True, slots=True)
class Flight:
    flight_id: str
    flight_no: str
    date: date
    dep_station: str
    arr_station: str
    dep_utc: datetime
    arr_utc: datetime
    block_hours: float
    aircraft: str
    aircraft_type: str
    seats: int


@dataclass(frozen=True, slots=True)
class Crew:
    crew_id: str
    name: str
    rank: Role
    base: str
    ratings: tuple[str, ...]
    seniority: int
    reachability_minutes: int
    status: str  # active | leave | training

    @property
    def is_pilot(self) -> bool:
        return self.rank in PILOT_ROLES


@dataclass(frozen=True, slots=True)
class PairingDay:
    pairing_id: str
    day_index: int
    date: date
    flight_ids: tuple[str, ...]
    report_utc: datetime
    release_utc: datetime

    @property
    def sectors(self) -> int:
        return len(self.flight_ids)


@dataclass(frozen=True, slots=True)
class Pairing:
    pairing_id: str
    aircraft: str
    days: tuple[PairingDay, ...]
    crew: tuple[tuple[str, Role], ...]  # (crew_id, role)

    def role_of(self, crew_id: str) -> Role | None:
        for cid, role in self.crew:
            if cid == crew_id:
                return role
        return None

    @property
    def total_sectors(self) -> int:
        return sum(d.sectors for d in self.days)


@dataclass(frozen=True, slots=True)
class DutySegment:
    """One duty period on a crew member's timeline.

    ``label`` is the pairing id for rostered work, or ``COVER`` for a proposed
    assignment being simulated. The generator's tuple layout was
    ``(date, report, release, duty_hours, flight_hours, pairing_id)``; this is
    the same thing with names.
    """

    date: date
    report_utc: datetime
    release_utc: datetime
    duty_hours: float
    flight_hours: float
    label: str

    @property
    def is_cover(self) -> bool:
        return self.label == "COVER"


@dataclass(frozen=True, slots=True)
class DutyClock:
    crew_id: str
    as_of_utc: datetime
    duty_hours_7d: float
    flight_hours_28d: float
    last_rest_ended: datetime | None
    daily_history: dict[date, tuple[float, float]]  # date -> (duty_h, flight_h)


@dataclass(frozen=True, slots=True)
class Reserve:
    crew_id: str
    base: str
    dates: tuple[date, ...]
    oncall_start: str  # "HH:MM"
    oncall_end: str


@dataclass(frozen=True, slots=True)
class Certification:
    crew_id: str
    cert_type: str
    valid_from: date
    valid_to: date


@dataclass(frozen=True, slots=True)
class Rule:
    rule_id: str
    text: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Costs:
    currency: str
    reserve_callout_pilot: int
    reserve_callout_cabin: int
    dayoff_callout_pilot: int
    dayoff_callout_cabin: int
    deadhead_positioning: int
    delay_cost_per_duty_hour: int
    cancellation_per_flight: int
    hotel_overnight: int

    def callout(self, *, is_reserve: bool, is_pilot: bool) -> int:
        if is_reserve:
            return self.reserve_callout_pilot if is_pilot else self.reserve_callout_cabin
        return self.dayoff_callout_pilot if is_pilot else self.dayoff_callout_cabin


@dataclass(frozen=True, slots=True)
class RiskSignal:
    crew_id: str
    as_of_utc: datetime
    disruption_risk_score: float
    drivers: tuple[str, ...]


# --------------------------------------------------------------------------
# Rule evaluation results
# --------------------------------------------------------------------------

Verdict = Literal["pass", "breach", "advisory", "not_applicable"]


@dataclass(frozen=True, slots=True)
class ArithmeticStep:
    """One line of shown work, so a controller can audit the number."""

    label: str
    expression: str
    value: float | str
    unit: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "expression": self.expression,
            "value": self.value,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class RuleVerdict:
    rule_id: str
    verdict: Verdict
    message: str
    subject_crew_id: str | None = None
    subject_date: date | None = None
    actual: float | None = None
    limit: float | None = None
    margin: float | None = None  # positive = headroom, negative = over
    arithmetic: tuple[ArithmeticStep, ...] = ()
    #: Sub-classification for a "gap between two duties" verdict (REST-04's own
    #: "rest" vs "downstream" distinction, or "overlap" for CONSTRAINT-OVERLAP).
    #: A structured field so the UI can pick a visual and a label without
    #: pattern-matching the message string. None for rules with no such shape.
    conflict_kind: str | None = None

    @property
    def passed(self) -> bool:
        return self.verdict in ("pass", "not_applicable", "advisory")

    @property
    def is_breach(self) -> bool:
        return self.verdict == "breach"

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "verdict": self.verdict,
            "message": self.message,
            "crew_id": self.subject_crew_id,
            "date": self.subject_date.isoformat() if self.subject_date else None,
            "actual": self.actual,
            "limit": self.limit,
            "margin": self.margin,
            "arithmetic": [step.as_dict() for step in self.arithmetic],
            "conflict_kind": self.conflict_kind,
        }


@dataclass(frozen=True, slots=True)
class LegalityReport:
    """Outcome of evaluating a candidate against a proposed cover."""

    crew_id: str
    legal: bool
    verdicts: tuple[RuleVerdict, ...]
    issues: tuple[str, ...]  # generator-format reason strings, in generator order

    @property
    def breaches(self) -> tuple[RuleVerdict, ...]:
        return tuple(v for v in self.verdicts if v.is_breach)

    def as_dict(self) -> dict[str, Any]:
        return {
            "crew_id": self.crew_id,
            "legal": self.legal,
            "issues": list(self.issues),
            "verdicts": [v.as_dict() for v in self.verdicts],
        }
