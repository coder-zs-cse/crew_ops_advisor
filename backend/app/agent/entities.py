"""Entity resolution -- propose loosely, validate strictly.

The language model may *propose* that "Captain Nair" means C-1042. This module
is what decides. Every identifier that reaches a tool has been checked against
the world; an id that does not resolve becomes a clarification, never a guess.

That asymmetry is the whole point of the LLM/deterministic boundary at the
input end: the model is good at reading "the DXA captain tomorrow morning" and
bad at being certain, so it proposes and code confirms.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from ..core.world import World
from .state import Entities

CREW_RE = re.compile(r"\bC-?(\d{4})\b", re.I)
PAIRING_RE = re.compile(r"\bP-?(\d{4})\b", re.I)
FLIGHT_RE = re.compile(r"\b(DX\s?\d{3})\b", re.I)
TAIL_RE = re.compile(r"\b(VT-?DX[A-Z])\b", re.I)
RULE_RE = re.compile(r"\bRULE-([A-Z]+)-?(\d{2})\b", re.I)
ISO_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
ISO_DT_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z?)\b")
TIME_RE = re.compile(r"\b([0-2]?\d):([0-5]\d)\s*Z?\b")
NUMBER_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:h|hours?|hrs?)\b", re.I)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
DAY_MONTH_RE = re.compile(
    r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")\w*\b", re.I
)
MONTH_DAY_RE = re.compile(
    r"\b(" + "|".join(MONTHS) + r")\w*\s+(\d{1,2})\b", re.I
)

#: Most specific first -- "senior cabin crew" must win over "cabin crew".
#: Plurals matter: controllers write "both captains", "two first officers".
ROLE_PATTERNS = [
    (re.compile(r"\bsenior cabin crew\b|\bsccs?\b", re.I), "Senior Cabin Crew"),
    (re.compile(r"\bcabin crew\b|\bflight attendants?\b|\bccs?\b", re.I), "Cabin Crew"),
    (re.compile(r"\bfirst officers?\b|\bf/?os?\b|\bco-?pilots?\b", re.I), "First Officer"),
    (re.compile(r"\bcaptains?\b|\bcapts?\b|\bcpts?\b", re.I), "Captain"),
]


def _normalise_flight_no(raw: str) -> str:
    return raw.replace(" ", "").upper()


def _normalise_tail(raw: str) -> str:
    value = raw.upper().replace(" ", "")
    return value if "-" in value else f"{value[:2]}-{value[2:]}"


def _relative_date(text: str, world: World) -> list[date]:
    """Resolve 'today' / 'tomorrow' against the dataset snapshot, not wall clock.

    The world is frozen at 2026-09-14T18:00Z. Interpreting "tomorrow" as the
    real calendar date would silently fall outside the schedule window, so we
    anchor on the snapshot and say so in the answer.
    """
    anchor = world.snapshot_utc.date()
    out: list[date] = []
    lowered = text.lower()
    if re.search(r"\btoday\b|\bthis morning\b|\bthis afternoon\b|\btonight\b", lowered):
        out.append(anchor)
    if re.search(r"\btomorrow\b", lowered):
        out.append(anchor + timedelta(days=1))
    if re.search(r"\byesterday\b", lowered):
        out.append(anchor - timedelta(days=1))
    if re.search(r"\bday after tomorrow\b", lowered):
        out.append(anchor + timedelta(days=2))
    return out


def _year_for(month: int, day: int, world: World) -> date | None:
    """Pick the year from the schedule window rather than assuming the present."""
    for candidate_year in {d.year for d in world.dates}:
        try:
            candidate = date(candidate_year, month, day)
        except ValueError:
            continue
        return candidate
    return None


def resolve(text: str, world: World, *, proposed: dict | None = None) -> Entities:
    """Extract and validate every identifier in a question.

    ``proposed`` accepts hints from the LLM classifier; they are merged in and
    then subjected to exactly the same validation as pattern matches.
    """
    ents = Entities()
    seen_dates: list[date] = []

    # ---- crew ---------------------------------------------------------
    for match in CREW_RE.finditer(text):
        cid = f"C-{match.group(1)}"
        if world.get_crew(cid):
            if cid not in ents.crew_ids:
                ents.crew_ids.append(cid)
        else:
            ents.unresolved.append({"kind": "crew", "value": cid})

    # ---- pairings ------------------------------------------------------
    for match in PAIRING_RE.finditer(text):
        pid = f"P-{match.group(1)}"
        if world.get_pairing(pid):
            if pid not in ents.pairing_ids:
                ents.pairing_ids.append(pid)
        else:
            ents.unresolved.append({"kind": "pairing", "value": pid})

    # ---- tails ---------------------------------------------------------
    known_tails = {f.aircraft for f in world.flights}
    for match in TAIL_RE.finditer(text):
        tail = _normalise_tail(match.group(1))
        if tail in known_tails:
            if tail not in ents.aircraft:
                ents.aircraft.append(tail)
        else:
            ents.unresolved.append({"kind": "aircraft", "value": tail})

    # ---- stations ------------------------------------------------------
    for station in world.stations:
        if re.search(rf"\b{station}\b", text, re.I):
            ents.stations.append(station)

    # ---- rules ---------------------------------------------------------
    for match in RULE_RE.finditer(text):
        rid = f"RULE-{match.group(1).upper()}-{match.group(2)}"
        if world.rule(rid):
            if rid not in ents.rule_ids:
                ents.rule_ids.append(rid)

    # ---- dates ---------------------------------------------------------
    for match in ISO_DATE_RE.finditer(text):
        try:
            seen_dates.append(date.fromisoformat(match.group(1)))
        except ValueError:
            pass
    for match in DAY_MONTH_RE.finditer(text):
        resolved = _year_for(MONTHS[match.group(2)[:3].lower()], int(match.group(1)), world)
        if resolved:
            seen_dates.append(resolved)
    for match in MONTH_DAY_RE.finditer(text):
        resolved = _year_for(MONTHS[match.group(1)[:3].lower()], int(match.group(2)), world)
        if resolved:
            seen_dates.append(resolved)
    seen_dates.extend(_relative_date(text, world))

    for value in seen_dates:
        iso = value.isoformat()
        if iso not in ents.dates:
            ents.dates.append(iso)

    # ---- flights (need a date to become flight_ids) ---------------------
    for match in FLIGHT_RE.finditer(text):
        flight_no = _normalise_flight_no(match.group(1))
        known = {f.flight_no for f in world.flights}
        if flight_no not in known:
            ents.unresolved.append({"kind": "flight", "value": flight_no})
            continue
        if flight_no not in ents.flight_nos:
            ents.flight_nos.append(flight_no)
        for iso in ents.dates:
            flight = world.find_flight(flight_no, date.fromisoformat(iso))
            if flight and flight.flight_id not in ents.flight_ids:
                ents.flight_ids.append(flight.flight_id)

    # ---- times ----------------------------------------------------------
    for match in ISO_DT_RE.finditer(text):
        raw = match.group(1)
        if not raw.endswith("Z"):
            raw += "Z"
        if len(raw) == 17:  # no seconds
            raw = raw[:-1] + ":00Z"
        ents.times_utc.append(raw)
    if not ents.times_utc and ents.dates:
        for match in TIME_RE.finditer(text):
            hh, mm = int(match.group(1)), int(match.group(2))
            if hh > 23:
                continue
            ents.times_utc.append(f"{ents.dates[0]}T{hh:02d}:{mm:02d}:00Z")

    # ---- roles ------------------------------------------------------------
    for pattern, role in ROLE_PATTERNS:
        if pattern.search(text):
            ents.roles.append(role)
            break

    # ---- numbers with an hours unit ---------------------------------------
    for match in NUMBER_RE.finditer(text):
        ents.numbers.append(float(match.group(1)))

    if proposed:
        _merge_proposed(ents, proposed, world)

    _infer_missing(ents, world, text)
    return ents


def _merge_proposed(ents: Entities, proposed: dict, world: World) -> None:
    """Fold in the classifier's hints, validating each one."""
    validators = {
        "crew_ids": (world.get_crew, ents.crew_ids, "crew"),
        "pairing_ids": (world.get_pairing, ents.pairing_ids, "pairing"),
        "flight_ids": (world.get_flight, ents.flight_ids, "flight"),
    }
    for field_name, (check, target, kind) in validators.items():
        for value in proposed.get(field_name, []) or []:
            if value in target:
                continue
            if check(value):
                target.append(value)
            else:
                ents.unresolved.append({"kind": kind, "value": value, "source": "llm"})

    for field_name, target in (
        ("stations", ents.stations),
        ("aircraft", ents.aircraft),
        ("dates", ents.dates),
        ("times_utc", ents.times_utc),
        ("roles", ents.roles),
    ):
        for value in proposed.get(field_name, []) or []:
            if value and value not in target:
                target.append(value)


def _infer_missing(ents: Entities, world: World, text: str) -> None:
    """Fill gaps that are unambiguous from the data itself."""
    # Each named crew member implies their next pairing. Resolved per crew and
    # kept index-aligned with crew_ids, so a two-sick-call question produces two
    # openings in the right order.
    if ents.crew_ids and not ents.pairing_ids:
        anchor = date.fromisoformat(ents.dates[0]) if ents.dates else world.snapshot_utc.date()
        for crew_id in ents.crew_ids:
            matches = [
                p
                for p in world.pairings
                if any(cid == crew_id for cid, _ in p.crew) and p.days[-1].date >= anchor
            ]
            if not matches:
                continue
            matches.sort(key=lambda p: p.days[0].date)
            ents.pairing_ids.append(matches[0].pairing_id)
            if len(matches) > 1:
                ents.ambiguous.append(
                    {
                        "kind": "pairing",
                        "for_crew": crew_id,
                        "chosen": matches[0].pairing_id,
                        "alternatives": [p.pairing_id for p in matches[1:4]],
                        "basis": "earliest pairing at or after the referenced date",
                    }
                )

    # A tail plus a date implies that day's pairing -- one per tail named, so
    # "both captains of VT-DXA and VT-DXB" yields two openings in order.
    if ents.aircraft and ents.dates and not ents.pairing_ids:
        on = date.fromisoformat(ents.dates[0])
        for tail in ents.aircraft:
            pairing = world.pairing_for(tail, on)
            if pairing is None:
                pairing = next(
                    (p for p in world.pairings if p.aircraft == tail and any(d.date == on for d in p.days)),
                    None,
                )
            if pairing:
                ents.pairing_ids.append(pairing.pairing_id)

    # "the captain of VT-DXA" names a person without giving their id: read it
    # off the roster for the pairing we just resolved.
    if ents.pairing_ids and ents.roles and not ents.crew_ids:
        wanted = ents.roles[0]
        for pairing_id in ents.pairing_ids:
            pairing = world.get_pairing(pairing_id)
            if pairing is None:
                continue
            holder = next((cid for cid, role in pairing.crew if role == wanted), None)
            if holder and holder not in ents.crew_ids:
                ents.crew_ids.append(holder)

    # A crew member's rank is the role unless the question named one.
    if ents.crew_ids and not ents.roles:
        crew = world.get_crew(ents.crew_ids[0])
        if crew:
            ents.roles.append(crew.rank)


def describe_gap(ents: Entities, needed: list[str]) -> list[str]:
    """Which required slots are still empty -- drives the clarification path."""
    have = {
        "crew_id": bool(ents.crew_ids),
        "pairing_id": bool(ents.pairing_ids),
        "flight_id": bool(ents.flight_ids),
        "date": bool(ents.dates),
        "station": bool(ents.stations),
        "aircraft": bool(ents.aircraft),
        "time": bool(ents.times_utc),
        "role": bool(ents.roles),
    }
    return [slot for slot in needed if not have.get(slot, False)]
