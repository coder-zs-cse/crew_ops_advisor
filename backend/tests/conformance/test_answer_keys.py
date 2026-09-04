"""Grade the engine against the dataset's own answer keys.

This is the gate. It runs with no database, no network and no model, so it can
sit in front of every commit — and it is the same code path the /eval surface
shows on stage.
"""

import pytest

from app.evalsuite import question_suite, scenario_suite


def _ids(report):
    return [(c["case_id"], c) for c in report["cases"]]


@pytest.fixture(scope="module")
def questions(data_dir):
    return question_suite.run_suite(data_dir)


@pytest.fixture(scope="module")
def scenarios(data_dir):
    return scenario_suite.run_suite(data_dir, suite="scenarios")


@pytest.fixture(scope="module")
def holdout(data_dir):
    return scenario_suite.run_suite(data_dir, suite="holdout")


def test_all_38_questions_graded(questions):
    assert questions["total"] == 38


@pytest.mark.parametrize("case_id,case", _ids(question_suite.run_suite(str(__import__("pathlib").Path(__file__).resolve().parents[2] / "data"))))
def test_question(case_id, case):
    assert case["passed"], f"{case_id}: {case['error'] or case['failed_checks']}"


def test_every_scenario(scenarios):
    failed = [c["case_id"] for c in scenarios["cases"] if not c["passed"]]
    assert not failed, f"scenarios failed: {failed}"


def test_held_out_scenarios(holdout):
    """Generalisation check — these were not used during development."""
    failed = [c["case_id"] for c in holdout["cases"] if not c["passed"]]
    assert not failed, f"held-out scenarios failed: {failed}"


def test_tier_coverage(questions):
    by_tier = questions["by_tier"]
    assert by_tier["1"]["total"] == 16
    assert by_tier["2"]["total"] == 14
    assert by_tier["3"]["total"] == 8
    for tier, stats in by_tier.items():
        assert stats["passed"] == stats["total"], f"tier {tier} has failures"
