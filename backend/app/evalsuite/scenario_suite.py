"""Run every shipped scenario through the engine and grade it.

This is the moat's regression test. It runs with no database, no network and no
model -- ~200ms for all six scenarios -- so it can gate every commit and be
shown live on stage.
"""

from __future__ import annotations

from typing import Any

from ..core.loader import load_world, read_json
from ..core.scenarios import run_event
from ..core.world import World
from .matchers import (
    CaseResult,
    Check,
    assessments_match,
    close,
    exact,
    exclusions_match,
    options_match,
    set_equal,
)


def _payload(world: World, event: dict) -> dict[str, Any]:
    return run_event(world, event).payload


def grade_scenario(world: World, scenario: dict) -> CaseResult:
    sid = scenario["scenario_id"]
    result = CaseResult(case_id=sid, tier=None, title=scenario.get("title", sid))
    key = scenario["answer_key"]

    try:
        payload = _payload(world, scenario["event"])
    except Exception as exc:  # noqa: BLE001 - surfaced in the report
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    etype = scenario["event"]["type"]

    if etype in ("SICK_CREW", "CERT_EXPIRY"):
        got_options = payload.get("answer_key_options", [])
        if "options" in key:
            result.checks += options_match("options", key["options"], got_options)
        if "excluded_candidates" in key:
            result.checks += exclusions_match(
                "excluded", key["excluded_candidates"], payload.get("excluded_candidates", [])
            )
        impact = payload.get("impact", {})
        if "uncovered_flights" in key:
            result.checks.append(
                set_equal("uncovered_flights", key["uncovered_flights"], impact.get("uncrewed_flights"))
            )
        if "uncovered_flights_day1" in key:
            result.checks.append(
                set_equal(
                    "uncovered_flights_day1",
                    key["uncovered_flights_day1"],
                    impact.get("uncovered_flights_day1"),
                )
            )
        if "uncovered_flights_day2" in key:
            result.checks.append(
                set_equal(
                    "uncovered_flights_day2",
                    key["uncovered_flights_day2"],
                    impact.get("uncovered_flights_day2"),
                )
            )
        if "passengers_at_risk_day1" in key:
            result.checks.append(
                exact(
                    "passengers_at_risk_day1",
                    key["passengers_at_risk_day1"],
                    impact.get("passengers_at_risk_day1"),
                )
            )
        if "expected_choice" in key and key["expected_choice"]:
            result.checks.append(
                exact(
                    "expected_choice.crew_id",
                    key["expected_choice"].get("crew_id"),
                    (payload.get("expected_choice") or {}).get("crew_id"),
                )
            )
        if "illegal_assignment" in key:
            got = payload.get("illegal_assignment", {})
            result.checks.append(exact("illegal.crew_id", key["illegal_assignment"]["crew_id"], got.get("crew_id")))
            result.checks.append(exact("illegal.date", key["illegal_assignment"]["date"], got.get("date")))
            result.checks.append(exact("illegal.rule", key["illegal_assignment"]["rule"], got.get("rule")))

    elif etype == "STATION_CLOSURE":
        result.checks.append(
            set_equal("affected_flights", key["affected_flights"], payload.get("affected_flights"))
        )
        if "per_flight_assessment" in key:
            result.checks += assessments_match(
                "per_flight", key["per_flight_assessment"], payload.get("per_flight_assessment", [])
            )

    elif etype == "DELAY":
        result.checks.append(close("fdp_after_delay", key["fdp_after_delay"], payload.get("fdp_after_delay")))
        result.checks.append(exact("fdp_limit", key["fdp_limit"], payload.get("fdp_limit")))
        result.checks.append(exact("breach", key["breach"], payload.get("breach")))
        if "options" in key:
            got = payload.get("options", [])
            result.checks.append(exact("options.count", len(key["options"]), len(got)))
            for i, exp in enumerate(key["options"]):
                act = got[i] if i < len(got) else {}
                result.checks.append(
                    exact(f"options[{i}].cost_inr", exp.get("cost_inr"), act.get("cost_inr"))
                )

    elif etype == "MULTI_SICK":
        for side, pairing_key in (("dxa", "options_dxa"), ("dxb", "options_dxb")):
            if pairing_key not in key:
                continue
            index = 0 if side == "dxa" else 1
            openings = payload.get("openings", [])
            got = openings[index].get("answer_key_options", []) if index < len(openings) else []
            result.checks += options_match(pairing_key, key[pairing_key], got)
        for side, exc_key in (("dxa", "excluded_dxa"), ("dxb", "excluded_dxb")):
            if exc_key not in key:
                continue
            index = 0 if side == "dxa" else 1
            openings = payload.get("openings", [])
            got = openings[index].get("excluded_candidates", []) if index < len(openings) else []
            result.checks += exclusions_match(exc_key, key[exc_key], got)
        if "optimal_joint_plan" in key:
            exp_plan = key["optimal_joint_plan"]
            got_plan = payload.get("optimal_joint_plan", {})
            result.checks.append(
                exact("joint.total_cost_inr", exp_plan["total_cost_inr"], got_plan.get("total_cost_inr"))
            )
            # Mirror assignments are equally correct: compare the multiset of
            # assigned crew, not which opening each covers.
            exp_crew = sorted(
                filter(None, [exp_plan["assign_dxa"].get("crew_id"), exp_plan["assign_dxb"].get("crew_id")])
            )
            got_crew = sorted(
                filter(None, [a.get("crew_id") for a in got_plan.get("assignments", {}).values()])
            )
            result.checks.append(Check("joint.assigned_crew (mirror-tolerant)", exp_crew == got_crew, exp_crew, got_crew))

    else:
        result.error = f"no grader for event type {etype}"

    return result


def run_suite(data_dir: str, *, suite: str = "scenarios") -> dict:
    world = load_world(data_dir)
    filename = "held_out_scenarios" if suite == "holdout" else "scenarios"
    scenarios = read_json(data_dir, filename)

    results = [grade_scenario(world, s) for s in scenarios]
    passed = sum(1 for r in results if r.passed)
    return {
        "suite": suite,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "cases": [r.as_dict() for r in results],
    }
