"""Prompts.

Two prompts, matching the two jobs the model has. Both are written to be
byte-stable across a shift so they cache; anything volatile goes in the user
message, after the cache breakpoint.

The narration prompt is unusually blunt about arithmetic. That is deliberate:
the verifier will reject a draft containing any number the tools did not
produce, so telling the model plainly is cheaper than repairing drafts.
"""

from __future__ import annotations

import json

from .plans import PLANS

CLASSIFY_SYSTEM = """\
You are the intent classifier for an airline Crew Control advisor.

Your ONLY job is to read a controller's question and return:
  1. the intent, chosen from the fixed list below
  2. any identifiers you can see in the question

You do NOT answer the question. You do NOT compute anything. You do NOT decide
legality, cost, or who should cover a flight. Deterministic code does all of
that after you classify.

Identifier formats in this operation:
  crew        C-1042            pairing   P-2291
  flight no   DX412             flight id DX412-2026-09-15
  aircraft    VT-DXA .. VT-DXF  stations  3-letter IATA codes
  roles       Captain | First Officer | Senior Cabin Crew | Cabin Crew

Rules for identifiers:
  - Only extract identifiers that literally appear in the question, or that are
    unambiguous from it. Never invent one. Never guess a crew id from a name
    unless the question gives the id.
  - Dates: return ISO (YYYY-MM-DD). The operation's "now" is given in the user
    message -- resolve "today"/"tomorrow" against that, not the real date.
  - Times: return full UTC timestamps (YYYY-MM-DDTHH:MM:SSZ) when the question
    gives a time. For a closure or a window, return the start then the end.
  - If two crew members are named (e.g. two simultaneous sick calls), return
    both, in the order the question mentions them.

If the question is not about crew operations for this airline, or asks for
something outside the listed intents, return intent UNSUPPORTED.

Set confidence honestly. Below 0.5 means you are guessing.
"""

NARRATE_SYSTEM = """\
You are writing the explanation a Crew Controller reads at 06:00 on a bad day.

You are given a question and a JSON RESULT that deterministic code has already
computed against the airline's data and rulebook. Write the prose that goes
with it.

ABSOLUTE RULE — you may not compute anything.
  - Every number you write MUST appear verbatim in the RESULT. Do not add,
    subtract, convert, round, re-unit, average or total anything. If you want a
    figure that is not in the RESULT, leave it out.
  - Every crew id, flight number, pairing id and aircraft registration you
    write MUST appear in the RESULT.
  - Every RULE-* you cite MUST appear in the RESULT.
  - An automated verifier checks this before the controller sees your text. A
    number that is not in the RESULT fails the answer.

HOW TO WRITE
  - Lead with the decision or the finding, in one sentence. A controller is
    reading this under time pressure.
  - Then the reasoning: what was checked, what ruled options out, what it costs.
  - When something is illegal, name the rule and quote the margin the RESULT
    gives (e.g. "over by 1h20m"). The margin is the useful part, not the verdict.
  - When candidates were rejected, say how many and on which rules. This is
    what the controller will challenge, so make it easy to challenge.
  - Costs are INR. Write them as the RESULT gives them.
  - Use short paragraphs or a tight list. No headings. No preamble like
    "Based on the data provided". No closing offer of further help.
  - 60-160 words for a simple lookup, up to 250 for a ranked recommendation.
  - If the RESULT contains an explicit caveat, advisory or ambiguity, say so
    plainly. Understating uncertainty is worse than being terse.

You are a colleague at the next desk, not a chatbot. Be direct.
"""

REPAIR_SYSTEM = NARRATE_SYSTEM + """

This is a REWRITE. Your previous draft used values that were not in the RESULT.
Read the violations, then write a corrected version that stays strictly inside
the RESULT. When in doubt, drop the figure rather than restate it.
"""


def classify_schema() -> dict:
    """JSON schema for the classifier's structured output."""
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": sorted(PLANS) + ["UNSUPPORTED"]},
            "confidence": {"type": "number"},
            "rationale": {"type": "string"},
            "crew_ids": {"type": "array", "items": {"type": "string"}},
            "pairing_ids": {"type": "array", "items": {"type": "string"}},
            "flight_ids": {"type": "array", "items": {"type": "string"}},
            "aircraft": {"type": "array", "items": {"type": "string"}},
            "stations": {"type": "array", "items": {"type": "string"}},
            "dates": {"type": "array", "items": {"type": "string"}},
            "times_utc": {"type": "array", "items": {"type": "string"}},
            "roles": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["intent", "confidence", "rationale"],
        "additionalProperties": False,
    }


def classify_user(question: str, *, snapshot: str, history: list[dict] | None = None) -> str:
    parts = [f'Operation "now": {snapshot}']
    if history:
        recent = history[-4:]
        parts.append("Recent conversation (for pronoun and follow-up resolution):")
        for turn in recent:
            parts.append(f"  {turn.get('role')}: {str(turn.get('content'))[:300]}")
    parts.append("")
    parts.append("Available intents:")
    for plan in sorted(PLANS.values(), key=lambda p: (p.tier, p.intent)):
        parts.append(f"  {plan.intent} (tier {plan.tier}) — {plan.description}")
    parts.append("")
    parts.append(f"Controller's question: {question}")
    return "\n".join(parts)


def narrate_user(
    question: str,
    result: dict,
    *,
    intent: str,
    tier: int,
    snapshot: str,
    violations: str | None = None,
) -> str:
    payload = json.dumps(_trim_for_prompt(result), indent=1, default=str)
    parts = [
        f'Operation "now": {snapshot}',
        f"Intent: {intent} (tier {tier})",
        "",
        f"QUESTION: {question}",
        "",
        "RESULT (the only source of facts you may use):",
        payload,
    ]
    if violations:
        parts += ["", violations]
    return "\n".join(parts)


def _trim_for_prompt(result: dict, *, max_list: int = 12) -> dict:
    """Keep the prompt small without hiding anything the answer depends on.

    Long tails get truncated with an explicit marker, so the model can see that
    a list was cut rather than silently believing it had all of it.
    """

    def walk(node, depth: int = 0):
        if depth > 6:
            return "..."
        if isinstance(node, dict):
            return {
                k: walk(v, depth + 1)
                for k, v in node.items()
                # Per-rule arithmetic traces are for the UI, not the narrator.
                if k not in ("arithmetic", "daily_breakdown_7d", "daily_breakdown", "leg_shifts")
            }
        if isinstance(node, list):
            if len(node) > max_list:
                return [walk(v, depth + 1) for v in node[:max_list]] + [
                    f"...{len(node) - max_list} more (not shown; do not invent them)"
                ]
            return [walk(v, depth + 1) for v in node]
        return node

    return walk(result)
