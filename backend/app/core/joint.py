"""Joint assignment across simultaneous openings.

When two captains call in sick on the same morning, the two openings compete
for the same scarce pool. Solving them independently double-books the cheapest
reserve; solving them jointly costs a little more on one opening and less
overall.

Exhaustive for small N (the realistic case for a crew desk handling concurrent
disruptions), with a greedy fallback guard for pathological inputs. Equal-cost
mirror assignments are equally correct -- the dataset says so explicitly -- so
we surface ties rather than pretending the tie-break is meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Sequence

from .candidates import CandidateSet

MAX_EXHAUSTIVE_COMBINATIONS = 250_000


@dataclass(frozen=True, slots=True)
class Opening:
    key: str
    label: str
    candidate_set: CandidateSet


@dataclass(frozen=True, slots=True)
class JointPlan:
    total_cost_inr: int
    assignments: dict[str, dict]
    tie_count: int
    alternatives: tuple[dict, ...]
    method: str

    def as_dict(self) -> dict:
        return {
            "total_cost_inr": self.total_cost_inr,
            "assignments": self.assignments,
            "tie_count": self.tie_count,
            "equal_cost_alternatives": list(self.alternatives),
            "method": self.method,
            "note": (
                "The same crew member cannot cover two openings. Equal-cost mirror "
                "assignments are equally correct."
            ),
        }


def _choices(cs: CandidateSet, unavailable: set[str]) -> list[dict]:
    """Every way to resolve one opening: each legal candidate, plus cancel.

    ``unavailable`` drops anyone who is themselves part of the disruption --
    a captain who called in sick for pairing B must not be offered as cover for
    pairing A, even though the per-opening enumeration (deliberately) still
    evaluated and reported on them.
    """
    out = [
        c.as_answer_key_dict() for c in cs.eligible if c.crew_id not in unavailable
    ]
    if cs.cancel is not None:
        out.append(cs.cancel.as_answer_key_dict())
    return out


def solve(openings: Sequence[Opening], *, unavailable: set[str] | None = None) -> JointPlan:
    if not openings:
        return JointPlan(0, {}, 0, (), "empty")

    blocked = unavailable or set()
    option_lists = [_choices(o.candidate_set, blocked) for o in openings]
    combinations = 1
    for lst in option_lists:
        combinations *= max(1, len(lst))

    method = "exhaustive"
    if combinations > MAX_EXHAUSTIVE_COMBINATIONS:
        method = "greedy"
        return _greedy(openings, option_lists)

    best_cost: int | None = None
    best: list[list[dict]] = []

    for combo in product(*option_lists):
        assigned = [c["crew_id"] for c in combo if c["crew_id"]]
        if len(assigned) != len(set(assigned)):
            continue  # same person cannot cover two openings
        total = sum(c["cost_inr"] for c in combo)
        if best_cost is None or total < best_cost:
            best_cost, best = total, [list(combo)]
        elif total == best_cost:
            best.append(list(combo))

    if best_cost is None:
        return _greedy(openings, option_lists)

    chosen = best[0]
    assignments = {o.key: chosen[i] for i, o in enumerate(openings)}
    alternatives = tuple(
        {o.key: alt[i] for i, o in enumerate(openings)} for alt in best[1:6]
    )

    return JointPlan(
        total_cost_inr=best_cost,
        assignments=assignments,
        tie_count=len(best),
        alternatives=alternatives,
        method=method,
    )


def _greedy(openings: Sequence[Opening], option_lists: list[list[dict]]) -> JointPlan:
    """Fallback: assign the scarcest opening first, cheapest available each time."""
    order = sorted(range(len(openings)), key=lambda i: len(option_lists[i]))
    used: set[str] = set()
    assignments: dict[str, dict] = {}
    total = 0
    for i in order:
        for option in option_lists[i]:
            cid = option["crew_id"]
            if cid and cid in used:
                continue
            if cid:
                used.add(cid)
            assignments[openings[i].key] = option
            total += option["cost_inr"]
            break
    return JointPlan(total, assignments, 1, (), "greedy")
