"""Rule boundary cases.

Limits are exact arithmetic, so the interesting inputs are the ones that land
*on* the boundary. Each of these was a real decision in the implementation, not
a hypothetical.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.core.duty import earliest_next_report, fdp_limit
from app.core.positioning import find_positioning
from app.core.rules.cert06 import certs_valid_on
from app.core.rules.engine import check_cover
from app.core.rules.rest04 import MIN_REST_HOURS, rest_between
from app.core.timeutil import fmt_hm, hrs, is_even_date, parse_dt
from app.core.windows import duty_hours_7d


# ---- RULE-FDP-01 ---------------------------------------------------------


@pytest.mark.parametrize(
    "sectors,expected",
    [(1, 13.0), (2, 13.0), (3, 12.5), (4, 12.0), (5, 11.5), (6, 11.0), (8, 10.0)],
)
def test_fdp_limit_reduces_only_beyond_two_sectors(sectors, expected):
    assert fdp_limit(sectors) == expected


# ---- RULE-REST-04 --------------------------------------------------------


def test_rest_of_exactly_twelve_hours_is_legal():
    release = parse_dt("2026-09-16T15:30:00Z")
    rest, ok = rest_between(release, release + timedelta(hours=MIN_REST_HOURS))
    assert rest == 12.0 and ok


def test_rest_one_minute_short_is_illegal():
    release = parse_dt("2026-09-16T15:30:00Z")
    _, ok = rest_between(release, release + timedelta(hours=12) - timedelta(minutes=1))
    assert not ok


def test_earliest_next_report_is_release_plus_twelve():
    assert earliest_next_report(parse_dt("2026-09-16T15:30:00Z")) == parse_dt(
        "2026-09-17T03:30:00Z"
    )


# ---- RULE-DUTY-02 --------------------------------------------------------


def test_flagship_duty_breach_magnitude(world):
    """C-2087 covering P-2291 busts the 7-day ceiling by exactly 1h20m."""
    report = check_cover(world, "C-2087", world.pairing("P-2291").days, exclude_pairing="P-2291")
    assert not report.legal
    breach = next(v for v in report.verdicts if v.rule_id == "RULE-DUTY-02" and v.is_breach)
    assert breach.actual == 61.33
    assert breach.limit == 60.0
    assert fmt_hm(breach.actual - breach.limit) == "1h20m"


def test_duty_window_is_seven_calendar_days_inclusive(world):
    """51.83h is the sum of C-2087's 9 Sep .. 14 Sep history, inclusive."""
    assert duty_hours_7d(world, "C-2087", date(2026, 9, 14)) == 51.83


def test_replacing_a_pairing_removes_its_own_hours(world):
    """A crew member taking over the pairing they already fly is not double-counted."""
    pairing = world.pairing("P-2291")
    incumbent = next(cid for cid, role in pairing.crew if role == "Captain")
    report = check_cover(world, incumbent, pairing.days, exclude_pairing="P-2291")
    duty_breaches = [v for v in report.verdicts if v.rule_id == "RULE-DUTY-02" and v.is_breach]
    assert not duty_breaches


# ---- RULE-QUAL-05 --------------------------------------------------------


def test_missing_rating_short_circuits_every_other_check(world):
    """An unrated pilot's duty hours are moot; the answer keys report one reason."""
    report = check_cover(world, "C-2091", world.pairing("P-2291").days, exclude_pairing="P-2291")
    assert report.issues == ("RULE-QUAL-05: no A320 rating",)


# ---- RULE-CERT-06 --------------------------------------------------------


def test_certificate_expiring_before_the_duty_date_is_a_breach(world):
    ok, expired = certs_valid_on(world, "C-5417", date(2026, 9, 19))
    assert not ok and "recurrent_training" in expired


def test_same_certificate_is_valid_two_days_earlier(world):
    ok, _ = certs_valid_on(world, "C-5417", date(2026, 9, 17))
    assert ok


# ---- RULE-BASE-07 / positioning ------------------------------------------


def test_date_parity_selects_the_positioning_flight(world):
    """DX589 arrives 07:45Z on even dates, DX402 arrives 08:45Z on odd ones."""
    assert is_even_date(date(2026, 9, 16))
    assert not is_even_date(date(2026, 9, 15))

    required = parse_dt("2026-09-15T07:00:00Z")
    odd = find_positioning(
        world, from_station="DEL", to_station="BLR", on=date(2026, 9, 15), required_departure=required
    )
    assert odd is not None and odd.flight_no == "DX402" and odd.delay_hours == 3.0

    even = find_positioning(
        world, from_station="DEL", to_station="BLR", on=date(2026, 9, 16), required_departure=required
    )
    assert even is not None and even.flight_no == "DX589"


def test_no_positioning_between_unserved_bases(world):
    assert (
        find_positioning(
            world,
            from_station="BOM",
            to_station="BLR",
            on=date(2026, 9, 15),
            required_departure=parse_dt("2026-09-15T07:00:00Z"),
        )
        is None
    )


# ---- rounding ------------------------------------------------------------


def test_hours_round_to_two_decimals_like_the_generator():
    assert hrs(timedelta(hours=9, minutes=30)) == 9.5
    assert hrs(timedelta(hours=11, minutes=15)) == 11.25
    assert hrs(timedelta(hours=1, minutes=20)) == 1.33


def test_breach_magnitudes_render_as_hours_and_minutes():
    assert fmt_hm(1.33) == "1h20m"
    assert fmt_hm(8.25) == "8h15m"
    assert fmt_hm(1.08) == "1h05m"
