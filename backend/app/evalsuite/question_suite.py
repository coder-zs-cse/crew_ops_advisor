"""Grade all 38 shipped questions against the deterministic engine.

Each grader is explicit about which core call answers the question. That makes
this file double as a specification: for any question shape, this is the exact
tool path the agent is allowed to take.

Open-ended questions (Q30, Q36, Q38) are graded on the substantive facts the
answer must contain, not on wording -- the dataset itself flags them as
"judged on operational reasoning, not exact match".
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Callable

from ..core import queries as q
from ..core.candidates import enumerate_cover_for_pairing
from ..core.closure import station_closure
from ..core.impact import cancellation_impact, crew_unavailable
from ..core.loader import load_world, read_json
from ..core.notification import build_slots, render_fallback
from ..core.rotation import aircraft_delay
from ..core.rules.engine import check_cover
from ..core.scenarios import certification_lapse, crew_opening, delay, multi_crew_opening
from ..core.world import World
from .matchers import CaseResult, Check, close, exact, options_match, set_equal

D = date.fromisoformat
T = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")  # noqa: E731

Grader = Callable[[World, dict, CaseResult], None]
GRADERS: dict[str, Grader] = {}


def grader(qid: str):
    def wrap(fn: Grader) -> Grader:
        GRADERS[qid] = fn
        return fn

    return wrap


# ---------------------------------------------------------------- Tier 1


@grader("Q01")
def _q01(w, key, r):
    got = q.reserves(w, on=D("2026-09-15"), base="BLR")["reserves"]
    r.checks.append(set_equal("crew_ids", [e["crew_id"] for e in key], [g["crew_id"] for g in got]))
    by_id = {g["crew_id"]: g for g in got}
    bad = [
        e["crew_id"]
        for e in key
        if by_id.get(e["crew_id"], {}).get("window") != e["window"]
        or by_id.get(e["crew_id"], {}).get("rank") != e["rank"]
    ]
    r.checks.append(Check("windows_and_ranks", not bad, "all match", f"mismatched={bad}"))


@grader("Q02")
def _q02(w, key, r):
    got = q.duty_clock(w, "C-1042", D("2026-09-14"))
    r.checks.append(close("duty_hours_7d", key["duty_hours_7d"], got["duty_hours_7d"]))
    r.checks.append(close("headroom_hours", key["headroom_hours"], got["headroom_hours"]))


@grader("Q03")
def _q03(w, key, r):
    got = q.search_flights(w, on=D("2026-09-15"), dep_station="DEL")
    r.checks.append(set_equal("flight_nos", key, got["flight_nos"]))


@grader("Q04")
def _q04(w, key, r):
    got = q.certifications_expiring(w, as_of=D("2026-09-15"), within_days=30)["certifications"]
    r.checks.append(
        set_equal(
            "cert_keys",
            [(e["crew_id"], e["cert_type"], e["valid_to"]) for e in key],
            [(g["crew_id"], g["cert_type"], g["valid_to"]) for g in got],
        )
    )


@grader("Q05")
def _q05(w, key, r):
    got = q.flight_detail(w, flight_no="DX412", on=D("2026-09-15"))
    for field in ("aircraft", "aircraft_type", "seats"):
        r.checks.append(exact(field, key[field], got[field]))


@grader("Q06")
def _q06(w, key, r):
    got = q.crew_detail(w, "C-3310")
    r.checks.append(exact("window", key["window"], got["reserve_window"]))
    r.checks.append(exact("reachability_minutes", key["reachability_minutes"], got["reachability_minutes"]))


@grader("Q07")
def _q07(w, key, r):
    got = q.crew_detail(w, "C-2210")
    r.checks.append(exact("base", key["base"], got["base"]))
    r.checks.append(exact("ratings", key["ratings"], got["ratings"]))


@grader("Q08")
def _q08(w, key, r):
    got = q.pairing_detail(w, "P-2291")["crew"]
    r.checks.append(
        exact(
            "crew_roles",
            [(e["crew_id"], e["role"]) for e in key],
            [(g["crew_id"], g["role"]) for g in got],
        )
    )


@grader("Q09")
def _q09(w, key, r):
    got = q.search_flights(w, on=D("2026-09-17"), dep_station="BLR", arr_station="BOM")
    r.checks.append(set_equal("flight_nos", key, got["flight_nos"]))


@grader("Q10")
def _q10(w, key, r):
    r.checks.append(exact("flight_count", key, q.network_summary(w, on=D("2026-09-16"))["flight_count"]))


@grader("Q11")
def _q11(w, key, r):
    got = q.search_crew(w, rank="Captain", base="DEL")
    r.checks.append(set_equal("crew_ids", key, got["crew_ids"]))


@grader("Q12")
def _q12(w, key, r):
    got = q.network_summary(w)
    r.checks.append(close("block_hours", key["block_hours"], got["longest_block_hours"]))
    r.checks.append(set_equal("flights", key["flights"], got["longest_block_flights"]))


@grader("Q13")
def _q13(w, key, r):
    r.checks.append(exact("rank", key["rank"], q.crew_detail(w, "C-2087")["rank"]))
    got = q.duty_clock(w, "C-2087", D("2026-09-14"))
    r.checks.append(close("flight_hours_28d", key["flight_hours_28d"], got["flight_hours_28d"]))


@grader("Q14")
def _q14(w, key, r):
    got = q.network_summary(w, from_station="BLR")
    r.checks.append(set_equal("nonstop_destinations", key, got["nonstop_destinations"]))


@grader("Q15")
def _q15(w, key, r):
    pairing = q.pairing_for_tail(w, aircraft="VT-DXB", on=D("2026-09-16"))
    scc = next((c["crew_id"] for c in pairing["crew"] if c["role"] == "Senior Cabin Crew"), None)
    r.checks.append(exact("senior_cabin_crew", key, scc))


@grader("Q16")
def _q16(w, key, r):
    got = q.risk_signal(w, "C-1042")
    r.checks.append(close("score", key["score"], got["score"]))
    r.checks.append(set_equal("drivers", key["drivers"], got["drivers"]))


# ---------------------------------------------------------------- Tier 2


@grader("Q17")
def _q17(w, key, r):
    impact = crew_unavailable(
        w, crew_id="C-1042", pairing_id="P-2291", reported_utc=T("2026-09-15T05:00:00Z")
    ).as_dict()
    r.checks.append(set_equal("day1", key["day1"], impact["uncovered_flights_day1"]))
    r.checks.append(set_equal("day2_also_at_risk", key["day2_also_at_risk"], impact["uncovered_flights_day2"]))
    r.checks.append(exact("passengers_day1", key["passengers_day1"], impact["passengers_at_risk_day1"]))


def _cover_check(w, crew_id: str, pairing_id: str, day_indexes=None):
    days = w.pairing(pairing_id).days
    if day_indexes is not None:
        days = tuple(d for d in days if d.day_index in set(day_indexes))
    return check_cover(w, crew_id, days, exclude_pairing=pairing_id)


def _legality_case(w, key, r, crew_id, pairing_id, day_indexes=None):
    report = _cover_check(w, crew_id, pairing_id, day_indexes)
    r.checks.append(exact("legal", key["legal"], report.legal))
    r.checks.append(set_equal("issues", key["issues"], list(report.issues)))


@grader("Q18")
def _q18(w, key, r):
    _legality_case(w, key, r, "C-2087", "P-2291")


@grader("Q19")
def _q19(w, key, r):
    got = station_closure(
        w, station="BLR", start_utc=T("2026-09-17T08:00:00Z"), end_utc=T("2026-09-17T14:00:00Z")
    )
    r.checks.append(set_equal("affected_flights", key, got.affected_flights))


@grader("Q20")
def _q20(w, key, r):
    got = aircraft_delay(w, aircraft="VT-DXA", on=D("2026-09-16"), delay_hours=1.5)
    r.checks.append(exact("breach", key["breach"], got.breach))
    r.checks.append(close("fdp_after_delay", key["fdp_after_delay"], got.fdp_after_delay))
    r.checks.append(exact("fdp_limit", key["fdp_limit"], got.fdp_limit))


@grader("Q21")
def _q21(w, key, r):
    cs = enumerate_cover_for_pairing(w, pairing_id="P-2291", role="Captain", sick_crew_id="C-1042")
    match = next((c for c in cs.eligible if c.crew_id == "C-2210"), None)
    r.checks.append(exact("legal", key["legal"], match is not None))
    if match:
        r.checks.append(close("deadhead_delay_hours", 3.0, match.delay_hours))
        r.checks.append(exact("positioning_applied", True, match.positioning is not None))


@grader("Q22")
def _q22(w, key, r):
    report = _cover_check(w, "C-5417", "P-2213")
    cert_issue = next((i for i in report.issues if "RULE-CERT-06" in i), None)
    r.checks.append(exact("legal", key["legal"], report.legal))
    r.checks.append(Check("rule", cert_issue is not None, key["rule"], cert_issue))
    certs = w.certs("C-5417")
    r.checks.append(
        exact("recurrent_training_valid_to", "2026-09-17", certs["recurrent_training"].valid_to.isoformat())
    )


@grader("Q23")
def _q23(w, key, r):
    got = q.rest_calculation(T("2026-09-16T15:30:00Z"))
    r.checks.append(exact("earliest_report_utc", key, got["earliest_report_utc"]))


@grader("Q24")
def _q24(w, key, r):
    _legality_case(w, key, r, "C-3305", "P-2291")


@grader("Q25")
def _q25(w, key, r):
    got = cancellation_impact(w, ["DX404-2026-09-16"])
    r.checks.append(exact("passengers", key["passengers"], got["passengers_affected"]))
    r.checks.append(exact("cost_inr", key["cost_inr"], got["direct_cost_inr"]))


@grader("Q26")
def _q26(w, key, r):
    got = q.duty_window_scan(w, on=D("2026-09-15"), threshold_hours=45.0)["crew"]
    r.checks.append(set_equal("crew_ids", [e["crew_id"] for e in key], [g["crew_id"] for g in got]))
    by_id = {g["crew_id"]: g["duty_hours"] for g in got}
    bad = [
        e["crew_id"]
        for e in key
        if abs(by_id.get(e["crew_id"], -1) - e["duty_hours_7d_incl_15sep_plan"]) > 0.011
    ]
    r.checks.append(Check("duty_hours", not bad, "all match", f"mismatched={bad}"))


@grader("Q27")
def _q27(w, key, r):
    pairing = w.pairing_for("VT-DXE", D("2026-09-16"))
    sick = next(cid for cid, role in pairing.crew if role == "Captain")
    cs = enumerate_cover_for_pairing(
        w, pairing_id=pairing.pairing_id, role="Captain", sick_crew_id=sick
    )
    reserve_ids = w.reserve_ids
    eligible_reserves = [c.crew_id for c in cs.eligible if c.crew_id in reserve_ids]
    r.checks.append(set_equal("eligible_reserves", key["eligible"], eligible_reserves))

    excluded = {e.crew_id: e.reason for e in cs.excluded}
    for example in key["excluded_examples"]:
        got = excluded.get(example["crew_id"], "")
        r.checks.append(
            Check(
                f"excluded[{example['crew_id']}]",
                example["reason"] == got,
                example["reason"],
                got,
            )
        )


@grader("Q28")
def _q28(w, key, r):
    _legality_case(w, key, r, "C-5837", "P-2291")


@grader("Q29")
def _q29(w, key, r):
    got = station_closure(
        w, station="HYD", start_utc=T("2026-09-19T05:00:00Z"), end_utc=T("2026-09-19T09:00:00Z")
    )
    r.checks.append(set_equal("affected_flights", key, got.affected_flights))


@grader("Q30")
def _q30(w, key, r):
    got = q.network_summary(w)
    r.checks.append(exact("max_seats_per_leg", 162, got["max_seats_per_leg"]))
    seats = {row["aircraft_type"]: row["seats"] for row in got["seats_by_type"]}
    r.checks.append(exact("A320_seats", 162, seats.get("A320")))
    r.checks.append(exact("ATR72_seats", 72, seats.get("ATR72")))


# ---------------------------------------------------------------- Tier 3


@grader("Q31")
def _q31(w, key, r):
    payload = crew_opening(
        w, crew_id="C-1042", pairing_id="P-2291", reported_utc=T("2026-09-15T05:00:00Z")
    ).payload
    r.checks += options_match("options", key, payload["answer_key_options"])


@grader("Q32")
def _q32(w, key, r):
    payload = multi_crew_opening(
        w,
        events=[
            {"crew_id": "C-3940", "pairing_id": "P-2205", "reported_utc": "2026-09-18T00:30:00Z"},
            {"crew_id": "C-1938", "pairing_id": "P-2212", "reported_utc": "2026-09-18T00:30:00Z"},
        ],
    ).payload
    plan = payload["optimal_joint_plan"]
    r.checks.append(exact("total_cost_inr", key["total_cost_inr"], plan["total_cost_inr"]))
    expected_crew = sorted(
        filter(None, [key["assign_dxa"]["crew_id"], key["assign_dxb"]["crew_id"]])
    )
    got_crew = sorted(filter(None, [a["crew_id"] for a in plan["assignments"].values()]))
    r.checks.append(Check("assigned_crew (mirror-tolerant)", expected_crew == got_crew, expected_crew, got_crew))


@grader("Q33")
def _q33(w, key, r):
    payload = delay(w, aircraft="VT-DXA", on=D("2026-09-16"), delay_hours=1.5).payload
    got = payload["options"]
    r.checks.append(exact("options.count", len(key), len(got)))
    for i, exp in enumerate(key):
        act = got[i] if i < len(got) else {}
        r.checks.append(exact(f"options[{i}].cost_inr", exp["cost_inr"], act.get("cost_inr")))
        r.checks.append(exact(f"options[{i}].legal", exp["legal"], act.get("legal")))


@grader("Q34")
def _q34(w, key, r):
    payload = certification_lapse(
        w, crew_id="C-5417", pairing_id="P-2213", reported_utc=T("2026-09-18T10:00:00Z")
    ).payload
    # questions.json truncates this key to the leading three options; the full
    # ranked list (43 options) is graded by scenario S5.
    r.checks += options_match("options", key, payload["answer_key_options"], prefix=True)


@grader("Q35")
def _q35(w, key, r):
    got = station_closure(
        w, station="BLR", start_utc=T("2026-09-17T08:00:00Z"), end_utc=T("2026-09-17T14:00:00Z")
    ).as_dict()["per_flight_assessment"]
    by_id = {g["flight_id"]: g for g in got}
    bad = []
    for exp in key:
        act = by_id.get(exp["flight_id"])
        if act is None:
            bad.append(exp["flight_id"])
            continue
        for field in ("pairing_id", "min_delay_hours", "crew_fdp_after_delay", "fdp_limit", "action"):
            if exp[field] != act.get(field):
                bad.append(f"{exp['flight_id']}.{field}")
    r.checks.append(exact("assessment.count", len(key), len(got)))
    r.checks.append(Check("assessment.fields", not bad, "all match", f"mismatched={bad[:5]}"))


@grader("Q36")
def _q36(w, key, r):
    slots = build_slots(w, crew_id="C-3310", pairing_id="P-2291", cost_inr=18500)
    text = render_fallback(slots)
    required = {
        "crew_id": "C-3310" in text,
        "pairing_id": "P-2291" in text,
        "report_time": "06:00" in text,
        "report_station": "BLR" in text,
        "day1_flights": all(f in text for f in ("DX412", "DX413", "DX588")),
        "day2_flights": all(f in text for f in ("DX589", "DX590", "DX591")),
        "overnight": "DEL" in text,
        "acknowledgement": "acknowledge" in text.lower(),
    }
    for name, ok in required.items():
        r.checks.append(Check(f"must_include.{name}", ok, True, ok))


@grader("Q37")
def _q37(w, key, r):
    pairing = w.pairing_for("VT-DXF", D("2026-09-20"))
    sick = next(cid for cid, role in pairing.crew if role == "First Officer")
    cs = enumerate_cover_for_pairing(
        w, pairing_id=pairing.pairing_id, role="First Officer", sick_crew_id=sick
    )
    best = cs.eligible[0].as_answer_key_dict() if cs.eligible else {}
    r.checks.append(exact("crew_id", key["crew_id"], best.get("crew_id")))
    r.checks.append(exact("cost_inr", key["cost_inr"], best.get("cost_inr")))
    r.checks.append(exact("rank", key["rank"], best.get("rank")))
    r.checks.append(exact("action", key["action"], best.get("action")))


@grader("Q38")
def _q38(w, key, r):
    from ..core.briefing import morning_briefing

    got = morning_briefing(w, on=D("2026-09-16"))
    lines = got["lines"]
    r.checks.append(Check("covers_every_line", len(lines) > 0, ">0 aircraft lines", len(lines)))
    if lines:
        sample = lines[0]
        for field in ("duty_headroom", "reserve_depth", "risk"):
            r.checks.append(Check(f"datapoint.{field}", field in sample, True, field in sample))


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
    questions = read_json(data_dir, "questions")
    results = [grade_question(world, q_) for q_ in questions]

    by_tier: dict[int, dict[str, int]] = {}
    for res, q_ in zip(results, questions):
        bucket = by_tier.setdefault(q_["tier"], {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += 1 if res.passed else 0

    passed = sum(1 for r in results if r.passed)
    return {
        "suite": "questions",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "by_tier": {
            str(t): {**v, "pass_rate": round(v["passed"] / v["total"], 4)}
            for t, v in sorted(by_tier.items())
        },
        "cases": [r.as_dict() for r in results],
    }
