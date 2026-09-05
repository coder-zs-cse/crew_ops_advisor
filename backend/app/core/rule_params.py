"""Read legality-rule parameters from the dataset, not from code.

Every numeric limit in the ruleset -- max duty hours, min rest, the FDP
formula's coefficients, the rolling-window lengths -- is shipped as
machine-readable ``params`` on each rule in ``rules.json`` precisely so it can
be changed without touching this codebase. Before this module existed, the
rule-evaluation code duplicated those numbers as bare Python constants and
never read ``rules.json`` at all: regenerating the dataset with a different
limit under the same rule id silently kept enforcing the old one. Every call
site that has a ``World`` must go through ``rule_param`` instead.

``DEFAULT_PARAMS`` still carries the sample dataset's own values. They are now
only a fallback -- for the handful of unit tests that exercise the pure
arithmetic with no ``World`` at all, and as a safety net if a rule or a
specific key is missing from a stripped-down dataset -- not the source of
truth. A complete ``rules.json`` always wins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .world import World

DEFAULT_PARAMS: dict[str, dict[str, float]] = {
    "RULE-FDP-01": {
        "base_fdp_hours": 13.0,
        "reduction_per_extra_sector_hours": 0.5,
        "free_sectors": 2,
    },
    "RULE-DUTY-02": {"max_duty_hours": 60.0, "window_days": 7},
    "RULE-FLT-03": {"max_flight_hours": 100.0, "window_days": 28},
    "RULE-REST-04": {"min_rest_hours": 12.0},
}


def rule_param(
    world: "World | None", rule_id: str, key: str, default: float | int | None = None
) -> Any:
    """One rule parameter, sourced from ``rules.json`` when a ``World`` is given.

    Falls back to ``default`` (or the sample dataset's own value in
    ``DEFAULT_PARAMS`` when ``default`` is not given) if ``world`` is
    ``None``, the rule isn't in this dataset, or the key is absent from its
    ``params`` -- so a stripped-down ``rules.json`` degrades gracefully
    instead of raising, but a complete one is always authoritative.
    """
    fallback = default if default is not None else DEFAULT_PARAMS.get(rule_id, {}).get(key)
    if world is None:
        return fallback
    rule = world.rule(rule_id)
    if rule is None or not rule.params:
        return fallback
    return rule.params.get(key, fallback)
