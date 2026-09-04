"""Build a :class:`World` from the shipped dataset JSON.

Pure stdlib. Takes a directory path or pre-parsed dicts, so tests can build a
world from fixtures without touching disk.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import (
    Certification,
    Costs,
    Crew,
    DutyClock,
    Flight,
    Pairing,
    PairingDay,
    Reserve,
    RiskSignal,
    Rule,
)
from .timeutil import parse_date, parse_dt
from .world import World

DATASET_FILES = (
    "flights",
    "crew",
    "rosters",
    "duty_clocks",
    "reserve_pool",
    "certifications",
    "rules",
    "costs",
    "risk_signals",
)


def read_dataset(data_dir: str | Path) -> dict[str, Any]:
    base = Path(data_dir)
    raw: dict[str, Any] = {}
    for name in DATASET_FILES:
        with open(base / f"{name}.json", encoding="utf-8") as fh:
            raw[name] = json.load(fh)
    return raw


def read_json(data_dir: str | Path, name: str) -> Any:
    with open(Path(data_dir) / f"{name}.json", encoding="utf-8") as fh:
        return json.load(fh)


def build_world(raw: dict[str, Any], snapshot_utc: str | None = None) -> World:
    flights = tuple(
        Flight(
            flight_id=f["flight_id"],
            flight_no=f["flight_no"],
            date=parse_date(f["date"]),
            dep_station=f["dep_station"],
            arr_station=f["arr_station"],
            dep_utc=parse_dt(f["dep_utc"]),
            arr_utc=parse_dt(f["arr_utc"]),
            block_hours=float(f["block_hours"]),
            aircraft=f["aircraft"],
            aircraft_type=f["aircraft_type"],
            seats=int(f["seats"]),
        )
        for f in raw["flights"]
    )

    crew = tuple(
        Crew(
            crew_id=c["crew_id"],
            name=c["name"],
            rank=c["rank"],
            base=c["base"],
            ratings=tuple(c["ratings"]),
            seniority=int(c["seniority"]),
            reachability_minutes=int(c["reachability_minutes"]),
            status=c.get("status", "active"),
        )
        for c in raw["crew"]
    )

    pairings = tuple(
        Pairing(
            pairing_id=p["pairing_id"],
            aircraft=p["aircraft"],
            days=tuple(
                PairingDay(
                    pairing_id=p["pairing_id"],
                    day_index=i,
                    date=parse_date(d["date"]),
                    flight_ids=tuple(d["flights"]),
                    report_utc=parse_dt(d["report_utc"]),
                    release_utc=parse_dt(d["release_utc"]),
                )
                for i, d in enumerate(p["days"])
            ),
            crew=tuple((m["crew_id"], m["role"]) for m in p["crew"]),
        )
        for p in raw["rosters"]["pairings"]
    )

    duty_clocks = tuple(
        DutyClock(
            crew_id=d["crew_id"],
            as_of_utc=parse_dt(d["as_of_utc"]),
            duty_hours_7d=float(d["duty_hours_7d"]),
            flight_hours_28d=float(d["flight_hours_28d"]),
            last_rest_ended=parse_dt(d["last_rest_ended"]) if d.get("last_rest_ended") else None,
            daily_history={
                parse_date(h["date"]): (float(h["duty_hours"]), float(h["flight_hours"]))
                for h in d["daily_history"]
            },
        )
        for d in raw["duty_clocks"]
    )

    reserves = tuple(
        Reserve(
            crew_id=r["crew_id"],
            base=r["base"],
            dates=tuple(parse_date(x) for x in r["dates"]),
            oncall_start=r["oncall_window_utc"]["start"],
            oncall_end=r["oncall_window_utc"]["end"],
        )
        for r in raw["reserve_pool"]
    )

    certifications = tuple(
        Certification(
            crew_id=c["crew_id"],
            cert_type=c["cert_type"],
            valid_from=parse_date(c["valid_from"]),
            valid_to=parse_date(c["valid_to"]),
        )
        for c in raw["certifications"]
    )

    rules = tuple(
        Rule(rule_id=r["rule_id"], text=r["text"], params=r.get("params", {}))
        for r in raw["rules"]["rules"]
    )

    c = raw["costs"]
    costs = Costs(
        currency=c["currency"],
        reserve_callout_pilot=int(c["reserve_callout_pilot"]),
        reserve_callout_cabin=int(c["reserve_callout_cabin"]),
        dayoff_callout_pilot=int(c["dayoff_callout_pilot"]),
        dayoff_callout_cabin=int(c["dayoff_callout_cabin"]),
        deadhead_positioning=int(c["deadhead_positioning"]),
        delay_cost_per_duty_hour=int(c["delay_cost_per_duty_hour"]),
        cancellation_per_flight=int(c["cancellation_per_flight"]),
        hotel_overnight=int(c["hotel_overnight"]),
    )

    risk_signals = tuple(
        RiskSignal(
            crew_id=r["crew_id"],
            as_of_utc=parse_dt(r["as_of_utc"]),
            disruption_risk_score=float(r["disruption_risk_score"]),
            drivers=tuple(r["drivers"]),
        )
        for r in raw["risk_signals"]
    )

    snapshot = parse_dt(snapshot_utc) if snapshot_utc else duty_clocks[0].as_of_utc

    return World(
        snapshot_utc=snapshot,
        flights=flights,
        crew=crew,
        pairings=pairings,
        duty_clocks=duty_clocks,
        reserves=reserves,
        certifications=certifications,
        rules=rules,
        costs=costs,
        risk_signals=risk_signals,
        flagged_exceptions=tuple(raw["rosters"].get("flagged_exceptions", ())),
    )


@lru_cache(maxsize=4)
def load_world(data_dir: str) -> World:
    """Load and cache the base world for a dataset directory."""
    return build_world(read_dataset(data_dir))


def snapshot_date(world: World) -> date:
    return world.snapshot_utc.date()
