"""Alerts, the virtual clock, and scheduler control."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.timeutil import parse_dt
from ...db.models import Alert
from ...db.session import get_db
from ...jobs import scheduler
from ..deps import get_clock, get_world

router = APIRouter(prefix="/api", tags=["ops"])

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


class ClockRequest(BaseModel):
    now_utc: datetime | None = None
    advance_hours: float | None = None
    advance_days: float | None = None
    reset: bool = False


@router.get("/alerts")
def list_alerts(
    state: str = "open",
    severity: str | None = None,
    limit: int = 100,
    session: Session = Depends(get_db),
) -> dict:
    stmt = select(Alert)
    if state != "all":
        stmt = stmt.where(Alert.state == state)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    rows = session.scalars(stmt.limit(limit)).all()
    rows.sort(key=lambda a: (SEVERITY_ORDER.get(a.severity, 3), a.type, a.id))

    counts = dict(
        session.execute(
            select(Alert.severity, func.count()).where(Alert.state == "open").group_by(Alert.severity)
        ).all()
    )

    return {
        "count": len(rows),
        "open_by_severity": {k: counts.get(k, 0) for k in ("critical", "warning", "info")},
        "alerts": [
            {
                "id": a.id,
                "type": a.type,
                "severity": a.severity,
                "title": a.title,
                "detail": a.detail,
                "entity_ref": a.entity_ref,
                "payload": a.payload,
                "suggested_question": a.suggested_question,
                "state": a.state,
                "detected_at": a.detected_at.isoformat(),
            }
            for a in rows
        ],
    }


@router.post("/alerts/sweep")
def sweep(only: list[str] | None = None) -> dict:
    """Run the watchers now. The console calls this after moving the clock."""
    return scheduler.sweep_alerts(only=only)


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: str, session: Session = Depends(get_db)) -> dict:
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, "alert not found")
    alert.state = "acknowledged"
    session.commit()
    return {"id": alert.id, "state": alert.state}


@router.post("/alerts/{alert_id}/resolve")
def resolve(alert_id: str, session: Session = Depends(get_db)) -> dict:
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, "alert not found")
    alert.state = "resolved"
    alert.resolved_at = get_clock().now
    session.commit()
    return {"id": alert.id, "state": alert.state}


@router.get("/clock")
def read_clock() -> dict:
    return get_clock().as_dict()


@router.post("/clock")
def set_clock(body: ClockRequest) -> dict:
    """Move the simulated 'now'.

    The dataset is frozen at 2026-09-14T18:00Z. Rather than pretend otherwise,
    the demo drives a virtual clock, and the watchers, "today" and every
    relative date read from it.
    """
    clock = get_clock()
    if body.reset:
        clock.reset()
    elif body.now_utc is not None:
        clock.set(body.now_utc.replace(tzinfo=None))
    elif body.advance_hours or body.advance_days:
        clock.advance(hours=body.advance_hours or 0.0, days=body.advance_days or 0.0)

    world = get_world()
    start, end = world.date_range()
    payload = clock.as_dict()
    payload["within_schedule"] = start <= clock.now.date() <= end
    payload["schedule"] = {"start": start.isoformat(), "end": end.isoformat()}
    return payload


@router.get("/scheduler")
def scheduler_status() -> dict:
    return scheduler.status()


@router.get("/health")
def health() -> dict:
    from ...agent.llm import get_client
    from ...config import get_settings
    from ...db.session import healthcheck

    settings = get_settings()
    world = get_world()
    return {
        "status": "ok",
        "version": settings.version,
        "world_loaded": len(world.flights) > 0,
        "snapshot_utc": world.snapshot_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_seed": settings.data_seed,
        "data_dir": settings.data_dir,
        "clock": get_clock().as_dict(),
        "database": healthcheck(),
        "scheduler": scheduler.status(),
        "llm": get_client().status,
    }
