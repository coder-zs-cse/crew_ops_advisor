"""Persist finished runs, and read them back for the run inspector."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..obs.tracer import RunTrace
from .models import AgentRun, AgentSpan, FactRow, RuleEvaluation

#: Facts are exhaustive by design (that is what makes the verifier work), but a
#: 1,800-row ledger per run is not worth storing forever. Keep enough to audit.
MAX_PERSISTED_FACTS = 400


def persist_run(session: Session, trace: RunTrace) -> None:
    summary = trace.summary()
    tokens = summary.get("tokens", {})

    session.merge(
        AgentRun(
            run_id=trace.run_id,
            conversation_id=trace.conversation_id,
            question=trace.question,
            intent=summary.get("intent"),
            tier=summary.get("tier"),
            confidence=summary.get("confidence"),
            plan_source=summary.get("plan_source"),
            status=trace.status,
            abstained=bool(summary.get("abstained")),
            verified=summary.get("verified", True),
            latency_ms=trace.duration_ms,
            tokens_in=tokens.get("input", 0),
            tokens_out=tokens.get("output", 0),
            span_count=len(trace.spans),
            tool_call_count=len(trace.tool_calls),
            fact_count=len(trace.facts),
            started_at=trace.started_at,
            ended_at=trace.ended_at,
        )
    )

    for span in trace.spans:
        session.merge(
            AgentSpan(
                span_id=span.span_id,
                run_id=span.run_id,
                parent_span_id=span.parent_span_id,
                name=span.name,
                type=span.type,
                started_at=span.started_at,
                ended_at=span.ended_at,
                duration_ms=span.duration_ms,
                status=span.status,
                error=span.error,
                input=_jsonable(span.input),
                output=_jsonable(span.output),
                input_hash=span.input_hash,
                output_hash=span.output_hash,
                attrs=_jsonable(span.attrs) or {},
            )
        )

    for fact in trace.facts[:MAX_PERSISTED_FACTS]:
        session.add(
            FactRow(
                run_id=fact.run_id,
                fact_id=fact.fact_id,
                key=fact.key[:200],
                value=str(fact.value)[:2000],
                unit=fact.unit,
                source_span_id=fact.source_span_id,
                source_tool=fact.source_tool,
                citation=fact.citation,
            )
        )

    for row in trace.rule_evaluations:
        session.add(
            RuleEvaluation(
                run_id=trace.run_id,
                span_id=row.get("span_id"),
                rule_id=row.get("rule_id", ""),
                subject_crew_id=row.get("crew_id"),
                subject_date=row.get("date"),
                verdict=row.get("verdict", ""),
                actual=row.get("actual"),
                limit_value=row.get("limit"),
                margin=row.get("margin"),
                message=row.get("message", ""),
                arithmetic=row.get("arithmetic", []),
            )
        )


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


def list_runs(session: Session, limit: int = 50, *, intent: str | None = None) -> list[dict]:
    stmt = select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit)
    if intent:
        stmt = stmt.where(AgentRun.intent == intent)
    return [_run_dict(r) for r in session.scalars(stmt)]


def get_run(session: Session, run_id: str) -> dict | None:
    run = session.get(AgentRun, run_id)
    if run is None:
        return None
    spans = session.scalars(
        select(AgentSpan).where(AgentSpan.run_id == run_id).order_by(AgentSpan.started_at)
    ).all()
    facts = session.scalars(
        select(FactRow).where(FactRow.run_id == run_id).order_by(FactRow.id)
    ).all()
    rules = session.scalars(
        select(RuleEvaluation).where(RuleEvaluation.run_id == run_id).order_by(RuleEvaluation.id)
    ).all()

    return {
        **_run_dict(run),
        "spans": [_span_dict(s) for s in spans],
        "facts": [
            {
                "fact_id": f.fact_id,
                "key": f.key,
                "value": f.value,
                "unit": f.unit,
                "source_span_id": f.source_span_id,
                "source_tool": f.source_tool,
            }
            for f in facts
        ],
        "rule_evaluations": [
            {
                "rule_id": r.rule_id,
                "crew_id": r.subject_crew_id,
                "date": r.subject_date,
                "verdict": r.verdict,
                "actual": r.actual,
                "limit": r.limit_value,
                "margin": r.margin,
                "message": r.message,
                "arithmetic": r.arithmetic,
            }
            for r in rules
        ],
    }


def _run_dict(run: AgentRun) -> dict:
    return {
        "run_id": run.run_id,
        "conversation_id": run.conversation_id,
        "question": run.question,
        "intent": run.intent,
        "tier": run.tier,
        "confidence": run.confidence,
        "plan_source": run.plan_source,
        "status": run.status,
        "abstained": run.abstained,
        "verified": run.verified,
        "latency_ms": run.latency_ms,
        "tokens": {"input": run.tokens_in, "output": run.tokens_out},
        "span_count": run.span_count,
        "tool_call_count": run.tool_call_count,
        "fact_count": run.fact_count,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
    }


def _span_dict(span: AgentSpan) -> dict:
    return {
        "span_id": span.span_id,
        "parent_span_id": span.parent_span_id,
        "name": span.name,
        "type": span.type,
        "started_at": span.started_at.isoformat() if span.started_at else None,
        "duration_ms": span.duration_ms,
        "status": span.status,
        "error": span.error,
        "input": span.input,
        "output": span.output,
        "attrs": span.attrs,
    }


def _rate(values: list) -> float | None:
    """Pass rate over the runs the check actually applies to."""
    if not values:
        return None
    return round(sum(1 for v in values if v) / len(values), 4)


def metrics(session: Session, *, hours: int = 24) -> dict:
    """Aggregates for the observability dashboard."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    runs = session.scalars(select(AgentRun).where(AgentRun.started_at >= since)).all()
    if not runs:
        runs = session.scalars(
            select(AgentRun).order_by(AgentRun.started_at.desc()).limit(200)
        ).all()

    latencies = sorted(r.latency_ms for r in runs if r.latency_ms is not None)

    def pct(p: float) -> float | None:
        if not latencies:
            return None
        index = min(len(latencies) - 1, int(round(p * (len(latencies) - 1))))
        return round(latencies[index], 2)

    by_intent: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    for run in runs:
        by_intent[run.intent or "unknown"] = by_intent.get(run.intent or "unknown", 0) + 1
        key = str(run.tier or "-")
        by_tier[key] = by_tier.get(key, 0) + 1

    tool_rows = session.execute(
        select(AgentSpan.name, func.count())
        .where(AgentSpan.type == "tool")
        .group_by(AgentSpan.name)
        .order_by(func.count().desc())
        .limit(20)
    ).all()

    node_rows = session.execute(
        select(AgentSpan.name, func.avg(AgentSpan.duration_ms), func.count())
        .where(AgentSpan.type == "node")
        .group_by(AgentSpan.name)
    ).all()

    total = len(runs) or 1
    return {
        "window_hours": hours,
        "run_count": len(runs),
        "latency_ms": {"p50": pct(0.5), "p95": pct(0.95), "max": pct(1.0)},
        "verification_pass_rate": _rate([r.verified for r in runs if r.verified is not None]),
        "abstention_rate": round(sum(1 for r in runs if r.abstained) / total, 4),
        "compiled_plan_rate": round(
            sum(1 for r in runs if r.plan_source == "compiled") / total, 4
        ),
        "tokens": {
            "input": sum(r.tokens_in for r in runs),
            "output": sum(r.tokens_out for r in runs),
        },
        "by_intent": dict(sorted(by_intent.items(), key=lambda kv: -kv[1])),
        "by_tier": dict(sorted(by_tier.items())),
        "tool_usage": [{"tool": name, "calls": count} for name, count in tool_rows],
        "node_latency_ms": [
            {"node": name, "avg_ms": round(avg or 0, 2), "count": count}
            for name, avg, count in node_rows
        ],
    }


def prune(session: Session, keep: int = 500) -> int:
    """Keep the trace store bounded."""
    keep_ids = session.scalars(
        select(AgentRun.run_id).order_by(AgentRun.started_at.desc()).limit(keep)
    ).all()
    if not keep_ids:
        return 0
    removed = session.execute(
        delete(AgentRun).where(AgentRun.run_id.not_in(keep_ids))
    ).rowcount
    for model in (AgentSpan, FactRow, RuleEvaluation):
        session.execute(delete(model).where(model.run_id.not_in(keep_ids)))
    return removed or 0
