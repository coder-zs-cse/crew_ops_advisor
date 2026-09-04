"""Deterministic answer assembly.

Two outputs, both produced by code:

* ``structured_answer`` -- the typed payload the UI renders. The model never
  authors this. Chat and the workbench render the same object, which is why
  they cannot disagree.
* ``template_narration`` -- a correct, plain prose answer with no model
  involved. It is the fallback when there are no credentials, when the model
  errors, and when a draft fails verification twice. Every graded question has
  one, so the system is fully functional with the LLM switched off.

The LLM's contribution is to write that prose better. It is an upgrade to the
answer, not the source of it.
"""

from __future__ import annotations

from typing import Any

from ..core.rules.engine import ALL_RULE_IDS


def _inr(value: Any) -> str:
    try:
        return f"₹{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _plural(n: int, one: str, many: str | None = None) -> str:
    return one if n == 1 else (many or one + "s")


def compose(intent: str, schema: str, results: dict[str, dict], world_snapshot: str) -> dict:
    """Build the structured answer from the tool results of a compiled plan."""
    builder = BUILDERS.get(schema, _generic)
    answer = builder(results)
    answer.setdefault("schema", schema)
    answer.setdefault("intent", intent)
    answer.setdefault("citations", [])
    answer["as_of"] = world_snapshot
    answer["tools_used"] = list(results)
    return answer


# --------------------------------------------------------------------------
# Builders -- one per answer schema
# --------------------------------------------------------------------------


def _generic(r: dict) -> dict:
    primary = next(iter(r.values()), {})
    return {"headline": "Result", "primary": primary, "detail": r}


def _crew(r: dict) -> dict:
    c = r.get("get_crew", {})
    if not c.get("crew_id"):
        return {"headline": "Not found", "primary": c, "not_found": True}
    ratings = ", ".join(c.get("ratings", []))
    reserve = " · on reserve" if c.get("is_reserve") else ""
    return {
        "headline": f"{c['rank']} {c['crew_id']} — {c['name']}, based {c['base']}, rated {ratings}{reserve}",
        "primary": c,
        "citations": ["RULE-QUAL-05", "RULE-CERT-06"],
    }


def _crew_list(r: dict) -> dict:
    s = r.get("search_crew", {})
    filters = {k: v for k, v in (s.get("filters") or {}).items() if v}
    label = ", ".join(f"{k}={v}" for k, v in filters.items()) or "all crew"
    return {
        "headline": f"{s.get('count', 0)} crew match {label}",
        "primary": s,
        "crew_ids": s.get("crew_ids", []),
    }


def _roster(r: dict) -> dict:
    roster = r.get("get_roster_for_crew", {})
    crew = r.get("get_crew", {})
    n = roster.get("duty_count", 0)
    return {
        "headline": f"{crew.get('rank', 'Crew')} {roster.get('crew_id')} has {n} rostered {_plural(n, 'duty', 'duties')} this week",
        "primary": roster,
        "crew": crew,
    }


def _duty_clock(r: dict) -> dict:
    d = r.get("get_duty_clock", {})
    if not d.get("crew_id"):
        return {"headline": "Not found", "primary": d, "not_found": True}
    return {
        "headline": (
            f"{d['crew_id']}: {d['duty_hours_7d']}h duty in the 7 days to {d['as_of']} "
            f"— {d['headroom_hours']}h headroom of the 60h limit"
        ),
        "primary": d,
        "citations": ["RULE-DUTY-02", "RULE-FLT-03"],
    }


def _flight(r: dict) -> dict:
    f = r.get("get_flight", {})
    if not f.get("flight_id"):
        return {"headline": "Not found", "primary": f, "not_found": True}
    return {
        "headline": (
            f"{f['flight_no']} on {f['date']}: {f['dep_station']}–{f['arr_station']}, "
            f"{f['aircraft']} ({f['aircraft_type']}, {f['seats']} seats)"
        ),
        "primary": f,
    }


def _flight_list(r: dict) -> dict:
    s = r.get("search_flights", {})
    n = s.get("count", 0)
    return {
        "headline": f"{n} {_plural(n, 'flight')} match — {', '.join(s.get('flight_nos', [])[:10]) or 'none'}",
        "primary": s,
    }


def _pairing(r: dict) -> dict:
    p = r.get("get_pairing", {})
    if not p.get("pairing_id"):
        return {"headline": "Not found", "primary": p, "not_found": True}
    days = len(p.get("days", []))
    return {
        "headline": (
            f"{p['pairing_id']} — {p['aircraft']} ({p['aircraft_type']}), "
            f"{days}-day, {p['total_sectors']} sectors, {len(p.get('crew', []))} crew"
        ),
        "primary": p,
    }


def _reserve_list(r: dict) -> dict:
    res = r.get("get_reserves", {})
    n = res.get("count", 0)
    where = f" at {res['base']}" if res.get("base") else ""
    return {
        "headline": f"{n} reserve crew{where} on {res.get('date')}",
        "primary": res,
        "citations": ["RULE-BASE-07"],
    }


def _cert_list(r: dict) -> dict:
    c = r.get("get_certifications", {})
    n = c.get("count", 0)
    return {
        "headline": f"{n} {_plural(n, 'certification')} expire within {c.get('within_days')} days of {c.get('as_of')}",
        "primary": c,
        "citations": ["RULE-CERT-06"],
    }


def _risk(r: dict) -> dict:
    s = r.get("get_risk_signal", {})
    if "score" in s:
        return {
            "headline": f"{s['crew_id']} disruption-risk score {s['score']}",
            "primary": s,
        }
    return {"headline": f"Top {s.get('count', 0)} crew by disruption risk", "primary": s}


def _rules(r: dict) -> dict:
    rules = r.get("get_rule", {})
    return {
        "headline": f"{rules.get('count', 0)} legality {_plural(rules.get('count', 0), 'rule')}",
        "primary": rules,
        "citations": [x["rule_id"] for x in rules.get("rules", [])],
    }


def _costs(r: dict) -> dict:
    c = r.get("get_costs", {})
    return {"headline": f"Cost rate card ({c.get('currency', 'INR')})", "primary": c}


def _network(r: dict) -> dict:
    n = r.get("network_summary", {})
    where = f" on {n['date']}" if n.get("date") else ""
    return {"headline": f"{n.get('flight_count', 0)} flights{where}", "primary": n}


def _capabilities(r: dict) -> dict:
    c = r.get("list_supported_capabilities", {})
    return {"headline": "What this advisor can and cannot answer", "primary": c}


# ---- Tier 2 ---------------------------------------------------------------


def _impact(r: dict) -> dict:
    i = r.get("simulate_crew_unavailable", {})
    if not i.get("crew_id"):
        return {"headline": "No impact found", "primary": i, "not_found": True}
    now = len(i.get("uncovered_flights_day1", []))
    later = len(i.get("uncovered_flights_day2", []))
    tail = f", {later} more at risk on the following day" if later else ""
    return {
        "headline": (
            f"{i['role']} {i['crew_id']} off {i['pairing_id']}: {now} "
            f"{_plural(now, 'leg')} uncrewed, {i['passengers_at_risk_day1']} passengers{tail}"
        ),
        "primary": i,
        "citations": ["RULE-QUAL-05"],
    }


def _legality(r: dict) -> dict:
    res = r.get("check_legality") or r.get("simulate_assignment") or {}
    legal = res.get("legal")
    issues = res.get("issues") or ([res["reason"]] if res.get("reason") else [])
    if legal:
        headline = f"{res.get('crew_id')} can legally cover {res.get('pairing_id')} — all seven rules pass"
    else:
        headline = f"{res.get('crew_id')} cannot cover {res.get('pairing_id')}: {issues[0] if issues else 'ineligible'}"
    return {
        "headline": headline,
        "primary": res,
        "legal": legal,
        "issues": issues,
        "citations": res.get("rules_checked") or list(ALL_RULE_IDS),
    }


def _closure(r: dict) -> dict:
    c = r.get("simulate_station_closure", {})
    n = len(c.get("affected_flights", []))
    recrew = len(c.get("flights_requiring_recrew_or_cancel", []))
    return {
        "headline": (
            f"{c.get('station')} closure hits {n} {_plural(n, 'flight')}; "
            f"{recrew} exceed the operating crew's FDP after the minimum delay"
        ),
        "primary": c,
        "citations": ["RULE-FDP-01"],
    }


def _delay(r: dict) -> dict:
    d = r.get("simulate_delay") or r.get("resolve_delay_breach") or {}
    if d.get("breach"):
        headline = (
            f"{d.get('aircraft')} {d.get('delay_hours')}h delay busts RULE-FDP-01: "
            f"{d.get('fdp_after_delay')}h against a {d.get('fdp_limit')}h limit"
        )
    else:
        headline = (
            f"{d.get('aircraft')} {d.get('delay_hours')}h delay stays legal: "
            f"{d.get('fdp_after_delay')}h against a {d.get('fdp_limit')}h limit"
        )
    return {"headline": headline, "primary": d, "citations": ["RULE-FDP-01"]}


def _cancellation(r: dict) -> dict:
    c = r.get("simulate_cancellation", {})
    return {
        "headline": (
            f"{len(c.get('flight_ids', []))} {_plural(len(c.get('flight_ids', [])), 'leg')} cancelled: "
            f"{c.get('passengers_affected')} passengers, {_inr(c.get('direct_cost_inr'))} direct cost"
        ),
        "primary": c,
    }


def _rest(r: dict) -> dict:
    c = r.get("check_rest", {})
    return {
        "headline": f"Earliest legal next report is {c.get('earliest_report_utc')}",
        "primary": c,
        "citations": ["RULE-REST-04"],
    }


def _duty_scan(r: dict) -> dict:
    s = r.get("duty_window_scan", {})
    n = s.get("count", 0)
    return {
        "headline": (
            f"{n} crew at or above {s.get('threshold_hours')}h duty in the "
            f"{s.get('window_days')} days to {s.get('as_of')}"
        ),
        "primary": s,
        "citations": ["RULE-DUTY-02"],
    }


def _rotation(r: dict) -> dict:
    rot = r.get("propagate_rotation", {})
    return {
        "headline": f"{rot.get('aircraft')} flies {rot.get('leg_count')} legs on {rot.get('date')}",
        "primary": rot,
    }


# ---- Tier 3 ---------------------------------------------------------------


def _recommendation(r: dict) -> dict:
    res = r.get("resolve_disruption") or r.get("enumerate_cover_candidates") or {}
    # Prefer the rich option dicts for display; `answer_key_options` is the
    # minimal answer-key shape and exists for the conformance harness.
    options = res.get("options") or res.get("answer_key_options") or []
    legal = [o for o in options if o.get("crew_id")]
    best = legal[0] if legal else None
    excluded = res.get("exclusion_summary", {})
    impact = res.get("impact", {})

    if best:
        headline = (
            f"Assign {best['crew_id']} at {_inr(best['cost_inr'])} — cheapest of "
            f"{len(legal)} legal {_plural(len(legal), 'option')} "
            f"from {res.get('evaluated_count', 0)} candidates evaluated"
        )
    else:
        headline = "No legal cover found — cancellation is the only option"

    return {
        "headline": headline,
        "primary": best,
        "options": options,
        "legal_option_count": len(legal),
        "evaluated_count": res.get("evaluated_count"),
        "excluded_count": res.get("excluded_count"),
        "exclusion_summary": excluded,
        "excluded_candidates": res.get("excluded_candidates", []),
        "impact": impact,
        "detail": res,
        "citations": list(ALL_RULE_IDS),
    }


def _joint_recommendation(r: dict) -> dict:
    j = r.get("solve_joint_assignment", {})
    plan = j.get("optimal_joint_plan", {})
    assignments = plan.get("assignments", {})
    pairs = ", ".join(
        f"{pid} → {a.get('crew_id') or 'cancel'}" for pid, a in assignments.items()
    )
    return {
        "headline": f"Joint plan at {_inr(plan.get('total_cost_inr'))}: {pairs}",
        "primary": plan,
        "openings": j.get("openings", []),
        "detail": j,
        "citations": list(ALL_RULE_IDS),
    }


def _notification(r: dict) -> dict:
    n = r.get("draft_notification", {})
    slots = n.get("slots", {})
    return {
        "headline": f"Callout draft for {slots.get('crew_id')} — {slots.get('pairing_id')}",
        "primary": n,
        "slots": slots,
        "fallback_text": n.get("fallback_text"),
    }


def _briefing(r: dict) -> dict:
    b = r.get("morning_briefing", {})
    head = b.get("headline", {})
    fragile = head.get("fragile_fdp_lines", [])
    thin = head.get("thin_reserve_lines", [])
    bits = []
    if fragile:
        bits.append(f"{len(fragile)} {_plural(len(fragile), 'line')} with thin FDP margin")
    if thin:
        bits.append(f"{len(thin)} with a reserve gap")
    return {
        "headline": f"{b.get('line_count', 0)} aircraft lines on {b.get('date')}"
        + (f" — {', '.join(bits)}" if bits else " — all clear"),
        "primary": b,
        "citations": ["RULE-DUTY-02", "RULE-FDP-01", "RULE-BASE-07"],
    }


BUILDERS = {
    "crew": _crew,
    "crew_list": _crew_list,
    "roster": _roster,
    "duty_clock": _duty_clock,
    "flight": _flight,
    "flight_list": _flight_list,
    "pairing": _pairing,
    "reserve_list": _reserve_list,
    "cert_list": _cert_list,
    "risk": _risk,
    "rules": _rules,
    "costs": _costs,
    "network": _network,
    "capabilities": _capabilities,
    "impact": _impact,
    "legality": _legality,
    "closure": _closure,
    "delay": _delay,
    "cancellation": _cancellation,
    "rest": _rest,
    "duty_scan": _duty_scan,
    "rotation": _rotation,
    "recommendation": _recommendation,
    "joint_recommendation": _joint_recommendation,
    "notification": _notification,
    "briefing": _briefing,
}


# --------------------------------------------------------------------------
# Template narration -- the no-LLM path
# --------------------------------------------------------------------------


def template_narration(answer: dict) -> str:
    """A correct prose answer with no model involved."""
    schema = answer.get("schema", "generic")
    lines = [answer.get("headline", "")]

    if schema == "recommendation":
        best = answer.get("primary")
        impact = answer.get("impact") or {}
        if impact.get("uncovered_flights_day1"):
            legs = ", ".join(impact["uncovered_flights_day1"])
            lines.append(
                f"Uncrewed now: {legs} ({impact.get('passengers_at_risk_day1')} passengers)."
            )
            if impact.get("uncovered_flights_day2"):
                lines.append(
                    f"At risk on the next day of the pairing: "
                    f"{', '.join(impact['uncovered_flights_day2'])}."
                )
        if best:
            lines.append(f"Recommended: {best['action']} at {_inr(best['cost_inr'])}.")
            if best.get("delay_hours"):
                lines.append(f"This delays the first departure by {best['delay_hours']}h.")
        summary = answer.get("exclusion_summary") or {}
        if summary:
            parts = ", ".join(f"{count} on {rule}" for rule, count in summary.items())
            lines.append(
                f"{answer.get('excluded_count')} of {answer.get('evaluated_count')} candidates "
                f"were excluded: {parts}."
            )
        alternatives = [o for o in answer.get("options", []) if o.get("crew_id")][1:4]
        if alternatives:
            alts = "; ".join(f"{o['crew_id']} at {_inr(o['cost_inr'])}" for o in alternatives)
            lines.append(f"Next cheapest: {alts}.")

    elif schema == "legality":
        for issue in answer.get("issues", [])[:5]:
            lines.append(f"- {issue}")
        if answer.get("legal"):
            lines.append("All seven rules were evaluated and none is breached.")

    elif schema == "impact":
        i = answer.get("primary", {})
        if i.get("uncovered_flights_day1"):
            lines.append(f"Uncrewed: {', '.join(i['uncovered_flights_day1'])}.")
        if i.get("uncovered_flights_day2"):
            lines.append(f"At risk: {', '.join(i['uncovered_flights_day2'])}.")

    elif schema == "closure":
        c = answer.get("primary", {})
        breached = c.get("flights_requiring_recrew_or_cancel", [])
        if breached:
            lines.append(
                f"These need a fresh crew or cancellation: {', '.join(breached[:8])}"
                + (f" (+{len(breached) - 8} more)" if len(breached) > 8 else "")
                + "."
            )

    elif schema == "delay":
        d = answer.get("primary", {})
        if d.get("breach"):
            lines.append(d.get("breach_detail", ""))
            if d.get("legs_needing_recrew"):
                lines.append(
                    f"The crew can legally operate {d.get('max_legal_sectors')} of "
                    f"{d.get('sectors')} sectors; {', '.join(d['legs_needing_recrew'])} "
                    f"needs a fresh crew."
                )
        for option in d.get("options", [])[:2]:
            lines.append(f"Option {option['rank']}: {option['action']} — {_inr(option['cost_inr'])}.")

    elif schema == "duty_clock":
        d = answer.get("primary", {})
        lines.append(
            f"28-day block hours: {d.get('flight_hours_28d')}h of 100h "
            f"({d.get('flight_headroom_hours')}h headroom under RULE-FLT-03)."
        )

    elif schema == "reserve_list":
        for row in answer.get("primary", {}).get("reserves", [])[:12]:
            window = row["window"]
            lines.append(
                f"- {row['crew_id']} ({row['rank']}) on call {window['start']}–{window['end']}Z"
            )

    elif schema == "joint_recommendation":
        plan = answer.get("primary", {})
        for pairing_id, assignment in (plan.get("assignments") or {}).items():
            lines.append(
                f"- {pairing_id}: {assignment.get('action')} at {_inr(assignment.get('cost_inr'))}"
            )
        if plan.get("tie_count", 0) > 1:
            lines.append(
                f"{plan['tie_count']} plans tie at this cost; the mirror assignment is equally correct."
            )

    elif schema == "notification":
        return answer.get("fallback_text") or answer.get("headline", "")

    elif schema == "briefing":
        for line in answer.get("primary", {}).get("lines", [])[:8]:
            tight = line["duty_headroom"]["tightest_crew"] or {}
            lines.append(
                f"- {line['aircraft']}: FDP margin {line['duty_headroom']['fdp_margin_hours']}h; "
                f"tightest duty headroom {tight.get('headroom_hours')}h ({tight.get('crew_id')}); "
                f"reserve depth {line['reserve_depth']['by_rank'] or 'none'}"
            )

    elif schema in ("crew_list", "flight_list", "cert_list", "duty_scan"):
        primary = answer.get("primary", {})
        rows = (
            primary.get("crew")
            or primary.get("flights")
            or primary.get("certifications")
            or []
        )
        for row in rows[:12]:
            lines.append("- " + ", ".join(f"{k}: {v}" for k, v in list(row.items())[:5]))
        if len(rows) > 12:
            lines.append(f"...and {len(rows) - 12} more.")

    return "\n".join(x for x in lines if x)
