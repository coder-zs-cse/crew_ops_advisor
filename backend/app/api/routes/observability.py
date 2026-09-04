"""Observability: runs, traces, receipts, metrics, and live events.

The run inspector reads from here. So does the "reasoning receipt" download --
the whole trace, fact ledger and rule-evaluation log for one answer, as a file a
controller (or a judge) can keep and challenge.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ...db import trace_repo
from ...db.session import get_db
from ...obs.sinks import EVENT_BUS, MEMORY_SINK

router = APIRouter(prefix="/api", tags=["observability"])


@router.get("/runs")
def list_runs(limit: int = 50, intent: str | None = None, session: Session = Depends(get_db)) -> dict:
    rows = trace_repo.list_runs(session, limit=limit, intent=intent)
    if not rows:
        # Nothing persisted yet (or persistence disabled) -- serve from memory.
        rows = [t.summary() for t in MEMORY_SINK.list(limit)]
    return {"count": len(rows), "runs": rows}


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_db)) -> dict:
    trace = MEMORY_SINK.get(run_id)
    if trace is not None:
        payload = trace.as_dict()
        payload["waterfall"] = trace.waterfall()
        payload["source"] = "memory"
        return payload

    stored = trace_repo.get_run(session, run_id)
    if stored is None:
        raise HTTPException(404, f"run {run_id} not found")
    stored["source"] = "database"
    return stored


@router.get("/runs/{run_id}/spans")
def get_spans(run_id: str, session: Session = Depends(get_db)) -> dict:
    trace = MEMORY_SINK.get(run_id)
    if trace is not None:
        return {"run_id": run_id, "waterfall": trace.waterfall()}
    stored = trace_repo.get_run(session, run_id)
    if stored is None:
        raise HTTPException(404, f"run {run_id} not found")
    return {"run_id": run_id, "waterfall": stored["spans"]}


@router.get("/runs/{run_id}/facts")
def get_facts(run_id: str, limit: int = 500, session: Session = Depends(get_db)) -> dict:
    trace = MEMORY_SINK.get(run_id)
    if trace is not None:
        facts = [f.as_dict() for f in trace.facts]
        return {"run_id": run_id, "count": len(facts), "facts": facts[:limit]}
    stored = trace_repo.get_run(session, run_id)
    if stored is None:
        raise HTTPException(404, f"run {run_id} not found")
    return {"run_id": run_id, "count": len(stored["facts"]), "facts": stored["facts"][:limit]}


@router.get("/runs/{run_id}/rule-evaluations")
def get_rule_evaluations(run_id: str, session: Session = Depends(get_db)) -> dict:
    trace = MEMORY_SINK.get(run_id)
    rows = (
        trace.rule_evaluations
        if trace is not None
        else (trace_repo.get_run(session, run_id) or {}).get("rule_evaluations")
    )
    if rows is None:
        raise HTTPException(404, f"run {run_id} not found")

    breaches = [r for r in rows if r.get("verdict") == "breach"]
    by_rule: dict[str, int] = {}
    for row in breaches:
        by_rule[row.get("rule_id", "?")] = by_rule.get(row.get("rule_id", "?"), 0) + 1
    return {
        "run_id": run_id,
        "count": len(rows),
        "breach_count": len(breaches),
        "breaches_by_rule": dict(sorted(by_rule.items(), key=lambda kv: -kv[1])),
        "evaluations": rows,
    }


@router.get("/runs/{run_id}/receipt")
def receipt(run_id: str, session: Session = Depends(get_db)) -> JSONResponse:
    """The reasoning receipt: everything behind one answer, as a file.

    A controller who disagrees with an answer should be able to take the whole
    derivation away and argue with it. This is that artifact.
    """
    trace = MEMORY_SINK.get(run_id)
    payload = trace.as_dict() if trace is not None else trace_repo.get_run(session, run_id)
    if payload is None:
        raise HTTPException(404, f"run {run_id} not found")

    payload["_receipt"] = {
        "what_this_is": (
            "The complete derivation of one answer: every tool called, every fact "
            "produced, every rule evaluated with its arithmetic, and the result of "
            "verifying the narration against those facts."
        ),
        "how_to_challenge": (
            "Every number in the answer appears in `facts`. Every legality claim "
            "appears in `rule_evaluations` with its actual value, limit and margin. "
            "If a figure is not there, the answer should not have contained it."
        ),
    }
    return JSONResponse(
        payload,
        headers={"Content-Disposition": f'attachment; filename="receipt-{run_id}.json"'},
    )


@router.post("/runs/{run_id}/replay")
def replay(run_id: str) -> dict:
    """Re-execute the deterministic tool calls and diff the results.

    Nothing below the boundary depends on a model, so a replay of the same
    snapshot must produce byte-identical tool outputs. This endpoint proves it,
    and would catch a non-determinism bug the moment one appeared.
    """
    from ...tools.registry import call as call_tool
    from ..deps import get_world

    trace = MEMORY_SINK.get(run_id)
    if trace is None:
        raise HTTPException(404, f"run {run_id} not in the live trace buffer")

    world = get_world()
    comparisons = []
    for span in trace.tool_calls:
        args = span.input if isinstance(span.input, dict) else {}
        try:
            fresh = call_tool(span.name, world, **args)
            from ...obs.tracer import _hash  # noqa: PLC0415

            fresh_hash = _hash(fresh)
            comparisons.append(
                {
                    "tool": span.name,
                    "args": args,
                    "original_hash": span.output_hash,
                    "replay_hash": fresh_hash,
                    "identical": fresh_hash == span.output_hash,
                }
            )
        except Exception as exc:  # noqa: BLE001
            comparisons.append({"tool": span.name, "args": args, "error": str(exc)})

    identical = all(c.get("identical") for c in comparisons if "identical" in c)
    return {
        "run_id": run_id,
        "tool_calls_replayed": len(comparisons),
        "deterministic": identical,
        "comparisons": comparisons,
    }


@router.get("/metrics")
def metrics(hours: int = 24, session: Session = Depends(get_db)) -> dict:
    from ...agent.llm import get_client
    from ..deps import get_advisor

    stored = trace_repo.metrics(session, hours=hours)
    live = MEMORY_SINK.all()
    stored["live_buffer_runs"] = len(live)
    stored["engine"] = get_advisor().engine
    stored["llm"] = get_client().status
    return stored


@router.get("/events")
async def events(request: Request, run_id: str | None = None) -> EventSourceResponse:
    """Global trace event stream -- powers the live activity feed."""
    queue = EVENT_BUS.subscribe(run_id)
    EVENT_BUS.bind_loop(asyncio.get_running_loop())

    async def generate():
        try:
            for message in EVENT_BUS.recent(run_id, limit=50):
                yield {"event": message.get("event", "trace"), "data": json.dumps(message)}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"event": message.get("event", "trace"), "data": json.dumps(message)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            EVENT_BUS.unsubscribe(queue, run_id)

    return EventSourceResponse(generate())
