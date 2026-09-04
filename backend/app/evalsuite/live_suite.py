"""Grade the LIVE conversational system against the shipped answer keys.

``question_suite`` proves the deterministic core reproduces the answer keys by
calling it directly -- no agent, no model, no network. That is deliberate and
it is exactly why it is fast and identical on every run: it never leaves
Python. But looked at on its own, an evaluation that always finishes
instantly and always says 100% is indistinguishable from one that is faked.

This suite is the other half, and it is not a duplicate of the first. Every
question here is sent as plain English through ``Advisor.ask()`` -- the exact
path ``/api/chat`` uses, model included. Because ``compose()`` is pure code
fed by the same engine either way, a correct run reaches the *identical*
structured answer; what this suite actually exercises is everything ONLY the
live pipeline can get wrong: intent routing from free text, entity resolution
("the DXA captain" -> a crew_id), and whether the model's own narration
survives being checked against what the tools actually produced. It requires
a configured model. Without one every question would take the same
tool-only path ``question_suite`` already covers, and running it would just
be a slower way to learn nothing new -- so it refuses outright instead of
quietly re-proving the other suite.

Grading philosophy: reuse the verifier's own grounding check, one level up.
``app/agent/verify.py`` proves the model's prose contains no value absent from
this run's fact ledger. Here we run it in reverse -- every scalar the answer
key expects must be *present* in that same ledger. A routing bug that reaches
the wrong tool, or resolves the wrong crew member, shows up immediately as a
missing fact; a routing success reproduces the deterministic engine's numbers
exactly, because it is the same engine underneath.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ..agent.llm import get_client
from ..agent.runner import Advisor, AdvisorAnswer
from ..agent.verify import (
    CREW_RE,
    FLIGHT_RE,
    NUMBER_RE,
    PAIRING_RE,
    RULE_RE,
    TAIL_RE,
    _ledger_number_forms,
    _norm_number,
    build_fact_index,
)
from ..core.loader import read_json
from .matchers import CaseResult, Check

DEFAULT_CONCURRENCY = 6
ID_PATTERNS = (CREW_RE, FLIGHT_RE, PAIRING_RE, RULE_RE, TAIL_RE)


def _walk_leaves(node: Any):
    """Every scalar in a nested answer-key structure, in no particular order."""
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk_leaves(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_leaves(value)
    elif node is not None:
        yield node


def _raw_fact_values(answer: AdvisorAnswer) -> set:
    """Exact-typed values (bools included) the run actually produced.

    ``build_fact_index`` deliberately drops booleans -- narration never needs
    to "cite" a bare ``true`` -- but a legality verdict like ``legal: false``
    is exactly the kind of fact this suite must be able to check.
    """
    values: set = set()
    for fact in answer.trace.facts:
        try:
            values.add(fact.value)
        except TypeError:
            pass
    for row in answer.trace.rule_evaluations:
        for key in ("verdict", "actual", "limit", "margin", "rule_id"):
            value = row.get(key)
            if value is not None:
                try:
                    values.add(value)
                except TypeError:
                    pass
    return values


def _grounded(leaf: Any, index: dict[str, set[str]], raw: set) -> bool:
    """Does this expected value actually appear somewhere in the run?"""
    if isinstance(leaf, bool):
        return leaf in raw
    if isinstance(leaf, (int, float)):
        if leaf in raw:
            return True
        return bool(_ledger_number_forms(leaf) & index["numbers"])
    if isinstance(leaf, str):
        text = leaf.strip()
        if not text:
            return True  # an empty string carries no claim
        if leaf in raw or leaf in index["tokens"]:
            return True
        # A prose field ("action", "reason"): the composed string can differ
        # in wording from a hand-written expected value even when it is
        # correct, so check what is actually checkable -- the ids and numbers
        # embedded in it -- rather than demanding a verbatim match.
        ids = [m for pattern in ID_PATTERNS for m in pattern.findall(text)]
        if ids and not all(i in index["tokens"] for i in ids):
            return False
        numbers = NUMBER_RE.findall(text)
        if numbers and not all(_norm_number(n) in index["numbers"] for n in numbers):
            return False
        # No id, no number, and not found verbatim: only meaningful for short
        # enum-like strings (a source label, a station code); those must match.
        return bool(ids or numbers) or len(text) <= 24 and text in (raw | index["tokens"])
    return True


def _grade_notification_draft(answer: AdvisorAnswer, result: CaseResult) -> None:
    """Q36: judged on required content, not exact wording -- same as question_suite."""
    text = (answer.structured or {}).get("fallback_text") or answer.narration or ""
    required = {
        "crew_id": "C-3310" in text,
        "pairing_id": "P-2291" in text,
        "report_time": "06:00" in text,
        "report_station": "BLR" in text,
        "day1_flights": all(f in text for f in ("DX412", "DX413", "DX588")),
        "day2_flights": all(f in text for f in ("DX589", "DX590", "DX591")),
        "overnight": "DEL" in text,
        "acknowledgement": "acknowledge" in text.lower(),
    }
    for name, ok in required.items():
        result.checks.append(Check(f"must_include.{name}", ok, True, ok))


def _grade_briefing(answer: AdvisorAnswer, result: CaseResult) -> None:
    """Q38: the dataset itself marks this 'judged on operational reasoning, not exact match'."""
    lines = ((answer.structured or {}).get("primary") or {}).get("lines") or []
    result.checks.append(Check("covers_every_line", len(lines) > 0, ">0 aircraft lines", len(lines)))
    if lines:
        sample = lines[0]
        for field in ("duty_headroom", "reserve_depth", "risk"):
            result.checks.append(Check(f"datapoint.{field}", field in sample, True, field in sample))


#: Questions whose answer key is a content checklist, not literal values --
#: the generic leaf-grounding check below is the wrong tool for these two, and
#: question_suite.py grades them the same bespoke way for the same reason.
OPEN_ENDED_GRADERS = {
    "Q36": _grade_notification_draft,
    "Q38": _grade_briefing,
}


def grade_live_question(advisor: Advisor, question: dict) -> CaseResult:
    qid = question["question_id"]
    result = CaseResult(case_id=qid, tier=question["tier"], title=question["prompt"])
    started = time.perf_counter()

    try:
        answer = advisor.ask(question["prompt"])
    except Exception as exc:  # noqa: BLE001 - surfaced in the report, not raised
        result.error = f"{type(exc).__name__}: {exc}"
        result.meta = {"latency_ms": round((time.perf_counter() - started) * 1000, 2)}
        return result

    latency = round((time.perf_counter() - started) * 1000, 2)
    result.meta = {
        "latency_ms": latency,
        "intent": (answer.intent or {}).get("name"),
        "intent_source": (answer.intent or {}).get("source"),
        "plan_source": answer.plan_source,
    }

    result.checks.append(
        Check(
            "not_abstained",
            not answer.abstained,
            False,
            answer.abstained,
            detail="" if not answer.abstained else (answer.narration or "")[:160],
        )
    )

    if answer.verification is not None:
        verified = bool(answer.verification.get("passed"))
        downgraded = bool(answer.verification.get("downgraded"))
        # A downgrade IS the safety net working: the model's draft failed
        # grounding, and the controller was served the engine's own figures
        # instead of the unsafe draft. That is a successful catch, not a
        # defect -- grading it as a failure would penalise the system for
        # protecting the answer, which is backwards. Only an unverified
        # narration that was NOT caught (shouldn't be reachable, but would be
        # a real bug if it were) counts against this case.
        safe = verified or downgraded
        result.checks.append(
            Check(
                "narration_safe",
                safe,
                True,
                safe,
                detail=(
                    answer.verification.get("summary", "")
                    + (" — downgraded to the engine's grounded figures" if downgraded and not verified else "")
                ),
            )
        )

    special = OPEN_ENDED_GRADERS.get(qid)
    if special is not None:
        special(answer, result)
        return result

    index = build_fact_index(answer.trace)
    raw = _raw_fact_values(answer)
    missing = [leaf for leaf in _walk_leaves(question["expected_answer"]) if not _grounded(leaf, index, raw)]
    result.checks.append(
        Check(
            "answer_grounded",
            not missing,
            "every expected value present in this run's facts",
            f"{len(missing)} ungrounded" if missing else "all grounded",
            detail=str(missing[:6]) if missing else "",
        )
    )

    return result


def run_suite(
    data_dir: str,
    advisor: Advisor,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    limit: int | None = None,
) -> dict:
    client = get_client()
    if not client.available:
        return {
            "suite": "live",
            "available": False,
            "error": "Configure an API key to run the live-agent evaluation.",
            "total": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0.0,
            "cases": [],
        }

    questions = read_json(data_dir, "questions")
    if limit:
        questions = questions[:limit]
    order = {q["question_id"]: i for i, q in enumerate(questions)}

    started = time.perf_counter()
    results: list[CaseResult] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(grade_live_question, advisor, q) for q in questions]
        for future in as_completed(futures):
            results.append(future.result())
    wall_ms = round((time.perf_counter() - started) * 1000, 2)

    results.sort(key=lambda c: order.get(c.case_id, 0))

    tiers: dict[str, dict[str, int]] = {}
    for case in results:
        bucket = tiers.setdefault(str(case.tier), {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += 1 if case.passed else 0

    passed = sum(1 for c in results if c.passed)
    latencies = [c.meta.get("latency_ms", 0) for c in results]
    return {
        "suite": "live",
        "available": True,
        "provider": client.provider,
        "model": client.model,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "by_tier": {
            key: {**value, "pass_rate": round(value["passed"] / value["total"], 4)}
            for key, value in sorted(tiers.items())
        },
        "cases": [c.as_dict() for c in results],
        "wall_ms": wall_ms,
        "concurrency": concurrency,
        "latency_ms": {
            "avg": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            "max": round(max(latencies), 2) if latencies else 0,
            "min": round(min(latencies), 2) if latencies else 0,
        },
    }
