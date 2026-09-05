"""Grade the generalization suite -- 17 questions + 3 scenarios written to
probe edges the original 38 questions / 6 scenarios never reach (see
data/GENERALIZATION_FINDINGS.md in the dataset repo for the full writeup:
unknown/malformed entities, out-of-window dates, exact rule boundaries, a
shallow candidate pool, and four things that were genuinely wrong until this
suite's own findings got them fixed -- RULE-FLT-03 being advisory-only,
check_legality/simulate_assignment skipping status and rank preconditions,
and name references silently resolving to the wrong person).

Deliberately a separate file from test_answer_keys.py: that file's exact-count
assertions (38 questions, 16/14/8 tier split, 6 scenarios) are the original
answer-key benchmark's own guarantee, and this suite must never be able to
perturb them by growing or shrinking here.
"""

import pytest

from app.evalsuite import generalization_suite


@pytest.fixture(scope="module")
def report(data_dir):
    return generalization_suite.run_suite(data_dir)


def _ids(rep):
    return [(c["case_id"], c) for c in rep["cases"]]


def test_all_20_generalization_cases_graded(report):
    assert report["total"] == 20


@pytest.mark.parametrize(
    "case_id,case",
    _ids(generalization_suite.run_suite(str(__import__("pathlib").Path(__file__).resolve().parents[2] / "data"))),
)
def test_generalization_case(case_id, case):
    assert case["passed"], f"{case_id}: {case['error'] or case['failed_checks']}"


def test_every_generalization_case_has_a_grader(report):
    no_grader = [c["case_id"] for c in report["cases"] if c["error"] == "no grader implemented"]
    assert not no_grader, f"missing graders: {no_grader}"
