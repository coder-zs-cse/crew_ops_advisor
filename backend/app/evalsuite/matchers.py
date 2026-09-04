"""Structural matchers for comparing our output to the shipped answer keys.

Different fields deserve different strictness. Flight lists are sets (order is
presentation). Costs and ranks are exact (they are the answer). Exclusion
reasons are compared on rule id plus any numbers in the string, so a reworded
message still passes but a wrong magnitude does not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
RULE_RE = re.compile(r"RULE-[A-Z]+-\d+")


@dataclass
class Check:
    name: str
    passed: bool
    expected: Any = None
    actual: Any = None
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "expected": _trim(self.expected),
            "actual": _trim(self.actual),
            "detail": self.detail,
        }


@dataclass
class CaseResult:
    case_id: str
    tier: int | None
    title: str
    checks: list[Check] = field(default_factory=list)
    error: str | None = None
    #: Free-form extras a suite wants attached (e.g. live-agent latency and
    #: routed intent) without widening this shared dataclass's required fields.
    meta: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.passed for c in self.checks)

    def as_dict(self) -> dict:
        out = {
            "case_id": self.case_id,
            "tier": self.tier,
            "title": self.title,
            "passed": self.passed,
            "error": self.error,
            "checks": [c.as_dict() for c in self.checks],
            "failed_checks": [c.as_dict() for c in self.checks if not c.passed],
        }
        if self.meta:
            out["meta"] = self.meta
        return out


def _trim(value: Any, limit: int = 600) -> Any:
    text = repr(value)
    return value if len(text) <= limit else text[:limit] + "..."


def set_equal(name: str, expected, actual) -> Check:
    exp, act = set(expected or []), set(actual or [])
    if exp == act:
        return Check(name, True, sorted(exp), sorted(act))
    return Check(
        name,
        False,
        sorted(exp),
        sorted(act),
        detail=f"missing={sorted(exp - act)} unexpected={sorted(act - exp)}",
    )


def exact(name: str, expected, actual) -> Check:
    return Check(name, expected == actual, expected, actual)


def close(name: str, expected: float, actual: float, tol: float = 0.011) -> Check:
    ok = expected is not None and actual is not None and abs(expected - actual) <= tol
    return Check(name, bool(ok), expected, actual)


def numbers_in(text: str) -> set[str]:
    return {n.rstrip("0").rstrip(".") if "." in n else n for n in NUMBER_RE.findall(text or "")}


def rules_in(text: str) -> set[str]:
    return set(RULE_RE.findall(text or ""))


def reason_equivalent(expected: str, actual: str) -> bool:
    """Same rules cited and same magnitudes -- wording may differ."""
    if expected == actual:
        return True
    if actual is None:
        return False
    if rules_in(expected) != rules_in(actual):
        return False
    return numbers_in(expected).issubset(numbers_in(actual))


def options_match(
    name: str, expected: list[dict], actual: list[dict], *, prefix: bool = False
) -> list[Check]:
    """Compare ranked options positionally.

    ``prefix=True`` when the answer key lists only the top N of a longer ranked
    list (questions.json truncates some Tier-3 keys to the leading options).
    """
    if prefix:
        checks = [
            Check(
                f"{name}.count>=expected",
                len(actual) >= len(expected),
                f">={len(expected)}",
                len(actual),
            )
        ]
    else:
        checks = [exact(f"{name}.count", len(expected), len(actual))]
    for i, exp in enumerate(expected):
        if i >= len(actual):
            checks.append(Check(f"{name}[{i}]", False, exp, None, "missing option"))
            continue
        act = actual[i]
        same = (
            exp.get("crew_id") == act.get("crew_id")
            and exp.get("cost_inr") == act.get("cost_inr")
            and abs(float(exp.get("delay_hours", 0)) - float(act.get("delay_hours", 0))) < 1e-9
            and exp.get("rank") == act.get("rank")
        )
        checks.append(
            Check(
                f"{name}[{i}] rank={exp.get('rank')}",
                same,
                {k: exp.get(k) for k in ("rank", "crew_id", "cost_inr", "delay_hours")},
                {k: act.get(k) for k in ("rank", "crew_id", "cost_inr", "delay_hours")},
            )
        )
    return checks


def exclusions_match(name: str, expected: list[dict], actual: list[dict]) -> list[Check]:
    exp_by_id = {e["crew_id"]: e["reason"] for e in expected}
    act_by_id = {e["crew_id"]: e["reason"] for e in actual}

    checks = [set_equal(f"{name}.crew_ids", exp_by_id, act_by_id)]
    mismatched = []
    for cid, reason in exp_by_id.items():
        if not reason_equivalent(reason, act_by_id.get(cid, "")):
            mismatched.append({"crew_id": cid, "expected": reason, "actual": act_by_id.get(cid)})
    checks.append(
        Check(
            f"{name}.reasons",
            not mismatched,
            f"{len(exp_by_id)} reasons",
            f"{len(mismatched)} mismatched",
            detail=str(mismatched[:3]) if mismatched else "",
        )
    )
    return checks


def assessments_match(name: str, expected: list[dict], actual: list[dict]) -> list[Check]:
    exp_by_id = {e["flight_id"]: e for e in expected}
    act_by_id = {e["flight_id"]: e for e in actual}
    checks = [set_equal(f"{name}.flight_ids", exp_by_id, act_by_id)]

    bad = []
    for fid, exp in exp_by_id.items():
        act = act_by_id.get(fid)
        if act is None:
            bad.append({"flight_id": fid, "detail": "missing"})
            continue
        for key in ("pairing_id", "min_delay_hours", "crew_fdp_after_delay", "fdp_limit", "action"):
            if exp.get(key) != act.get(key):
                bad.append({"flight_id": fid, "field": key, "expected": exp.get(key), "actual": act.get(key)})
    checks.append(
        Check(
            f"{name}.fields",
            not bad,
            f"{len(exp_by_id)} assessments",
            f"{len(bad)} field mismatches",
            detail=str(bad[:3]) if bad else "",
        )
    )
    return checks
