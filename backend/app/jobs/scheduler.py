"""APScheduler wiring.

Jobs run against the virtual clock, so advancing the clock in the demo makes
the board change. Alerts are upserted by a stable id, so a repeated pass
refreshes rather than duplicates, and a controller's acknowledgement survives
the next sweep.
"""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from ..config import get_settings
from ..db.models import Alert, EvalRun
from ..db.session import session_scope
from . import watchers

log = logging.getLogger("crewops.jobs")

_scheduler: BackgroundScheduler | None = None


def sweep_alerts(*, only: list[str] | None = None) -> dict:
    """Run every watcher and reconcile the alert board."""
    from ..api.deps import get_clock, get_world

    world = get_world()
    now: datetime = get_clock().now
    drafts = watchers.run_all(world, now, only=only)

    created = updated = 0
    with session_scope() as session:
        seen = set()
        for draft in drafts:
            seen.add(draft.id)
            existing = session.get(Alert, draft.id)
            if existing is None:
                session.add(
                    Alert(
                        id=draft.id,
                        type=draft.type,
                        severity=draft.severity,
                        title=draft.title,
                        detail=draft.detail,
                        entity_ref=draft.entity_ref,
                        payload=draft.payload,
                        suggested_question=draft.suggested_question,
                        detected_at=now,
                    )
                )
                created += 1
            elif existing.state == "open":
                # Refresh the content, keep the identity and the timestamp.
                existing.severity = draft.severity
                existing.title = draft.title
                existing.detail = draft.detail
                existing.payload = draft.payload
                updated += 1

        # Anything previously open that no longer fires has been resolved by
        # the passage of time (or by a decision).
        stale = session.scalars(select(Alert).where(Alert.state == "open")).all()
        auto_resolved = 0
        for alert in stale:
            if alert.id not in seen:
                alert.state = "resolved"
                alert.resolved_at = now
                auto_resolved += 1

    summary = {
        "swept_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "found": len(drafts),
        "created": created,
        "updated": updated,
        "auto_resolved": auto_resolved,
        "watchers": sorted(watchers.WATCHERS),
    }
    log.info("alert sweep: %s", summary)
    return summary


def nightly_eval() -> dict:
    """Regression-test our own correctness against the shipped answer keys."""
    from ..evalsuite import question_suite, scenario_suite

    data_dir = get_settings().data_dir
    questions = question_suite.run_suite(data_dir)
    scenarios = scenario_suite.run_suite(data_dir, suite="scenarios")

    total = questions["total"] + scenarios["total"]
    passed = questions["passed"] + scenarios["passed"]
    with session_scope() as session:
        session.add(
            EvalRun(
                suite="scheduled",
                total=total,
                passed=passed,
                pass_rate=round(passed / total, 4) if total else 0.0,
                by_tier=questions["by_tier"],
                report={"cases": questions["cases"] + scenarios["cases"]},
            )
        )
    log.info("scheduled eval: %s/%s", passed, total)
    return {"total": total, "passed": passed}


def prune_traces() -> dict:
    from ..db import trace_repo

    with session_scope() as session:
        removed = trace_repo.prune(session, keep=500)
    return {"removed": removed}


JOBS = {
    "sweep_alerts": (sweep_alerts, "interval"),
    "nightly_eval": (nightly_eval, "interval"),
    "prune_traces": (prune_traces, "interval"),
}


def start() -> BackgroundScheduler | None:
    global _scheduler
    settings = get_settings()
    if not settings.scheduler_enabled or _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        sweep_alerts,
        "interval",
        seconds=settings.watcher_interval_seconds,
        id="sweep_alerts",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(nightly_eval, "interval", hours=6, id="nightly_eval", max_instances=1)
    _scheduler.add_job(prune_traces, "interval", hours=12, id="prune_traces", max_instances=1)
    _scheduler.start()
    log.info("scheduler started with %d jobs", len(_scheduler.get_jobs()))
    return _scheduler


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def status() -> dict:
    if _scheduler is None:
        return {"running": False, "jobs": []}
    return {
        "running": _scheduler.running,
        "jobs": [
            {
                "id": job.id,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
            for job in _scheduler.get_jobs()
        ],
    }
