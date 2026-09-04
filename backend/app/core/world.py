"""The operational world: an immutable, fully-indexed snapshot of the airline.

Design note -- why an in-memory world and not "just query Postgres":

* The legality engine walks a crew member's whole 28-day timeline for every
  candidate, for every duty day. On a 24-candidate enumeration that is a few
  thousand lookups. Doing that over SQL round-trips is both slower and harder
  to keep bit-identical with the answer keys.
* The conformance harness has to run with zero infrastructure. ``World`` loads
  from the shipped JSON in ~40ms, so ``pytest`` needs no database.

Postgres remains the system of record for everything the API *writes* (traces,
decisions, alerts, eval runs) and backs the paginated read endpoints. The world
snapshot is read-only by construction: ``apply()`` returns a new ``World``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from .models import (
    Certification,
    Costs,
    Crew,
    DutyClock,
    DutySegment,
    Flight,
    Pairing,
    PairingDay,
    Reserve,
    RiskSignal,
    Rule,
)
from .timeutil import hrs


@dataclass(frozen=True)
class World:
    """An immutable operational snapshot plus derived indexes."""

    snapshot_utc: datetime
    flights: tuple[Flight, ...]
    crew: tuple[Crew, ...]
    pairings: tuple[Pairing, ...]
    duty_clocks: tuple[DutyClock, ...]
    reserves: tuple[Reserve, ...]
    certifications: tuple[Certification, ...]
    rules: tuple[Rule, ...]
    costs: Costs
    risk_signals: tuple[RiskSignal, ...]
    flagged_exceptions: tuple[dict[str, Any], ...] = ()

    # Overlay bookkeeping (populated by World.apply)
    lineage: tuple[dict[str, Any], ...] = ()
    unavailable_crew: frozenset[str] = frozenset()

    # ---- derived indexes, built in __post_init__ -------------------------
    _by_flight: dict[str, Flight] = field(default_factory=dict, repr=False, compare=False)
    _by_crew: dict[str, Crew] = field(default_factory=dict, repr=False, compare=False)
    _by_pairing: dict[str, Pairing] = field(default_factory=dict, repr=False, compare=False)
    _pairing_of_flight: dict[str, tuple[Pairing, PairingDay]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _clock_of: dict[str, DutyClock] = field(default_factory=dict, repr=False, compare=False)
    _reserve_of: dict[str, Reserve] = field(default_factory=dict, repr=False, compare=False)
    _certs_of: dict[str, dict[str, Certification]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _risk_of: dict[str, RiskSignal] = field(default_factory=dict, repr=False, compare=False)
    _rule_of: dict[str, Rule] = field(default_factory=dict, repr=False, compare=False)
    _week_duties: dict[str, tuple[DutySegment, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _history: dict[str, dict[date, tuple[float, float]]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _flights_by_date: dict[date, tuple[Flight, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _flights_by_tail: dict[str, tuple[Flight, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_flight", {f.flight_id: f for f in self.flights})
        object.__setattr__(self, "_by_crew", {c.crew_id: c for c in self.crew})
        object.__setattr__(self, "_by_pairing", {p.pairing_id: p for p in self.pairings})
        object.__setattr__(self, "_clock_of", {d.crew_id: d for d in self.duty_clocks})
        object.__setattr__(self, "_reserve_of", {r.crew_id: r for r in self.reserves})
        object.__setattr__(self, "_risk_of", {r.crew_id: r for r in self.risk_signals})
        object.__setattr__(self, "_rule_of", {r.rule_id: r for r in self.rules})

        certs: dict[str, dict[str, Certification]] = defaultdict(dict)
        for cert in self.certifications:
            certs[cert.crew_id][cert.cert_type] = cert
        object.__setattr__(self, "_certs_of", dict(certs))

        pof: dict[str, tuple[Pairing, PairingDay]] = {}
        for pairing in self.pairings:
            for day in pairing.days:
                for fid in day.flight_ids:
                    pof[fid] = (pairing, day)
        object.__setattr__(self, "_pairing_of_flight", pof)

        by_date: dict[date, list[Flight]] = defaultdict(list)
        by_tail: dict[str, list[Flight]] = defaultdict(list)
        for f in self.flights:
            by_date[f.date].append(f)
            by_tail[f.aircraft].append(f)
        object.__setattr__(
            self,
            "_flights_by_date",
            {d: tuple(sorted(v, key=lambda x: x.dep_utc)) for d, v in by_date.items()},
        )
        object.__setattr__(
            self,
            "_flights_by_tail",
            {t: tuple(sorted(v, key=lambda x: x.dep_utc)) for t, v in by_tail.items()},
        )

        object.__setattr__(self, "_history", {d.crew_id: d.daily_history for d in self.duty_clocks})
        object.__setattr__(self, "_week_duties", self._build_week_duties())

    # ------------------------------------------------------------------
    # Derived: the rostered duty timeline (generator's ``week_duties``)
    # ------------------------------------------------------------------
    def _build_week_duties(self) -> dict[str, tuple[DutySegment, ...]]:
        acc: dict[str, list[DutySegment]] = {c.crew_id: [] for c in self.crew}
        for pairing in self.pairings:
            for day in pairing.days:
                flight_hours = round(
                    sum(self._by_flight[fid].block_hours for fid in day.flight_ids), 2
                )
                seg = DutySegment(
                    date=day.date,
                    report_utc=day.report_utc,
                    release_utc=day.release_utc,
                    duty_hours=hrs(day.release_utc - day.report_utc),
                    flight_hours=flight_hours,
                    label=pairing.pairing_id,
                )
                for crew_id, _role in pairing.crew:
                    acc.setdefault(crew_id, []).append(seg)
        # The generator sorts by date; keep that ordering exactly.
        return {cid: tuple(sorted(v, key=lambda s: s.date)) for cid, v in acc.items()}

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def flight(self, flight_id: str) -> Flight:
        return self._by_flight[flight_id]

    def get_flight(self, flight_id: str) -> Flight | None:
        return self._by_flight.get(flight_id)

    def find_flight(self, flight_no: str, on: date) -> Flight | None:
        return self._by_flight.get(f"{flight_no}-{on.isoformat()}")

    def crew_member(self, crew_id: str) -> Crew:
        return self._by_crew[crew_id]

    def get_crew(self, crew_id: str) -> Crew | None:
        return self._by_crew.get(crew_id)

    def pairing(self, pairing_id: str) -> Pairing:
        return self._by_pairing[pairing_id]

    def get_pairing(self, pairing_id: str) -> Pairing | None:
        return self._by_pairing.get(pairing_id)

    def pairing_of_flight(self, flight_id: str) -> tuple[Pairing, PairingDay] | None:
        return self._pairing_of_flight.get(flight_id)

    def pairing_for(self, tail: str, on: date) -> Pairing | None:
        for pairing in self.pairings:
            if pairing.aircraft == tail and pairing.days[0].date == on:
                return pairing
        return None

    def pairings_covering(self, crew_id: str, on: date) -> list[Pairing]:
        out = []
        for pairing in self.pairings:
            if any(cid == crew_id for cid, _ in pairing.crew) and any(
                d.date == on for d in pairing.days
            ):
                out.append(pairing)
        return out

    def clock(self, crew_id: str) -> DutyClock:
        return self._clock_of[crew_id]

    def reserve(self, crew_id: str) -> Reserve | None:
        return self._reserve_of.get(crew_id)

    @property
    def reserve_ids(self) -> frozenset[str]:
        return frozenset(self._reserve_of)

    def certs(self, crew_id: str) -> dict[str, Certification]:
        return self._certs_of.get(crew_id, {})

    def risk(self, crew_id: str) -> RiskSignal | None:
        return self._risk_of.get(crew_id)

    def rule(self, rule_id: str) -> Rule | None:
        return self._rule_of.get(rule_id)

    def week_duties(self, crew_id: str) -> tuple[DutySegment, ...]:
        return self._week_duties.get(crew_id, ())

    def history(self, crew_id: str) -> dict[date, tuple[float, float]]:
        return self._history.get(crew_id, {})

    def flights_on(self, on: date) -> tuple[Flight, ...]:
        return self._flights_by_date.get(on, ())

    def flights_of_tail(self, tail: str) -> tuple[Flight, ...]:
        return self._flights_by_tail.get(tail, ())

    @property
    def stations(self) -> tuple[str, ...]:
        return tuple(sorted({f.dep_station for f in self.flights} | {f.arr_station for f in self.flights}))

    @property
    def dates(self) -> tuple[date, ...]:
        return tuple(sorted(self._flights_by_date))

    def crew_where(
        self,
        *,
        rank: str | None = None,
        base: str | None = None,
        rating: str | None = None,
        status: str | None = None,
    ) -> list[Crew]:
        out = []
        for c in self.crew:
            if rank and c.rank != rank:
                continue
            if base and c.base != base:
                continue
            if rating and rating not in c.ratings:
                continue
            if status and c.status != status:
                continue
            out.append(c)
        return out

    def is_available(self, crew_id: str) -> bool:
        """False if an overlay (e.g. a sick call) removed this crew member."""
        return crew_id not in self.unavailable_crew

    # ------------------------------------------------------------------
    # Forking
    # ------------------------------------------------------------------
    def apply(self, event: dict[str, Any], **overrides: Any) -> "World":
        """Return a NEW world with ``event`` recorded in the lineage.

        The base snapshot is never mutated. Chained disruptions are just
        ``world.apply(e1).apply(e2)`` -- the lineage records the chain.
        """
        return replace(
            self,
            lineage=self.lineage + (event,),
            **overrides,
        )

    def with_crew_unavailable(self, crew_ids: Iterable[str], event: dict[str, Any]) -> "World":
        return self.apply(
            event,
            unavailable_crew=self.unavailable_crew | frozenset(crew_ids),
        )

    def date_range(self) -> tuple[date, date]:
        ds = self.dates
        return ds[0], ds[-1]

    def history_span(self) -> tuple[date, date]:
        any_hist = next(iter(self._history.values()), {})
        if not any_hist:
            start, _ = self.date_range()
            return start, start
        keys = sorted(any_hist)
        return keys[0], keys[-1]

    def horizon_end(self) -> date:
        return self.date_range()[1] + timedelta(days=1)
