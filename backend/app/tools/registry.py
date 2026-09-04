"""Tool registry.

A tool is a thin, typed, side-effect-free wrapper over ``app.core``. Tools do
no arithmetic of their own -- if you find yourself computing something here,
it belongs in the core, where the conformance harness can see it.

Every call is traced and every scalar it returns lands in the run's fact
ledger, which is what makes the narration verifier possible.
"""

from __future__ import annotations

import functools
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from ..obs.tracer import TRACER

ToolFn = Callable[..., dict]


@dataclass
class ToolSpec:
    name: str
    description: str
    tier: int
    fn: ToolFn
    citations: tuple[str, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)
    category: str = "general"

    def json_schema(self) -> dict:
        """OpenAI/Anthropic-style function schema for LLM tool selection."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters.get("properties", {}),
                "required": self.parameters.get("required", []),
            },
        }


REGISTRY: dict[str, ToolSpec] = {}


def tool(
    name: str,
    description: str,
    *,
    tier: int = 1,
    citations: tuple[str, ...] = (),
    category: str = "general",
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
):
    """Register a function as an agent tool, with tracing and fact harvesting."""

    def decorate(fn: ToolFn) -> ToolFn:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> dict:
            traced_args = {k: _jsonable(v) for k, v in kwargs.items()}
            with TRACER.span(name, "tool", input=traced_args, tier=tier) as span:
                result = fn(*args, **kwargs)
                payload = result if isinstance(result, dict) else {"value": result}
                span.output = payload
                span.attrs["result_summary"] = _summarise(payload)
                TRACER.record_facts_from(payload, prefix=name, tool=name)
                recorded = TRACER.harvest_rule_evaluations(payload)
                if recorded:
                    span.attrs["rule_evaluations"] = recorded
                if citations:
                    span.attrs["citations"] = list(citations)
                return payload

        REGISTRY[name] = ToolSpec(
            name=name,
            description=description,
            tier=tier,
            fn=wrapper,
            citations=citations,
            category=category,
            parameters={"properties": properties or {}, "required": required or []},
        )
        return wrapper

    return decorate


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _summarise(payload: dict) -> str:
    """One line a human can read in the live trace stream."""
    for key in ("count", "evaluated_count", "flight_count", "line_count"):
        if key in payload:
            extra = ""
            if "eligible_count" in payload:
                extra = f" -> {payload['eligible_count']} legal, {payload.get('excluded_count', 0)} excluded"
            return f"{key}={payload[key]}{extra}"
    if "legal" in payload:
        issues = payload.get("issues") or []
        return f"legal={payload['legal']}" + (f", {len(issues)} issue(s)" if issues else "")
    if "breach" in payload:
        return f"breach={payload['breach']}"
    keys = [k for k in payload if not k.startswith("_")][:4]
    return ", ".join(keys)


def get(name: str) -> ToolSpec:
    if name not in REGISTRY:
        raise KeyError(f"unknown tool {name!r}; available: {', '.join(sorted(REGISTRY))}")
    return REGISTRY[name]


def call(name: str, world: Any, **kwargs: Any) -> dict:
    spec = get(name)
    sig = inspect.signature(spec.fn)
    accepted = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return spec.fn(world, **accepted)


def catalog(tier: int | None = None) -> list[dict]:
    return [
        {
            "name": s.name,
            "description": s.description,
            "tier": s.tier,
            "category": s.category,
            "citations": list(s.citations),
            "parameters": s.parameters,
        }
        for s in sorted(REGISTRY.values(), key=lambda s: (s.tier, s.category, s.name))
        if tier is None or s.tier == tier
    ]


def schemas(names: list[str] | None = None) -> list[dict]:
    specs = REGISTRY.values() if names is None else [get(n) for n in names]
    return [s.json_schema() for s in specs]
