"""Evaluation: grade ourselves against the shipped answer keys, on demand.

Two genuinely different suites live here, and the difference is the point.

``engine``   calls app.core directly -- no agent, no model, no network. Fast
             and identical every run, by construction: it is proof the
             deterministic core reproduces the answer keys, nothing more.

``live``     sends each question's own English through Advisor.ask() -- the
             exact path /api/chat uses, model included. It takes real wall
             time, makes real API calls, and can genuinely fail (wrong
             routing, a verification failure) in ways the engine suite
             structurally cannot. It requires a configured model.

A "correctness scorecard" that only ever shows the first kind, instantly and
identically, is easy to mistake for a fake one. Showing both -- and being
explicit about what each does and doesn't prove -- is the fix.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...db.models import EvalRun
from ...db.session import get_db
from ...evalsuite import live_suite, question_suite, scenario_suite
from ..deps import get_advisor

router = APIRouter(prefix="/api/eval", tags=["eval"])

SUITES = ("questions", "scenarios", "holdout", "all", "live")

SUITE_DESCRIPTIONS = {
    "questions": "Calls app.core directly against the 38 shipped questions. No agent, no model, no network -- proof the deterministic engine's math matches the answer keys. Fast and identical on every run by construction.",
    "scenarios": "Calls app.core directly against the 6 worked scenarios (S1-S6). Same guarantee as 'questions', at the scenario level.",
    "holdout": "The 2 held-out scenarios (H1-H2), used once to check generalisation, not to build the logic.",
    "all": "The three suites above, combined. This is the deterministic-engine scorecard -- it never touches the model.",
    "live": "Sends each question's own English through the real agent -- the exact path /api/chat uses, model included. Takes real wall-clock time and can genuinely fail on routing or verification. Requires a configured API key.",
}


def _engine_run(suite: str) -> dict:
    data_dir = get_settings().data_dir
    if suite == "questions":
        return question_suite.run_suite(data_dir)
    if suite in ("scenarios", "holdout"):
        return scenario_suite.run_suite(data_dir, suite=suite)
    if suite == "all":
        questions = question_suite.run_suite(data_dir)
        scenarios = scenario_suite.run_suite(data_dir, suite="scenarios")
        holdout = scenario_suite.run_suite(data_dir, suite="holdout")
        total = questions["total"] + scenarios["total"] + holdout["total"]
        passed = questions["passed"] + scenarios["passed"] + holdout["passed"]
        return {
            "suite": "all",
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 4) if total else 0.0,
            "by_tier": questions["by_tier"],
            "suites": {"questions": questions, "scenarios": scenarios, "holdout": holdout},
            "cases": questions["cases"] + scenarios["cases"] + holdout["cases"],
        }
    raise HTTPException(400, f"unknown suite {suite!r}; expected one of {SUITES}")


@router.post("/run")
def run_eval(
    suite: str = "all",
    persist: bool = True,
    concurrency: int = 6,
    limit: int | None = None,
    session: Session = Depends(get_db),
) -> dict:
    if suite not in SUITES:
        raise HTTPException(400, f"unknown suite {suite!r}; expected one of {SUITES}")

    started = time.perf_counter()
    if suite == "live":
        data_dir = get_settings().data_dir
        report = live_suite.run_suite(data_dir, get_advisor(), concurrency=concurrency, limit=limit)
        if not report.get("available"):
            # Distinct from "ran and failed": nothing ran at all, so don't
            # persist a hollow 0/0 record that a naive reader could mistake
            # for a total wipe-out on the scorecard.
            raise HTTPException(400, report["error"])
    else:
        report = _engine_run(suite)

    duration = round((time.perf_counter() - started) * 1000, 2)
    report["duration_ms"] = duration
    report["description"] = SUITE_DESCRIPTIONS.get(suite, "")

    if persist:
        session.add(
            EvalRun(
                suite=suite,
                total=report["total"],
                passed=report["passed"],
                pass_rate=report["pass_rate"],
                by_tier=report.get("by_tier", {}),
                report={"cases": report["cases"], "meta": {k: v for k, v in report.items() if k not in ("cases",)}},
                duration_ms=duration,
            )
        )
        session.commit()

    return report


@router.get("/latest")
def latest(suite: str = "all", session: Session = Depends(get_db)) -> dict:
    if suite not in SUITES:
        raise HTTPException(400, f"unknown suite {suite!r}; expected one of {SUITES}")
    row = session.scalars(
        select(EvalRun).where(EvalRun.suite == suite).order_by(EvalRun.created_at.desc()).limit(1)
    ).first()
    if row is None:
        return run_eval(suite=suite, persist=True, session=session)
    meta = row.report.get("meta", {})
    return {
        "suite": row.suite,
        "total": row.total,
        "passed": row.passed,
        "failed": row.total - row.passed,
        "pass_rate": row.pass_rate,
        "by_tier": row.by_tier,
        "duration_ms": row.duration_ms,
        "created_at": row.created_at.isoformat(),
        "cases": row.report.get("cases", []),
        "description": SUITE_DESCRIPTIONS.get(row.suite, ""),
        **{k: v for k, v in meta.items() if k not in ("suite", "total", "passed", "failed", "pass_rate", "by_tier", "duration_ms", "cases")},
    }


@router.get("/history")
def history(limit: int = 20, session: Session = Depends(get_db)) -> dict:
    rows = session.scalars(
        select(EvalRun).order_by(EvalRun.created_at.desc()).limit(limit)
    ).all()
    return {
        "count": len(rows),
        "runs": [
            {
                "id": r.id,
                "suite": r.suite,
                "total": r.total,
                "passed": r.passed,
                "pass_rate": r.pass_rate,
                "by_tier": r.by_tier,
                "duration_ms": r.duration_ms,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/questions")
def questions() -> dict:
    """The graded question set, so the console can offer them as prompts."""
    from ...core.loader import read_json

    rows = read_json(get_settings().data_dir, "questions")
    return {
        "count": len(rows),
        "questions": [
            {"question_id": r["question_id"], "tier": r["tier"], "prompt": r["prompt"]}
            for r in rows
        ],
    }
