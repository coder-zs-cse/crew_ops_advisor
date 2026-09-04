"""Deadhead positioning (RULE-BASE-07 support).

Table-driven on purpose. The shipped network only supports DEL->BLR same-day
positioning, but that is a property of the *data*, not of the algorithm: adding
a city pair here is a one-line change and every downstream cost, delay and
legality calculation follows automatically.

Timing convention from the dataset README:
    new report      = positioning arrival + 15 min transit
    new departure   = new report + 60 min report lead
    delay to flight = max(0, new departure - scheduled departure)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .timeutil import at, hrs, is_even_date

TRANSIT_MINUTES = 15
REPORT_LEAD_MINUTES = 60


@dataclass(frozen=True, slots=True)
class PositioningLeg:
    """One published option for repositioning crew between two stations."""

    from_station: str
    to_station: str
    flight_no: str
    arrival_hhmm: str
    #: "even" | "odd" | "daily" -- which dates this leg operates on
    date_parity: str = "daily"

    def operates_on(self, day: date) -> bool:
        if self.date_parity == "daily":
            return True
        return is_even_date(day) if self.date_parity == "even" else not is_even_date(day)


#: The positioning table. Derived from the published schedule: DX589 arrives BLR
#: 07:45Z on even dates, DX402 arrives 08:45Z on odd dates.
POSITIONING_TABLE: tuple[PositioningLeg, ...] = (
    PositioningLeg("DEL", "BLR", "DX589", "07:45", "even"),
    PositioningLeg("DEL", "BLR", "DX402", "08:45", "odd"),
)


@dataclass(frozen=True, slots=True)
class PositioningOption:
    from_station: str
    to_station: str
    flight_no: str
    arrival: datetime
    new_report: datetime
    delay_hours: float

    def as_dict(self) -> dict:
        return {
            "from_station": self.from_station,
            "to_station": self.to_station,
            "flight_no": self.flight_no,
            "arrival_utc": self.arrival.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "new_report_utc": self.new_report.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "delay_hours": self.delay_hours,
        }


def find_positioning(
    world,
    *,
    from_station: str,
    to_station: str,
    on: date,
    required_departure: datetime,
) -> PositioningOption | None:
    """Cheapest (earliest-arriving) way to get crew from base to the duty start.

    Returns ``None`` when no same-day positioning exists, which RULE-BASE-07
    turns into an exclusion.
    """
    candidates = [
        leg
        for leg in POSITIONING_TABLE
        if leg.from_station == from_station and leg.to_station == to_station and leg.operates_on(on)
    ]
    if not candidates:
        return None

    best: PositioningOption | None = None
    for leg in candidates:
        arrival = at(on, leg.arrival_hhmm)
        new_report = arrival + timedelta(minutes=TRANSIT_MINUTES)
        new_departure = new_report + timedelta(minutes=REPORT_LEAD_MINUTES)
        delay = round(max(0.0, hrs(new_departure - required_departure)), 2)
        option = PositioningOption(
            from_station=from_station,
            to_station=to_station,
            flight_no=leg.flight_no,
            arrival=arrival,
            new_report=new_report,
            delay_hours=delay,
        )
        if best is None or option.delay_hours < best.delay_hours:
            best = option
    return best
