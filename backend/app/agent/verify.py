"""Narration verification -- the guard that makes the boundary real.

Claiming "the LLM never does arithmetic" is cheap. This module checks it.

After the model writes its prose, every number, crew id, flight id, pairing id
and rule id in that prose is looked up in the run's fact ledger. Anything the
tools did not produce is a violation. One repair attempt is allowed, with the
violations fed back; a second failure downgrades the answer to structured-only
plus an honest note. A fluent, confident, wrong number cannot reach the
controller, because it cannot get past this function.

Deliberate tolerances, each with a reason:

* Numbers appearing in the user's own question are allowed -- echoing the
  question back is not a claim.
* Small integers 0-24 are allowed unqualified: they are list positions, hours
  of the day, "all three legs". Requiring provenance for "three" produces
  constant false positives without catching a single real hallucination.
* Numbers written inside a date or time already validated as a fact are not
  re-checked digit by digit.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..obs.tracer import RunTrace
from .state import VerificationReport

NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
CREW_RE = re.compile(r"\bC-\d{4}\b")
FLIGHT_RE = re.compile(r"\bDX\d{3}\b")
PAIRING_RE = re.compile(r"\bP-\d{4}\b")
RULE_RE = re.compile(r"\bRULE-[A-Z]+-\d{2}\b")
TAIL_RE = re.compile(r"\bVT-DX[A-Z]\b")

#: Bare integers below this are treated as prose, not as claims.
SMALL_INT_CEILING = 24


def _norm_number(raw: str) -> str:
    value = raw.replace(",", "")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value or "0"


def _ledger_number_forms(value: Any) -> set[str]:
    """Every string form a ledger number might legitimately be written as."""
    forms: set[str] = set()
    if isinstance(value, bool):
        return forms
    if isinstance(value, (int, float)):
        forms.add(_norm_number(str(value)))
        forms.add(_norm_number(f"{value:.2f}"))
        if float(value).is_integer():
            forms.add(str(int(value)))
        # 1.33h is also written "1h20m"; expose the minute part.
        fractional = abs(float(value)) % 1
        if fractional:
            forms.add(str(int(round(fractional * 60))))
        forms.add(str(int(abs(float(value)))))
    elif isinstance(value, str):
        for match in NUMBER_RE.finditer(value):
            forms.add(_norm_number(match.group(0)))
    return forms


def build_fact_index(trace: RunTrace) -> dict[str, set[str]]:
    numbers: set[str] = set()
    tokens: set[str] = set()

    for fact in trace.facts:
        numbers |= _ledger_number_forms(fact.value)
        if isinstance(fact.value, str):
            for pattern in (CREW_RE, FLIGHT_RE, PAIRING_RE, RULE_RE, TAIL_RE):
                tokens |= set(pattern.findall(fact.value))
            tokens.add(fact.value)
        for pattern in (CREW_RE, FLIGHT_RE, PAIRING_RE, RULE_RE, TAIL_RE):
            tokens |= set(pattern.findall(fact.key))

    for row in trace.rule_evaluations:
        if row.get("rule_id"):
            tokens.add(row["rule_id"])
        for field in ("actual", "limit", "margin"):
            if row.get(field) is not None:
                numbers |= _ledger_number_forms(row[field])
        if row.get("message"):
            for match in NUMBER_RE.finditer(row["message"]):
                numbers.add(_norm_number(match.group(0)))
            for pattern in (CREW_RE, FLIGHT_RE, PAIRING_RE, RULE_RE, TAIL_RE):
                tokens |= set(pattern.findall(row["message"]))

    return {"numbers": numbers, "tokens": tokens}


def _check_entities(
    name: str,
    pattern: re.Pattern,
    narration: str,
    allowed: set[str],
    question: str,
) -> tuple[dict, list[dict]]:
    found = set(pattern.findall(narration))
    asked = set(pattern.findall(question))
    unknown = sorted(found - allowed - asked)
    return (
        {
            "name": name,
            "passed": not unknown,
            "checked": len(found),
            "detail": f"{len(found)} referenced, {len(unknown)} ungrounded",
        },
        [
            {"check": name, "value": v, "reason": "not produced by any tool in this run"}
            for v in unknown
        ],
    )


def verify_narration(
    narration: str,
    trace: RunTrace,
    *,
    question: str = "",
    structured: dict | None = None,
    cited_rules: Iterable[str] = (),
) -> VerificationReport:
    if not narration:
        return VerificationReport(passed=True, checks=[{"name": "narration", "passed": True, "detail": "empty"}])

    index = build_fact_index(trace)
    checks: list[dict] = []
    violations: list[dict] = []

    # 1. Numeric provenance ------------------------------------------------
    question_numbers = {_norm_number(m.group(0)) for m in NUMBER_RE.finditer(question)}
    ungrounded: list[str] = []
    checked = 0
    for match in NUMBER_RE.finditer(narration):
        raw = _norm_number(match.group(0))
        checked += 1
        if raw in index["numbers"] or raw in question_numbers:
            continue
        try:
            if abs(float(raw)) <= SMALL_INT_CEILING and float(raw).is_integer():
                continue
        except ValueError:
            continue
        ungrounded.append(match.group(0))
    checks.append(
        {
            "name": "numeric_provenance",
            "passed": not ungrounded,
            "checked": checked,
            "detail": f"{checked} numbers, {len(ungrounded)} ungrounded",
        }
    )
    violations += [
        {"check": "numeric_provenance", "value": v, "reason": "no tool produced this number"}
        for v in sorted(set(ungrounded))
    ]

    # 2. Entity existence ---------------------------------------------------
    for name, pattern in (
        ("crew_ids_grounded", CREW_RE),
        ("flight_ids_grounded", FLIGHT_RE),
        ("pairing_ids_grounded", PAIRING_RE),
        ("aircraft_grounded", TAIL_RE),
    ):
        check, found_violations = _check_entities(
            name, pattern, narration, index["tokens"], question
        )
        checks.append(check)
        violations += found_violations

    # 3. Rule citations must have a matching evaluation ---------------------
    evaluated = {row.get("rule_id") for row in trace.rule_evaluations}
    evaluated |= set(index["tokens"])
    evaluated |= set(cited_rules)
    mentioned = set(RULE_RE.findall(narration))
    uncited = sorted(mentioned - evaluated - set(RULE_RE.findall(question)))
    checks.append(
        {
            "name": "rule_citations",
            "passed": not uncited,
            "checked": len(mentioned),
            "detail": f"{len(mentioned)} cited, {len(uncited)} without an evaluation",
        }
    )
    violations += [
        {"check": "rule_citations", "value": v, "reason": "cited but never evaluated in this run"}
        for v in uncited
    ]

    # 4. Legality claims must agree with the structured verdict -------------
    contradiction = _legality_contradiction(narration, structured)
    checks.append(
        {
            "name": "legality_consistency",
            "passed": contradiction is None,
            "detail": contradiction or "narration agrees with the computed verdict",
        }
    )
    if contradiction:
        violations.append(
            {"check": "legality_consistency", "value": contradiction, "reason": "contradicts the engine"}
        )

    return VerificationReport(
        passed=not violations, checks=checks, violations=violations
    )


LEGAL_CLAIM = re.compile(r"\b(is|are|would be|remains?) legal\b|\bno (rule )?breach|\bcompliant\b", re.I)
ILLEGAL_CLAIM = re.compile(r"\b(is|are|would be) (not legal|illegal)\b|\bbreach(es|ed)?\b|\bexceeds?\b|\bviolat", re.I)


def _legality_contradiction(narration: str, structured: dict | None) -> str | None:
    """Catch prose that says 'legal' when the engine said otherwise."""
    if not structured:
        return None
    verdict = structured.get("legal")
    if verdict is None:
        verdict = (structured.get("primary") or {}).get("legal")
    if verdict is None:
        return None

    says_legal = bool(LEGAL_CLAIM.search(narration))
    says_illegal = bool(ILLEGAL_CLAIM.search(narration))

    if verdict is False and says_legal and not says_illegal:
        return "narration asserts the assignment is legal but the engine returned legal=false"
    if verdict is True and says_illegal and not says_legal:
        return "narration asserts a breach but the engine returned legal=true"
    return None


def violations_prompt(report: VerificationReport) -> str:
    """Feedback for the single repair attempt."""
    lines = ["Your previous draft failed verification. Fix these and rewrite:"]
    for violation in report.violations[:12]:
        lines.append(f"- {violation['check']}: '{violation['value']}' — {violation['reason']}")
    lines.append(
        "Use ONLY values present in the tool results provided. Do not compute, round, "
        "convert or infer any number. If a figure you want is not in the results, omit it."
    )
    return "\n".join(lines)
