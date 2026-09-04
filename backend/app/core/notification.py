"""Crew notification drafting.

The slots are deterministic; only the wording is left to the language model.
``build_slots`` returns everything a message must contain, extracted from the
world -- so a drafted notification cannot invent a report time or a flight
number. ``render_fallback`` produces a correct, unglamorous message with no
model involved at all, which is what ships if the LLM is unavailable or its
draft fails verification.
"""

from __future__ import annotations

from datetime import timedelta

from .world import World


def build_slots(
    world: World,
    *,
    crew_id: str,
    pairing_id: str,
    delay_hours: float = 0.0,
    positioning: dict | None = None,
    cost_inr: int | None = None,
) -> dict:
    crew = world.crew_member(crew_id)
    pairing = world.pairing(pairing_id)
    first = pairing.days[0]
    report = first.report_utc + timedelta(hours=delay_hours)

    legs = []
    for day in pairing.days:
        for fid in day.flight_ids:
            f = world.flight(fid)
            legs.append(
                {
                    "flight_no": f.flight_no,
                    "date": f.date.isoformat(),
                    "route": f"{f.dep_station}-{f.arr_station}",
                    "dep_utc": f.dep_utc.strftime("%H:%MZ"),
                    "arr_utc": f.arr_utc.strftime("%H:%MZ"),
                }
            )

    return {
        "crew_id": crew_id,
        "crew_name": crew.name,
        "rank": crew.rank,
        "base": crew.base,
        "reachability_minutes": crew.reachability_minutes,
        "pairing_id": pairing_id,
        "aircraft": pairing.aircraft,
        "aircraft_type": world.flight(first.flight_ids[0]).aircraft_type,
        "report_utc": report.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "report_station": world.flight(first.flight_ids[0]).dep_station,
        "release_utc": pairing.days[-1].release_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "days": len(pairing.days),
        "sectors": pairing.total_sectors,
        "legs": legs,
        "overnight_station": (
            world.flight(pairing.days[0].flight_ids[-1]).arr_station
            if len(pairing.days) > 1
            else None
        ),
        "positioning": positioning,
        "cost_inr": cost_inr,
        "currency": world.costs.currency,
    }


def render_fallback(slots: dict) -> str:
    """A correct message with zero model involvement."""
    lines = [
        f"CREW CALLOUT — {slots['pairing_id']}",
        "",
        f"{slots['rank']} {slots['crew_name']} ({slots['crew_id']}),",
        "",
        f"You are called out to operate pairing {slots['pairing_id']} "
        f"({slots['aircraft']}, {slots['aircraft_type']}).",
        f"Report: {slots['report_utc']} at {slots['report_station']}.",
        f"Duty: {slots['days']} day(s), {slots['sectors']} sectors.",
    ]
    if slots.get("overnight_station"):
        lines.append(f"Night stop: {slots['overnight_station']}.")
    if slots.get("positioning"):
        p = slots["positioning"]
        lines.append(
            f"Positioning: {p['flight_no']} {p['from_station']}-{p['to_station']}, "
            f"arriving {p['arrival_utc']}."
        )
    lines.append("")
    lines.append("Sectors:")
    for leg in slots["legs"]:
        lines.append(
            f"  {leg['flight_no']}  {leg['date']}  {leg['route']}  "
            f"{leg['dep_utc']}-{leg['arr_utc']}"
        )
    lines.append("")
    lines.append("Please acknowledge receipt to Crew Control.")
    return "\n".join(lines)
