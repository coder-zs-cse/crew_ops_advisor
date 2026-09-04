"""Cost model.

Every cost is itemised so the UI can show a breakdown on hover and the narrator
can cite the components rather than a single opaque number.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Costs


@dataclass(frozen=True, slots=True)
class CostLine:
    label: str
    amount: int
    basis: str

    def as_dict(self) -> dict:
        return {"label": self.label, "amount": self.amount, "basis": self.basis}


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    currency: str
    lines: tuple[CostLine, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return int(sum(line.amount for line in self.lines))

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "total": self.total,
            "lines": [line.as_dict() for line in self.lines],
        }


def callout_cost(
    costs: Costs, *, is_reserve: bool, is_pilot: bool, delay_hours: float = 0.0, deadhead: bool = False
) -> CostBreakdown:
    """Cost of covering a duty with one crew member.

    Mirrors the reference model exactly:
        callout + (deadhead ? positioning + round(delay_h * delay_rate) : 0)
    """
    lines = [
        CostLine(
            label="Reserve callout" if is_reserve else "Day-off callout",
            amount=costs.callout(is_reserve=is_reserve, is_pilot=is_pilot),
            basis=f"{'reserve' if is_reserve else 'day-off'} {'pilot' if is_pilot else 'cabin'} rate",
        )
    ]
    if deadhead:
        lines.append(
            CostLine(
                label="Deadhead positioning",
                amount=costs.deadhead_positioning,
                basis="RULE-BASE-07 positioning sector",
            )
        )
        lines.append(
            CostLine(
                label="Delay cost",
                amount=int(round(delay_hours * costs.delay_cost_per_duty_hour)),
                basis=f"{delay_hours}h x {costs.delay_cost_per_duty_hour}/h on first departure",
            )
        )
    return CostBreakdown(currency=costs.currency, lines=tuple(lines))


def cancellation_cost(costs: Costs, n_flights: int) -> CostBreakdown:
    return CostBreakdown(
        currency=costs.currency,
        lines=(
            CostLine(
                label="Cancellation",
                amount=costs.cancellation_per_flight * n_flights,
                basis=f"{n_flights} legs x {costs.cancellation_per_flight}/leg",
            ),
        ),
    )


def delay_cost(costs: Costs, delay_hours: float) -> CostBreakdown:
    return CostBreakdown(
        currency=costs.currency,
        lines=(
            CostLine(
                label="Delay cost",
                amount=int(round(delay_hours * costs.delay_cost_per_duty_hour)),
                basis=f"{delay_hours}h x {costs.delay_cost_per_duty_hour}/h",
            ),
        ),
    )


def complement_callout_cost(costs: Costs, roles: list[str]) -> CostBreakdown:
    """Cost of calling out a whole reserve set (S4's tail-leg re-crew)."""
    from .models import PILOT_ROLES

    lines = []
    for role in roles:
        is_pilot = role in PILOT_ROLES
        lines.append(
            CostLine(
                label=f"Reserve callout - {role}",
                amount=costs.callout(is_reserve=True, is_pilot=is_pilot),
                basis="reserve pilot rate" if is_pilot else "reserve cabin rate",
            )
        )
    return CostBreakdown(currency=costs.currency, lines=tuple(lines))
