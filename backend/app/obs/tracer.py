"""Tracing: spans, the fact ledger, and the rule-evaluation log.

Three things are recorded for every agent run, and all three are product
surfaces rather than log files:

* **spans**  -- a tree of node / llm / tool / sql / rule / sim / verify events
  with timings and raw I/O. Rendered as a waterfall in the run inspector.
* **facts**  -- an append-only ledger of every scalar any tool produced, tagged
  with the span that produced it. The narration verifier checks the model's
  prose against this; a number that is not in the ledger cannot be shown.
* **rule evaluations** -- every RuleVerdict, with actual/limit/margin and the
  arithmetic. This is what a controller challenges.

Spans carry ``input_hash``/``output_hash`` so a deterministic run can be
replayed and diffed.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

SpanType = str  # node | llm | tool | sql | rule | sim | verify | graph

_current_run: contextvars.ContextVar["RunTrace | None"] = contextvars.ContextVar(
    "crewops_run", default=None
)
_current_span: contextvars.ContextVar["Span | None"] = contextvars.ContextVar(
    "crewops_span", default=None
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: Any) -> str:
    try:
        blob = json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        blob = repr(value)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _short(value: Any, limit: int = 4000) -> Any:
    """Keep raw I/O inspectable without letting a 43-option list bloat a trace."""
    if isinstance(value, (str, bytes)):
        text = value if isinstance(value, str) else value.decode("utf-8", "replace")
        return text if len(text) <= limit else text[:limit] + f"... [{len(text)} chars]"
    if isinstance(value, list) and len(value) > 50:
        return value[:50] + [f"... [{len(value)} items total]"]
    if isinstance(value, dict):
        return {k: _short(v, limit) for k, v in value.items()}
    return value


@dataclass
class Span:
    span_id: str
    run_id: str
    parent_span_id: str | None
    name: str
    type: SpanType
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: float | None = None
    input: Any = None
    output: Any = None
    input_hash: str | None = None
    output_hash: str | None = None
    status: str = "running"
    error: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "run_id": self.run_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "type": self.type,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_ms": self.duration_ms,
            "input": _short(self.input),
            "output": _short(self.output),
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "status": self.status,
            "error": self.error,
            "attrs": self.attrs,
        }


@dataclass
class Fact:
    fact_id: str
    run_id: str
    key: str
    value: Any
    source_span_id: str | None
    source_tool: str | None
    unit: str = ""
    citation: str = ""

    def as_dict(self) -> dict:
        return {
            "fact_id": self.fact_id,
            "key": self.key,
            "value": self.value,
            "unit": self.unit,
            "source_span_id": self.source_span_id,
            "source_tool": self.source_tool,
            "citation": self.citation,
        }


@dataclass
class RunTrace:
    run_id: str
    started_at: datetime
    question: str = ""
    conversation_id: str | None = None
    spans: list[Span] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    rule_evaluations: list[dict] = field(default_factory=list)
    ended_at: datetime | None = None
    status: str = "running"
    metadata: dict[str, Any] = field(default_factory=dict)

    # ---- derived ------------------------------------------------------
    @property
    def duration_ms(self) -> float | None:
        if self.ended_at is None:
            return None
        return round((self.ended_at - self.started_at).total_seconds() * 1000, 2)

    @property
    def tool_calls(self) -> list[Span]:
        return [s for s in self.spans if s.type == "tool"]

    @property
    def llm_calls(self) -> list[Span]:
        return [s for s in self.spans if s.type == "llm"]

    def token_usage(self) -> dict[str, int]:
        return {
            "input": sum(int(s.attrs.get("tokens_in", 0)) for s in self.llm_calls),
            "output": sum(int(s.attrs.get("tokens_out", 0)) for s in self.llm_calls),
        }

    def fact_values(self) -> list[Any]:
        return [f.value for f in self.facts]

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "question": self.question,
            "conversation_id": self.conversation_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_ms": self.duration_ms,
            # Same number under the name the API and UI use, so a run served
            # from the live buffer and one read back from Postgres agree.
            "latency_ms": self.duration_ms,
            "status": self.status,
            "span_count": len(self.spans),
            "tool_call_count": len(self.tool_calls),
            "llm_call_count": len(self.llm_calls),
            "fact_count": len(self.facts),
            "rule_evaluation_count": len(self.rule_evaluations),
            "tokens": self.token_usage(),
            **self.metadata,
        }

    def as_dict(self) -> dict:
        return {
            **self.summary(),
            "spans": [s.as_dict() for s in self.spans],
            "facts": [f.as_dict() for f in self.facts],
            "rule_evaluations": self.rule_evaluations,
        }

    def waterfall(self) -> list[dict]:
        """Spans flattened with depth + relative offset, ready to draw."""
        by_parent: dict[str | None, list[Span]] = {}
        for span in self.spans:
            by_parent.setdefault(span.parent_span_id, []).append(span)

        origin = self.started_at
        rows: list[dict] = []

        def walk(parent: str | None, depth: int) -> None:
            for span in sorted(by_parent.get(parent, []), key=lambda s: s.started_at):
                rows.append(
                    {
                        **span.as_dict(),
                        "depth": depth,
                        "offset_ms": round((span.started_at - origin).total_seconds() * 1000, 2),
                    }
                )
                walk(span.span_id, depth + 1)

        walk(None, 0)
        return rows


class Tracer:
    """Creates runs and spans, and fans them out to registered sinks."""

    def __init__(self) -> None:
        self._sinks: list[Any] = []

    def add_sink(self, sink: Any) -> None:
        self._sinks.append(sink)

    def _emit(self, event: str, payload: Any) -> None:
        for sink in self._sinks:
            try:
                sink.handle(event, payload)
            except Exception:  # noqa: BLE001 - observability must never break a run
                pass

    # ---- runs ---------------------------------------------------------
    @contextmanager
    def run(
        self, question: str = "", *, conversation_id: str | None = None, run_id: str | None = None
    ) -> Iterator[RunTrace]:
        trace = RunTrace(
            run_id=run_id or f"run_{uuid.uuid4().hex[:12]}",
            started_at=_now(),
            question=question,
            conversation_id=conversation_id,
        )
        run_token = _current_run.set(trace)
        span_token = _current_span.set(None)
        self._emit("run_start", trace)
        try:
            yield trace
            trace.status = "ok"
        except Exception as exc:  # noqa: BLE001
            trace.status = "error"
            trace.metadata["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            trace.ended_at = _now()
            _current_span.reset(span_token)
            _current_run.reset(run_token)
            self._emit("run_end", trace)

    # ---- spans --------------------------------------------------------
    @contextmanager
    def span(
        self, name: str, span_type: SpanType = "node", *, input: Any = None, **attrs: Any
    ) -> Iterator[Span]:
        trace = _current_run.get()
        if trace is None:
            # Tracing is optional: core code can run outside a run context.
            yield Span("span_untraced", "run_untraced", None, name, span_type, _now())
            return

        parent = _current_span.get()
        span = Span(
            span_id=f"sp_{uuid.uuid4().hex[:12]}",
            run_id=trace.run_id,
            parent_span_id=parent.span_id if parent else None,
            name=name,
            type=span_type,
            started_at=_now(),
            input=input,
            input_hash=_hash(input) if input is not None else None,
            attrs=dict(attrs),
        )
        trace.spans.append(span)
        token = _current_span.set(span)
        started = time.perf_counter()
        self._emit("span_start", span)
        try:
            yield span
            span.status = "ok"
        except Exception as exc:  # noqa: BLE001
            span.status = "error"
            span.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            span.ended_at = _now()
            span.duration_ms = round((time.perf_counter() - started) * 1000, 2)
            if span.output is not None:
                span.output_hash = _hash(span.output)
            _current_span.reset(token)
            self._emit("span_end", span)

    # ---- ledger -------------------------------------------------------
    def record_fact(
        self, key: str, value: Any, *, unit: str = "", citation: str = "", tool: str | None = None
    ) -> Fact | None:
        trace = _current_run.get()
        if trace is None:
            return None
        span = _current_span.get()
        fact = Fact(
            fact_id=f"f_{len(trace.facts) + 1:04d}",
            run_id=trace.run_id,
            key=key,
            value=value,
            source_span_id=span.span_id if span else None,
            source_tool=tool or (span.name if span else None),
            unit=unit,
            citation=citation,
        )
        trace.facts.append(fact)
        self._emit("fact", fact)
        return fact

    def record_facts_from(self, payload: Any, *, prefix: str = "", tool: str | None = None) -> int:
        """Harvest every scalar in a tool result into the ledger.

        Deliberately exhaustive rather than curated: the verifier's job is to
        prove the narration said nothing the tools did not produce, so the
        ledger must contain everything the tools *did* produce.
        """
        count = 0

        def walk(node: Any, path: str) -> None:
            nonlocal count
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, f"{path}.{k}" if path else str(k))
            elif isinstance(node, (list, tuple)):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")
            elif isinstance(node, (int, float, str, bool)) and node is not None:
                self.record_fact(path, node, tool=tool)
                count += 1

        walk(payload, prefix)
        return count

    def harvest_rule_evaluations(self, payload: Any, _depth: int = 0) -> int:
        """Pull every RuleVerdict out of a nested result and log it.

        Verdicts turn up at several depths -- top level for a legality check,
        inside each option and each excluded candidate for the enumeration
        routines -- and all of them belong in the run's rule-evaluation log.
        """
        if _depth > 6:
            return 0
        found: list[dict] = []

        def walk(node: Any, depth: int) -> None:
            if depth > 6:
                return
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "verdicts" and isinstance(value, list):
                        found.extend(v for v in value if isinstance(v, dict) and "rule_id" in v)
                    else:
                        walk(value, depth + 1)
            elif isinstance(node, list):
                for item in node:
                    walk(item, depth + 1)

        walk(payload, _depth)
        if found:
            self.record_rule_evaluations(found)
        return len(found)

    def record_rule_evaluations(self, verdicts: list[dict]) -> None:
        trace = _current_run.get()
        if trace is None:
            return
        span = _current_span.get()
        for verdict in verdicts:
            row = {**verdict, "span_id": span.span_id if span else None}
            trace.rule_evaluations.append(row)
            self._emit("rule_evaluation", row)

    # ---- helpers ------------------------------------------------------
    @property
    def current_run(self) -> RunTrace | None:
        return _current_run.get()

    @property
    def current_span(self) -> Span | None:
        return _current_span.get()


#: Process-wide tracer. Sinks are attached at application start-up.
TRACER = Tracer()
