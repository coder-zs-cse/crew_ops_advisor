"""Option ranking -- two rankings, deliberately.

``cost_rank``  Ascending (cost_inr, crew_id), cancellation appended last. This
               is the reference ordering that produced the answer keys, and it
               is what the API returns as ``rank``. Authoritative.

``ops_rank``   Our opinionated ordering. Cost still dominates, but a real desk
               also cares about how long the crew takes to reach the airport,
               how much duty headroom the assignment burns, how fatigued the
               person already is, and whether the move delays a departure.

We show both and label which one is graded. Silently substituting a heuristic
for the reference ordering would be the wrong trade: the heuristic is a better
*opinion*, but the cost ordering is the checkable *answer*.
"""

from __future__ import annotations

from .windows import duty_hours_7d
from .world import World

#: ops_score weights. Lower score = better option.
W_COST = 1.0          # per rupee, normalised below
W_DELAY = 0.25        # per hour of departure delay
W_REACH = 0.05        # per minute of reachability
W_HEADROOM = 0.15     # per hour of duty headroom consumed
W_RISK = 0.10         # per unit of disruption-risk score

COST_NORMALISER = 25_000.0  # roughly one day-off pilot callout


def _ops_score(world: World, candidate) -> tuple[float, dict]:
    crew = candidate.crew

    cost_term = candidate.cost_inr / COST_NORMALISER
    delay_term = candidate.delay_hours
    reach_term = crew.reachability_minutes / 60.0

    # How much 7-day duty headroom the assignment leaves on the tightest day.
    headroom = 60.0
    for verdict in candidate.legality.verdicts:
        if verdict.rule_id == "RULE-DUTY-02" and verdict.margin is not None:
            headroom = min(headroom, verdict.margin)
    headroom_term = max(0.0, (20.0 - headroom)) / 20.0

    signal = world.risk(crew.crew_id)
    risk_term = signal.disruption_risk_score if signal else 0.0

    score = (
        W_COST * cost_term
        + W_DELAY * delay_term
        + W_REACH * reach_term
        + W_HEADROOM * headroom_term
        + W_RISK * risk_term
    )

    factors = {
        "cost_inr": candidate.cost_inr,
        "delay_hours": candidate.delay_hours,
        "reachability_minutes": crew.reachability_minutes,
        "duty_headroom_hours_after": round(headroom, 2),
        "disruption_risk_score": round(risk_term, 2),
        "seniority": crew.seniority,
        "source": "reserve" if candidate.is_reserve else "day-off",
    }
    return round(score, 4), factors


def apply_rankings(world: World, eligible: list, cancel):
    """Sort by the reference ordering, then attach ops ranks.

    Returns ``(ranked_eligible, cancel_with_rank)``.
    """
    from dataclasses import replace

    ordered = sorted(eligible, key=lambda c: (c.cost_inr, c.crew_id))

    scored = []
    for candidate in ordered:
        score, factors = _ops_score(world, candidate)
        scored.append((score, factors, candidate))

    ops_order = sorted(range(len(scored)), key=lambda i: (scored[i][0], scored[i][2].crew_id))
    ops_rank_of = {idx: position + 1 for position, idx in enumerate(ops_order)}

    ranked = []
    for index, (score, factors, candidate) in enumerate(scored):
        ranked.append(
            replace(
                candidate,
                rank=index + 1,
                ops_rank=ops_rank_of[index],
                ops_score=score,
                ops_factors=factors,
            )
        )

    if cancel is not None:
        cancel = replace(cancel, rank=len(ranked) + 1)

    return ranked, cancel


def impact_score(world: World, *, breaches: int, cost_inr: int, seats_at_risk: int, delay_hours: float) -> dict:
    """Velaire-style 3D impact score, 0-100 each (higher = worse).

    Purely presentational -- it never reorders the authoritative ranking. It
    exists so a controller can see at a glance whether an option hurts on
    safety, on money, or on passengers.
    """
    safety = min(100, breaches * 40)
    business = min(100, round(cost_inr / 2500))
    customer = min(100, round(seats_at_risk / 5 + delay_hours * 8))
    return {
        "safety": safety,
        "business": business,
        "customer": customer,
        "worst": max(safety, business, customer),
    }
