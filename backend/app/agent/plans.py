"""Intent taxonomy, the pattern router, and the compiled plan library.

Why compiled plans instead of letting the model choose tools every time:

* **Latency.** A known intent costs one classification call and one narration
  call. Free-form tool selection costs a planning round-trip plus a turn per
  tool. On a live shift that is the difference between 2 seconds and 20.
* **Correctness.** For the question shapes we have graded against answer keys,
  the right tool sequence is *known*. Re-deriving it per request only creates
  opportunities to derive it wrong.
* **Auditability.** ``plan_source: "compiled"`` on a run means the tool path
  was fixed in advance and is in version control. That is a much stronger
  claim than "the model usually picks the right tools".

Free-form LLM planning remains the fallback for genuinely novel questions --
it is the exception, not the default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .state import Entities, Intent

# --------------------------------------------------------------------------
# Plan definition
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One tool call in a compiled plan.

    ``args`` maps tool parameter names to a callable over the resolved
    entities, so a plan is data plus tiny pure functions -- no branching logic
    hidden inside the executor.
    """

    tool: str
    args: dict[str, Callable[[Entities], Any]] = field(default_factory=dict)
    optional: bool = False
    when: Callable[[Entities], bool] | None = None

    def build_args(self, ents: Entities) -> dict:
        return {k: fn(ents) for k, fn in self.args.items()}

    def applies(self, ents: Entities) -> bool:
        return self.when is None or self.when(ents)


@dataclass(frozen=True)
class Plan:
    intent: str
    tier: int
    steps: tuple[Step, ...]
    needs: tuple[str, ...] = ()
    primary_tool: str | None = None
    answer_schema: str = "generic"
    description: str = ""


# shorthand accessors over Entities
C = lambda e: e.crew_id  # noqa: E731
P = lambda e: e.pairing_id  # noqa: E731
D = lambda e: e.date  # noqa: E731
S = lambda e: e.station  # noqa: E731
TAIL = lambda e: e.tail  # noqa: E731
ROLE = lambda e: e.roles[0] if e.roles else None  # noqa: E731
TIME = lambda e: e.times_utc[0] if e.times_utc else None  # noqa: E731
FIDS = lambda e: e.flight_ids  # noqa: E731
FNO = lambda e: e.flight_nos[0] if e.flight_nos else None  # noqa: E731
HOURS = lambda default: (lambda e: e.numbers[0] if e.numbers else default)  # noqa: E731


PLANS: dict[str, Plan] = {}


def register(plan: Plan) -> Plan:
    PLANS[plan.intent] = plan
    return plan


# --------------------------------------------------------------------------
# Tier 1 -- lookup
# --------------------------------------------------------------------------

register(Plan("CREW_LOOKUP", 1, (Step("get_crew", {"crew_id": C}),), ("crew_id",), "get_crew", "crew", "Who is this crew member?"))
register(Plan("CREW_SEARCH", 1, (Step("search_crew", {"rank": ROLE, "base": S}),), (), "search_crew", "crew_list", "Find crew by rank/base/rating."))
register(
    Plan(
        "ROSTER_LOOKUP",
        1,
        (Step("get_roster_for_crew", {"crew_id": C}), Step("get_crew", {"crew_id": C})),
        ("crew_id",),
        "get_roster_for_crew",
        "roster",
        "What is this crew member rostered to fly?",
    )
)
register(
    Plan(
        "DUTY_CLOCK",
        1,
        (Step("get_duty_clock", {"crew_id": C, "as_of": D}), Step("get_rule", {"rule_id": lambda e: "RULE-DUTY-02"})),
        ("crew_id",),
        "get_duty_clock",
        "duty_clock",
        "Duty/flight hours and headroom.",
    )
)
register(Plan("FLIGHT_LOOKUP", 1, (Step("get_flight", {"flight_no": FNO, "date": D, "flight_id": lambda e: e.flight_ids[0] if e.flight_ids else None}),), (), "get_flight", "flight", "One flight leg."))
register(Plan("FLIGHT_SEARCH", 1, (Step("search_flights", {"date": D, "dep_station": lambda e: e.stations[0] if e.stations else None, "arr_station": lambda e: e.stations[1] if len(e.stations) > 1 else None, "aircraft": TAIL}),), (), "search_flights", "flight_list", "Flights by date/route/tail."))
register(Plan("PAIRING_LOOKUP", 1, (Step("get_pairing", {"pairing_id": P, "aircraft": TAIL, "date": D}),), (), "get_pairing", "pairing", "A pairing and its crew."))
register(Plan("RESERVE_LIST", 1, (Step("get_reserves", {"date": D, "base": S, "rank": ROLE, "covering_report_utc": TIME}),), ("date",), "get_reserves", "reserve_list", "Who is on reserve."))
register(Plan("CERT_EXPIRY_LIST", 1, (Step("get_certifications", {"as_of": D, "within_days": lambda e: int(e.numbers[0]) if e.numbers else 30, "crew_id": C}),), (), "get_certifications", "cert_list", "Expiring certifications."))
register(Plan("RISK_LOOKUP", 1, (Step("get_risk_signal", {"crew_id": C}),), (), "get_risk_signal", "risk", "Disruption-risk signal."))
register(Plan("RULE_LOOKUP", 1, (Step("get_rule", {"rule_id": lambda e: e.rule_ids[0] if e.rule_ids else None}),), (), "get_rule", "rules", "The legality ruleset."))
register(Plan("COST_LOOKUP", 1, (Step("get_costs"),), (), "get_costs", "costs", "The cost rate card."))
register(Plan("NETWORK_SUMMARY", 1, (Step("network_summary", {"date": D, "from_station": S}),), (), "network_summary", "network", "Network-level facts."))
register(Plan("CAPABILITIES", 1, (Step("list_supported_capabilities"),), (), "list_supported_capabilities", "capabilities", "What this advisor can answer."))

# --------------------------------------------------------------------------
# Tier 2 -- consequence
# --------------------------------------------------------------------------

register(
    Plan(
        "SICK_IMPACT",
        2,
        (
            Step("simulate_crew_unavailable", {"crew_id": C, "pairing_id": P, "reported_utc": TIME}),
            Step("get_crew", {"crew_id": C}),
        ),
        ("crew_id",),
        "simulate_crew_unavailable",
        "impact",
        "Which flights are now uncrewed?",
    )
)
register(
    Plan(
        "LEGALITY_CHECK",
        2,
        (
            Step("check_legality", {"crew_id": C, "pairing_id": P}),
            Step("get_duty_clock", {"crew_id": C, "as_of": D}),
        ),
        ("crew_id", "pairing_id"),
        "check_legality",
        "legality",
        "Can this crew member legally take this duty?",
    )
)
register(
    Plan(
        "ASSIGNMENT_WHATIF",
        2,
        (Step("simulate_assignment", {"crew_id": C, "pairing_id": P}),),
        ("crew_id", "pairing_id"),
        "simulate_assignment",
        "legality",
        "If I move X onto Y, does anything breach?",
    )
)
register(
    Plan(
        "STATION_CLOSURE",
        2,
        (
            Step(
                "simulate_station_closure",
                {
                    "station": S,
                    "start_utc": lambda e: e.times_utc[0] if e.times_utc else None,
                    "end_utc": lambda e: e.times_utc[1] if len(e.times_utc) > 1 else None,
                },
            ),
        ),
        ("station", "time"),
        "simulate_station_closure",
        "closure",
        "Crew impact of a station closure.",
    )
)
register(
    Plan(
        "DELAY_IMPACT",
        2,
        (Step("simulate_delay", {"aircraft": TAIL, "date": D, "delay_hours": HOURS(1.5)}),),
        ("aircraft", "date"),
        "simulate_delay",
        "delay",
        "Does a delay bust the crew's FDP?",
    )
)
register(
    Plan(
        "CANCELLATION_IMPACT",
        2,
        (Step("simulate_cancellation", {"flight_ids": FIDS}),),
        ("flight_id",),
        "simulate_cancellation",
        "cancellation",
        "Passengers and cost of cancelling.",
    )
)
register(
    Plan(
        "REST_CALC",
        2,
        (Step("check_rest", {"release_utc": TIME}), Step("get_rule", {"rule_id": lambda e: "RULE-REST-04"})),
        ("time",),
        "check_rest",
        "rest",
        "Earliest legal next report.",
    )
)
register(
    Plan(
        "DUTY_SCAN",
        2,
        (Step("duty_window_scan", {"date": D, "threshold_hours": HOURS(45.0)}),),
        ("date",),
        "duty_window_scan",
        "duty_scan",
        "Who is near a duty limit.",
    )
)
register(
    Plan(
        "ROTATION_VIEW",
        2,
        (Step("propagate_rotation", {"aircraft": TAIL, "date": D}),),
        ("aircraft", "date"),
        "propagate_rotation",
        "rotation",
        "The tail's rotation and turn times.",
    )
)

# --------------------------------------------------------------------------
# Tier 3 -- recommendation
# --------------------------------------------------------------------------

register(
    Plan(
        "COVER_RECOMMENDATION",
        3,
        (
            Step("resolve_disruption", {"crew_id": C, "pairing_id": P, "reported_utc": TIME}),
            Step("get_crew", {"crew_id": C}),
            Step("get_costs"),
        ),
        ("crew_id",),
        "resolve_disruption",
        "recommendation",
        "Ranked, priced, rule-checked resolution options.",
    )
)
register(
    Plan(
        "CANDIDATE_ENUMERATION",
        3,
        (Step("enumerate_cover_candidates", {"pairing_id": P, "role": ROLE, "sick_crew_id": C}),),
        ("pairing_id", "role"),
        "enumerate_cover_candidates",
        "recommendation",
        "Every candidate for an opening, with rejections.",
    )
)
def _joint_openings(e: Entities) -> list[dict]:
    """Pair each named crew member with their own pairing, in order."""
    return [
        {"pairing_id": pid, "sick_crew_id": cid}
        for cid, pid in zip(e.crew_ids, e.pairing_ids)
    ]


register(
    Plan(
        "JOINT_RECOMMENDATION",
        3,
        (Step("solve_joint_assignment", {"openings": _joint_openings}),),
        ("crew_id", "pairing_id"),
        "solve_joint_assignment",
        "joint_recommendation",
        "Optimal plan across simultaneous openings competing for one pool.",
    )
)
register(
    Plan(
        "DELAY_RECOMMENDATION",
        3,
        (Step("resolve_delay_breach", {"aircraft": TAIL, "date": D, "delay_hours": HOURS(1.5)}),),
        ("aircraft", "date"),
        "resolve_delay_breach",
        "recommendation",
        "What to do about an FDP breach caused by a delay.",
    )
)
register(
    Plan(
        "NOTIFICATION_DRAFT",
        3,
        (Step("draft_notification", {"crew_id": C, "pairing_id": P}),),
        ("crew_id", "pairing_id"),
        "draft_notification",
        "notification",
        "Draft the crew callout message.",
    )
)
register(
    Plan(
        "BRIEFING",
        3,
        (Step("morning_briefing", {"date": D}),),
        (),
        "morning_briefing",
        "briefing",
        "The standing morning briefing.",
    )
)

# --------------------------------------------------------------------------
# Pattern router
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    intent: str
    pattern: re.Pattern
    weight: float = 1.0
    requires: tuple[str, ...] = ()


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


ROUTER_RULES: tuple[Rule, ...] = (
    # Tier 3 first: recommendation language beats the lookup it contains.
    Rule("COVER_RECOMMENDATION", _rx(r"what should i do|what do i do|recommend|resolution options|ranked options|best (option|replacement)|resolve (their|the|this)|options with cost"), 1.3),
    Rule("COVER_RECOMMENDATION", _rx(r"\b(sick|unavailable|out|calls? in sick|called in sick|off sick)\b.*\b(what|who|cover|replace|options?)\b"), 1.2),
    Rule("COVER_RECOMMENDATION", _rx(r"cheapest (legal )?way to cover|who (can|should) cover"), 1.3),
    Rule("JOINT_RECOMMENDATION", _rx(r"both .*(sick|out)|two .*(captains?|first officers?) .*(sick|out)|simultaneous|joint (crewing )?plan|allocate .*across both"), 1.5),
    Rule("DELAY_RECOMMENDATION", _rx(r"(delay|delayed).*(what should|recommend|do about|fdp breach)"), 1.4),
    Rule("NOTIFICATION_DRAFT", _rx(r"\bdraft\b.*\b(notification|message|callout|sms|email)\b|\bnotify\b.*\bcrew\b|write the callout"), 1.5),
    Rule("BRIEFING", _rx(r"morning briefing|standing briefing|daily briefing|start of shift|three data points"), 1.5),
    # Outranks RESERVE_LIST's bare "on-call window" match (1.2): a question
    # asking whether reserves are qualified/eligible needs the rule engine run
    # against each one, not a raw window listing with no verdict attached.
    Rule("CANDIDATE_ENUMERATION", _rx(r"which (reserve|reserves|candidates?|crew).*(qualified|eligible|cover|available)|list candidates"), 1.4),
    # Tier 2
    Rule("STATION_CLOSURE", _rx(r"\b(closed|closure|shut|closes)\b"), 1.4),
    Rule("DELAY_IMPACT", _rx(r"\b(delay|delayed)\b.*\b(breach|limit|fdp|legal)\b|\b\d+\s*(-|\s)?(minute|min|hour|h)\b.*delay"), 1.2),
    Rule("SICK_IMPACT", _rx(r"which flights are (now )?(uncrewed|uncovered|at risk)|what (flights|legs) (are|become) (uncrewed|uncovered)|immediately uncrewed"), 1.4),
    Rule("ASSIGNMENT_WHATIF", _rx(r"\bif i (move|assign|put|swap)\b|\bmove\b.*\bonto\b|\bassign\b.*\bto\b.*\bdoes\b"), 1.3),
    # "legally cover ... if positioned to X" needs RULE-BASE-07 deadhead
    # modelling, which plain check_legality does not do (it always assumes
    # delay_hours=0, no positioning). Weighted to beat LEGALITY_CHECK even
    # when its own "legally" and "can ... cover" patterns both also match the
    # same sentence (1.0 + 1.5) -- this doesn't silently answer "no delay"
    # when a real deadhead applies.
    Rule("ASSIGNMENT_WHATIF", _rx(r"\bif positioned\b|\bpositioned to\b|\bdeadhead(ed|ing)?\b|\brepositioned?\b"), 3.0),
    Rule("LEGALITY_CHECK", _rx(r"\b(legal|legally|breach|breaches|violate|compliant|allowed)\b"), 1.0),
    # "Can X cover Y?" / "Can X operate Y?" is a legality question. Without
    # this it scores only on the nouns and lands on a pairing lookup, which
    # answers a question nobody asked.
    Rule(
        "LEGALITY_CHECK",
        _rx(r"\bcan\b.{0,40}\b(cover|operate|take|fly)\b|\bwhy or why not\b|\bfit to fly\b"),
        1.5,
    ),
    Rule("CANCELLATION_IMPACT", _rx(r"\bcancel(led|ling)?\b.*\b(passengers?|cost)\b|if .* is cancelled"), 1.3),
    Rule("REST_CALC", _rx(r"earliest .*(report|duty)|minimum rest|how long before they can|released at"), 1.3),
    Rule("DUTY_SCAN", _rx(r"which crew have .*(duty hours|hours)|who is (near|close to|approaching) .*(limit|60)|\bor more duty hours\b"), 1.4),
    Rule("ROTATION_VIEW", _rx(r"\brotation\b|\bturn ?(time|around)\b"), 1.1),
    # Tier 1
    Rule("RESERVE_LIST", _rx(r"\bon reserve\b|\breserve pool\b|\bwho'?s on reserve\b|\bstandby\b|on-?call window"), 1.2),
    Rule("DUTY_CLOCK", _rx(r"duty hours|flight hours|headroom|how many hours|hours (left|remaining)|accrued"), 1.1),
    Rule("CERT_EXPIRY_LIST", _rx(r"\b(licence|license|certificat|medical|recurrent|dangerous goods)\w*\b.*\b(expir|lapse|valid)|expiring within"), 1.2),
    Rule("RISK_LOOKUP", _rx(r"risk score|disruption risk|risk signal|what drives it"), 1.3),
    Rule("RULE_LOOKUP", _rx(r"\bRULE-[A-Z]+-\d+\b|what does the rule|rulebook|ruleset"), 0.9),
    Rule("COST_LOOKUP", _rx(r"\b(rate card|cost rates?|how much does .* cost|callout rate|deadhead cost)\b"), 1.2),
    Rule("PAIRING_LOOKUP", _rx(r"\bpairing\b|\bwho (is|are) (assigned|rostered|on)\b|crew complement|in what roles"), 1.0),
    Rule("ROSTER_LOOKUP", _rx(r"\broster\b|what is .* flying|what are they flying|their assignments"), 1.0),
    Rule("FLIGHT_SEARCH", _rx(r"which flights|what flights|flights (depart|from|to|between)|how many flights"), 1.0),
    Rule("FLIGHT_LOOKUP", _rx(r"which aircraft operates|how many seats|what aircraft"), 1.1),
    Rule("NETWORK_SUMMARY", _rx(r"longest block|most seats|nonstop|network|stations does|serve nonstop|in total"), 1.0),
    Rule("CREW_SEARCH", _rx(r"how many (captains?|first officers?|cabin crew)|list (all )?(captains?|crew)|based at"), 1.0),
    Rule("CREW_LOOKUP", _rx(r"what is .*(base|rating|rank)|who is C-?\d{4}|tell me about"), 0.9),
    Rule("CAPABILITIES", _rx(r"what can you (do|answer)|your capabilities|help\b"), 1.2),
)


#: Which family an intent belongs to. Two strong matches inside one family is
#: normal phrasing; two strong matches across families is a compound question.
FAMILY = {
    "lookup": {
        "CREW_LOOKUP", "CREW_SEARCH", "ROSTER_LOOKUP", "DUTY_CLOCK", "FLIGHT_LOOKUP",
        "FLIGHT_SEARCH", "PAIRING_LOOKUP", "RESERVE_LIST", "CERT_EXPIRY_LIST",
        "RISK_LOOKUP", "RULE_LOOKUP", "COST_LOOKUP", "NETWORK_SUMMARY", "CAPABILITIES",
    },
    "consequence": {
        "SICK_IMPACT", "LEGALITY_CHECK", "ASSIGNMENT_WHATIF", "STATION_CLOSURE",
        "DELAY_IMPACT", "CANCELLATION_IMPACT", "REST_CALC", "DUTY_SCAN", "ROTATION_VIEW",
    },
    "recommendation": {
        "COVER_RECOMMENDATION", "CANDIDATE_ENUMERATION", "JOINT_RECOMMENDATION",
        "DELAY_RECOMMENDATION", "NOTIFICATION_DRAFT", "BRIEFING",
    },
}


def family_of(intent: str) -> str:
    for name, members in FAMILY.items():
        if intent in members:
            return name
    return "other"


#: A second reading scoring at least this fraction of the winner makes the
#: question compound rather than merely fuzzy.
AMBIGUITY_RATIO = 0.6

#: Phrasings that ask for a judgement the seven rules do not encode. The system
#: can compute every input to these and still has no defensible threshold for
#: the answer, so it says that instead of inventing one.
POLICY_RE = _rx(
    r"\bshould (we|i)\b.*\b(pre-?emptive|swap out|stand ?down|rest|replace|risk)\b"
    r"|\bis it worth\b|\bworth (the|it)\b|\bwhich is better\b|\bbetter overall\b"
    r"|\bdo you (think|recommend) we should\b|\bwould you\b.*\brather\b"
)

DECISION_MEMORY_RE = _rx(
    r"\b(last time|previously|before|history of|past decision|what did we decide|what was decided)\b"
    r".*\b(sick|unavailable|out|decision|chose|assigned|covered)\b"
)

#: Two independent disruptions in one sentence. Each is modelled; the pair is
#: not, and answering only the second one silently is the dangerous outcome.
_EVENT_A = r"clos(?:e|es|ed|ing|ure)|delay(?:s|ed|ing)?|cancell?(?:s|ed|ing|ation)?"
_EVENT_B = r"sick|calls?\s+in|unavailable|laps(?:e|ed|es)|expir(?:e|ed|es)"
COMPOUND_EVENT_RE = _rx(
    rf"\b(?:{_EVENT_A})\b.{{0,100}}\b(?:and|plus|whilst|while|at the same time)\b.{{0,100}}\b(?:{_EVENT_B})\b"
    rf"|\b(?:{_EVENT_B})\b.{{0,100}}\b(?:and|plus|whilst|while|at the same time)\b.{{0,100}}\b(?:{_EVENT_A})\b"
)


def route(question: str, ents: Entities) -> Intent:
    """Score every rule; the winner is the intent.

    Deterministic, inspectable, and good enough on its own -- the LLM
    classifier that follows can override it, but the system answers correctly
    with no model at all.
    """
    scores: dict[str, float] = {}
    hits: dict[str, list[str]] = {}

    for rule in ROUTER_RULES:
        match = rule.pattern.search(question)
        if not match:
            continue
        scores[rule.intent] = scores.get(rule.intent, 0.0) + rule.weight
        hits.setdefault(rule.intent, []).append(match.group(0)[:40])

    # Entity-shape nudges: what the question mentions constrains what it means.
    if ents.station and not ents.crew_ids:
        scores["STATION_CLOSURE"] = scores.get("STATION_CLOSURE", 0.0) + 0.1
    # "What is C-3310's on-call window and reachability?" is a crew lookup, not
    # a roster query: a named crew member with no date wants their own record,
    # which already carries the reserve window.
    if ents.crew_ids and not ents.dates and "RESERVE_LIST" in scores:
        scores["CREW_LOOKUP"] = scores.get("CREW_LOOKUP", 0.0) + scores.pop("RESERVE_LIST") + 0.2
    if ents.crew_ids and not scores:
        scores["CREW_LOOKUP"] = 0.6
    if ents.pairing_ids and ents.crew_ids and "LEGALITY_CHECK" in scores:
        scores["LEGALITY_CHECK"] += 0.2
    if len(ents.crew_ids) > 1 and "COVER_RECOMMENDATION" in scores:
        scores["JOINT_RECOMMENDATION"] = scores.get("JOINT_RECOMMENDATION", 0.0) + 0.6

    if not scores:
        if POLICY_RE.search(question):
            return Intent(
                "CAPABILITIES", 1, 0.4, "pattern",
                "policy phrasing with no computable intent",
                policy_question=True,
            )
        return Intent("UNSUPPORTED", 1, 0.0, "pattern", "no routing rule matched")

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best, best_score = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None

    total = sum(scores.values())
    confidence = min(0.95, best_score / total if total else 0.0)
    # A single decisive match is more confident than the ratio suggests.
    if len(scores) == 1:
        confidence = min(0.92, 0.55 + best_score * 0.25)

    # --- honesty guards ----------------------------------------------
    # Answering half of a two-part question, confidently, is the failure mode
    # this system exists to avoid. Both guards are deliberately narrow: they
    # look for two *events* joined by a conjunction, or for a phrasing that
    # asks for a judgement rather than a computation.
    #
    # An earlier version also flagged any question whose runner-up intent came
    # from a different family. That fired on ordinary phrasing -- "BLR is
    # closed, which flights are affected?" legitimately matches both a closure
    # intent and a flight lookup -- and abstained on nine of the graded
    # questions. A guard that refuses good questions is worse than no guard, so
    # it was removed rather than tuned.
    policy = bool(POLICY_RE.search(question))
    compound = bool(COMPOUND_EVENT_RE.search(question))
    if bool(DECISION_MEMORY_RE.search(question)):
        from app.agent.state import Intent as _Intent
        return _Intent(
            name="UNSUPPORTED",
            tier=1,
            confidence=0.99,
            source="pattern",
            rationale="decision memory not available — decisions are stored but not queried",
            compound=False,
            policy_question=False,
        )

    plan = PLANS.get(best)
    return Intent(
        name=best,
        tier=plan.tier if plan else 1,
        confidence=round(confidence, 3),
        source="pattern",
        rationale=f"matched {hits.get(best, [])}",
        runner_up=(runner_up[0], round(runner_up[1], 2)) if runner_up else None,
        compound=compound,
        policy_question=policy,
    )


def plan_for(intent: str) -> Plan | None:
    return PLANS.get(intent)


def catalog() -> list[dict]:
    return [
        {
            "intent": p.intent,
            "tier": p.tier,
            "description": p.description,
            "needs": list(p.needs),
            "tools": [s.tool for s in p.steps],
            "answer_schema": p.answer_schema,
        }
        for p in sorted(PLANS.values(), key=lambda p: (p.tier, p.intent))
    ]
