"""Routing, and the guards that make the system decline rather than guess.

Two things are tested together here because they trade against each other: a
guard strict enough to catch a dangerous question can also refuse a good one.
Every graded question must route to an answer, *and* the known-bad question
shapes must abstain. Tuning either one without re-running the other is how a
system quietly gets worse.
"""

from __future__ import annotations

import pytest

from app.agent.plans import PLANS, route
from app.agent.entities import resolve
from app.core.loader import read_json


@pytest.fixture(scope="module")
def advisor(world):
    from app.agent import Advisor
    from app.obs import MEMORY_SINK, TRACER

    if MEMORY_SINK not in getattr(TRACER, "_sinks", []):
        TRACER.add_sink(MEMORY_SINK)
    return Advisor(world)


@pytest.fixture(scope="module")
def graded(data_dir):
    return read_json(data_dir, "questions")


# ---- every graded question must produce an answer ------------------------


def test_every_graded_question_routes_to_an_answer(advisor, graded):
    """A guard that refuses good questions is worse than no guard."""
    abstained = []
    for question in graded:
        answer = advisor.ask(question["prompt"])
        if answer.abstained:
            abstained.append((question["question_id"], answer.narration.split("\n")[0]))
    assert not abstained, f"abstained on graded questions: {abstained}"


#: The questions where picking the wrong tool would produce a wrong answer,
#: rather than merely a differently-shaped right one. Tier alone is too weak a
#: proxy: Q30 ("most seats at risk") is graded Tier 2 but a network summary
#: answers it exactly, and demanding a Tier-2 tool there would be cargo cult.
EXPECTED_INTENT = {
    "Q02": "DUTY_CLOCK",
    "Q17": "SICK_IMPACT",
    "Q18": "LEGALITY_CHECK",
    "Q19": "STATION_CLOSURE",
    "Q20": "DELAY_IMPACT",
    "Q23": "REST_CALC",
    "Q24": "LEGALITY_CHECK",
    "Q26": "DUTY_SCAN",
    "Q28": "LEGALITY_CHECK",
    "Q29": "STATION_CLOSURE",
    "Q31": "COVER_RECOMMENDATION",
    "Q32": "JOINT_RECOMMENDATION",
    "Q34": "COVER_RECOMMENDATION",
    "Q35": "STATION_CLOSURE",
    "Q36": "NOTIFICATION_DRAFT",
    "Q38": "BRIEFING",
}


def test_questions_route_to_the_intent_that_answers_them(advisor, graded):
    wrong = []
    for question in graded:
        expected = EXPECTED_INTENT.get(question["question_id"])
        if not expected:
            continue
        answer = advisor.ask(question["prompt"])
        got = (answer.intent or {}).get("name")
        if got != expected:
            wrong.append((question["question_id"], expected, got))
    assert not wrong, f"mis-routed: {wrong}"


def test_station_closure_answer_includes_a_recovery_plan(advisor):
    """Q35 asks for a plan, not a list of delayed flights."""
    answer = advisor.ask(
        "BLR closes 08:00-14:00Z on 17 Sep. Outline the recovery plan across affected pairings."
    )
    plan = (answer.structured or {}).get("primary", {}).get("recovery_plan")
    assert plan, "closure answer carries no recovery plan"
    assert all("tail_legs_needing_recrew" in row for row in plan)


# ---- the guards ----------------------------------------------------------

POLICY_QUESTIONS = [
    "Should we pre-emptively swap C-1042 out of tomorrow given his 0.78 risk score?",
    "Which is better overall: assign C-3310, or cancel DX588 and protect the day-2 legs?",
    "Is it worth calling out a reserve for P-2291 or should we just take the delay?",
]

COMPOUND_QUESTIONS = [
    "If BLR closes 08:00-14:00 on 17 Sep AND the VT-DXA captain calls in sick that morning, what do I do?",
    "VT-DXA is delayed 90 minutes and the first officer calls in sick — what now?",
]

OUT_OF_SCOPE = [
    "How many passengers will misconnect if DX412 is delayed 3 hours?",
    "Which hotel should the DEL night-stop crew use?",
    "What is the weather at BLR tomorrow?",
]


@pytest.mark.parametrize("question", POLICY_QUESTIONS)
def test_policy_questions_are_declined(advisor, question):
    """The inputs are computable; the threshold is not in the ruleset."""
    answer = advisor.ask(question)
    assert answer.abstained
    assert "policy call" in answer.narration.lower()


@pytest.mark.parametrize("question", COMPOUND_QUESTIONS)
def test_compound_disruptions_are_split_not_half_answered(advisor, question):
    """Answering one of two events, confidently, is the worst outcome."""
    answer = advisor.ask(question)
    assert answer.abstained
    assert "more than one part" in answer.narration.lower()


@pytest.mark.parametrize("question", OUT_OF_SCOPE)
def test_out_of_scope_questions_abstain(advisor, question):
    answer = advisor.ask(question)
    assert answer.abstained


def test_abstention_says_what_it_can_do_instead(advisor):
    answer = advisor.ask("What is the weather at BLR tomorrow?")
    assert answer.structured is not None
    assert answer.structured.get("suggestions")


# ---- entity resolution ---------------------------------------------------


def test_unknown_crew_id_is_not_silently_dropped(world):
    ents = resolve("Is C-9999 legal for P-2291?", world)
    assert {"kind": "crew", "value": "C-9999"} in ents.unresolved


def test_relative_dates_anchor_on_the_snapshot_not_wall_clock(world):
    """'Tomorrow' must land inside the schedule window, not two years past it."""
    ents = resolve("Who is on reserve tomorrow?", world)
    assert ents.dates == ["2026-09-15"]


def test_two_tails_resolve_to_two_pairings_in_order(world):
    ents = resolve(
        "Both captains of VT-DXA and VT-DXB are sick at 00:30Z on 18 Sep.", world
    )
    assert len(ents.pairing_ids) == 2
    assert len(ents.crew_ids) == 2
    assert ents.roles[0] == "Captain"


def test_every_registered_intent_has_a_plan():
    for name, plan in PLANS.items():
        assert plan.steps, f"{name} has no tool steps"
        assert plan.answer_schema


def test_router_is_deterministic(world):
    question = "Captain C-1042 is out for pairing P-2291. What should I do?"
    ents = resolve(question, world)
    first = route(question, ents)
    for _ in range(5):
        again = route(question, resolve(question, world))
        assert again.name == first.name and again.confidence == first.confidence
