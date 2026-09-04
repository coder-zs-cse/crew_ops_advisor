"""The LangGraph.

    ingest → classify → resolve → route ─┬→ abstain ──────────────┐
                                         ├→ clarify ──────────────┤
                                         └→ plan → execute →      │
                                            compose → narrate →   │
                                            verify ─┬→ repair ────┤
                                                    └→ finalise ←─┘

Design notes:

* **classify** consults the deterministic pattern router first, then asks the
  model. The model can override, but only above a confidence floor, and the
  router's answer is recorded either way -- so a disagreement is visible in the
  trace rather than silent.
* **resolve** validates every identifier against the world. The model proposes;
  this node decides.
* **plan** looks up a compiled plan. Free-form LLM tool selection is the
  fallback, not the default (see plans.py for why).
* **compose** is pure code. The structured answer never passes through a model.
* **verify** gates the prose. Two failures downgrade to the template narration
  with an honest note, rather than shipping an unverified number.

Falls back to a hand-rolled sequential executor if langgraph is not installed,
so the service always starts.
"""

from __future__ import annotations

import time
from typing import Any

from ..core.world import World
from ..obs.tracer import TRACER
from ..tools import REGISTRY
from ..tools.registry import call as call_tool
from .compose import compose, template_narration
from .entities import describe_gap, resolve
from .llm import get_client
from .plans import Plan, plan_for, route
from .prompts import (
    NARRATE_SYSTEM,
    REPAIR_SYSTEM,
    classify_schema,
    classify_user,
    narrate_user,
)
from .state import Abstention, AdvisorState, Entities, Intent, ToolCall, VerificationReport
from .verify import verify_narration, violations_prompt

#: Below this the pattern router's answer is treated as a guess.
ROUTER_FLOOR = 0.35
#: The model must beat the router by this much to override it.
LLM_OVERRIDE_MARGIN = 0.15
MAX_REPAIRS = 1


# ==========================================================================
# Nodes
# ==========================================================================


def node_ingest(state: AdvisorState, world: World) -> dict:
    with TRACER.span("ingest", "node", input={"question": state["question"]}) as span:
        span.output = {"history_turns": len(state.get("history") or [])}
        return {"tool_calls": [], "results": {}, "repair_attempts": 0, "citations": []}


def node_classify(state: AdvisorState, world: World) -> dict:
    question = state["question"]
    with TRACER.span("classify_intent", "node", input={"question": question}) as span:
        # 1. Deterministic router -- always runs, always recorded.
        preliminary = resolve(question, world)
        routed = route(question, preliminary)
        span.attrs["router_intent"] = routed.name
        span.attrs["router_confidence"] = routed.confidence

        chosen = routed
        proposed: dict = {}

        # 2. Model classification -- may override, above a margin.
        client = get_client()
        if client.available:
            parsed = client.classify(
                system=__import__(
                    "app.agent.prompts", fromlist=["CLASSIFY_SYSTEM"]
                ).CLASSIFY_SYSTEM,
                user=classify_user(
                    question,
                    snapshot=world.snapshot_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    history=state.get("history"),
                ),
                schema=classify_schema(),
            )
            if parsed and parsed.get("intent"):
                proposed = parsed
                llm_confidence = float(parsed.get("confidence", 0.0))
                span.attrs["llm_intent"] = parsed["intent"]
                span.attrs["llm_confidence"] = llm_confidence
                plan = plan_for(parsed["intent"])
                overrides = (
                    parsed["intent"] != routed.name
                    and llm_confidence >= routed.confidence + LLM_OVERRIDE_MARGIN
                ) or routed.confidence < ROUTER_FLOOR
                if overrides and (plan or parsed["intent"] == "UNSUPPORTED"):
                    chosen = Intent(
                        name=parsed["intent"],
                        tier=plan.tier if plan else 1,
                        confidence=llm_confidence,
                        source="llm",
                        rationale=parsed.get("rationale", ""),
                    )
                    span.attrs["overrode_router"] = True

        span.output = {"intent": chosen.as_dict()}
        return {"intent": chosen, "_proposed": proposed}


def node_resolve(state: AdvisorState, world: World) -> dict:
    with TRACER.span("resolve_entities", "node") as span:
        entities = resolve(state["question"], world, proposed=state.get("_proposed") or {})
        span.output = entities.as_dict()
        span.attrs["unresolved"] = len(entities.unresolved)
        span.attrs["ambiguous"] = len(entities.ambiguous)
        return {"entities": entities}


def route_decision(state: AdvisorState) -> str:
    intent: Intent | None = state.get("intent")
    entities: Entities = state.get("entities") or Entities()

    if intent is None or intent.name == "UNSUPPORTED":
        return "abstain"
    plan = plan_for(intent.name)
    if plan is None:
        return "abstain"
    # A judgement the ruleset does not encode, or a question with two distinct
    # readings, must not be silently reduced to whichever half we can compute.
    if intent.policy_question or intent.compound:
        return "clarify"
    if entities.unresolved:
        return "clarify"
    if describe_gap(entities, list(plan.needs)):
        return "clarify"
    return "plan"


def node_abstain(state: AdvisorState, world: World) -> dict:
    with TRACER.span("abstain", "node") as span:
        capabilities = call_tool("list_supported_capabilities", world)
        abstention = Abstention(
            reason=(
                "That is outside what I can compute reliably from this dataset, so I would "
                "rather say so than guess."
            ),
            missing=[],
            suggestions=capabilities.get("can_answer", [])[:5],
            capabilities=capabilities,
        )
        span.output = abstention.as_dict()
        return {
            "abstention": abstention,
            "structured_answer": {"schema": "abstention", **abstention.as_dict()},
            "narration": _abstain_text(abstention),
        }


def node_clarify(state: AdvisorState, world: World) -> dict:
    intent: Intent = state["intent"]
    entities: Entities = state["entities"]
    plan = plan_for(intent.name)
    missing = describe_gap(entities, list(plan.needs)) if plan else []

    with TRACER.span("clarify", "node") as span:
        span.attrs.update({"compound": intent.compound, "policy": intent.policy_question})

        if intent.policy_question:
            abstention = Abstention(
                reason=(
                    "That is a policy call the rulebook does not encode. I can compute every "
                    "input to it, but the seven rules give me no threshold for the decision "
                    "itself, so I will not invent one."
                ),
                missing=["a policy threshold this ruleset does not define"],
                suggestions=[
                    "I can tell you the crew member's disruption-risk score and its drivers.",
                    "I can tell you their remaining duty and block-hour headroom.",
                    "I can price and rank every legal cover option, so you can see what the "
                    "swap would cost before you decide.",
                    "Ask me any of those and the judgement stays yours.",
                ],
            )
        elif intent.compound:
            readings = [
                f"{intent.name.replace('_', ' ').lower()}",
                *([intent.runner_up[0].replace("_", " ").lower()] if intent.runner_up else []),
            ]
            abstention = Abstention(
                reason=(
                    "That question has more than one part, and I model each part separately "
                    "rather than together. Answering only one of them and sounding certain "
                    "would be the worst outcome, so I would rather split it."
                ),
                missing=["a single disruption per question"],
                suggestions=[
                    f"I read it as: {' — and — '.join(readings)}.",
                    "Ask each part on its own and I will answer both exactly.",
                    "For genuinely compound disruptions, the Workbench chains them: run the "
                    "first event, then apply the second to the world it produced.",
                ],
            )
        else:
            questions = [_slot_question(slot, world) for slot in missing]
            for item in entities.unresolved:
                questions.append(
                    f"I could not find {item['kind']} {item['value']!r} in the dataset — "
                    f"can you check the identifier?"
                )
            abstention = Abstention(
                reason="I need one more detail before I can answer this without guessing.",
                missing=missing or [u["kind"] for u in entities.unresolved],
                suggestions=questions,
            )
        span.output = abstention.as_dict()
        return {
            "abstention": abstention,
            "structured_answer": {
                "schema": "clarification",
                "intent": intent.name,
                **abstention.as_dict(),
            },
            "narration": "\n".join(
                [abstention.reason, "", *(f"- {s}" for s in abstention.suggestions)]
            ),
        }


def node_plan(state: AdvisorState, world: World) -> dict:
    intent: Intent = state["intent"]
    entities: Entities = state["entities"]
    plan: Plan = plan_for(intent.name)

    with TRACER.span("plan", "node") as span:
        steps = []
        for step in plan.steps:
            if not step.applies(entities):
                continue
            args = {k: v for k, v in step.build_args(entities).items() if v is not None}
            steps.append({"tool": step.tool, "args": args})
        span.attrs["plan_source"] = "compiled"
        span.attrs["step_count"] = len(steps)
        span.output = steps
        return {"plan": steps, "plan_source": "compiled"}


def node_execute(state: AdvisorState, world: World) -> dict:
    calls: list[ToolCall] = []
    results: dict[str, Any] = {}

    with TRACER.span("execute_tools", "node") as span:
        for step in state["plan"]:
            started = time.perf_counter()
            record = ToolCall(tool=step["tool"], args=step["args"])
            try:
                if step["tool"] not in REGISTRY:
                    raise KeyError(f"unknown tool {step['tool']}")
                record.result = call_tool(step["tool"], world, **step["args"])
                results[step["tool"]] = record.result
            except Exception as exc:  # noqa: BLE001 - reported, not raised
                record.error = f"{type(exc).__name__}: {exc}"
            record.duration_ms = round((time.perf_counter() - started) * 1000, 2)
            calls.append(record)

        span.attrs["tools_run"] = len(calls)
        span.attrs["tools_failed"] = sum(1 for c in calls if c.error)
        span.output = [c.as_dict() for c in calls]
        return {"tool_calls": calls, "results": results}


def node_compose(state: AdvisorState, world: World) -> dict:
    intent: Intent = state["intent"]
    plan: Plan = plan_for(intent.name)

    with TRACER.span("compose_answer", "node") as span:
        answer = compose(
            intent.name,
            plan.answer_schema,
            state["results"],
            world.snapshot_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        answer["tier"] = plan.tier
        answer["confidence"] = intent.confidence
        span.output = {"schema": answer.get("schema"), "headline": answer.get("headline")}
        return {"structured_answer": answer, "citations": answer.get("citations", [])}


def node_narrate(state: AdvisorState, world: World) -> dict:
    answer = state["structured_answer"] or {}
    intent: Intent = state["intent"]
    fallback = template_narration(answer)

    with TRACER.span("narrate", "node") as span:
        client = get_client()
        if not client.available:
            span.attrs["source"] = "template"
            span.output = {"chars": len(fallback)}
            return {"narration": fallback, "narration_source": "template"}

        repairing = state.get("repair_attempts", 0) > 0
        violations = None
        if repairing and state.get("verification"):
            violations = violations_prompt(state["verification"])

        text = client.narrate(
            system=REPAIR_SYSTEM if repairing else NARRATE_SYSTEM,
            user=narrate_user(
                state["question"],
                answer,
                intent=intent.name,
                tier=answer.get("tier", intent.tier),
                snapshot=world.snapshot_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                violations=violations,
            ),
        )
        source = "llm" if text else "template"
        span.attrs["source"] = source
        span.output = {"chars": len(text or fallback)}
        return {"narration": text or fallback, "narration_source": source}


def node_verify(state: AdvisorState, world: World) -> dict:
    trace = TRACER.current_run
    with TRACER.span("verify", "node") as span:
        if trace is None:
            report = VerificationReport(passed=True, checks=[])
        else:
            report = verify_narration(
                state.get("narration") or "",
                trace,
                question=state["question"],
                structured=state.get("structured_answer"),
                cited_rules=state.get("citations") or [],
            )
        report.repair_attempts = state.get("repair_attempts", 0)
        span.attrs["passed"] = report.passed
        span.attrs["violations"] = len(report.violations)
        span.output = report.as_dict()
        return {"verification": report}


def verify_decision(state: AdvisorState) -> str:
    report: VerificationReport | None = state.get("verification")
    if report is None or report.passed:
        return "finalise"
    if state.get("repair_attempts", 0) < MAX_REPAIRS:
        return "repair"
    return "downgrade"


def node_repair(state: AdvisorState, world: World) -> dict:
    with TRACER.span("repair", "node") as span:
        attempts = state.get("repair_attempts", 0) + 1
        span.attrs["attempt"] = attempts
        return {"repair_attempts": attempts}


def node_downgrade(state: AdvisorState, world: World) -> dict:
    """Second failure: serve the computed answer, and say what happened.

    If the failing text was our own template rather than a model draft, that is
    a defect in this codebase, not an untrustworthy answer. It is flagged on the
    trace for us to fix; the controller is not told the model misbehaved when it
    never ran.
    """
    with TRACER.span("downgrade", "node") as span:
        answer = state.get("structured_answer") or {}
        report: VerificationReport = state["verification"]
        report.downgraded = True
        span.attrs["violations"] = len(report.violations)

        text = template_narration(answer)
        if state.get("narration_source") == "llm":
            text += (
                "\n\nNote: I drafted an explanation I could not verify against my own "
                "computations, so I have replaced it with the figures exactly as the "
                "engine produced them."
            )
        else:
            span.attrs["template_verification_gap"] = True
            span.attrs["ungrounded"] = [v["value"] for v in report.violations][:8]

        return {"narration": text, "verification": report}


def node_finalise(state: AdvisorState, world: World) -> dict:
    with TRACER.span("finalise", "node") as span:
        trace = TRACER.current_run
        if trace is not None:
            intent: Intent | None = state.get("intent")
            trace.metadata.update(
                {
                    "intent": intent.name if intent else None,
                    "tier": intent.tier if intent else None,
                    "confidence": intent.confidence if intent else None,
                    "plan_source": state.get("plan_source", "none"),
                    "abstained": state.get("abstention") is not None,
                    "verified": bool(
                        state.get("verification") and state["verification"].passed
                    ),
                }
            )
        span.output = {"narration_chars": len(state.get("narration") or "")}
        return {}


# ==========================================================================
# Helpers
# ==========================================================================


def _abstain_text(abstention: Abstention) -> str:
    lines = [abstention.reason, "", "What I can answer:"]
    lines += [f"- {s}" for s in abstention.suggestions]
    if abstention.capabilities:
        lines += ["", "What I deliberately do not answer:"]
        lines += [f"- {s}" for s in abstention.capabilities.get("cannot_answer", [])[:4]]
    return "\n".join(lines)


def _slot_question(slot: str, world: World) -> str:
    start, end = world.dates[0], world.dates[-1]
    return {
        "crew_id": "Which crew member? Give the id, e.g. C-1042.",
        "pairing_id": "Which pairing? Give the id (P-2291) or the aircraft and date.",
        "flight_id": "Which flight? Give the flight number and the date.",
        "date": f"Which date? The schedule covers {start} to {end}.",
        "station": "Which station? Use the three-letter code, e.g. BLR.",
        "aircraft": "Which aircraft? Use the registration, e.g. VT-DXA.",
        "time": "What time (UTC)? For a closure I need the start and end of the window.",
        "role": "Which role — Captain, First Officer, Senior Cabin Crew or Cabin Crew?",
    }.get(slot, f"I need the {slot}.")


# ==========================================================================
# Graph construction
# ==========================================================================


def build_graph(world: World):
    """Compile the LangGraph. Falls back to a sequential runner if unavailable."""
    try:
        from langgraph.graph import END, START, StateGraph  # noqa: PLC0415
    except ImportError:
        return None

    def bind(fn):
        def node(state: AdvisorState) -> dict:
            return fn(state, world)

        node.__name__ = fn.__name__
        return node

    graph = StateGraph(AdvisorState)
    graph.add_node("ingest", bind(node_ingest))
    graph.add_node("classify", bind(node_classify))
    graph.add_node("resolve", bind(node_resolve))
    graph.add_node("abstain", bind(node_abstain))
    graph.add_node("clarify", bind(node_clarify))
    graph.add_node("plan", bind(node_plan))
    graph.add_node("execute", bind(node_execute))
    graph.add_node("compose", bind(node_compose))
    graph.add_node("narrate", bind(node_narrate))
    graph.add_node("verify", bind(node_verify))
    graph.add_node("repair", bind(node_repair))
    graph.add_node("downgrade", bind(node_downgrade))
    graph.add_node("finalise", bind(node_finalise))

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "classify")
    graph.add_edge("classify", "resolve")
    graph.add_conditional_edges(
        "resolve",
        route_decision,
        {"abstain": "abstain", "clarify": "clarify", "plan": "plan"},
    )
    graph.add_edge("abstain", "finalise")
    graph.add_edge("clarify", "finalise")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "compose")
    graph.add_edge("compose", "narrate")
    graph.add_edge("narrate", "verify")
    graph.add_conditional_edges(
        "verify",
        verify_decision,
        {"finalise": "finalise", "repair": "repair", "downgrade": "downgrade"},
    )
    graph.add_edge("repair", "narrate")
    graph.add_edge("downgrade", "finalise")
    graph.add_edge("finalise", END)

    return graph.compile()


def run_sequential(state: AdvisorState, world: World) -> AdvisorState:
    """The same graph, hand-rolled. Used when langgraph is not installed."""
    state.update(node_ingest(state, world))
    state.update(node_classify(state, world))
    state.update(node_resolve(state, world))

    branch = route_decision(state)
    if branch == "abstain":
        state.update(node_abstain(state, world))
    elif branch == "clarify":
        state.update(node_clarify(state, world))
    else:
        state.update(node_plan(state, world))
        state.update(node_execute(state, world))
        state.update(node_compose(state, world))
        while True:
            state.update(node_narrate(state, world))
            state.update(node_verify(state, world))
            decision = verify_decision(state)
            if decision == "repair":
                state.update(node_repair(state, world))
                continue
            if decision == "downgrade":
                state.update(node_downgrade(state, world))
            break

    state.update(node_finalise(state, world))
    return state
