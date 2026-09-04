"""The standing morning briefing (question Q38).

Three data points per aircraft line, chosen because each one answers a
different question a controller asks at 06:00:

* **duty_headroom** -- "can today's crew legally finish the day if it slips?"
  The tightest 7-day duty margin across the rostered complement, plus the FDP
  margin on the duty itself. A line with 0.5h of FDP margin is one gate delay
  from a re-crew.
* **reserve_depth** -- "if someone drops out, who can actually take it?"
  Reserves are useless unless their on-call window covers *this* line's report
  time and they hold *this* aircraft's rating, so the count is filtered on both.
* **risk** -- "who is most likely to drop out?" The provided disruption-risk
  signal for today's rostered crew. We consume it; we do not model it.

Together they are a coverage forecast: how fragile the line is, how deep the
bench is, and how likely the bench gets called.
"""

from __future__ import annotations

from datetime import date

from .duty import fdp_limit
from .rules.duty02 import MAX_DUTY_HOURS
from .timeutil import at, fmt_dt, hrs
from .windows import DUTY, window_sum
from .world import World


def morning_briefing(world: World, *, on: date) -> dict:
    lines = []

    for pairing in sorted(world.pairings, key=lambda p: (p.aircraft, p.days[0].date)):
        day = next((d for d in pairing.days if d.date == on), None)
        if day is None:
            continue

        aircraft_type = world.flight(day.flight_ids[0]).aircraft_type
        dep_station = world.flight(day.flight_ids[0]).dep_station

        # 1. Legality headroom -------------------------------------------
        duty_hours = hrs(day.release_utc - day.report_utc)
        limit = fdp_limit(day.sectors)
        tightest = None
        for crew_id, role in pairing.crew:
            used = window_sum(world, crew_id, on, 7, DUTY)
            margin = round(MAX_DUTY_HOURS - used, 2)
            if tightest is None or margin < tightest["headroom_hours"]:
                tightest = {
                    "crew_id": crew_id,
                    "role": role,
                    "duty_hours_7d": used,
                    "headroom_hours": margin,
                }

        # 2. Reserve depth ------------------------------------------------
        depth: dict[str, int] = {}
        available: dict[str, list[str]] = {}
        for reserve in world.reserves:
            if on not in reserve.dates or reserve.base != dep_station:
                continue
            crew = world.crew_member(reserve.crew_id)
            if aircraft_type not in crew.ratings:
                continue
            start = at(on, reserve.oncall_start)
            end = at(on, reserve.oncall_end)
            if not (start <= day.report_utc <= end):
                continue
            depth[crew.rank] = depth.get(crew.rank, 0) + 1
            available.setdefault(crew.rank, []).append(crew.crew_id)

        roles_needed = sorted({role for _, role in pairing.crew})
        uncovered_roles = [role for role in roles_needed if depth.get(role, 0) == 0]

        # 3. Disruption risk ----------------------------------------------
        risks = []
        for crew_id, role in pairing.crew:
            signal = world.risk(crew_id)
            if signal is None:
                continue
            risks.append(
                {
                    "crew_id": crew_id,
                    "role": role,
                    "score": signal.disruption_risk_score,
                    "drivers": list(signal.drivers),
                }
            )
        risks.sort(key=lambda x: -x["score"])

        lines.append(
            {
                "aircraft": pairing.aircraft,
                "aircraft_type": aircraft_type,
                "pairing_id": pairing.pairing_id,
                "date": on.isoformat(),
                "report_utc": fmt_dt(day.report_utc),
                "release_utc": fmt_dt(day.release_utc),
                "sectors": day.sectors,
                "seats": sum(world.flight(fid).seats for fid in day.flight_ids),
                "duty_headroom": {
                    "tightest_crew": tightest,
                    "fdp_hours": duty_hours,
                    "fdp_limit": limit,
                    "fdp_margin_hours": round(limit - duty_hours, 2),
                    "fragile": round(limit - duty_hours, 2) <= 1.0,
                    "rule": "RULE-DUTY-02 / RULE-FDP-01",
                },
                "reserve_depth": {
                    "by_rank": depth,
                    "available": available,
                    "uncovered_roles": uncovered_roles,
                    "filtered_on": "base, aircraft rating, and on-call window covering this report time",
                    "rule": "RULE-BASE-07 / RULE-QUAL-05",
                },
                "risk": {
                    "highest": risks[0] if risks else None,
                    "crew": risks[:3],
                    "note": "provided pre-computed signal, not a model output",
                },
            }
        )

    fragile = [x for x in lines if x["duty_headroom"]["fragile"]]
    thin = [x for x in lines if x["reserve_depth"]["uncovered_roles"]]

    return {
        "date": on.isoformat(),
        "lines": lines,
        "line_count": len(lines),
        "headline": {
            "fragile_fdp_lines": [x["aircraft"] for x in fragile],
            "thin_reserve_lines": [x["aircraft"] for x in thin],
            "highest_risk_crew": max(
                (x["risk"]["highest"] for x in lines if x["risk"]["highest"]),
                key=lambda r: r["score"],
                default=None,
            ),
        },
        "rationale": [
            "duty_headroom — can today's crew legally absorb a slip?",
            "reserve_depth — if someone drops out, who can legally take it?",
            "risk — who is most likely to drop out?",
        ],
    }
