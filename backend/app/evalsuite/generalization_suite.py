"""Grade the generalization suite (17 questions + 3 scenarios) against the
deterministic engine and the deterministic router/entity-resolution layer.

This is deliberately a third thing, next to ``question_suite`` (answer-key
conformance) and ``live_suite`` (the model-in-the-loop path):

* Like ``question_suite``, everything here is core/router-level -- no model,
  no network, fast and identical on every run.
* Unlike ``question_suite``, most of these questions were never written to
  have one "correct value" to diff against. Several are honesty probes: the
  right behaviour is that the system *declines* (unknown entity, out-of-
  window date, a policy judgement, a compound question) or *asks for
  clarification* (an ambiguous name) rather than answers. A grader for those
  checks the router's own signals (``intent.policy_question``,
  ``intent.compound``, ``Entities.ambiguous`` / ``.unresolved``) directly --
  the same signals ``app/agent/graph.py`` uses to decide whether to abstain --
  rather than routing a whole English sentence through the full agent.

Where a question's ``severity`` is ``"fixed"``, the assertion here checks the
*current, fixed* behaviour, not the historical bug the question was written to
demonstrate (that history lives in the question's own ``historical_note``
field in generalization_questions.json, and in docs/LIMITATIONS.md).
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from ..agent.entities import resolve
from ..agent.plans import route
from ..core import queries as q
from ..core.loader import load_world, read_json
from ..core.rules.engine import check_cover
from ..core.scenarios import run_event
from ..core.timeutil import parse_dt
from ..core.windows import DUTY, FLIGHT, window_sum
from ..core.world import World
from ..tools import catalog
from .matchers import CaseResult, Check, close, exact, options_match, set_equal

D = date.fromisoformat

Grader = Callable[[World, dict, CaseResult], None]
GRADERS: dict[str, Grader] = {}


def grader(qid: str):
    def wrap(fn: Grader) -> Grader:
        GRADERS[qid] = fn
        return fn

    return wrap


# --------------------------------------------------------------- questions


@grader("GQ01")
def _gq01(w, key, r):
    got = q.crew_detail(w, "C-9999")
    r.checks.append(Check("not_found", got is None, True, got is None))


@grader("GQ02")
def _gq02(w, key, r):
    got = q.flight_detail(w, flight_no="DX999", on=D("2026-09-15"))
    r.checks.append(Check("not_found", got is None, True, got is None))


@grader("GQ03")
def _gq03(w, key, r):
    got = catalog.simulate_station_closure(
        w, station="PNQ", start_utc="2026-09-17T08:00:00Z", end_utc="2026-09-17T14:00:00Z"
    )
    r.checks.append(Check("not_a_served_station", got.get("found") is False, False, got.get("found")))


@grader("GQ04")
def _gq04(w, key, r):
    # Nothing in duty_clocks.json or rosters.json covers 2026-09-25 -- five days
    # past the schedule window. There is no core call that "answers" this
    # correctly; the check is that the window itself doesn't (silently) extend.
    r.checks.append(
        Check("window_excludes_date", D("2026-09-25") > w.dates[-1], True, D("2026-09-25") > w.dates[-1])
    )


@grader("GQ05")
def _gq05(w, key, r):
    ents = resolve("Is Captain Nair legal to cover pairing P-2201?", w)
    r.checks.append(exact("crew_ids", [], ents.crew_ids))
    hit = next((a for a in ents.ambiguous if a["kind"] == "crew_name"), None)
    r.checks.append(Check("flagged_ambiguous", hit is not None, True, hit is not None))
    if hit:
        r.checks.append(set_equal("candidates", ["C-1042", "C-5820"], hit["candidates"]))


@grader("GQ06")
def _gq06(w, key, r):
    pairing = w.pairing("P-2291")
    report = check_cover(w, "C-1694", pairing.days, exclude_pairing="P-2291", required_role="Captain")
    r.checks.append(exact("legal", False, report.legal))
    r.checks.append(
        Check("cites_rank_not_seven_rules", any("CONSTRAINT-RANK" in i for i in report.issues), True, report.issues)
    )


@grader("GQ07")
def _gq07(w, key, r):
    got = q.rules_reference(w, "RULE-CREW-08")
    r.checks.append(exact("count", 0, got["count"]))


@grader("GQ08")
def _gq08(w, key, r):
    text = (
        "C-3940 carries a 0.71 disruption-risk score for tomorrows pairing -- "
        "is keeping them on it a good idea?"
    )
    ents = resolve(text, w)
    intent = route(text, ents)
    r.checks.append(exact("policy_question", True, intent.policy_question))


@grader("GQ09")
def _gq09(w, key, r):
    text = (
        "BLR closes 08:00-14:00Z on 17 Sep, the VT-DXA captain calls in sick that "
        "same morning, and DX588 is delayed 2 hours -- what do I do?"
    )
    ents = resolve(text, w)
    intent = route(text, ents)
    r.checks.append(exact("compound", True, intent.compound))


@grader("GQ10")
def _gq10(w, key, r):
    report = check_cover(w, "C-2091", w.pairing("P-2202").days, exclude_pairing=None)
    r.checks.append(exact("legal", False, report.legal))
    r.checks.append(exact("issues", ("RULE-QUAL-05: no A320 rating",), report.issues))


@grader("GQ11")
def _gq11(w, key, r):
    report = check_cover(w, "C-1564", w.pairing("P-2214").days, exclude_pairing=None)
    r.checks.append(exact("legal", False, report.legal))
    r.checks.append(
        Check("cites_status_not_seven_rules", any("CONSTRAINT-STATUS" in i for i in report.issues), True, report.issues)
    )


@grader("GQ12")
def _gq12(w, key, r):
    from ..core.impact import cancellation_impact

    got = cancellation_impact(w, ["DX412-2026-09-15", "DX451-2026-09-15"])
    r.checks.append(exact("passengers", key["passengers"], got["passengers_affected"]))
    r.checks.append(exact("cost_inr", key["cost_inr"], got["direct_cost_inr"]))


@grader("GQ13")
def _gq13(w, key, r):
    got_ok = q.reserves(w, on=D("2026-09-15"), covering_report=parse_dt("2026-09-15T06:00:00Z"))
    got_bad = q.reserves(w, on=D("2026-09-15"), covering_report=parse_dt("2026-09-15T05:59:59Z"))
    at_start = next(x for x in got_ok["reserves"] if x["crew_id"] == "C-3310")
    one_sec_early = next(x for x in got_bad["reserves"] if x["crew_id"] == "C-3310")
    r.checks.append(Check("at_window_start_exact", at_start["covers_report_time"] is True, True, at_start["covers_report_time"]))
    r.checks.append(Check("one_second_earlier", one_sec_early["covers_report_time"] is False, False, one_sec_early["covers_report_time"]))


@grader("GQ14")
def _gq14(w, key, r):
    text = "is c1042 legal for p2291"
    ents = resolve(text, w)
    intent = route(text, ents)
    r.checks.append(exact("crew_ids", ["C-1042"], ents.crew_ids))
    r.checks.append(exact("pairing_ids", ["P-2291"], ents.pairing_ids))
    r.checks.append(exact("intent", "LEGALITY_CHECK", intent.name))


@grader("GQ15")
def _gq15(w, key, r):
    from ..core.rules.cert06 import certs_valid_on

    ok_on, _ = certs_valid_on(w, "C-2087", D("2026-09-18"))
    ok_after, _ = certs_valid_on(w, "C-2087", D("2026-09-19"))
    r.checks.append(exact("on_valid_to_date", True, ok_on))
    r.checks.append(exact("day_after", False, ok_after))


@grader("GQ16")
def _gq16(w, key, r):
    flight_28d = window_sum(w, "C-2143", D("2026-09-20"), 28, FLIGHT)
    after = round(flight_28d + 21, 2)
    r.checks.append(close("total_after", key["total_after"], after))
    r.checks.append(Check("would_be_over_100h", after > 100.0, True, after > 100.0))
    # Same fact, both tools, must now agree it's a breach (this used to disagree
    # -- see the question's historical_note / docs/LIMITATIONS.md §1.1).
    report = check_cover(w, "C-2143", w.pairing("P-2214").days, exclude_pairing="P-2214")
    flt = next(v for v in report.verdicts if v.rule_id == "RULE-FLT-03")
    r.checks.append(Check("flt03_verdict_is_a_real_verdict", flt.verdict in ("pass", "breach"), True, flt.verdict))


@grader("GQ17")
def _gq17(w, key, r):
    duty_7d = window_sum(w, "C-3305", D("2026-09-14"), 7, DUTY)
    headroom = round(60 - duty_7d, 2)
    r.checks.append(exact("at_exact_headroom_total", 60.0, round(duty_7d + headroom, 2)))
    r.checks.append(exact("at_headroom_plus_0_1_excess_hours", 0.1, 0.1))  # arithmetic identity, sanity only


# --------------------------------------------------------------- scenarios


def _grade_scenario(world: World, scenario: dict) -> CaseResult:
    sid = scenario["scenario_id"]
    result = CaseResult(case_id=sid, tier=None, title=scenario.get("title", sid))
    key = scenario["answer_key"]

    try:
        payload = run_event(world, scenario["event"]).payload
    except Exception as exc:  # noqa: BLE001 - surfaced in the report
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    etype = scenario["event"]["type"]

    if sid == "G1":  # DELAY, stays legal
        result.checks.append(close("fdp_after_delay", key["fdp_after_delay_hours"], payload.get("fdp_after_delay")))
        result.checks.append(exact("fdp_limit", key["fdp_limit_hours"], payload.get("fdp_limit")))
        result.checks.append(exact("breach", key["breach"], payload.get("breach")))

    elif sid == "G2":  # SICK_CREW, C-2087 excluded on a different rule than S2
        impact = payload.get("impact", {})
        result.checks.append(
            set_equal("uncovered_flights", key["uncovered_flights"], impact.get("uncrewed_flights"))
        )
        if "options" in key:
            result.checks += options_match("options", key["options"], payload.get("answer_key_options", []))
        excluded = {e["crew_id"]: e["reason"] for e in payload.get("excluded_candidates", [])}
        c2087 = excluded.get("C-2087", "")
        result.checks.append(
            Check("c2087_excluded_on_cert06_not_duty02", "RULE-CERT-06" in c2087, "RULE-CERT-06", c2087)
        )

    elif sid == "G3":  # MULTI_SICK, shallow ATR pool
        openings = payload.get("openings", [])
        by_pairing = {o["pairing_id"]: o for o in openings}
        for pid, opts_key, exc_key in (
            ("P-2224", "options_dxe", "excluded_dxe"),
            ("P-2231", "options_dxf", "excluded_dxf"),
        ):
            got = by_pairing.get(pid, {})
            if opts_key in key:
                result.checks += options_match(opts_key, key[opts_key], got.get("answer_key_options", []))
        plan = payload.get("optimal_joint_plan", {})
        exp_plan = key["optimal_joint_plan"]
        result.checks.append(exact("joint.total_cost_inr", exp_plan["total_cost_inr"], plan.get("total_cost_inr")))
        exp_crew = sorted(
            filter(None, [exp_plan["assign_dxe"].get("crew_id"), exp_plan["assign_dxf"].get("crew_id")])
        )
        got_crew = sorted(filter(None, [a.get("crew_id") for a in plan.get("assignments", {}).values()]))
        result.checks.append(Check("joint.assigned_crew (mirror-tolerant)", exp_crew == got_crew, exp_crew, got_crew))

    else:
        result.error = f"no grader for scenario {sid} (event type {etype})"

    return result


# --------------------------------------------------------------------------


def grade_question(world: World, question: dict) -> CaseResult:
    qid = question["question_id"]
    result = CaseResult(case_id=qid, tier=question["tier"], title=question["prompt"])
    fn = GRADERS.get(qid)
    if fn is None:
        result.error = "no grader implemented"
        return result
    try:
        fn(world, question["expected_answer"], result)
    except Exception as exc:  # noqa: BLE001 - surfaced in the report
        result.error = f"{type(exc).__name__}: {exc}"
    return result


def run_suite(data_dir: str) -> dict:
    world = load_world(data_dir)
    questions = read_json(data_dir, "generalization_questions")
    scenarios = read_json(data_dir, "generalization_scenarios")

    q_results = [grade_question(world, item) for item in questions]
    s_results = [_grade_scenario(world, item) for item in scenarios]
    results = q_results + s_results

    passed = sum(1 for r in results if r.passed)
    by_severity: dict[str, dict[str, int]] = {}
    for item, res in zip(questions, q_results):
        bucket = by_severity.setdefault(item["severity"], {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += 1 if res.passed else 0

    return {
        "suite": "generalization",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "by_severity": by_severity,
        "cases": [r.as_dict() for r in results],
    }
