"""The seven-rule legality engine.

One module per rule. Each returns a ``RuleVerdict`` carrying both the
answer-key-format message and a structured arithmetic trace for the UI.
"""

from .base import CoverContext
from .base07 import BaseAndPositioningRule
from .cert06 import CertificationRule, certs_valid_on, days_to_expiry
from .duty02 import MAX_DUTY_HOURS, SevenDayDutyRule
from .engine import ALL_RULE_IDS, ENGINE, RuleEngine, check_cover
from .fdp01 import FlightDutyPeriodRule, check_fdp
from .flt03 import MAX_FLIGHT_HOURS, TwentyEightDayFlightRule
from .qual05 import AircraftRatingRule
from .rest04 import MIN_REST_HOURS, MinimumRestRule, NoOverlapRule, rest_between

__all__ = [
    "ALL_RULE_IDS",
    "ENGINE",
    "MAX_DUTY_HOURS",
    "MAX_FLIGHT_HOURS",
    "MIN_REST_HOURS",
    "AircraftRatingRule",
    "BaseAndPositioningRule",
    "CertificationRule",
    "CoverContext",
    "FlightDutyPeriodRule",
    "MinimumRestRule",
    "NoOverlapRule",
    "RuleEngine",
    "SevenDayDutyRule",
    "TwentyEightDayFlightRule",
    "certs_valid_on",
    "check_cover",
    "check_fdp",
    "days_to_expiry",
    "rest_between",
]
