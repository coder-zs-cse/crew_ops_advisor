"""The agent's toolbelt.

Thirty tools across four categories. Each is a thin wrapper over ``app.core``
-- no arithmetic lives here. Parameter schemas are declared inline so the LLM
can be handed a real function-calling spec for the queries that fall outside
the compiled-plan library.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..core import queries as q
from ..core.briefing import morning_briefing
from ..core.candidates import enumerate_cover, enumerate_cover_for_pairing
from ..core.closure import station_closure
from ..core.duty import day_block_hours, fdp_limit
from ..core.impact import cancellation_impact, crew_unavailable
from ..core.joint import Opening, solve
from ..core.notification import build_slots, render_fallback
from ..core.ranking import impact_score
from ..core.rotation import aircraft_delay, tail_rotation
from ..core.rule_params import rule_param
from ..core.rules.engine import check_cover
from ..core.scenarios import certification_lapse, crew_opening, delay as delay_scenario
from ..core.timeutil import parse_date, parse_dt
from ..core.windows import DUTY, FLIGHT, window_sum
from ..core.world import World
from .registry import tool

STR = {"type": "string"}
NUM = {"type": "number"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}
DATE = {"type": "string", "description": "ISO date, YYYY-MM-DD"}
DTIME = {"type": "string", "description": "UTC timestamp, YYYY-MM-DDTHH:MM:SSZ"}


def _d(value: Any) -> date | None:
    if value is None:
        return None
    return value if isinstance(value, date) and not isinstance(value, datetime) else parse_date(str(value))


def _t(value: Any) -> datetime | None:
    if value is None:
        return None
    return value if isinstance(value, datetime) else parse_dt(str(value))


def _missing(kind: str, ident: str) -> dict:
    return {
        "found": False,
        "error": f"no {kind} matching {ident!r} in the dataset",
        "hint": "check the identifier; this system never invents entities",
    }


# ==========================================================================
# Retrieval (Tier 1)
# ==========================================================================


@tool(
    "get_crew",
    "Look up one crew member: rank, base, aircraft ratings, seniority, reachability, "
    "reserve status, certifications and disruption-risk score.",
    tier=1,
    category="retrieval",
    properties={"crew_id": STR},
    required=["crew_id"],
)
def get_crew(world: World, *, crew_id: str) -> dict:
    detail = q.crew_detail(world, crew_id)
    return detail or _missing("crew member", crew_id)


@tool(
    "search_crew",
    "Find crew by rank, base, aircraft rating and/or status (active/leave/training).",
    tier=1,
    category="retrieval",
    properties={"rank": STR, "base": STR, "rating": STR, "status": STR, "limit": INT},
)
def search_crew(
    world: World,
    *,
    rank: str | None = None,
    base: str | None = None,
    rating: str | None = None,
    status: str | None = None,
    limit: int | None = None,
) -> dict:
    return q.search_crew(world, rank=rank, base=base, rating=rating, status=status, limit=limit)


@tool(
    "get_flight",
    "One flight leg with its aircraft, seats, times, operating pairing and crew.",
    tier=1,
    category="retrieval",
    properties={"flight_id": STR, "flight_no": STR, "date": DATE},
)
def get_flight(
    world: World, *, flight_id: str | None = None, flight_no: str | None = None, date: Any = None
) -> dict:
    detail = q.flight_detail(world, flight_id=flight_id, flight_no=flight_no, on=_d(date))
    return detail or _missing("flight", flight_id or f"{flight_no} on {date}")


@tool(
    "search_flights",
    "Flights filtered by date, departure station, arrival station, flight number or tail.",
    tier=1,
    category="retrieval",
    properties={
        "date": DATE,
        "dep_station": STR,
        "arr_station": STR,
        "flight_no": STR,
        "aircraft": STR,
    },
)
def search_flights(
    world: World,
    *,
    date: Any = None,
    dep_station: str | None = None,
    arr_station: str | None = None,
    flight_no: str | None = None,
    aircraft: str | None = None,
) -> dict:
    return q.search_flights(
        world,
        on=_d(date),
        dep_station=dep_station,
        arr_station=arr_station,
        flight_no=flight_no,
        aircraft=aircraft,
    )


@tool(
    "get_pairing",
    "A pairing: its aircraft, days, report/release times, legs and full crew complement. "
    "Address it by pairing_id, or by aircraft tail plus date.",
    tier=1,
    category="retrieval",
    properties={"pairing_id": STR, "aircraft": STR, "date": DATE},
)
def get_pairing(
    world: World, *, pairing_id: str | None = None, aircraft: str | None = None, date: Any = None
) -> dict:
    if pairing_id:
        detail = q.pairing_detail(world, pairing_id)
    elif aircraft and date:
        detail = q.pairing_for_tail(world, aircraft=aircraft, on=_d(date))
    else:
        return {"found": False, "error": "provide pairing_id, or aircraft plus date"}
    return detail or _missing("pairing", pairing_id or f"{aircraft} on {date}")


@tool(
    "get_roster_for_crew",
    "Every published duty for one crew member across the schedule week.",
    tier=1,
    category="retrieval",
    properties={"crew_id": STR},
    required=["crew_id"],
)
def get_roster_for_crew(world: World, *, crew_id: str) -> dict:
    if world.get_crew(crew_id) is None:
        return _missing("crew member", crew_id)
    return q.roster_for_crew(world, crew_id)


@tool(
    "get_duty_clock",
    "Duty and flight-hour accruals for a crew member, with headroom under "
    "RULE-DUTY-02 (60h/7d) and RULE-FLT-03 (100h/28d), plus a per-day breakdown.",
    tier=1,
    category="retrieval",
    citations=("RULE-DUTY-02", "RULE-FLT-03"),
    properties={"crew_id": STR, "as_of": DATE},
    required=["crew_id"],
)
def get_duty_clock(world: World, *, crew_id: str, as_of: Any = None) -> dict:
    detail = q.duty_clock(world, crew_id, _d(as_of))
    return detail or _missing("crew member", crew_id)


@tool(
    "duty_window_scan",
    "Every crew member at or above a duty-hour threshold in the rolling window "
    "ending on a date, including that day's planned duty.",
    tier=2,
    category="retrieval",
    citations=("RULE-DUTY-02",),
    properties={"date": DATE, "threshold_hours": NUM, "days": INT},
    required=["date"],
)
def duty_window_scan(
    world: World, *, date: Any, threshold_hours: float = 45.0, days: int = 7
) -> dict:
    return q.duty_window_scan(world, on=_d(date), threshold_hours=threshold_hours, days=days)


@tool(
    "get_certifications",
    "Certifications expiring within N days of a date. Covers licence, medical, "
    "recurrent training and dangerous goods.",
    tier=1,
    category="retrieval",
    citations=("RULE-CERT-06",),
    properties={"as_of": DATE, "within_days": INT, "crew_id": STR},
)
def get_certifications(
    world: World, *, as_of: Any = None, within_days: int = 30, crew_id: str | None = None
) -> dict:
    return q.certifications_expiring(
        world,
        as_of=_d(as_of) or world.snapshot_utc.date(),
        within_days=within_days,
        crew_id=crew_id,
    )


@tool(
    "get_reserves",
    "Reserve crew on a date, with on-call windows. Pass covering_report_utc to test "
    "which windows actually cover a required report time.",
    tier=1,
    category="retrieval",
    citations=("RULE-BASE-07",),
    properties={"date": DATE, "base": STR, "rank": STR, "covering_report_utc": DTIME},
    required=["date"],
)
def get_reserves(
    world: World,
    *,
    date: Any,
    base: str | None = None,
    rank: str | None = None,
    covering_report_utc: Any = None,
) -> dict:
    return q.reserves(
        world, on=_d(date), base=base, rank=rank, covering_report=_t(covering_report_utc)
    )


@tool(
    "get_risk_signal",
    "Pre-computed disruption-risk score and its drivers, for one crew member or the "
    "top N. This is a provided input, not a model this system builds.",
    tier=1,
    category="retrieval",
    properties={"crew_id": STR, "top_n": INT},
)
def get_risk_signal(world: World, *, crew_id: str | None = None, top_n: int = 10) -> dict:
    if crew_id:
        detail = q.risk_signal(world, crew_id)
        return detail or _missing("risk signal", crew_id)
    return q.top_risk(world, limit=top_n)


@tool(
    "get_rule",
    "The machine-readable text and parameters of one legality rule, or all seven. "
    "Use this to ground any rule citation.",
    tier=1,
    category="retrieval",
    properties={"rule_id": STR},
)
def get_rule(world: World, *, rule_id: str | None = None) -> dict:
    return q.rules_reference(world, rule_id)


@tool(
    "get_costs",
    "The cost rate card: callout, deadhead, delay, cancellation and hotel rates.",
    tier=1,
    category="retrieval",
)
def get_costs(world: World) -> dict:
    return q.cost_reference(world)


@tool(
    "network_summary",
    "Network-level facts: flight counts, stations served, nonstop destinations from a "
    "station, longest block time (with ties) and the largest seat count per leg.",
    tier=1,
    category="retrieval",
    properties={"date": DATE, "from_station": STR},
)
def network_summary(world: World, *, date: Any = None, from_station: str | None = None) -> dict:
    return q.network_summary(world, on=_d(date), from_station=from_station)


# ==========================================================================
# Legality (Tier 2)
# ==========================================================================


@tool(
    "compute_duty_period",
    "Report time, release time, sector count, flight duty period and the RULE-FDP-01 "
    "limit for one day of a pairing, optionally after a delay.",
    tier=2,
    category="legality",
    citations=("RULE-FDP-01",),
    properties={"pairing_id": STR, "day_index": INT, "delay_hours": NUM},
    required=["pairing_id"],
)
def compute_duty_period(
    world: World, *, pairing_id: str, day_index: int = 0, delay_hours: float = 0.0
) -> dict:
    pairing = world.get_pairing(pairing_id)
    if pairing is None or day_index >= len(pairing.days):
        return _missing("pairing day", f"{pairing_id}[{day_index}]")
    day = pairing.days[day_index]
    scheduled = round((day.release_utc - day.report_utc).total_seconds() / 3600, 2)
    after = round(scheduled + delay_hours, 2)
    limit = fdp_limit(day.sectors, world)
    base = rule_param(world, "RULE-FDP-01", "base_fdp_hours", 13.0)
    free = rule_param(world, "RULE-FDP-01", "free_sectors", 2)
    reduction = rule_param(world, "RULE-FDP-01", "reduction_per_extra_sector_hours", 0.5)
    return {
        "pairing_id": pairing_id,
        "date": day.date.isoformat(),
        "report_utc": day.report_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "release_utc": day.release_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sectors": day.sectors,
        "flight_ids": list(day.flight_ids),
        "block_hours": day_block_hours(world, day),
        "fdp_hours": scheduled,
        "fdp_hours_after_delay": after,
        "fdp_limit": limit,
        "fdp_margin_hours": round(limit - after, 2),
        "within_limit": after <= limit + 1e-6,
        "rule": "RULE-FDP-01",
        "formula": f"{base} - {reduction} x max(0, {day.sectors} - {free}) = {limit}",
    }


@tool(
    "check_legality",
    "Run all seven rules against a proposed assignment: can this crew member legally "
    "cover this pairing? Returns a verdict per rule with the arithmetic shown.",
    tier=2,
    category="legality",
    citations=(
        "RULE-FDP-01",
        "RULE-DUTY-02",
        "RULE-FLT-03",
        "RULE-REST-04",
        "RULE-QUAL-05",
        "RULE-CERT-06",
        "RULE-BASE-07",
    ),
    properties={
        "crew_id": STR,
        "pairing_id": STR,
        "day_indexes": {"type": "array", "items": INT},
        "delay_hours": NUM,
        "replace_existing": BOOL,
    },
    required=["crew_id", "pairing_id"],
)
def check_legality(
    world: World,
    *,
    crew_id: str,
    pairing_id: str,
    day_indexes: list[int] | None = None,
    delay_hours: float = 0.0,
    replace_existing: bool = True,
) -> dict:
    if world.get_crew(crew_id) is None:
        return _missing("crew member", crew_id)
    pairing = world.get_pairing(pairing_id)
    if pairing is None:
        return _missing("pairing", pairing_id)

    days = pairing.days
    if day_indexes:
        wanted = set(day_indexes)
        days = tuple(d for d in days if d.day_index in wanted)

    report = check_cover(
        world,
        crew_id,
        days,
        exclude_pairing=pairing_id if replace_existing else None,
        delay_hours=delay_hours,
    )
    payload = report.as_dict()
    payload.update(
        {
            "pairing_id": pairing_id,
            "cover_dates": [d.date.isoformat() for d in days],
            "delay_hours": delay_hours,
            "rules_checked": [
                "RULE-FDP-01",
                "RULE-DUTY-02",
                "RULE-FLT-03",
                "RULE-REST-04",
                "RULE-QUAL-05",
                "RULE-CERT-06",
                "RULE-BASE-07",
            ],
        }
    )
    return payload


@tool(
    "check_rest",
    "Earliest legal next report after a release, under RULE-REST-04 (12h).",
    tier=2,
    category="legality",
    citations=("RULE-REST-04",),
    properties={"release_utc": DTIME, "next_report_utc": DTIME},
    required=["release_utc"],
)
def check_rest(world: World, *, release_utc: Any, next_report_utc: Any = None) -> dict:
    release = _t(release_utc)
    min_rest_hours = rule_param(world, "RULE-REST-04", "min_rest_hours", 12.0)
    payload = q.rest_calculation(release, min_rest_hours=min_rest_hours)
    if next_report_utc:
        nxt = _t(next_report_utc)
        rest = round((nxt - release).total_seconds() / 3600, 2)
        payload.update(
            {
                "proposed_report_utc": nxt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "rest_hours": rest,
                "legal": rest >= min_rest_hours - 1e-6,
                "shortfall_hours": round(max(0.0, min_rest_hours - rest), 2),
            }
        )
    return payload


@tool(
    "simulate_duty_window",
    "Project a crew member's 7-day duty and 28-day block totals if extra duty were "
    "added on a date. Shows before, added and after against both limits.",
    tier=2,
    category="legality",
    citations=("RULE-DUTY-02", "RULE-FLT-03"),
    properties={"crew_id": STR, "date": DATE, "added_duty_hours": NUM, "added_flight_hours": NUM},
    required=["crew_id", "date"],
)
def simulate_duty_window(
    world: World,
    *,
    crew_id: str,
    date: Any,
    added_duty_hours: float = 0.0,
    added_flight_hours: float = 0.0,
) -> dict:
    if world.get_crew(crew_id) is None:
        return _missing("crew member", crew_id)
    on = _d(date)
    duty_window_days = int(rule_param(world, "RULE-DUTY-02", "window_days", 7))
    flight_window_days = int(rule_param(world, "RULE-FLT-03", "window_days", 28))
    duty_limit = rule_param(world, "RULE-DUTY-02", "max_duty_hours", 60.0)
    flight_limit = rule_param(world, "RULE-FLT-03", "max_flight_hours", 100.0)

    duty_before = window_sum(world, crew_id, on, duty_window_days, DUTY)
    flight_before = window_sum(world, crew_id, on, flight_window_days, FLIGHT)
    duty_after = round(duty_before + added_duty_hours, 2)
    flight_after = round(flight_before + added_flight_hours, 2)
    return {
        "crew_id": crew_id,
        "date": on.isoformat(),
        "duty_hours_7d_before": duty_before,
        "duty_hours_7d_after": duty_after,
        "duty_limit": duty_limit,
        "duty_breach": duty_after > duty_limit + 1e-6,
        "duty_excess_hours": round(max(0.0, duty_after - duty_limit), 2),
        "flight_hours_28d_before": flight_before,
        "flight_hours_28d_after": flight_after,
        "flight_limit": flight_limit,
        "flight_breach": flight_after > flight_limit + 1e-6,
        "daily_breakdown": q.duty_clock(world, crew_id, on)["daily_breakdown_7d"],
    }


# ==========================================================================
# Simulation (Tier 2)
# ==========================================================================


@tool(
    "simulate_crew_unavailable",
    "A crew member drops out (sick call, cert lapse). Returns the flights immediately "
    "uncrewed, the downstream legs of the same pairing that are now at risk, and the "
    "passengers affected.",
    tier=2,
    category="simulation",
    properties={"crew_id": STR, "pairing_id": STR, "reported_utc": DTIME},
    required=["crew_id"],
)
def simulate_crew_unavailable(
    world: World, *, crew_id: str, pairing_id: str | None = None, reported_utc: Any = None
) -> dict:
    if world.get_crew(crew_id) is None:
        return _missing("crew member", crew_id)
    impact = crew_unavailable(
        world, crew_id=crew_id, pairing_id=pairing_id, reported_utc=_t(reported_utc)
    )
    if impact is None:
        return {
            "found": False,
            "error": f"{crew_id} has no pairing at or after the reported time",
        }
    return impact.as_dict()


@tool(
    "simulate_station_closure",
    "A station closes for a window. Returns every affected departure and arrival, the "
    "minimum delay to reopening, and whether each operating crew's FDP survives it.",
    tier=2,
    category="simulation",
    citations=("RULE-FDP-01",),
    properties={"station": STR, "start_utc": DTIME, "end_utc": DTIME},
    required=["station", "start_utc", "end_utc"],
)
def simulate_station_closure(world: World, *, station: str, start_utc: Any, end_utc: Any) -> dict:
    # Go through the scenario layer, not the bare impact function: it adds the
    # per-pairing recovery plan, which is what makes this a Tier-3 answer
    # rather than a list of delayed flights.
    from ..core.scenarios import closure as closure_scenario

    return closure_scenario(
        world, station=station, start_utc=_t(start_utc), end_utc=_t(end_utc)
    ).payload


@tool(
    "simulate_delay",
    "An aircraft is delayed. Returns the shifted rotation, the crew's flight duty "
    "period after the delay against its limit, how many sectors they can still legally "
    "operate, and which tail legs need a fresh crew.",
    tier=2,
    category="simulation",
    citations=("RULE-FDP-01",),
    properties={"aircraft": STR, "date": DATE, "delay_hours": NUM},
    required=["aircraft", "date", "delay_hours"],
)
def simulate_delay(world: World, *, aircraft: str, date: Any, delay_hours: float) -> dict:
    impact = aircraft_delay(world, aircraft=aircraft, on=_d(date), delay_hours=delay_hours)
    if impact is None:
        return _missing("pairing", f"{aircraft} on {date}")
    return impact.as_dict()


@tool(
    "propagate_rotation",
    "The tail's legs for a date with turn times -- the rotation fragility view.",
    tier=2,
    category="simulation",
    properties={"aircraft": STR, "date": DATE},
    required=["aircraft", "date"],
)
def propagate_rotation(world: World, *, aircraft: str, date: Any) -> dict:
    legs = tail_rotation(world, aircraft, _d(date))
    tight = [leg for leg in legs if leg["turn_hours_to_next"] is not None and leg["turn_hours_to_next"] <= 1.0]
    return {
        "aircraft": aircraft,
        "date": _d(date).isoformat(),
        "leg_count": len(legs),
        "legs": legs,
        "tight_turns": [leg["flight_id"] for leg in tight],
    }


@tool(
    "simulate_assignment",
    "What-if: move a specific crew member onto a specific pairing. Returns legality "
    "per rule, the cost, any positioning required, and the delay it causes.",
    tier=2,
    category="simulation",
    citations=("RULE-DUTY-02", "RULE-REST-04", "RULE-BASE-07"),
    properties={"crew_id": STR, "pairing_id": STR, "day_indexes": {"type": "array", "items": INT}},
    required=["crew_id", "pairing_id"],
)
def simulate_assignment(
    world: World, *, crew_id: str, pairing_id: str, day_indexes: list[int] | None = None
) -> dict:
    crew = world.get_crew(crew_id)
    if crew is None:
        return _missing("crew member", crew_id)
    pairing = world.get_pairing(pairing_id)
    if pairing is None:
        return _missing("pairing", pairing_id)

    incumbent = next((cid for cid, role in pairing.crew if role == crew.rank), None)
    candidates = enumerate_cover_for_pairing(
        world,
        pairing_id=pairing_id,
        role=crew.rank,
        sick_crew_id=incumbent,
        day_indexes=day_indexes,
    )

    match = next((c for c in candidates.eligible if c.crew_id == crew_id), None)
    if match is not None:
        return {
            "crew_id": crew_id,
            "pairing_id": pairing_id,
            "legal": True,
            "option": match.as_dict(),
            "cost_inr": match.cost_inr,
            "delay_hours": match.delay_hours,
            "would_rank": match.rank,
            "of_options": len(candidates.eligible),
        }

    excluded = next((e for e in candidates.excluded if e.crew_id == crew_id), None)
    return {
        "crew_id": crew_id,
        "pairing_id": pairing_id,
        "legal": False,
        "reason": excluded.reason if excluded else "not an eligible candidate for this opening",
        "rule_ids": list(excluded.rule_ids) if excluded else [],
        "verdicts": [v.as_dict() for v in excluded.verdicts] if excluded else [],
    }


@tool(
    "simulate_cancellation",
    "Cancel one or more legs: passengers affected, direct cost, and which aircraft "
    "rotations break as a result.",
    tier=2,
    category="simulation",
    properties={"flight_ids": {"type": "array", "items": STR}},
    required=["flight_ids"],
)
def simulate_cancellation(world: World, *, flight_ids: list[str]) -> dict:
    unknown = [fid for fid in flight_ids if world.get_flight(fid) is None]
    if unknown:
        return {"found": False, "error": f"unknown flight ids: {unknown}"}
    return cancellation_impact(world, flight_ids)


# ==========================================================================
# Recommendation (Tier 3)
# ==========================================================================


@tool(
    "enumerate_cover_candidates",
    "THE core recommendation tool. Evaluates every active crew member of the required "
    "rank -- reserves and day-off line crew alike -- against all seven rules, prices "
    "the legal ones, ranks them by cost, and returns a reason for every rejection.",
    tier=3,
    category="recommendation",
    citations=(
        "RULE-FDP-01",
        "RULE-DUTY-02",
        "RULE-FLT-03",
        "RULE-REST-04",
        "RULE-QUAL-05",
        "RULE-CERT-06",
        "RULE-BASE-07",
    ),
    properties={
        "pairing_id": STR,
        "role": STR,
        "sick_crew_id": STR,
        "day_indexes": {"type": "array", "items": INT},
    },
    required=["pairing_id", "role"],
)
def enumerate_cover_candidates(
    world: World,
    *,
    pairing_id: str,
    role: str,
    sick_crew_id: str | None = None,
    day_indexes: list[int] | None = None,
) -> dict:
    pairing = world.get_pairing(pairing_id)
    if pairing is None:
        return _missing("pairing", pairing_id)
    result = enumerate_cover_for_pairing(
        world,
        pairing_id=pairing_id,
        role=role,
        sick_crew_id=sick_crew_id,
        day_indexes=day_indexes,
    )
    return result.as_dict()


@tool(
    "resolve_disruption",
    "End-to-end Tier-3 answer for a crew member dropping off a pairing: impact "
    "analysis plus ranked, priced, rule-checked resolution options and every "
    "rejected candidate with its reason.",
    tier=3,
    category="recommendation",
    citations=(
        "RULE-FDP-01",
        "RULE-DUTY-02",
        "RULE-REST-04",
        "RULE-QUAL-05",
        "RULE-CERT-06",
        "RULE-BASE-07",
    ),
    properties={"crew_id": STR, "pairing_id": STR, "reported_utc": DTIME, "reason": STR},
    required=["crew_id"],
)
def resolve_disruption(
    world: World,
    *,
    crew_id: str,
    pairing_id: str | None = None,
    reported_utc: Any = None,
    reason: str = "SICK_CREW",
) -> dict:
    if world.get_crew(crew_id) is None:
        return _missing("crew member", crew_id)
    if reason == "CERT_EXPIRY" and pairing_id:
        return certification_lapse(
            world, crew_id=crew_id, pairing_id=pairing_id, reported_utc=_t(reported_utc)
        ).payload
    return crew_opening(
        world, crew_id=crew_id, pairing_id=pairing_id, reported_utc=_t(reported_utc)
    ).payload


@tool(
    "resolve_delay_breach",
    "Tier-3 answer for an aircraft delay that busts a crew's FDP: partial re-crew "
    "versus cancellation, costed.",
    tier=3,
    category="recommendation",
    citations=("RULE-FDP-01",),
    properties={"aircraft": STR, "date": DATE, "delay_hours": NUM},
    required=["aircraft", "date", "delay_hours"],
)
def resolve_delay_breach(world: World, *, aircraft: str, date: Any, delay_hours: float) -> dict:
    return delay_scenario(
        world, aircraft=aircraft, on=_d(date), delay_hours=delay_hours
    ).payload


@tool(
    "solve_joint_assignment",
    "Two or more simultaneous openings competing for one pool. Minimises total cost "
    "with no crew member assigned twice, and reports equal-cost alternatives.",
    tier=3,
    category="recommendation",
    properties={
        "openings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"pairing_id": STR, "role": STR, "sick_crew_id": STR},
            },
        }
    },
    required=["openings"],
)
def solve_joint_assignment(world: World, *, openings: list[dict]) -> dict:
    built = []
    sick = set()
    for spec in openings:
        pairing_id = spec["pairing_id"]
        pairing = world.get_pairing(pairing_id)
        if pairing is None:
            return _missing("pairing", pairing_id)
        role = spec.get("role")
        sick_id = spec.get("sick_crew_id")
        if role is None and sick_id:
            role = pairing.role_of(sick_id)
        if sick_id:
            sick.add(sick_id)
        cs = enumerate_cover_for_pairing(
            world, pairing_id=pairing_id, role=role, sick_crew_id=sick_id
        )
        built.append(Opening(key=pairing_id, label=f"{role} on {pairing_id}", candidate_set=cs))

    plan = solve(built, unavailable=sick)
    return {
        "openings": [
            {"pairing_id": o.key, "label": o.label, **o.candidate_set.as_dict()} for o in built
        ],
        "optimal_joint_plan": plan.as_dict(),
    }


@tool(
    "estimate_cost",
    "Price an action from the rate card, itemised.",
    tier=3,
    category="recommendation",
    properties={
        "kind": {"type": "string", "enum": ["callout", "cancellation", "delay"]},
        "is_reserve": BOOL,
        "is_pilot": BOOL,
        "deadhead": BOOL,
        "delay_hours": NUM,
        "n_flights": INT,
    },
    required=["kind"],
)
def estimate_cost(
    world: World,
    *,
    kind: str,
    is_reserve: bool = True,
    is_pilot: bool = True,
    deadhead: bool = False,
    delay_hours: float = 0.0,
    n_flights: int = 1,
) -> dict:
    from ..core.costing import callout_cost, cancellation_cost, delay_cost

    if kind == "callout":
        breakdown = callout_cost(
            world.costs,
            is_reserve=is_reserve,
            is_pilot=is_pilot,
            delay_hours=delay_hours,
            deadhead=deadhead,
        )
    elif kind == "cancellation":
        breakdown = cancellation_cost(world.costs, n_flights)
    elif kind == "delay":
        breakdown = delay_cost(world.costs, delay_hours)
    else:
        return {"error": f"unknown cost kind {kind!r}"}
    return {"kind": kind, **breakdown.as_dict()}


@tool(
    "score_impact",
    "Three-dimensional impact score (safety / business / customer, 0-100, higher is "
    "worse). Presentational only -- it never reorders the cost ranking.",
    tier=3,
    category="recommendation",
    properties={"breaches": INT, "cost_inr": INT, "seats_at_risk": INT, "delay_hours": NUM},
)
def score_impact(
    world: World,
    *,
    breaches: int = 0,
    cost_inr: int = 0,
    seats_at_risk: int = 0,
    delay_hours: float = 0.0,
) -> dict:
    return impact_score(
        world,
        breaches=breaches,
        cost_inr=cost_inr,
        seats_at_risk=seats_at_risk,
        delay_hours=delay_hours,
    )


@tool(
    "draft_notification",
    "Assemble the deterministic slots for a crew callout message (report time, legs, "
    "night stop, positioning) plus a correct plain-text fallback rendering.",
    tier=3,
    category="recommendation",
    properties={"crew_id": STR, "pairing_id": STR, "delay_hours": NUM, "cost_inr": INT},
    required=["crew_id", "pairing_id"],
)
def draft_notification(
    world: World,
    *,
    crew_id: str,
    pairing_id: str,
    delay_hours: float = 0.0,
    cost_inr: int | None = None,
) -> dict:
    if world.get_crew(crew_id) is None:
        return _missing("crew member", crew_id)
    if world.get_pairing(pairing_id) is None:
        return _missing("pairing", pairing_id)
    slots = build_slots(
        world, crew_id=crew_id, pairing_id=pairing_id, delay_hours=delay_hours, cost_inr=cost_inr
    )
    return {"slots": slots, "fallback_text": render_fallback(slots)}


@tool(
    "morning_briefing",
    "The standing morning briefing: three data points per aircraft line -- duty "
    "headroom, reserve depth filtered to this line's rating and report time, and the "
    "provided disruption-risk signal for today's rostered crew.",
    tier=3,
    category="recommendation",
    citations=("RULE-DUTY-02", "RULE-FDP-01", "RULE-BASE-07", "RULE-QUAL-05"),
    properties={"date": DATE},
)
def briefing(world: World, *, date: Any = None) -> dict:
    return morning_briefing(world, on=_d(date) or world.snapshot_utc.date())


# ==========================================================================
# Meta
# ==========================================================================


@tool(
    "list_supported_capabilities",
    "What this advisor can and cannot answer. Used to abstain honestly rather than "
    "guess at an out-of-scope question.",
    tier=1,
    category="meta",
)
def list_supported_capabilities(world: World) -> dict:
    from .registry import catalog

    return {
        "snapshot_utc": world.snapshot_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schedule_window": [d.isoformat() for d in (world.dates[0], world.dates[-1])],
        "can_answer": [
            "crew, flight, pairing, roster, reserve, certification and cost lookups",
            "duty-hour and flight-hour accruals with headroom under RULE-DUTY-02 / RULE-FLT-03",
            "legality of a proposed assignment against all seven rules, with arithmetic",
            "sick call, certification lapse, station closure, aircraft delay and cancellation impact",
            "ranked, priced, rule-checked cover options with every rejection explained",
            "joint plans for simultaneous disruptions",
            "crew callout notification drafting",
        ],
        "cannot_answer": [
            "passenger rebooking, misconnects or compensation — no booking data exists",
            "hotel allocation and crew payroll",
            "predicting who will call in sick — risk signals are a provided input",
            "regulations beyond the seven rules in rules.json",
            "anything outside the 2026-09-14 to 2026-09-20 schedule window",
            "policy judgements the ruleset does not encode (e.g. whether to pre-emptively "
            "swap a high-risk crew member out)",
        ],
        "tool_count": len(catalog()),
    }
