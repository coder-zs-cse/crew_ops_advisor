"""Run the advisor: one question in, one verified answer plus its trace out."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.world import World
from ..obs.tracer import TRACER, RunTrace
from .graph import build_graph, run_sequential
from .state import AdvisorState


@dataclass
class AdvisorAnswer:
    run_id: str
    question: str
    narration: str
    structured: dict | None
    intent: dict | None
    entities: dict
    tier: int | None
    citations: list[str]
    verification: dict | None
    abstained: bool
    plan: list[dict]
    plan_source: str
    tool_calls: list[dict]
    latency_ms: float | None
    trace: RunTrace

    def as_dict(self, *, include_trace: bool = False) -> dict:
        payload = {
            "run_id": self.run_id,
            "question": self.question,
            "answer": self.narration,
            "structured": self.structured,
            "intent": self.intent,
            "entities": self.entities,
            "tier": self.tier,
            "citations": self.citations,
            "verification": self.verification,
            "abstained": self.abstained,
            "plan": self.plan,
            "plan_source": self.plan_source,
            "tool_calls": self.tool_calls,
            "latency_ms": self.latency_ms,
            "trace_summary": self.trace.summary(),
        }
        if include_trace:
            payload["trace"] = self.trace.as_dict()
        return payload


class Advisor:
    """Holds the compiled graph and the world snapshot."""

    def __init__(self, world: World) -> None:
        self.world = world
        self._graph = build_graph(world)

    @property
    def engine(self) -> str:
        return "langgraph" if self._graph is not None else "sequential"

    def ask(
        self,
        question: str,
        *,
        conversation_id: str | None = None,
        history: list[dict] | None = None,
        run_id: str | None = None,
    ) -> AdvisorAnswer:
        initial: AdvisorState = {
            "question": question,
            "conversation_id": conversation_id,
            "history": history or [],
        }

        with TRACER.run(question, conversation_id=conversation_id, run_id=run_id) as trace:
            initial["run_id"] = trace.run_id
            # The "operation now" timestamp is given to the model as trusted
            # context (it's in the narrate prompt), not something a tool
            # produced -- without this, a model that reasonably echoes today's
            # date gets flagged by the numeric-provenance check as if it had
            # invented the number, forcing a pointless repair/downgrade cycle.
            TRACER.record_fact(
                "world.snapshot_utc",
                self.world.snapshot_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                tool="world",
            )
            with TRACER.span("advisor", "graph", input={"engine": self.engine}):
                if self._graph is not None:
                    final: Any = self._graph.invoke(initial)
                else:
                    final = run_sequential(dict(initial), self.world)

        intent = final.get("intent")
        entities = final.get("entities")
        verification = final.get("verification")
        structured = final.get("structured_answer")

        return AdvisorAnswer(
            run_id=trace.run_id,
            question=question,
            narration=final.get("narration") or "",
            structured=structured,
            intent=intent.as_dict() if intent else None,
            entities=entities.as_dict() if entities else {},
            tier=(structured or {}).get("tier") or (intent.tier if intent else None),
            citations=final.get("citations") or [],
            verification=verification.as_dict() if verification else None,
            abstained=final.get("abstention") is not None,
            plan=final.get("plan") or [],
            plan_source=final.get("plan_source", "none"),
            tool_calls=[c.as_dict() for c in (final.get("tool_calls") or [])],
            latency_ms=trace.duration_ms,
            trace=trace,
        )
