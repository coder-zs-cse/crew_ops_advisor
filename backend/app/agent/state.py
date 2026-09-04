"""Agent state.

The fact ledger and the rule-evaluation log live on the tracer, not here --
state carries the *decisions* (intent, entities, plan) and the *outputs*
(structured answer, narration, verification). Keeping them apart means a run
can be replayed from its plan without replaying its narration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

Tier = Literal[1, 2, 3]


@dataclass
class Entities:
    """Canonical identifiers, every one validated against the world."""

    crew_ids: list[str] = field(default_factory=list)
    pairing_ids: list[str] = field(default_factory=list)
    flight_ids: list[str] = field(default_factory=list)
    flight_nos: list[str] = field(default_factory=list)
    aircraft: list[str] = field(default_factory=list)
    stations: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    times_utc: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    numbers: list[float] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)

    @property
    def crew_id(self) -> str | None:
        return self.crew_ids[0] if self.crew_ids else None

    @property
    def pairing_id(self) -> str | None:
        return self.pairing_ids[0] if self.pairing_ids else None

    @property
    def date(self) -> str | None:
        return self.dates[0] if self.dates else None

    @property
    def station(self) -> str | None:
        return self.stations[0] if self.stations else None

    @property
    def tail(self) -> str | None:
        return self.aircraft[0] if self.aircraft else None

    def as_dict(self) -> dict:
        return {
            k: v
            for k, v in {
                "crew_ids": self.crew_ids,
                "pairing_ids": self.pairing_ids,
                "flight_ids": self.flight_ids,
                "flight_nos": self.flight_nos,
                "aircraft": self.aircraft,
                "stations": self.stations,
                "dates": self.dates,
                "times_utc": self.times_utc,
                "roles": self.roles,
                "rule_ids": self.rule_ids,
                "numbers": self.numbers,
                "unresolved": self.unresolved,
                "ambiguous": self.ambiguous,
            }.items()
            if v
        }


@dataclass
class Intent:
    name: str
    tier: Tier
    confidence: float
    source: str = "pattern"  # pattern | llm | fallback
    rationale: str = ""
    #: Second-place reading and its score, when the question is ambiguous.
    runner_up: tuple[str, float] | None = None
    #: True when the question asks two materially different things at once, or
    #: asks for a judgement the ruleset does not encode. Both are cases where
    #: answering one half confidently is worse than saying so.
    compound: bool = False
    policy_question: bool = False

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "tier": self.tier,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "rationale": self.rationale,
            "runner_up": list(self.runner_up) if self.runner_up else None,
            "compound": self.compound,
            "policy_question": self.policy_question,
        }


@dataclass
class ToolCall:
    tool: str
    args: dict[str, Any]
    result: dict | None = None
    error: str | None = None
    duration_ms: float | None = None

    def as_dict(self) -> dict:
        return {
            "tool": self.tool,
            "args": self.args,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "ok": self.error is None,
        }


@dataclass
class Abstention:
    reason: str
    missing: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    capabilities: dict | None = None

    def as_dict(self) -> dict:
        return {
            "abstained": True,
            "reason": self.reason,
            "missing": self.missing,
            "suggestions": self.suggestions,
            "capabilities": self.capabilities,
        }


@dataclass
class VerificationReport:
    passed: bool
    checks: list[dict] = field(default_factory=list)
    violations: list[dict] = field(default_factory=list)
    repair_attempts: int = 0
    downgraded: bool = False

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "checks": self.checks,
            "violations": self.violations,
            "repair_attempts": self.repair_attempts,
            "downgraded": self.downgraded,
            "summary": (
                f"{sum(1 for c in self.checks if c['passed'])}/{len(self.checks)} checks passed"
                if self.checks
                else "not run"
            ),
        }


class AdvisorState(TypedDict, total=False):
    """LangGraph channel schema."""

    run_id: str
    conversation_id: str | None
    question: str
    history: list[dict]

    intent: Intent | None
    entities: Entities
    plan: list[dict]
    plan_source: str

    tool_calls: list[ToolCall]
    results: dict[str, Any]

    structured_answer: dict | None
    narration: str | None
    citations: list[str]

    verification: VerificationReport | None
    abstention: Abstention | None
    repair_attempts: int
    error: str | None
